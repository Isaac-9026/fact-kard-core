"""
Tests obligatorios del Paso 3 (`importacion_worker`, comando `procesar_trabajos_importacion` y endpoints `202`):
1. Flujo completo `202` -> `procesar_siguiente_trabajo()` -> `COMPLETADO` para `CONFIRMAR` y `ANULAR`.
2. Fallo forzado cerca del final de confirmación: rollback total (0 comprobantes, 0 movimientos,
   0 auditoría contable, 0 lotes) y trabajo en `ERROR` con staging limpio.
3. Reintento / idempotencia: no duplica comprobantes ni movimientos; tras anular vía worker permite reimportar.
4. Concurrencia por empresa (`SKIP LOCKED` y `pg_advisory_xact_lock`) + rechazo de anulación duplicada.
5. Recuperación de huérfano en `PROCESANDO` sin heartbeat vigente al arrancar el worker.
6. Aislamiento multiempresa en `GET /trabajos/<id>/` y `GET /trabajos/`, y tolerancia a fallo de Redis.
"""
import tempfile
import threading
import time
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.core.cache import caches
from django.core.management import call_command
from django.db import connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.auditoria.models import Auditoria
from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.documentos.importacion_worker import (
    MENSAJE_HUERFANO,
    adquirir_lock_empresa,
    clave_progreso,
    ejecutar_trabajo,
    encolar_confirmacion_importacion,
    leer_progreso,
    procesar_siguiente_trabajo,
    reportar_progreso,
)
from apps.documentos.models import Documento, ImportacionLote, ImportacionTrabajo
from apps.documentos.tests_importacion_kardex import OPC, compra, excel, venta
from apps.empresas.models import ConfigEmpresa, Establecimiento, Periodo
from apps.inventario.models import Almacen, Producto, ProductoUnidad
from apps.kardex.models import Movimiento
from apps.usuarios.models import Usuario, UsuarioEmpresa


class ImportacionWorkerPaso3Tests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()
        self.p1 = self.crear_producto('011004')

    def _archivo(self, numero=1081):
        buf = excel([
            compra('011004', 3, 'F035', numero, 10, 12),
            venta('011004', 5, 1, 'F001', numero, 2, 15, ('',)),
        ], OPC)
        buf.name = f'lote_{numero}.xlsx'
        return buf

    def test_flujo_completo_202_worker_confirmar_anular_y_reimportar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'staging'
            with override_settings(IMPORTACION_STAGING_DIR=root):
                # 1. Confirmar vía HTTP -> 202 Accepted
                resp_conf = self.client.post(
                    reverse('importacion-entradas-salidas-confirmar'),
                    {'archivos': [self._archivo(101)], 'almacen': self.almacen.id},
                    format='multipart',
                    **self.headers,
                )
                self.assertEqual(resp_conf.status_code, 202, resp_conf.data)
                trabajo_conf_id = resp_conf.data['trabajo_id']
                self.assertEqual(resp_conf.data['estado'], 'EN_COLA')

                # 2. Procesar con worker -> COMPLETADO
                trabajo_conf = procesar_siguiente_trabajo()
                self.assertIsNotNone(trabajo_conf)
                self.assertEqual(trabajo_conf.id, trabajo_conf_id)
                self.assertEqual(trabajo_conf.estado, 'COMPLETADO')
                self.assertIsNotNone(trabajo_conf.lote_id)
                self.assertIsNotNone(trabajo_conf.finalizado_en)
                self.assertEqual(trabajo_conf.resumen_json['comprobantes'], 2)
                self.assertFalse((root / trabajo_conf.staging_dir).exists())
                self.assertEqual(Documento.objects.filter(empresa=self.empresa, estado='CONFIRMADO').count(), 2)
                self.assertEqual(Movimiento.objects.filter(empresa=self.empresa).count(), 2)

                progreso_cache = leer_progreso(trabajo_conf_id)
                self.assertIsNotNone(progreso_cache)
                self.assertEqual(progreso_cache['fase'], 'COMPLETADO')
                self.assertIn('heartbeat', progreso_cache)

                # Idempotencia: llamar de nuevo con cola vacía o sobre trabajo ya completado no duplica
                self.assertIsNone(procesar_siguiente_trabajo())
                ejecutar_trabajo(trabajo_conf_id)
                self.assertEqual(Documento.objects.filter(empresa=self.empresa, estado='CONFIRMADO').count(), 2)
                self.assertEqual(Movimiento.objects.filter(empresa=self.empresa).count(), 2)

                # 3. Anular vía HTTP -> 202 Accepted (sin guardar contraseña en BD)
                url_anular = reverse('importacion-lote-anular', args=[trabajo_conf.lote_id])
                resp_anular = self.client.post(
                    url_anular,
                    {'motivo': 'Anulación de prueba completa', 'password_confirmacion': self.PASSWORD_PRUEBAS},
                    format='json',
                    **self.headers,
                )
                self.assertEqual(resp_anular.status_code, 202, resp_anular.data)
                trabajo_anular_id = resp_anular.data['trabajo_id']
                t_anular = ImportacionTrabajo.objects.get(pk=trabajo_anular_id)
                self.assertEqual(t_anular.parametros_json, {'motivo': 'Anulación de prueba completa'})
                self.assertNotIn('password_confirmacion', t_anular.parametros_json)

                # Rechaza anulación duplicada mientras la primera está activa (EN_COLA o PROCESANDO)
                dup = self.client.post(
                    url_anular,
                    {'motivo': 'Intento duplicado', 'password_confirmacion': self.PASSWORD_PRUEBAS},
                    format='json',
                    **self.headers,
                )
                self.assertEqual(dup.status_code, 400)

                # Procesar anulación
                res_anular = procesar_siguiente_trabajo()
                self.assertEqual(res_anular.id, trabajo_anular_id)
                self.assertEqual(res_anular.estado, 'COMPLETADO')
                self.assertEqual(ImportacionLote.objects.get(pk=trabajo_conf.lote_id).estado, 'ANULADO')
                self.assertEqual(Documento.objects.filter(empresa=self.empresa, estado='CONFIRMADO').count(), 0)

                # 4. Tras anular vía worker, permite reimportar el mismo archivo exacto
                resp_reimp = self.client.post(
                    reverse('importacion-entradas-salidas-confirmar'),
                    {'archivos': [self._archivo(101)], 'almacen': self.almacen.id},
                    format='multipart',
                    **self.headers,
                )
                self.assertEqual(resp_reimp.status_code, 202)
                res_reimp = procesar_siguiente_trabajo()
                self.assertEqual(res_reimp.estado, 'COMPLETADO')
                self.assertNotEqual(res_reimp.lote_id, trabajo_conf.lote_id)
                self.assertEqual(Documento.objects.filter(empresa=self.empresa, estado='CONFIRMADO').count(), 2)

    def test_fallo_forzado_al_final_revierte_todo_y_marca_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'staging'
            with override_settings(IMPORTACION_STAGING_DIR=root):
                auditorias_antes = Auditoria.objects.filter(empresa=self.empresa).count()
                trabajo = encolar_confirmacion_importacion(
                    empresa_id=self.empresa.id,
                    usuario=self.usuario,
                    archivos=[('fallo.xlsx', self._archivo(202))],
                    almacen_id=self.almacen.id,
                )

                # Falla justo cuando ya se grabaron comprobantes y auditoría del lote, al cerrar el trabajo
                original_save = ImportacionTrabajo.save

                def fallo_al_completar(instancia, *args, **kwargs):
                    if instancia.estado == 'COMPLETADO':
                        raise RuntimeError('Fallo forzado antes del commit final')
                    return original_save(instancia, *args, **kwargs)

                with mock.patch.object(ImportacionTrabajo, 'save', autospec=True, side_effect=fallo_al_completar):
                    resultado = procesar_siguiente_trabajo()

                self.assertEqual(resultado.estado, 'ERROR')
                self.assertIsNotNone(resultado.finalizado_en)
                self.assertTrue(bool(resultado.error_detalle))
                self.assertFalse((root / trabajo.staging_dir).exists())
                # Rollback total: 0 comprobantes, 0 movimientos, 0 auditoría contable, 0 lotes
                self.assertEqual(ImportacionLote.objects.filter(empresa=self.empresa).count(), 0)
                self.assertEqual(Documento.objects.filter(empresa=self.empresa).count(), 0)
                self.assertEqual(Movimiento.objects.filter(empresa=self.empresa).count(), 0)
                self.assertEqual(Auditoria.objects.filter(empresa=self.empresa).count(), auditorias_antes)

    def test_recuperacion_de_huerfanos_sin_heartbeat_al_arrancar_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'staging'
            with override_settings(IMPORTACION_STAGING_DIR=root):
                # Huérfano 1: sin clave de progreso en Redis
                h_sin_redis = encolar_confirmacion_importacion(
                    empresa_id=self.empresa.id,
                    usuario=self.usuario,
                    archivos=[('h1.xlsx', self._archivo(301))],
                    almacen_id=self.almacen.id,
                )
                h_sin_redis.estado = 'PROCESANDO'
                h_sin_redis.iniciado_en = timezone.now() - timedelta(minutes=10)
                h_sin_redis.save(update_fields=['estado', 'iniciado_en'])
                caches['default'].delete(clave_progreso(h_sin_redis.id))

                # Huérfano 2: heartbeat expirado en Redis
                h_expirado = encolar_confirmacion_importacion(
                    empresa_id=self.empresa.id,
                    usuario=self.usuario,
                    archivos=[('h2.xlsx', self._archivo(302))],
                    almacen_id=self.almacen.id,
                )
                h_expirado.estado = 'PROCESANDO'
                h_expirado.iniciado_en = timezone.now() - timedelta(minutes=10)
                h_expirado.save(update_fields=['estado', 'iniciado_en'])
                caches['default'].set(
                    clave_progreso(h_expirado.id),
                    {
                        'trabajo_id': h_expirado.id,
                        'fase': 'GRABANDO_COMPROBANTES',
                        'actual': 1,
                        'total': 5,
                        'heartbeat': (timezone.now() - timedelta(minutes=10)).isoformat(),
                    },
                    timeout=3600,
                )

                # Trabajo activo con heartbeat vigente: NO debe marcarse como huérfano
                activo = encolar_confirmacion_importacion(
                    empresa_id=self.empresa.id,
                    usuario=self.usuario,
                    archivos=[('activo.xlsx', self._archivo(303))],
                    almacen_id=self.almacen.id,
                )
                activo.estado = 'PROCESANDO'
                activo.iniciado_en = timezone.now()
                activo.save(update_fields=['estado', 'iniciado_en'])
                reportar_progreso(activo.id, 'GRABANDO_COMPROBANTES', 1, 2, 'En curso')

                vivo = Path(tmp) / 'fk-tareas.vivo'
                call_command('procesar_trabajos_importacion', once=True, archivo_vivo=str(vivo))
                self.assertTrue(vivo.is_file())

                for h in (h_sin_redis, h_expirado):
                    h.refresh_from_db()
                    self.assertEqual(h.estado, 'ERROR')
                    self.assertEqual(h.error_detalle, MENSAJE_HUERFANO)
                    self.assertIsNotNone(h.finalizado_en)
                    self.assertFalse((root / h.staging_dir).exists())

                activo.refresh_from_db()
                self.assertEqual(activo.estado, 'PROCESANDO')
                self.assertTrue((root / activo.staging_dir).is_dir())

    def test_aislamiento_multiempresa_permisos_y_fallback_redis(self):
        Almacen.objects.create(empresa=self.empresa, establecimiento=self.establecimiento, codigo='AL2', nombre='DOS')
        resp_sin_almacen = self.client.post(
            reverse('importacion-entradas-salidas-confirmar'),
            {'archivos': [self._archivo(401)]},
            format='multipart',
            **self.headers,
        )
        self.assertEqual(resp_sin_almacen.status_code, 400)
        self.assertFalse(ImportacionTrabajo.objects.exists())

        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(IMPORTACION_STAGING_DIR=tmp):
                trabajo = encolar_confirmacion_importacion(
                    empresa_id=self.empresa.id,
                    usuario=self.usuario,
                    archivos=[('ok.xlsx', self._archivo(402))],
                    almacen_id=self.almacen.id,
                )

                # Sin membresía en la empresa ajena -> 403
                headers_otra = {'HTTP_X_EMPRESA_ID': str(self.otra_empresa.id)}
                self.assertEqual(
                    self.client.get(reverse('importacion-trabajo-detail', args=[trabajo.id]), **headers_otra).status_code,
                    403,
                )

                # Admin de otra empresa -> 404 en detalle y [] en listado (aislamiento por empresa_id)
                admin_otra = Usuario.objects.create(username='admin_otra_imp', email='otra@test.pe', password_hash='x')
                UsuarioEmpresa.objects.create(usuario=admin_otra, empresa=self.otra_empresa, rol='ADMIN')
                self.client.force_authenticate(user=admin_otra)
                self.assertEqual(
                    self.client.get(reverse('importacion-trabajo-detail', args=[trabajo.id]), **headers_otra).status_code,
                    404,
                )
                lista_otra = self.client.get(reverse('importacion-trabajos'), **headers_otra)
                self.assertEqual(lista_otra.status_code, 200)
                self.assertEqual(lista_otra.data, [])
                self.client.force_authenticate(user=self.usuario)

                # Empresa propia ADMIN: ve el trabajo en lista y detalle
                detalle = self.client.get(reverse('importacion-trabajo-detail', args=[trabajo.id]), **self.headers)
                self.assertEqual(detalle.status_code, 200)
                self.assertEqual(detalle.data['trabajo_id'], trabajo.id)
                self.assertEqual(detalle.data['estado'], 'EN_COLA')

                lista = self.client.get(reverse('importacion-trabajos'), {'estado': 'EN_COLA'}, **self.headers)
                self.assertEqual(lista.status_code, 200)
                self.assertEqual([t['id'] for t in lista.data], [trabajo.id])

                # Si Redis falla por completo, el worker y el endpoint siguen funcionando
                cache_roto = mock.MagicMock()
                cache_roto.set.side_effect = ConnectionError('Redis caído')
                cache_roto.get.side_effect = ConnectionError('Redis caído')
                with mock.patch('apps.documentos.importacion_worker.caches', {'default': cache_roto}):
                    procesado = procesar_siguiente_trabajo()
                    self.assertEqual(procesado.estado, 'COMPLETADO')
                    consulta = self.client.get(reverse('importacion-trabajo-detail', args=[trabajo.id]), **self.headers)
                    self.assertEqual(consulta.status_code, 200)
                    self.assertEqual(consulta.data['estado'], 'COMPLETADO')
                    self.assertEqual(consulta.data['progreso']['fase'], 'COMPLETADO')

                # Rol USUARIO no puede consultar trabajos
                no_admin = Usuario.objects.create(username='usuario_solo', email='u@test.pe', password_hash='x')
                UsuarioEmpresa.objects.create(usuario=no_admin, empresa=self.empresa, rol='USUARIO')
                self.client.force_authenticate(user=no_admin)
                self.assertEqual(
                    self.client.get(reverse('importacion-trabajo-detail', args=[trabajo.id]), **self.headers).status_code,
                    403,
                )

    def test_progreso_actualiza_heartbeat_durante_recalculo_kardex(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'staging'
            with override_settings(IMPORTACION_STAGING_DIR=root):
                # Sembramos primero una venta posterior para forzar recálculo retroactivo en la importación
                confirmar_previo = encolar_confirmacion_importacion(
                    empresa_id=self.empresa.id,
                    usuario=self.usuario,
                    archivos=[(
                        'compra_inicial.xlsx',
                        excel([
                            compra('011004', 2, 'F035', 1, 10, 10),
                            venta('011004', 10, 1, 'F001', 2, 2, 10, ('',)),
                        ], OPC),
                    )],
                    almacen_id=self.almacen.id,
                    proveedores={'20555000111': '20555000111'},
                )
                self.assertEqual(procesar_siguiente_trabajo().estado, 'COMPLETADO', confirmar_previo.id)

                trabajo = encolar_confirmacion_importacion(
                    empresa_id=self.empresa.id,
                    usuario=self.usuario,
                    archivos=[('retroactivo.xlsx', excel([compra('011004', 5, 'F035', 3, 10, 12)], OPC))],
                    almacen_id=self.almacen.id,
                    proveedores={'20555000111': '20555000111'},
                )
                caches['default'].delete(clave_progreso(trabajo.id))

                fases = []
                orig_reportar = reportar_progreso

                def captura_progreso(trabajo_id, fase, actual=0, total=0, mensaje='', **kwargs):
                    fases.append((fase, actual, total))
                    return orig_reportar(trabajo_id, fase, actual, total, mensaje, **kwargs)

                with mock.patch('apps.documentos.importacion_worker.reportar_progreso', side_effect=captura_progreso):
                    procesado = procesar_siguiente_trabajo()

                self.assertEqual(procesado.estado, 'COMPLETADO')
                recalc = [f for f in fases if f[0] == 'RECALCULANDO_KARDEX']
                self.assertGreaterEqual(len(recalc), 2)
                self.assertEqual(recalc[-1], ('RECALCULANDO_KARDEX', 1, 1))
                self.assertEqual(leer_progreso(trabajo.id)['fase'], 'COMPLETADO')


class ImportacionConcurrenciaWorkerTests(Bloque2Fixture, TransactionTestCase):
    """Pruebas multi-conexión en PostgreSQL: `SKIP LOCKED` y `pg_advisory_xact_lock` por empresa."""

    def setUp(self):
        self.crear_base()
        self.p1 = self.crear_producto('011004')
        est_otra = Establecimiento.objects.create(empresa=self.otra_empresa, codigo_sunat='0000', nombre='PRINCIPAL OTRA')
        ConfigEmpresa.objects.create(empresa=self.otra_empresa, establecimiento_principal=est_otra)
        self.otra_almacen = Almacen.objects.create(
            empresa=self.otra_empresa, establecimiento=est_otra, codigo='ALM', nombre='ALMACEN OTRA',
        )
        Periodo.objects.create(
            empresa=self.otra_empresa, anio=2026, mes=1, orden=202601,
            fecha_inicio=date(2026, 1, 1), fecha_fin=date(2026, 1, 31), estado='ABIERTO',
        )
        self.p_otra = Producto.objects.create(
            empresa=self.otra_empresa, codigo_interno='011004', descripcion='PRODUCTO 011004 OTRA',
            tipo_existencia_codigo=self.tipo_existencia,
        )
        ProductoUnidad.objects.create(
            producto=self.p_otra, unidad_codigo=self.und, factor_a_base=Decimal('1.00000000'), es_base=True,
        )
        UsuarioEmpresa.objects.create(usuario=self.usuario, empresa=self.otra_empresa, rol='ADMIN')

    def _archivo(self, numero):
        buf = excel([compra('011004', 3, 'F035', numero, 10, 12)], OPC)
        buf.name = f'conc_{numero}.xlsx'
        return buf

    def test_skip_locked_y_serializacion_por_empresa(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'staging'
            with override_settings(IMPORTACION_STAGING_DIR=root):
                t1 = encolar_confirmacion_importacion(
                    empresa_id=self.empresa.id, usuario=self.usuario,
                    archivos=[('e1.xlsx', self._archivo(701))], almacen_id=self.almacen.id,
                )
                t2 = encolar_confirmacion_importacion(
                    empresa_id=self.otra_empresa.id, usuario=self.usuario,
                    archivos=[('e2.xlsx', self._archivo(702))], almacen_id=self.otra_almacen.id,
                )

                barrera = threading.Barrier(2)
                reclamados = []
                errores = []

                def correr_worker():
                    try:
                        barrera.wait(timeout=10)
                        res = procesar_siguiente_trabajo()
                        if res is not None:
                            reclamados.append(res.id)
                    except Exception as exc:  # noqa: BLE001
                        errores.append(exc)
                    finally:
                        connection.close()

                h1 = threading.Thread(target=correr_worker)
                h2 = threading.Thread(target=correr_worker)
                h1.start()
                h2.start()
                h1.join(timeout=30)
                h2.join(timeout=30)

                self.assertEqual(errores, [])
                self.assertEqual(sorted(reclamados), sorted([t1.id, t2.id]))
                t1.refresh_from_db()
                t2.refresh_from_db()
                self.assertEqual((t1.estado, t2.estado), ('COMPLETADO', 'COMPLETADO'))

        if connection.vendor == 'postgresql':
            eventos = []
            lock_tomado = threading.Event()
            liberar = threading.Event()
            segundo_esperando = threading.Event()

            def hilo_1():
                try:
                    with transaction.atomic():
                        adquirir_lock_empresa(self.empresa.id)
                        eventos.append('inicio_1')
                        lock_tomado.set()
                        liberar.wait(timeout=5)
                        eventos.append('fin_1')
                finally:
                    connection.close()

            def hilo_2():
                try:
                    lock_tomado.wait(timeout=5)
                    segundo_esperando.set()
                    with transaction.atomic():
                        adquirir_lock_empresa(self.empresa.id)
                        eventos.append('inicio_2')
                        eventos.append('fin_2')
                finally:
                    connection.close()

            a = threading.Thread(target=hilo_1)
            b = threading.Thread(target=hilo_2)
            a.start()
            b.start()
            segundo_esperando.wait(timeout=5)
            time.sleep(0.15)
            liberar.set()
            a.join(timeout=10)
            b.join(timeout=10)
            self.assertEqual(eventos, ['inicio_1', 'fin_1', 'inicio_2', 'fin_2'])
