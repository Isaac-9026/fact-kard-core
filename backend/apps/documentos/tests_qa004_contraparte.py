"""
QA-004 — en una VENTA la lista y el detalle mostraban `ruc_emisor` (la propia empresa) como
si fuera el RUC del cliente. La API expone ahora el documento del tercero: proveedor en una
compra, cliente en una venta. `ruc_emisor` no cambia (sigue siendo el emisor del comprobante).
"""
from django.test import TestCase
from django.urls import reverse

from apps.documentos.fixtures_bloque2 import Bloque2Fixture


class ContraparteDocumentoTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()
        self.compra = self.compra_confirmada('10', '12', fecha='2026-01-05')
        self.venta = self.documento_confirmado('VENTA', [self.linea('VENTA', '1', '30')], fecha='2026-01-08')

    def listar(self, **params):
        resp = self.client.get(reverse('documento-list-create'), params, **self.headers)
        self.assertEqual(resp.status_code, 200)
        datos = resp.data['results'] if isinstance(resp.data, dict) else resp.data
        return {d['id']: d for d in datos}

    def test_venta_muestra_el_cliente_y_no_la_empresa(self):
        venta = self.listar()[self.venta]
        self.assertEqual(venta['ruc_emisor'], self.empresa.ruc)  # emisor = la empresa (sin cambios)
        self.assertEqual(venta['tercero_numero_documento'], self.cliente.numero_documento)
        self.assertEqual(venta['tercero_tipo_documento'], '6')
        self.assertEqual(venta['tercero_razon_social'], 'CLIENTE B2')
        self.assertNotEqual(venta['tercero_numero_documento'], self.empresa.ruc)

    def test_compra_muestra_el_proveedor(self):
        compra = self.listar()[self.compra]
        self.assertEqual(compra['tercero_numero_documento'], self.proveedor.numero_documento)
        self.assertEqual(compra['tercero_razon_social'], 'PROVEEDOR B2')
        self.assertEqual(compra['ruc_emisor'], self.proveedor.numero_documento)

    def test_detalle_trae_el_documento_del_tercero(self):
        resp = self.client.get(reverse('documento-detail', args=[self.venta]), **self.headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['tercero_numero_documento'], self.cliente.numero_documento)

    def test_buscar_por_ruc_del_cliente(self):
        encontrados = self.listar(search=self.cliente.numero_documento)
        self.assertIn(self.venta, encontrados)
        self.assertNotIn(self.compra, encontrados)
