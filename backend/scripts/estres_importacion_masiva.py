"""
Suite de paridad bit-a-bit y pruebas de estrés masivo (Paso 5: 8,000 y 20,000 filas).

Ubicado en `backend/scripts/` (fuera del auto-discovery de `manage.py test`).
Ejecutar con:
  python -u -c "import os, sys, django; sys.path.insert(0, r'backend'); os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings'); django.setup(); from django.test.runner import DiscoverRunner; sys.exit(DiscoverRunner(verbosity=2, keepdb=True, interactive=False).run_tests(['scripts.estres_importacion_masiva']))"
"""
import contextlib
import io
import os
import sys
import tempfile
import threading
import time
import tracemalloc
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.core.cache import caches
from django.db import connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from openpyxl import Workbook

import apps.auditoria.services as aud_srv
import apps.documentos.importacion_kardex_confirmar as conf_mod
import apps.documentos.importacion_kardex_excel as exc_mod
import apps.documentos.services as doc_srv
import apps.kardex.services as kar_srv
from apps.auditoria.models import Auditoria
from apps.catalogos.models import TipoComprobante
from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.documentos.importacion_kardex_confirmar import anular_lote_importacion, confirmar_importacion_kardex
from apps.documentos.importacion_kardex_excel import previsualizar_importacion_kardex
from apps.documentos.importacion_worker import (
    adquirir_lock_empresa,
    clave_progreso,
    encolar_anulacion_lote,
    encolar_confirmacion_importacion,
    procesar_siguiente_trabajo,
    recuperar_trabajos_huerfanos,
)
from apps.documentos.models import Documento, ImportacionLote, ImportacionTrabajo
from apps.empresas.models import ConfigEmpresa, Establecimiento, Periodo
from apps.empresas.services import cerrar_periodo
from apps.inventario.models import Almacen, Producto
from apps.kardex.models import Movimiento, RecalculoDetalle, SaldoCppActual, StockAlmacen
from apps.usuarios.models import Usuario, UsuarioEmpresa

ROOT = Path(__file__).resolve().parent.parent.parent
ARCHIVO_BETOTAL = ROOT / 'datos' / '011004 - BETOTAL.xlsx'
ARCHIVO_PHYTEX = ROOT / 'datos' / '011049 - PHYTEX 500.xlsx'
ARCHIVO_MAIZ = ROOT / 'datos' / '021007 - MAIZ AMARILLO MOLIDO.xlsx'
RUC_PROV = '20555000111'
RUC_CLI = '20666000111'


class _RollbackPass(Exception):
    pass


def _rss_mb() -> float:
    """Lee el Resident Set Size actual del proceso sin costo de CPU (Windows/Linux)."""
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes

        class _PMC(ctypes.Structure):
            _fields_ = [
                ('cb', wintypes.DWORD),
                ('PageFaultCount', wintypes.DWORD),
                ('PeakWorkingSetSize', ctypes.c_size_t),
                ('WorkingSetSize', ctypes.c_size_t),
                ('QuotaPeakPagedPoolUsage', ctypes.c_size_t),
                ('QuotaPagedPoolUsage', ctypes.c_size_t),
                ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
                ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
                ('PagefileUsage', ctypes.c_size_t),
                ('PeakPagefileUsage', ctypes.c_size_t),
            ]

        pmc = _PMC()
        pmc.cb = ctypes.sizeof(_PMC)
        proc = ctypes.windll.kernel32.GetCurrentProcess()
        if ctypes.windll.psapi.GetProcessMemoryInfo(proc, ctypes.byref(pmc), pmc.cb):
            return pmc.WorkingSetSize / (1024 * 1024)
    return 0.0


def _snapshot_kardex(empresa_id: int) -> dict:
    saldos = sorted(
        (codigo, str(c), str(v), str(cpp))
        for codigo, c, v, cpp in SaldoCppActual.objects.filter(empresa_id=empresa_id)
        .values_list('producto__codigo_interno', 'cantidad_total', 'valor_total_pen', 'cpp_pen')
    )
    stocks = sorted(
        (almacen_id, codigo, str(c))
        for almacen_id, codigo, c in StockAlmacen.objects.filter(empresa_id=empresa_id)
        .values_list('almacen_id', 'producto__codigo_interno', 'cantidad_actual')
    )
    movimientos = [
        (
            m.producto.codigo_interno,
            m.almacen_id,
            m.fecha_movimiento.isoformat(),
            m.prioridad_dia,
            m.secuencia,
            m.tipo_operacion.codigo_interno,
            m.naturaleza,
            str(m.cantidad_base),
            str(m.valor_ajuste_pen) if m.valor_ajuste_pen is not None else None,
            m.es_extorno,
            str(m.valorizacion.costo_unitario_pen),
            str(m.valorizacion.valor_movimiento_pen),
            str(m.valorizacion.saldo_cantidad_empresa),
            str(m.valorizacion.saldo_valor_empresa),
            str(m.valorizacion.cpp_empresa),
        )
        for m in Movimiento.objects.filter(empresa_id=empresa_id)
        .select_related('producto', 'tipo_operacion', 'valorizacion')
        .order_by('producto__codigo_interno', 'fecha_movimiento', 'prioridad_dia', 'secuencia', 'id')
    ]
    recalculo_detalles = sorted(
        (
            rd.movimiento.producto.codigo_interno,
            rd.movimiento.fecha_movimiento.isoformat(),
            rd.movimiento.prioridad_dia,
            rd.movimiento.secuencia,
            str(rd.cpp_anterior),
            str(rd.cpp_nuevo),
            str(rd.valor_anterior),
            str(rd.valor_nuevo),
            str(rd.saldo_anterior),
            str(rd.saldo_nuevo),
        )
        for rd in RecalculoDetalle.objects.filter(recalculo__empresa_id=empresa_id)
        .select_related('movimiento__producto')
    )
    auditoria_conteo = dict(
        sorted(
            Counter(
                Auditoria.objects.filter(empresa_id=empresa_id).values_list('accion', 'entidad')
            ).items()
        )
    )
    return {
        'saldos': saldos,
        'stocks': stocks,
        'movimientos': movimientos,
        'recalculo_detalles': recalculo_detalles,
        'auditoria': auditoria_conteo,
    }


@contextlib.contextmanager
def _modo_referencia_sin_caches_paso5():
    """
    Desactiva los cachés y deferrals de escritura del Paso 5 (sin alterar `modo_lote_kardex` del Paso 2
    para recálculo retroactivo por producto) para comparar paridad bit-a-bit.
    """
    @contextlib.contextmanager
    def dummy_lote_docs(*, empresa_id, preload_duplicados=True, preload_anulacion=False):
        yield {'sin_pagos_ids': None, 'movimientos_por_doc': None}

    @contextlib.contextmanager
    def dummy_buffer_aud():
        yield

    orig_modo_docs = conf_mod.modo_lote_documentos
    orig_ctx_docs_1 = doc_srv.ctx_lote_documentos
    orig_ctx_docs_2 = kar_srv._ctx_lote
    orig_buf_1 = kar_srv.buffer_auditoria_lote

    conf_mod.modo_lote_documentos = dummy_lote_docs
    doc_srv.ctx_lote_documentos = lambda empresa_id=None: None
    kar_srv._ctx_lote = lambda empresa_id=None: None
    kar_srv.buffer_auditoria_lote = dummy_buffer_aud
    try:
        yield
    finally:
        conf_mod.modo_lote_documentos = orig_modo_docs
        doc_srv.ctx_lote_documentos = orig_ctx_docs_1
        kar_srv._ctx_lote = orig_ctx_docs_2
        kar_srv.buffer_auditoria_lote = orig_buf_1


def _generar_excel_sintetico(total_filas: int, *, n_completar: int = 30, n_nc: int = 160, n_compras: int = 480) -> bytes:
    """
    Genera exactamente `total_filas` con:
    - `n_completar` comprobantes COMPLETAR (2 líneas c/u en 2026-01-03)
    - `n_compras` compras NUEVAS (4 líneas c/u en meses 1..12)
    - Ventas NUEVAS (mix de 3 y 4 líneas en meses 1..12)
    - `n_nc` notas de crédito 05 Devolución Recibida entre meses (devolviendo ventas del mes anterior)
    """
    filas_completar = n_completar * 2
    filas_compras = n_compras * 4
    filas_ventas = total_filas - filas_completar - filas_compras - n_nc
    assert filas_ventas >= 300, 'Total de filas insuficiente para el reparto mínimo'

    # Descomponer `filas_ventas = 3*a + 4*b` -> por defecto ~60% de 4 líneas
    n_ventas_4 = min(filas_ventas // 4, int((filas_ventas // 4) * 0.6))
    resto = filas_ventas - n_ventas_4 * 4
    while resto % 3 != 0 and n_ventas_4 > 0:
        n_ventas_4 -= 1
        resto += 4
    n_ventas_3 = resto // 3
    total_ventas = n_ventas_4 + n_ventas_3

    wb = Workbook(write_only=True)
    ws = wb.create_sheet()
    ws.append([None, 'COMPROBANTE', None, None, None, 'Tipo de Operación', 'ENTRADAS', None, None, 'SALIDAS', None, None, 'RUC/DNI', 'Precio unitario'])
    ws.append([None, 'Fecha', 'Tipo', 'Serie', 'Número', None, 'Cantidad', 'Costo Unitario', 'Costo Total', 'Cantidad', 'Costo Unitario', 'Costo Total', None, None])

    productos = [f'P-{i:03d}' for i in range(1, 11)]
    filas_totales = 0

    for idx in range(1, n_completar + 1):
        ws.append(['P-001', date(2026, 1, 3), 3, 'BS01', idx, '01 Venta', 0, 0, 0, 2, 10, 20, '', 18])
        ws.append(['P-002', date(2026, 1, 3), 3, 'BS01', idx, '01 Venta', 0, 0, 0, 2, 10, 20, '', 18])
        filas_totales += 2

    compras_por_mes = [n_compras // 12 + (1 if m < n_compras % 12 else 0) for m in range(12)]
    num_compra = 1
    for mes_idx, cant in enumerate(compras_por_mes, start=1):
        for c in range(cant):
            dia = 2 + (c % 20)
            for l in range(4):
                prod = productos[(num_compra + l) % len(productos)]
                ws.append([prod, date(2026, mes_idx, dia), 1, 'FC01', num_compra, '02 Compra', 50, 11, 550, 0, 0, 0, RUC_PROV, None])
                filas_totales += 1
            num_compra += 1

    ventas_por_mes = [total_ventas // 12 + (1 if m < total_ventas % 12 else 0) for m in range(12)]
    num_venta = 1
    ventas_mes = defaultdict(list)
    for mes_idx, cant in enumerate(ventas_por_mes, start=1):
        for v in range(cant):
            dia = 5 + (v % 22)
            n_lineas = 4 if num_venta <= n_ventas_4 else 3
            for l in range(n_lineas):
                prod = productos[(num_venta + l) % len(productos)]
                ws.append([prod, date(2026, mes_idx, dia), 1, 'FV01', num_venta, '01 Venta', 0, 0, 0, 2, 10.5, 21, RUC_CLI, 20])
                filas_totales += 1
                if l == 0:
                    ventas_mes[mes_idx].append(prod)
            num_venta += 1

    for i in range(n_nc):
        mes_origen = (i % 11) + 1
        mes_nc = mes_origen + 1
        lista = ventas_mes[mes_origen]
        prod = lista[(i // 11) % len(lista)]
        dia_nc = 1 + (i % 15)
        ws.append([prod, date(2026, mes_nc, dia_nc), 7, 'NC01', i + 1, '05 Devolución Recibida', 2, 0, 0, 0, 0, 0, RUC_CLI, None])
        filas_totales += 1

    assert filas_totales == total_filas, f'Esperadas {total_filas} filas, generadas {filas_totales}'
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


class _MixinBaseEstres:
    def _preparar_periodos(self, anio: int):
        res = {}
        for mes in range(1, 13):
            if anio == 2026 and mes == 1:
                res[1] = self.enero
                continue
            fin = date(anio, 12, 31) if mes == 12 else (date(anio, mes + 1, 1) - date.resolution)
            res[mes], _ = Periodo.objects.get_or_create(
                empresa=self.empresa, anio=anio, mes=mes,
                defaults={'orden': anio * 100 + mes, 'fecha_inicio': date(anio, mes, 1), 'fecha_fin': fin, 'estado': 'ABIERTO'},
            )
        return res

    def _preparar_escenario_sintetico(self, n_completar: int = 30):
        self.crear_base()
        TipoComprobante.objects.get_or_create(codigo_sunat='03', defaults={'descripcion': 'BOLETA'})
        self._preparar_periodos(2026)
        prods = [self.crear_producto(f'P-{i:03d}') for i in range(1, 11)]
        self.documento_confirmado('COMPRA', [
            self.linea('COMPRA', '100000', '10', producto=p) for p in prods
        ], fecha='2026-01-01')

        wb_prev = Workbook(write_only=True)
        ws_prev = wb_prev.create_sheet()
        ws_prev.append([None, 'COMPROBANTE', None, None, None, 'Tipo de Operación', 'ENTRADAS', None, None, 'SALIDAS', None, None, 'Precio unitario'])
        ws_prev.append([None, 'Fecha', 'Tipo', 'Serie', 'Número', None, 'Cantidad', 'Costo Unitario', 'Costo Total', 'Cantidad', 'Costo Unitario', 'Costo Total', None])
        for idx in range(1, n_completar + 1):
            ws_prev.append(['P-001', date(2026, 1, 3), 3, 'BS01', idx, '01 Venta', 0, 0, 0, 2, 10, 20, 18])
        buf_prev = io.BytesIO()
        wb_prev.save(buf_prev)
        confirmar_importacion_kardex(
            empresa_id=self.empresa.id, usuario=self.usuario,
            archivos=[('previo_completar.xlsx', io.BytesIO(buf_prev.getvalue()))],
            almacen_id=self.almacen.id,
        )


class ParidadYEstresMasivoTests(_MixinBaseEstres, Bloque2Fixture, TestCase):
    def test_01_paridad_bit_a_bit_betotal_y_phytex(self):
        self.crear_base()
        TipoComprobante.objects.get_or_create(codigo_sunat='03', defaults={'descripcion': 'BOLETA'})
        p_bet = self.crear_producto('011004')
        p_phy = self.crear_producto('011049')
        periodos_2023 = self._preparar_periodos(2023)
        self.documento_confirmado('COMPRA', [
            self.linea('COMPRA', '100', '34', producto=p_bet),
            self.linea('COMPRA', '250', '20', producto=p_phy),
        ], fecha='2023-01-01', periodo=periodos_2023[1])

        archivos_bytes = [
            ('011004 - BETOTAL.xlsx', ARCHIVO_BETOTAL.read_bytes()),
            ('011049 - PHYTEX 500.xlsx', ARCHIVO_PHYTEX.read_bytes()),
        ]
        fn = lambda: [(n, io.BytesIO(b)) for n, b in archivos_bytes]
        prev = previsualizar_importacion_kardex(empresa_id=self.empresa.id, archivos=fn())
        proveedores = {
            c['clave_proveedor']: RUC_PROV
            for c in prev['comprobantes']
            if c['requiere_proveedor'] and c['clave_proveedor']
        }

        snap_ref_conf = snap_ref_anul = None
        try:
            with transaction.atomic():
                with _modo_referencia_sin_caches_paso5():
                    res_ref = confirmar_importacion_kardex(
                        empresa_id=self.empresa.id, usuario=self.usuario,
                        archivos=fn(), almacen_id=self.almacen.id, proveedores=proveedores,
                    )
                    snap_ref_conf = _snapshot_kardex(self.empresa.id)
                    anular_lote_importacion(
                        empresa_id=self.empresa.id, lote_id=res_ref['lote'],
                        usuario=self.usuario, motivo='Paridad ref',
                    )
                    snap_ref_anul = _snapshot_kardex(self.empresa.id)
                raise _RollbackPass()
        except _RollbackPass:
            pass

        res_opt = confirmar_importacion_kardex(
            empresa_id=self.empresa.id, usuario=self.usuario,
            archivos=fn(), almacen_id=self.almacen.id, proveedores=proveedores,
        )
        snap_opt_conf = _snapshot_kardex(self.empresa.id)
        anular_lote_importacion(
            empresa_id=self.empresa.id, lote_id=res_opt['lote'],
            usuario=self.usuario, motivo='Paridad opt',
        )
        snap_opt_anul = _snapshot_kardex(self.empresa.id)

        self.assertEqual(snap_opt_conf, snap_ref_conf)
        self.assertEqual(snap_opt_anul, snap_ref_anul)
        print(
            f'\n[PARIDAD OK] BETOTAL+PHYTEX: '
            f'movs_conf={len(snap_opt_conf["movimientos"])}, '
            f'recalc_conf={len(snap_opt_conf["recalculo_detalles"])}, '
            f'movs_anul={len(snap_opt_anul["movimientos"])}, '
            f'recalc_anul={len(snap_opt_anul["recalculo_detalles"])}'
        )

    def _medir_lote(self, *, etiqueta: str, archivos_bytes: list, esperar_filas: int):
        fn = lambda: [(n, io.BytesIO(b)) for n, b in archivos_bytes]
        size_mb = sum(len(b) for _, b in archivos_bytes) / (1024 * 1024)

        prev_ini = previsualizar_importacion_kardex(empresa_id=self.empresa.id, archivos=fn())
        proveedores = {
            c['clave_proveedor']: RUC_PROV
            for c in prev_ini['comprobantes']
            if c['requiere_proveedor'] and c['clave_proveedor']
        }

        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(IMPORTACION_STAGING_DIR=Path(tmp) / 'staging'):
                # 1. Confirmar vía worker
                t_conf_job = encolar_confirmacion_importacion(
                    empresa_id=self.empresa.id, usuario=self.usuario,
                    archivos=fn(), almacen_id=self.almacen.id, proveedores=proveedores,
                )
                q_conf = [0]

                def count_wrapper(execute, sql, params, many, context):
                    q_conf[0] += 1
                    return execute(sql, params, many, context)

                rss_ini_c = _rss_mb()
                t0 = time.perf_counter()
                with connection.execute_wrapper(count_wrapper):
                    res_conf_job = procesar_siguiente_trabajo()
                conf_s = time.perf_counter() - t0
                rss_conf = _rss_mb()

                self.assertEqual(res_conf_job.estado, 'COMPLETADO', res_conf_job.error_detalle)
                lote_id = res_conf_job.lote_id

                # 2. Anular vía worker
                encolar_anulacion_lote(
                    empresa_id=self.empresa.id, usuario=self.usuario,
                    lote_id=lote_id, motivo=f'Estrés {etiqueta}',
                )
                q_anul = [0]

                def count_wrapper_anul(execute, sql, params, many, context):
                    q_anul[0] += 1
                    return execute(sql, params, many, context)

                rss_ini_a = _rss_mb()
                t0 = time.perf_counter()
                with connection.execute_wrapper(count_wrapper_anul):
                    res_anul_job = procesar_siguiente_trabajo()
                anul_s = time.perf_counter() - t0
                rss_anul = _rss_mb()

                self.assertEqual(res_anul_job.estado, 'COMPLETADO', res_anul_job.error_detalle)

                # 3. Reimportación limpia del mismo Excel tras anular el lote completo
                reimp_job = encolar_confirmacion_importacion(
                    empresa_id=self.empresa.id, usuario=self.usuario,
                    archivos=fn(), almacen_id=self.almacen.id, proveedores=proveedores,
                )
                reimp_res = procesar_siguiente_trabajo()
                self.assertEqual(reimp_res.id, reimp_job.id)
                self.assertEqual(reimp_res.estado, 'COMPLETADO', reimp_res.error_detalle)

        print(
            f'\n[ESTRES {etiqueta}] filas={prev_ini["resumen"]["filas"]} (esperadas~{esperar_filas}), '
            f'comprobantes={prev_ini["resumen"]["comprobantes"]}, xlsx={size_mb:.2f}MB | '
            f'CONFIRMAR: {conf_s:.2f}s, RSS={rss_conf:.1f}MB (+{max(0.0, rss_conf - rss_ini_c):.1f}MB), SQL={q_conf[0]} | '
            f'ANULAR: {anul_s:.2f}s, RSS={rss_anul:.1f}MB (+{max(0.0, rss_anul - rss_ini_a):.1f}MB), SQL={q_anul[0]} | '
            f'REIMPORTAR=COMPLETADO'
        )
        return lote_id

    def test_02_estres_8000_real_maiz_y_8000_20000_sinteticos(self):
        with mock.patch.object(exc_mod, 'MAX_FILAS', 30000), mock.patch.object(exc_mod, 'MAX_COMPROBANTES_LOTE', 15000):
            # A) Archivo real MAIZ AMARILLO MOLIDO (7,978 filas)
            self.crear_base()
            TipoComprobante.objects.get_or_create(codigo_sunat='03', defaults={'descripcion': 'BOLETA'})
            try:
                with transaction.atomic():
                    periodos_2023 = self._preparar_periodos(2023)
                    p_maiz = self.crear_producto('021007')
                    self.documento_confirmado('COMPRA', [
                        self.linea('COMPRA', '500000', '2.5', producto=p_maiz),
                    ], fecha='2023-01-01', periodo=periodos_2023[1])
                    maiz_bytes = ARCHIVO_MAIZ.read_bytes()
                    t0 = time.perf_counter()
                    prev_maiz = previsualizar_importacion_kardex(
                        empresa_id=self.empresa.id,
                        archivos=[('021007 - MAIZ AMARILLO MOLIDO.xlsx', io.BytesIO(maiz_bytes))],
                    )
                    prev_s = time.perf_counter() - t0
                    print(
                        f"\n[MAIZ REAL PREVIA] size={len(maiz_bytes)/(1024*1024):.2f}MB, "
                        f"previs={prev_s:.2f}s, resumen={prev_maiz['resumen']}"
                    )
                    raise _RollbackPass()
            except _RollbackPass:
                pass

            # Prepara escenario sintético una sola vez sobre la base ya creada
            self._preparar_periodos(2026)
            prods = [self.crear_producto(f'P-{i:03d}') for i in range(1, 11)]
            self.documento_confirmado('COMPRA', [
                self.linea('COMPRA', '100000', '10', producto=p) for p in prods
            ], fecha='2026-01-01')
            wb_prev = Workbook(write_only=True)
            ws_prev = wb_prev.create_sheet()
            ws_prev.append([None, 'COMPROBANTE', None, None, None, 'Tipo de Operación', 'ENTRADAS', None, None, 'SALIDAS', None, None, 'Precio unitario'])
            ws_prev.append([None, 'Fecha', 'Tipo', 'Serie', 'Número', None, 'Cantidad', 'Costo Unitario', 'Costo Total', 'Cantidad', 'Costo Unitario', 'Costo Total', None])
            for idx in range(1, 31):
                ws_prev.append(['P-001', date(2026, 1, 3), 3, 'BS01', idx, '01 Venta', 0, 0, 0, 2, 10, 20, 18])
            buf_prev = io.BytesIO()
            wb_prev.save(buf_prev)
            confirmar_importacion_kardex(
                empresa_id=self.empresa.id, usuario=self.usuario,
                archivos=[('previo_completar.xlsx', io.BytesIO(buf_prev.getvalue()))],
                almacen_id=self.almacen.id,
            )

            # B) Sintético 8,000 filas (rollback limpio antes de 20,000)
            try:
                with transaction.atomic():
                    xls_8k = _generar_excel_sintetico(8000, n_completar=30, n_nc=160, n_compras=480)
                    self._medir_lote(
                        etiqueta='SINTETICO_8000',
                        archivos_bytes=[('sintetico_8000.xlsx', xls_8k)],
                        esperar_filas=8000,
                    )
                    raise _RollbackPass()
            except _RollbackPass:
                pass

            # C) Sintético 20,000 filas (completo: worker confirm + annul + reimport)
            try:
                with transaction.atomic():
                    xls_20k = _generar_excel_sintetico(20000, n_completar=30, n_nc=400, n_compras=1200)
                    self._medir_lote(
                        etiqueta='SINTETICO_20000',
                        archivos_bytes=[('sintetico_20000.xlsx', xls_20k)],
                        esperar_filas=20000,
                    )
                    raise _RollbackPass()
            except _RollbackPass:
                pass

    def test_03_fallo_forzado_y_reinicio_worker_en_lote_grande(self):
        with mock.patch.object(exc_mod, 'MAX_FILAS', 30000), mock.patch.object(exc_mod, 'MAX_COMPROBANTES_LOTE', 15000):
            self._preparar_escenario_sintetico(n_completar=30)
            xls_8k = _generar_excel_sintetico(8000, n_completar=30, n_nc=160, n_compras=480)
            fn = lambda: [('lote_8k.xlsx', io.BytesIO(xls_8k))]
            proveedores = {RUC_PROV: RUC_PROV}

            docs_antes = Documento.objects.filter(empresa=self.empresa).count()
            movs_antes = Movimiento.objects.filter(empresa=self.empresa).count()
            auds_antes = Auditoria.objects.filter(empresa=self.empresa).count()

            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / 'staging'
                with override_settings(IMPORTACION_STAGING_DIR=root):
                    # 1. Fallo forzado al final del lote de 8,000 filas -> rollback atómico total
                    trabajo_err = encolar_confirmacion_importacion(
                        empresa_id=self.empresa.id, usuario=self.usuario,
                        archivos=fn(), almacen_id=self.almacen.id, proveedores=proveedores,
                    )
                    orig_save = ImportacionTrabajo.save

                    def fallo_final(instancia, *args, **kwargs):
                        if instancia.estado == 'COMPLETADO':
                            raise RuntimeError('Corte forzado casi al final')
                        return orig_save(instancia, *args, **kwargs)

                    with mock.patch.object(ImportacionTrabajo, 'save', autospec=True, side_effect=fallo_final):
                        r_err = procesar_siguiente_trabajo()

                    self.assertEqual(r_err.id, trabajo_err.id)
                    self.assertEqual(r_err.estado, 'ERROR')
                    self.assertEqual(Documento.objects.filter(empresa=self.empresa).count(), docs_antes)
                    self.assertEqual(Movimiento.objects.filter(empresa=self.empresa).count(), movs_antes)
                    self.assertEqual(Auditoria.objects.filter(empresa=self.empresa).count(), auds_antes)
                    self.assertFalse((root / trabajo_err.staging_dir).exists())

                    # 2. Reinicio simulado de worker: PROCESANDO sin heartbeat -> huérfano ERROR -> re-subida limpia
                    huerfano = encolar_confirmacion_importacion(
                        empresa_id=self.empresa.id, usuario=self.usuario,
                        archivos=fn(), almacen_id=self.almacen.id, proveedores=proveedores,
                    )
                    huerfano.estado = 'PROCESANDO'
                    huerfano.iniciado_en = timezone.now()
                    huerfano.save(update_fields=['estado', 'iniciado_en'])
                    caches['default'].delete(clave_progreso(huerfano.id))

                    self.assertEqual(recuperar_trabajos_huerfanos(), 1)
                    huerfano.refresh_from_db()
                    self.assertEqual(huerfano.estado, 'ERROR')

                    limpio = encolar_confirmacion_importacion(
                        empresa_id=self.empresa.id, usuario=self.usuario,
                        archivos=fn(), almacen_id=self.almacen.id, proveedores=proveedores,
                    )
                    res_ok = procesar_siguiente_trabajo()
                    self.assertEqual(res_ok.id, limpio.id)
                    self.assertEqual(res_ok.estado, 'COMPLETADO', res_ok.error_detalle)
                    self.assertEqual(ImportacionLote.objects.filter(empresa=self.empresa, estado='CONFIRMADO').count(), 2)
                    print('\n[FALLO FORZADO + HUERFANO 8000 FILAS] Rollback y recuperación limpia OK')


class ConcurrenciaMasivaYManualTests(_MixinBaseEstres, Bloque2Fixture, TransactionTestCase):
    serialized_rollback = True

    def test_04_concurrencia_misma_empresa_distinta_y_cierre_periodo(self):
        self.crear_base()
        TipoComprobante.objects.get_or_create(codigo_sunat='03', defaults={'descripcion': 'BOLETA'})
        self._preparar_periodos(2026)
        p1 = self.crear_producto('P-001')
        p2 = self.crear_producto('P-002')
        self.documento_confirmado('COMPRA', [
            self.linea('COMPRA', '10000', '10', producto=p1),
            self.linea('COMPRA', '10000', '10', producto=p2),
        ], fecha='2026-01-01')

        est_otra = Establecimiento.objects.create(empresa=self.otra_empresa, codigo_sunat='0000', nombre='OTRA')
        ConfigEmpresa.objects.create(empresa=self.otra_empresa, establecimiento_principal=est_otra)
        otra_almacen = Almacen.objects.create(empresa=self.otra_empresa, establecimiento=est_otra, codigo='AL2', nombre='OTRO')
        Periodo.objects.create(
            empresa=self.otra_empresa, anio=2026, mes=1, orden=202601,
            fecha_inicio=date(2026, 1, 1), fecha_fin=date(2026, 1, 31), estado='ABIERTO',
        )
        p_otra = Producto.objects.create(
            empresa=self.otra_empresa, codigo_interno='P-001', descripcion='PROD OTRA',
            tipo_existencia_codigo=self.tipo_existencia,
        )
        from apps.inventario.models import ProductoUnidad
        ProductoUnidad.objects.create(
            producto=p_otra, unidad_codigo=self.und,
            factor_a_base=Decimal('1.00000000'), es_base=True,
        )
        UsuarioEmpresa.objects.create(usuario=self.usuario, empresa=self.otra_empresa, rol='ADMIN')

        def hacer_excel(serie: str, ini: int, cantidad_comprobantes: int, prod: str = 'P-001'):
            wb = Workbook(write_only=True)
            ws = wb.create_sheet()
            ws.append([None, 'COMPROBANTE', None, None, None, 'Tipo de Operación', 'ENTRADAS', None, None, 'SALIDAS', None, None, 'RUC/DNI', 'Precio unitario'])
            ws.append([None, 'Fecha', 'Tipo', 'Serie', 'Número', None, 'Cantidad', 'Costo Unitario', 'Costo Total', 'Cantidad', 'Costo Unitario', 'Costo Total', None, None])
            for idx in range(ini, ini + cantidad_comprobantes):
                ws.append([prod, date(2026, 1, 5), 1, serie, idx, '02 Compra', 5, 11, 55, 0, 0, 0, RUC_PROV, None])
            buf = io.BytesIO()
            wb.save(buf)
            return buf.getvalue()

        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(IMPORTACION_STAGING_DIR=Path(tmp) / 'staging'):
                # 1. Dos cargas simultáneas en la misma empresa (serializadas) + 1 de otra empresa (paralela)
                t_a1 = encolar_confirmacion_importacion(
                    empresa_id=self.empresa.id, usuario=self.usuario,
                    archivos=[('a1.xlsx', io.BytesIO(hacer_excel('FC01', 1, 50)))],
                    almacen_id=self.almacen.id, proveedores={RUC_PROV: RUC_PROV},
                )
                t_a2 = encolar_confirmacion_importacion(
                    empresa_id=self.empresa.id, usuario=self.usuario,
                    archivos=[('a2.xlsx', io.BytesIO(hacer_excel('FC02', 1, 50)))],
                    almacen_id=self.almacen.id, proveedores={RUC_PROV: RUC_PROV},
                )
                t_b1 = encolar_confirmacion_importacion(
                    empresa_id=self.otra_empresa.id, usuario=self.usuario,
                    archivos=[('b1.xlsx', io.BytesIO(hacer_excel('FC03', 1, 50)))],
                    almacen_id=otra_almacen.id, proveedores={RUC_PROV: RUC_PROV},
                )

                barrera = threading.Barrier(3)
                errores = []
                orden_empresa_a = []
                lock_orden = threading.Lock()
                orig_confirmar = conf_mod.confirmar_importacion_kardex

                def tracked_confirmar(**kwargs):
                    eid = kwargs['empresa_id']
                    if eid == self.empresa.id:
                        with lock_orden:
                            orden_empresa_a.append(('start', len(orden_empresa_a)))
                    res = orig_confirmar(**kwargs)
                    if eid == self.empresa.id:
                        with lock_orden:
                            orden_empresa_a.append(('end', len(orden_empresa_a)))
                    return res

                def correr():
                    try:
                        barrera.wait(timeout=10)
                        while procesar_siguiente_trabajo() is not None:
                            pass
                    except Exception as exc:  # noqa: BLE001
                        errores.append(exc)
                    finally:
                        connection.close()

                with mock.patch('apps.documentos.importacion_worker.confirmar_importacion_kardex', side_effect=tracked_confirmar):
                    hilos = [threading.Thread(target=correr) for _ in range(3)]
                    for h in hilos:
                        h.start()
                    for h in hilos:
                        h.join(timeout=60)

                self.assertEqual(errores, [])
                for t in (t_a1, t_a2, t_b1):
                    t.refresh_from_db()
                    self.assertEqual(t.estado, 'COMPLETADO', t.error_detalle)
                # Nunca dos inicios consecutivos sin cerrar el anterior en la misma empresa
                self.assertEqual([ev for ev, _ in orden_empresa_a], ['start', 'end', 'start', 'end'])

                # 2. Confirmación manual concurrente sobre el mismo producto P-001 + lote masivo
                doc_manual_id = self.crear(
                    self.payload('COMPRA', [self.linea('COMPRA', '7', '10', producto=p1)], fecha='2026-01-06')
                ).data['id']
                self.revisar(doc_manual_id)
                from apps.documentos.services import confirmar_documento_validacion
                t_a3 = encolar_confirmacion_importacion(
                    empresa_id=self.empresa.id, usuario=self.usuario,
                    archivos=[('a3.xlsx', io.BytesIO(hacer_excel('FC04', 1, 20)))],
                    almacen_id=self.almacen.id, proveedores={RUC_PROV: RUC_PROV},
                )
                barrera_2 = threading.Barrier(2)
                errores_2 = []

                def hilo_lote():
                    try:
                        barrera_2.wait(timeout=10)
                        res = procesar_siguiente_trabajo()
                        assert res is not None and res.estado == 'COMPLETADO', getattr(res, 'error_detalle', None)
                    except Exception as exc:  # noqa: BLE001
                        errores_2.append(exc)
                    finally:
                        connection.close()

                def hilo_manual():
                    try:
                        barrera_2.wait(timeout=10)
                        confirmar_documento_validacion(doc_manual_id, self.empresa.id, self.usuario.id)
                    except Exception as exc:  # noqa: BLE001
                        errores_2.append(exc)
                    finally:
                        connection.close()

                hl = threading.Thread(target=hilo_lote)
                hm = threading.Thread(target=hilo_manual)
                hl.start()
                hm.start()
                hl.join(timeout=60)
                hm.join(timeout=60)
                self.assertEqual(errores_2, [])
                # Saldo P-001 = 10000 inicial + 50*5 (a1) + 50*5 (a2) + 20*5 (a3) + 7 (manual) = 10607
                saldo_p1 = SaldoCppActual.objects.get(empresa=self.empresa, producto=p1)
                self.assertEqual(saldo_p1.cantidad_total, Decimal('10607.00000000'))

                # 3. Cierre de período mientras se intenta encolar/procesar otro lote del período cerrado
                cerrar_periodo(empresa_id=self.empresa.id, periodo_id=self.enero.id, usuario=self.usuario)
                t_cerrado = encolar_confirmacion_importacion(
                    empresa_id=self.empresa.id, usuario=self.usuario,
                    archivos=[('cerrado.xlsx', io.BytesIO(hacer_excel('FC09', 1, 5)))],
                    almacen_id=self.almacen.id, proveedores={RUC_PROV: RUC_PROV},
                )
                r_cerrado = procesar_siguiente_trabajo()
                self.assertEqual(r_cerrado.id, t_cerrado.id)
                self.assertEqual(r_cerrado.estado, 'ERROR')
                self.assertIsNone(r_cerrado.lote_id)
                self.assertEqual(ImportacionLote.objects.filter(empresa=self.empresa).count(), 3)
                self.assertTrue(bool(r_cerrado.error_detalle))
                print('\n[CONCURRENCIA + MANUAL + CIERRE PERIODO OK]')
