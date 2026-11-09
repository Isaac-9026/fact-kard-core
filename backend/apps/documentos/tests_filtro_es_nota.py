"""
Navegación por flujo: Compras/Ventas (sin notas) y Notas de Crédito/Débito reutilizan el
mismo listado de documentos con el filtro `es_nota`. Sin el filtro, el listado no cambia.
"""
from django.test import TestCase
from django.urls import reverse

from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.documentos.models import Documento, DocumentoDetalle


class FiltroEsNotaTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()
        self.compra = self.compra_confirmada('5', '10')
        self.venta = self.documento_confirmado('VENTA', [self.linea('VENTA', '2', '30')], fecha='2026-01-11')
        detalle = DocumentoDetalle.objects.get(documento_id=self.venta).id
        self.nota = self.documento_confirmado(
            'VENTA', [self.linea('DEVOLUCION_VENTA', '1', '30', detalle_origen=detalle)],
            tipo=self.nota_credito, origen=Documento.objects.get(pk=self.venta), fecha='2026-01-12')

    def ids(self, **params):
        resp = self.client.get(reverse('documento-list-create'), {'page_size': 50, **params}, **self.headers)
        self.assertEqual(resp.status_code, 200, resp.data)
        return {d['id'] for d in resp.data['results']}

    def test_comprobantes_sin_filtro_incluye_todo(self):
        self.assertEqual(self.ids(), {self.compra, self.venta, self.nota})

    def test_compras_y_ventas_excluyen_notas(self):
        self.assertEqual(self.ids(clase='COMPRA', es_nota='false'), {self.compra})
        self.assertEqual(self.ids(clase='VENTA', es_nota='false'), {self.venta})

    def test_solo_notas(self):
        self.assertEqual(self.ids(es_nota='true'), {self.nota})
        self.assertEqual(self.ids(es_nota='true', clase='COMPRA'), set())

    def test_valor_invalido_400(self):
        resp = self.client.get(reverse('documento-list-create'), {'es_nota': 'quizas'}, **self.headers)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('es_nota', resp.data)
