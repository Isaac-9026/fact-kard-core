"""
Tests del Paso 4 (Backend):
- Previsualización paginada en servidor (`POST /previsualizar/` -> `previsualizacion_id`, página 1 y contadores totales).
- Paginación y filtros (`GET /previsualizaciones/<id>/comprobantes/`), incluyendo `a_completar` y `sin_proveedor` multipágina.
- Descarga completa de errores, conflictos y observaciones en `.xlsx` (`errores-excel/`) con neutralización de fórmulas.
- Aislamiento multiempresa, permisos ADMIN y expiración por TTL.
"""
import io
import json
import tempfile
import time
from datetime import date
from pathlib import Path

from django.test import TestCase, override_settings
from django.urls import reverse
from openpyxl import load_workbook

from apps.catalogos.models import TipoComprobante
from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.documentos.importacion_kardex_confirmar import confirmar_importacion_kardex
from apps.documentos.importacion_previsualizaciones import (
    PREVISUALIZACION_TTL_SEGUNDOS,
    guardar_previsualizacion,
)
from apps.documentos.tests_importacion_kardex import OPC, compra, excel, venta
from apps.empresas.models import ConfigEmpresa, Establecimiento, Periodo
from apps.usuarios.models import Usuario, UsuarioEmpresa


class PrevisualizacionPaginadaTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()
        TipoComprobante.objects.get_or_create(codigo_sunat='03', defaults={'descripcion': 'BOLETA'})
        self.p1 = self.crear_producto('011004')
        self.p2 = self.crear_producto('011049')
        self.documento_confirmado('COMPRA', [self.linea('COMPRA', '1000', '10', producto=self.p1)], fecha='2026-01-01')

    def _lote_grande_mixto(self):
        """Genera un Excel con 140 comprobantes variados para probar paginación y filtros."""
        filas = []
        # 5 comprobantes en febrero 2026 (no existe periodo -> ERROR)
        for i in range(1, 6):
            filas.append(['011004', date(2026, 2, i), 1, 'F099', i, '01 Venta', 0, 0, 0, 1, 10, 10])
        # 60 compras sin RUC -> ERROR + sin_proveedor (> 1 página cuando page_size=50)
        for i in range(1, 61):
            filas.append(compra('011004', 3, 'F035', i, 2, 10)[:12])
        # 75 ventas válidas -> NUEVO
        for i in range(1, 76):
            filas.append(venta('011004', 5, 3, 'BS01', i, 1, 12, ('',)))
        buf = excel(filas, OPC)
        buf.name = 'anual_mixto.xlsx'
        return buf

    def test_previsualizar_devuelve_contadores_totales_y_primera_pagina(self):
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(IMPORTACION_STAGING_DIR=tmp):
                resp = self.client.post(
                    reverse('importacion-entradas-salidas-previsualizar') + '?page_size=50',
                    {'archivos': [self._lote_grande_mixto()]},
                    format='multipart',
                    **self.headers,
                )
                self.assertEqual(resp.status_code, 200, resp.data)
                data = resp.data
                self.assertRegex(data['previsualizacion_id'], r'^[a-f0-9]{32}$')
                self.assertEqual(len(data['comprobantes']), 50)
                self.assertEqual(data['paginacion'], {
                    'page': 1,
                    'page_size': 50,
                    'total': 140,
                    'total_pages': 3,
                    'has_next': True,
                    'has_previous': False,
                })

                resumen = data['resumen']
                self.assertEqual(resumen['total_filas'], 140)
                self.assertEqual(resumen['total_comprobantes'], 140)
                self.assertEqual(resumen['nuevos'], 75)
                self.assertEqual(resumen['errores'], 65)
                self.assertEqual(resumen['sin_proveedor'], 60)
                self.assertEqual(resumen['periodos_detectados'], ['2026-01', '2026-02'])
                self.assertEqual(data['contadores']['todos'], 140)
                self.assertEqual(data['contadores']['sin_proveedor'], 60)

                # Página 2 y página 3 desde GET /comprobantes/
                url_pag = reverse('importacion-previsualizacion-comprobantes', args=[data['previsualizacion_id']])
                p2 = self.client.get(url_pag, {'page': 2, 'page_size': 50}, **self.headers)
                self.assertEqual(p2.status_code, 200)
                self.assertEqual(len(p2.data['comprobantes']), 50)
                self.assertEqual(p2.data['paginacion']['page'], 2)

                p3 = self.client.get(url_pag, {'page': 3, 'page_size': 50}, **self.headers)
                self.assertEqual(p3.status_code, 200)
                self.assertEqual(len(p3.data['comprobantes']), 40)
                self.assertFalse(p3.data['paginacion']['has_next'])

                # Filtro sin_proveedor paginado + claves completas bajo demanda
                sp1 = self.client.get(
                    url_pag,
                    {'filtro': 'sin_proveedor', 'page': 1, 'page_size': 50, 'incluir_claves': '1'},
                    **self.headers,
                )
                self.assertEqual(sp1.status_code, 200)
                self.assertEqual(sp1.data['paginacion']['total'], 60)
                self.assertEqual(sp1.data['paginacion']['total_pages'], 2)
                self.assertEqual(len(sp1.data['comprobantes']), 50)
                self.assertEqual(len(sp1.data['claves_sin_proveedor']), 60)

                sp2 = self.client.get(url_pag, {'filtro': 'sin_proveedor', 'page': 2, 'page_size': 50}, **self.headers)
                self.assertEqual(sp2.status_code, 200)
                self.assertEqual(len(sp2.data['comprobantes']), 10)
                self.assertNotIn('claves_sin_proveedor', sp2.data)

                # Validación de límites de page_size
                invalido = self.client.get(url_pag, {'page_size': 10}, **self.headers)
                self.assertEqual(invalido.status_code, 400)
                invalido_max = self.client.get(url_pag, {'page_size': 500}, **self.headers)
                self.assertEqual(invalido_max.status_code, 400)

    def test_filtro_a_completar_y_descarga_excel_errores_completa(self):
        # 1. Importar una boleta inicial con producto p1 para generar luego estado COMPLETAR
        inicial = excel([venta('011004', 5, 3, 'BS01', 500, 1, 12)])
        confirmar_importacion_kardex(
            empresa_id=self.empresa.id, usuario=self.usuario,
            archivos=[('inicial.xlsx', inicial)], almacen_id=self.almacen.id,
        )
        self.documento_confirmado('COMPRA', [self.linea('COMPRA', '100', '10', producto=self.p2)], fecha='2026-01-01')

        # 2. Previsualizar lote con 1 COMPLETAR, 55 errores (>1 página) y 1 observación con fórmula maliciosa
        opc_obs = ('RUC/DNI', 'Precio unitario')
        filas = [venta('011049', 5, 3, 'BS01', 500, 2, 20, ('', 25))]
        for i in range(1, 56):
            filas.append(['=1+1', date(2026, 2, 1), 1, 'FERR', i, '01 Venta', 0, 0, 0, 1, 10, 10, '20555000111', 15])
        filas.append(venta('011004', 6, 1, 'FS01', 777, 1, 0, ('', None)))  # factura sin RUC + sin precio -> observaciones
        archivo = excel(filas, opc_obs)
        archivo.name = '=HYPERLINK("http://evil.example","x").xlsx'

        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(IMPORTACION_STAGING_DIR=tmp):
                resp = self.client.post(
                    reverse('importacion-entradas-salidas-previsualizar') + '?page_size=50',
                    {'archivos': [archivo]},
                    format='multipart',
                    **self.headers,
                )
                self.assertEqual(resp.status_code, 200, resp.data)
                prev_id = resp.data['previsualizacion_id']
                self.assertEqual(resp.data['contadores']['a_completar'], 1)
                self.assertEqual(resp.data['contadores']['errores'], 55)
                self.assertEqual(resp.data['contadores']['observaciones'], 1)

                url_pag = reverse('importacion-previsualizacion-comprobantes', args=[prev_id])
                comp_resp = self.client.get(url_pag, {'filtro': 'a_completar'}, **self.headers)
                self.assertEqual(comp_resp.status_code, 200)
                self.assertEqual(len(comp_resp.data['comprobantes']), 1)
                self.assertEqual(comp_resp.data['comprobantes'][0]['estado'], 'COMPLETAR')

                obs_resp = self.client.get(url_pag, {'filtro': 'observaciones'}, **self.headers)
                self.assertEqual(obs_resp.status_code, 200)
                self.assertEqual(len(obs_resp.data['comprobantes']), 1)
                self.assertEqual(obs_resp.data['comprobantes'][0]['serie'], 'FS01')

                # Descargar Excel completo de errores + conflictos + observaciones (sin límite de página)
                url_xlsx = reverse('importacion-previsualizacion-errores-excel', args=[prev_id])
                resp_xlsx = self.client.get(url_xlsx, **self.headers)
                self.assertEqual(resp_xlsx.status_code, 200)
                self.assertIn('spreadsheetml.sheet', resp_xlsx['Content-Type'])

                libro = load_workbook(io.BytesIO(resp_xlsx.content))
                hoja_comp = libro['Comprobantes']
                hoja_filas = libro['Detalle_Filas']
                # Comprobantes: 3 encabezados + 1 título tabla + 55 ERROR + 1 FS01 observado = 60 filas
                self.assertEqual(hoja_comp.max_row, 60)
                # Detalle_Filas: 1 encabezado + 55 ERROR + 1 FS01 observado = 57 filas
                self.assertEqual(hoja_filas.max_row, 57)
                # Protección contra inyección de fórmulas
                for hoja in (hoja_comp, hoja_filas):
                    for fila in hoja.iter_rows():
                        for celda in fila:
                            self.assertNotEqual(celda.data_type, 'f')

    def test_aislamiento_multiempresa_permisos_y_ttl(self):
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(IMPORTACION_STAGING_DIR=tmp):
                resp = self.client.post(
                    reverse('importacion-entradas-salidas-previsualizar'),
                    {'archivos': [excel([venta('011004', 5, 3, 'BS01', 1, 1, 10)])]},
                    format='multipart',
                    **self.headers,
                )
                self.assertEqual(resp.status_code, 200)
                prev_id = resp.data['previsualizacion_id']

                # Admin de otra empresa recibe 404 tanto en comprobantes como en errores-excel
                est_otra = Establecimiento.objects.create(empresa=self.otra_empresa, codigo_sunat='0000', nombre='OTRA')
                ConfigEmpresa.objects.create(empresa=self.otra_empresa, establecimiento_principal=est_otra)
                admin_otra = Usuario.objects.create(username='admin_otra_prev', email='op@test.pe', password_hash='x')
                UsuarioEmpresa.objects.create(usuario=admin_otra, empresa=self.otra_empresa, rol='ADMIN')
                self.client.force_authenticate(user=admin_otra)
                headers_otra = {'HTTP_X_EMPRESA_ID': str(self.otra_empresa.id)}

                self.assertEqual(
                    self.client.get(reverse('importacion-previsualizacion-comprobantes', args=[prev_id]), **headers_otra).status_code,
                    404,
                )
                self.assertEqual(
                    self.client.get(reverse('importacion-previsualizacion-errores-excel', args=[prev_id]), **headers_otra).status_code,
                    404,
                )

                # Rol USUARIO de la misma empresa recibe 403
                lector = Usuario.objects.create(username='usuario_prev', email='up@test.pe', password_hash='x')
                UsuarioEmpresa.objects.create(usuario=lector, empresa=self.empresa, rol='USUARIO')
                self.client.force_authenticate(user=lector)
                self.assertEqual(
                    self.client.get(reverse('importacion-previsualizacion-comprobantes', args=[prev_id]), **self.headers).status_code,
                    403,
                )

                # Expiración por TTL devuelve 404 y elimina el archivo temporal
                self.client.force_authenticate(user=self.usuario)
                meta_exp = guardar_previsualizacion(empresa_id=self.empresa.id, resultado={'comprobantes': [], 'filas': []}, ttl=1)
                ruta = Path(tmp) / 'previsualizaciones' / f"{meta_exp['previsualizacion_id']}.json"
                dato = json.loads(ruta.read_text(encoding='utf-8'))
                dato['expira_ts'] = time.time() - PREVISUALIZACION_TTL_SEGUNDOS
                ruta.write_text(json.dumps(dato), encoding='utf-8')

                exp_resp = self.client.get(
                    reverse('importacion-previsualizacion-comprobantes', args=[meta_exp['previsualizacion_id']]),
                    **self.headers,
                )
                self.assertEqual(exp_resp.status_code, 404)
                self.assertFalse(ruta.exists())
