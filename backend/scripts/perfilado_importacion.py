"""
Script temporal de perfilado — Paso 1 (sin modificar lógica de producción ni BD real).
Ejecutar con:
  .venv\\Scripts\\python.exe backend\\manage.py test apps.documentos.tests_perfilado_paso1 -v 2
"""
import contextlib
import io
import re
import sys
import time
import tracemalloc
from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.db import connection, transaction
from django.test import TestCase
from openpyxl import Workbook

from apps.catalogos.models import TipoComprobante
from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.documentos.importacion_kardex_confirmar import anular_lote_importacion, confirmar_importacion_kardex
from apps.documentos.importacion_kardex_excel import previsualizar_importacion_kardex
from apps.empresas.models import Periodo

RUC_PROV = '20555000111'
ARCHIVO_BETOTAL = r'd:\fact-kard\archivos\011004 - BETOTAL.xlsx'
ARCHIVO_PHYTEX = r'd:\fact-kard\archivos\011049 - PHYTEX 500.xlsx'

_RE_VALUES = re.compile(r'VALUES\s*\([^)]+\)', re.IGNORECASE)
_RE_IN = re.compile(r'IN\s*\([^)]+\)', re.IGNORECASE)


class _RollbackPass(Exception):
    pass


def _normalizar_sql(sql: str) -> str:
    s = ' '.join(sql.split())
    s = _RE_VALUES.sub('VALUES (...)', s)
    s = _RE_IN.sub('IN (...)', s)
    if len(s) > 170:
        s = s[:170] + '...'
    return s


class _Perfilador:
    def __init__(self, track_ram: bool = False):
        self.stack = []
        self.last_ts = None
        self.tiempo = defaultdict(float)
        self.queries = defaultdict(int)
        self.sql_tiempo = defaultdict(float)
        self.sql_por_patron = defaultdict(lambda: {'count': 0, 'time': 0.0, 'fase': ''})
        self.track_ram = track_ram
        self.ram_pico_mb = defaultdict(float)
        self.sub_tiempo = defaultdict(float)
        self.sub_queries = defaultdict(int)

    def _flush_time(self):
        now = time.perf_counter()
        if self.stack and self.last_ts is not None:
            self.tiempo[self.stack[-1]] += now - self.last_ts
        self.last_ts = now

    @contextlib.contextmanager
    def phase(self, nombre: str):
        self._flush_time()
        self.stack.append(nombre)
        if self.track_ram:
            tracemalloc.reset_peak()
        try:
            yield
        finally:
            if self.track_ram:
                _, peak = tracemalloc.get_traced_memory()
                peak_mb = peak / (1024 * 1024)
                if peak_mb > self.ram_pico_mb[nombre]:
                    self.ram_pico_mb[nombre] = peak_mb
            self._flush_time()
            self.stack.pop()

    def execute_wrapper(self, execute, sql, params, many, context):
        fase = self.stack[-1] if self.stack else 'OTRO'
        t0 = time.perf_counter()
        try:
            return execute(sql, params, many, context)
        finally:
            dt = time.perf_counter() - t0
            self.queries[fase] += 1
            self.sql_tiempo[fase] += dt
            patron = f'[{fase}] {_normalizar_sql(sql)}'
            entry = self.sql_por_patron[patron]
            entry['count'] += 1
            entry['time'] += dt
            entry['fase'] = fase


@contextlib.contextmanager
def _instrumentar(profiler: _Perfilador):
    import apps.auditoria.services as aud_srv
    import apps.documentos.importacion_kardex_confirmar as conf_mod
    import apps.documentos.importacion_kardex_excel as exc_mod
    import apps.documentos.services as doc_srv
    import apps.kardex.services as kar_srv

    orig_leer = exc_mod.leer_archivo
    orig_analizar = exc_mod._analizar
    orig_modo_lote = conf_mod.modo_lote_kardex
    orig_aud = aud_srv.registrar_auditoria

    # Sub-instrumentación de Fase 2
    orig_validar = exc_mod._validar_contexto
    orig_emparejar = exc_mod._emparejar_devoluciones
    orig_existentes = exc_mod._existentes
    orig_comparar = exc_mod.comparar_con_registrado
    orig_simular = exc_mod._simular_stock

    def wrapped_sub(name, fn):
        def inner(*args, **kwargs):
            t0 = time.perf_counter()
            q0 = profiler.queries.get(profiler.stack[-1] if profiler.stack else 'OTRO', 0)
            try:
                return fn(*args, **kwargs)
            finally:
                profiler.sub_tiempo[name] += time.perf_counter() - t0
                q1 = profiler.queries.get(profiler.stack[-1] if profiler.stack else 'OTRO', 0)
                profiler.sub_queries[name] += max(0, q1 - q0)
        return inner

    def wrapped_leer(*args, **kwargs):
        with profiler.phase('Fase 1: Lectura Excel'):
            return orig_leer(*args, **kwargs)

    def wrapped_analizar(*args, **kwargs):
        with profiler.phase('Fase 2: Analisis (_analizar)'):
            return orig_analizar(*args, **kwargs)

    @contextlib.contextmanager
    def wrapped_modo_lote(**kwargs):
        cm = orig_modo_lote(**kwargs)
        cm.__enter__()
        exc_info = (None, None, None)
        try:
            yield
        except BaseException:
            exc_info = sys.exc_info()
            raise
        finally:
            fase_recalc = (
                'Fase 6: Anulacion'
                if (profiler.stack and profiler.stack[-1] == 'Fase 6: Anulacion')
                else 'Fase 5: Recalculo Kardex'
            )
            with profiler.phase(fase_recalc):
                cm.__exit__(*exc_info)

    def wrapped_aud(*args, **kwargs):
        fase_aud = (
            'Fase 6: Anulacion'
            if (profiler.stack and profiler.stack[-1] == 'Fase 6: Anulacion')
            else 'Fase 4: Auditoria'
        )
        with profiler.phase(fase_aud):
            return orig_aud(*args, **kwargs)

    exc_mod.leer_archivo = wrapped_leer
    exc_mod._analizar = wrapped_analizar
    conf_mod._analizar = wrapped_analizar
    conf_mod.modo_lote_kardex = wrapped_modo_lote
    aud_srv.registrar_auditoria = wrapped_aud
    doc_srv.registrar_auditoria = wrapped_aud
    kar_srv.registrar_auditoria = wrapped_aud
    conf_mod.registrar_auditoria = wrapped_aud

    exc_mod._validar_contexto = wrapped_sub('F2._validar_contexto', orig_validar)
    exc_mod._emparejar_devoluciones = wrapped_sub('F2._emparejar_devoluciones', orig_emparejar)
    exc_mod._existentes = wrapped_sub('F2._existentes', orig_existentes)
    exc_mod.comparar_con_registrado = wrapped_sub('F2.comparar_con_registrado', orig_comparar)
    exc_mod._simular_stock = wrapped_sub('F2._simular_stock', orig_simular)

    try:
        if profiler.track_ram:
            yield
        else:
            with connection.execute_wrapper(profiler.execute_wrapper):
                yield
    finally:
        exc_mod.leer_archivo = orig_leer
        exc_mod._analizar = orig_analizar
        conf_mod._analizar = orig_analizar
        conf_mod.modo_lote_kardex = orig_modo_lote
        aud_srv.registrar_auditoria = orig_aud
        doc_srv.registrar_auditoria = orig_aud
        kar_srv.registrar_auditoria = orig_aud
        conf_mod.registrar_auditoria = orig_aud

        exc_mod._validar_contexto = orig_validar
        exc_mod._emparejar_devoluciones = orig_emparejar
        exc_mod._existentes = orig_existentes
        exc_mod.comparar_con_registrado = orig_comparar
        exc_mod._simular_stock = orig_simular


def _generar_excel_sintetico_5000():
    """
    Genera exactamente 5,000 filas (1,480 comprobantes) en 12 meses de 2026:
    - 30 comprobantes COMPLETAR (60 filas: P-001 existente + P-002 nuevo)
    - 300 compras NUEVAS (1,200 filas: 25/mes x 4 líneas)
    - 1,050 ventas NUEVAS (3,640 filas: 560x3 + 490x4 líneas)
    - 100 devoluciones entre meses (100 filas en meses 2..12 devolviendo ventas del mes anterior)
    """
    wb = Workbook()
    ws = wb.active
    ws.append([None, 'COMPROBANTE', None, None, None, 'Tipo de Operación', 'ENTRADAS', None, None, 'SALIDAS', None, None, 'RUC/DNI', 'Precio unitario'])
    ws.append([None, 'Fecha', 'Tipo', 'Serie', 'Número', None, 'Cantidad', 'Costo Unitario', 'Costo Total', 'Cantidad', 'Costo Unitario', 'Costo Total', None, None])

    productos = [f'P-{i:03d}' for i in range(1, 11)]
    filas_totales = 0

    # 1. 30 comprobantes COMPLETAR (60 filas) en 2026-01-03
    for idx in range(1, 31):
        ws.append(['P-001', date(2026, 1, 3), 3, 'BS01', idx, '01 Venta', 0, 0, 0, 2, 10, 20, '', 18])
        ws.append(['P-002', date(2026, 1, 3), 3, 'BS01', idx, '01 Venta', 0, 0, 0, 2, 10, 20, '', 18])
        filas_totales += 2

    # 2. 300 compras (25 por mes, 4 líneas c/u = 1200 filas)
    num_compra = 1
    for mes in range(1, 13):
        for c in range(25):
            dia = 2 + (c % 20)
            for l in range(4):
                prod = productos[(num_compra + l) % len(productos)]
                ws.append([prod, date(2026, mes, dia), 1, 'FC01', num_compra, '02 Compra', 50, 11, 550, 0, 0, 0, RUC_PROV, None])
                filas_totales += 1
            num_compra += 1

    # 3. 1050 ventas (560 x 3 líneas + 490 x 4 líneas = 3640 filas)
    ventas_por_mes = [88] * 6 + [87] * 6  # suma 1050
    num_venta = 1
    ventas_registradas_mes = defaultdict(list)
    for mes in range(1, 13):
        for v in range(ventas_por_mes[mes - 1]):
            dia = 5 + (v % 22)
            n_lineas = 4 if num_venta <= 490 else 3
            for l in range(n_lineas):
                prod = productos[(num_venta + l) % len(productos)]
                ws.append([prod, date(2026, mes, dia), 1, 'FV01', num_venta, '01 Venta', 0, 0, 0, 2, 10.5, 21, '20666000111', 20])
                filas_totales += 1
                if l == 0:
                    ventas_registradas_mes[mes].append((prod, Decimal('2')))
            num_venta += 1

    # 4. 100 devoluciones entre meses (meses 2..12 devolviendo ventas del mes anterior)
    num_nc = 1
    for i in range(100):
        mes_origen = (i % 11) + 1
        mes_nc = mes_origen + 1
        prod, _ = ventas_registradas_mes[mes_origen][i // 11]
        dia_nc = 1 + (i % 15)
        ws.append([prod, date(2026, mes_nc, dia_nc), 7, 'NC01', num_nc, '05 Devolución Recibida', 2, 0, 0, 0, 0, 0, '20666000111', None])
        filas_totales += 1
        num_nc += 1

    assert filas_totales == 5000, f'Esperadas 5000 filas, obtenidas {filas_totales}'
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


class PerfiladoImportacionPaso1Tests(Bloque2Fixture, TestCase):
    def _preparar_periodos(self, anio: int):
        res = {}
        for mes in range(1, 13):
            if anio == 2026 and mes == 1:
                res[1] = self.enero
                continue
            fin = date(anio, 12, 31) if mes == 12 else (date(anio, mes + 1, 1) - date.resolution)
            res[mes] = Periodo.objects.create(
                empresa=self.empresa, anio=anio, mes=mes, orden=anio * 100 + mes,
                fecha_inicio=date(anio, mes, 1), fecha_fin=fin, estado='ABIERTO',
            )
        return res

    def _perfilar_escenario(self, nombre_escenario: str, archivos_bytes: list):
        archivos_fn = lambda: [(n, io.BytesIO(b)) for n, b in archivos_bytes]
        proveedores = {}

        prev_inicial = previsualizar_importacion_kardex(empresa_id=self.empresa.id, archivos=archivos_fn())
        for c in prev_inicial['comprobantes']:
            if c['requiere_proveedor'] and c['clave_proveedor']:
                proveedores[c['clave_proveedor']] = RUC_PROV

        # --- PASADA 1: Tiempos reales y SQL (en savepoint con rollback para no alterar estado para Pasada 2) ---
        prof = _Perfilador(track_ram=False)
        try:
            with transaction.atomic():
                with _instrumentar(prof):
                    prev = previsualizar_importacion_kardex(
                        empresa_id=self.empresa.id, archivos=archivos_fn(), proveedores=proveedores,
                    )
                    assert prev['resumen']['puede_confirmar'], f'Previsualización no confirmable: {prev["resumen"]}'

                    prev_t1 = prof.tiempo['Fase 1: Lectura Excel']
                    prev_q1 = prof.queries['Fase 1: Lectura Excel']
                    prev_t2 = prof.tiempo['Fase 2: Analisis (_analizar)']
                    prev_q2 = prof.queries['Fase 2: Analisis (_analizar)']
                    prev_sub_t = dict(prof.sub_tiempo)
                    prev_sub_q = dict(prof.sub_queries)

                    prof.tiempo.clear()
                    prof.queries.clear()
                    prof.sql_tiempo.clear()
                    prof.sql_por_patron.clear()

                    with prof.phase('Fase 3: ORM Comprobantes'):
                        res_conf = confirmar_importacion_kardex(
                            empresa_id=self.empresa.id, usuario=self.usuario,
                            archivos=archivos_fn(), almacen_id=self.almacen.id, proveedores=proveedores,
                        )
                    with prof.phase('Fase 6: Anulacion'):
                        res_anul = anular_lote_importacion(
                            empresa_id=self.empresa.id, lote_id=res_conf['lote'],
                            usuario=self.usuario, motivo='Perfilado Paso 1',
                        )
                raise _RollbackPass()
        except _RollbackPass:
            pass

        # --- PASADA 2: Pico de RAM (tracemalloc) por fase ---
        prof_ram = _Perfilador(track_ram=True)
        tracemalloc.start()
        try:
            with transaction.atomic():
                with _instrumentar(prof_ram):
                    previsualizar_importacion_kardex(
                        empresa_id=self.empresa.id, archivos=archivos_fn(), proveedores=proveedores,
                    )
                    ram_f1_prev = prof_ram.ram_pico_mb['Fase 1: Lectura Excel']
                    ram_f2_prev = prof_ram.ram_pico_mb['Fase 2: Analisis (_analizar)']
                    prof_ram.ram_pico_mb.clear()

                    with prof_ram.phase('Fase 3: ORM Comprobantes'):
                        res_conf_ram = confirmar_importacion_kardex(
                            empresa_id=self.empresa.id, usuario=self.usuario,
                            archivos=archivos_fn(), almacen_id=self.almacen.id, proveedores=proveedores,
                        )
                    with prof_ram.phase('Fase 6: Anulacion'):
                        anular_lote_importacion(
                            empresa_id=self.empresa.id, lote_id=res_conf_ram['lote'],
                            usuario=self.usuario, motivo='Perfilado Paso 1 RAM',
                        )
                raise _RollbackPass()
        except _RollbackPass:
            pass
        finally:
            tracemalloc.stop()

        print(f'\n==================== {nombre_escenario} ====================')
        print(f"Resumen: filas={prev['resumen']['filas']}, comprobantes={prev['resumen']['comprobantes']}, "
              f"nuevos={prev['resumen']['nuevos']}, completar={prev['resumen']['completar']}, "
              f"lineas_agregar={prev['resumen']['lineas_a_agregar']}, "
              f"anulados={res_anul['comprobantes_anulados']}, revertidas={res_anul['lineas_revertidas']}")
        print(f"Previsualizacion sola: F1={prev_t1:.3f}s ({prev_q1} q, {ram_f1_prev:.2f}MB) | "
              f"F2={prev_t2:.3f}s ({prev_q2} q, {ram_f2_prev:.2f}MB)")
        print('  Sub-etapas F2 (Previsualizacion): ' + ', '.join(
            f"{k}={prev_sub_t.get(k, 0):.3f}s ({prev_sub_q.get(k, 0)}q)"
            for k in ('F2._validar_contexto', 'F2._emparejar_devoluciones', 'F2._existentes',
                      'F2.comparar_con_registrado', 'F2._simular_stock')
        ))
        fases = [
            'Fase 1: Lectura Excel',
            'Fase 2: Analisis (_analizar)',
            'Fase 3: ORM Comprobantes',
            'Fase 4: Auditoria',
            'Fase 5: Recalculo Kardex',
            'Fase 6: Anulacion',
        ]
        total_conf_t = sum(prof.tiempo[f] for f in fases[:5])
        total_conf_q = sum(prof.queries[f] for f in fases[:5])
        print(f"Desglose Confirmar (F1..F5 total={total_conf_t:.3f}s, {total_conf_q} q) + Anular (F6):")
        for f in fases:
            print(f"  {f:32s} | {prof.tiempo[f]:7.3f}s | {prof_ram.ram_pico_mb[f]:6.2f} MB | {prof.queries[f]:6d} queries (SQL {prof.sql_tiempo[f]:6.3f}s)")

        top_tiempo = sorted(prof.sql_por_patron.items(), key=lambda kv: kv[1]['time'], reverse=True)[:10]
        print('--- TOP 10 SQL POR TIEMPO ---')
        for pat, info in top_tiempo:
            print(f"  {info['time']:.4f}s | {info['count']:6d}x | {pat}")
        top_count = sorted(prof.sql_por_patron.items(), key=lambda kv: kv[1]['count'], reverse=True)[:10]
        print('--- TOP 10 SQL POR CANTIDAD ---')
        for pat, info in top_count:
            print(f"  {info['count']:6d}x | {info['time']:.4f}s | {pat}")

    def test_perfilado_escenario_a_y_b(self):
        self.crear_base()
        TipoComprobante.objects.get_or_create(codigo_sunat='03', defaults={'descripcion': 'BOLETA'})

        # --- ESCENARIO A: BETOTAL + PHYTEX 500 ---
        p_bet = self.crear_producto('011004')
        p_phy = self.crear_producto('011049')
        periodos_2023 = self._preparar_periodos(2023)
        self.documento_confirmado('COMPRA', [
            self.linea('COMPRA', '100', '34', producto=p_bet),
            self.linea('COMPRA', '250', '20', producto=p_phy),
        ], fecha='2023-01-01', periodo=periodos_2023[1])

        with open(ARCHIVO_BETOTAL, 'rb') as f1, open(ARCHIVO_PHYTEX, 'rb') as f2:
            archivos_a = [('011004 - BETOTAL.xlsx', f1.read()), ('011049 - PHYTEX 500.xlsx', f2.read())]
        self._perfilar_escenario('ESCENARIO A: BETOTAL + PHYTEX 500 (Reales)', archivos_a)

        # --- ESCENARIO B: 5000 filas sinteticas ---
        self._preparar_periodos(2026)
        prods = [self.crear_producto(f'P-{i:03d}') for i in range(1, 11)]
        self.documento_confirmado('COMPRA', [
            self.linea('COMPRA', '10000', '10', producto=p) for p in prods
        ], fecha='2026-01-01')

        # Lote previo con 30 ventas BS01-1..30 de P-001 para probar estado COMPLETAR en el lote de 5000 filas
        wb_prev = Workbook()
        ws_prev = wb_prev.active
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

        excel_5000 = _generar_excel_sintetico_5000()
        self._perfilar_escenario('ESCENARIO B: SINTETICO 5000 FILAS (1480 comprobantes)', [('sintetico_5000.xlsx', excel_5000)])
