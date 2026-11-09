"""Bloque 10 — B10-08: un texto que empieza con "=" no debe llegar al Excel como fórmula."""
import io
from datetime import date
from decimal import Decimal

import openpyxl
from django.test import TestCase
from django.urls import reverse

from apps.documentos.fixtures_bloque2 import Bloque2Fixture

MALICIOSO = '=HYPERLINK("http://evil.example","clic")'


class ExcelSinFormulasTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()
        self.producto.codigo_interno = '=1+1'
        self.producto.descripcion = MALICIOSO
        self.producto.save()
        self.compra_confirmada('10', '10')

    def celdas(self, nombre_url, **params):
        resp = self.client.get(reverse(nombre_url), params, **self.headers)
        self.assertEqual(resp.status_code, 200)
        libro = openpyxl.load_workbook(io.BytesIO(resp.content))
        return [c for hoja in libro.worksheets for fila in hoja.iter_rows() for c in fila if c.value is not None]

    def assert_texto_literal(self, celdas):
        self.assertFalse([c.coordinate for c in celdas if c.data_type == 'f'])
        valores = {c.value for c in celdas}
        self.assertIn(MALICIOSO, valores)
        self.assertIn('=1+1', valores)

    def test_kardex_excel(self):
        self.assert_texto_literal(self.celdas('kardex-excel-export', periodo_id=self.enero.id))

    def test_formato_131_excel(self):
        celdas = self.celdas('formato-131-excel', periodo_id=self.enero.id)
        self.assertFalse([c.coordinate for c in celdas if c.data_type == 'f'])
        self.assertTrue(any(MALICIOSO in str(c.value) or c.value == '=1+1' for c in celdas))

    def test_numeros_siguen_siendo_numeros(self):
        celdas = self.celdas('kardex-excel-export', periodo_id=self.enero.id)
        self.assertTrue(any(c.data_type == 'n' and c.value == Decimal('100') or c.value == 100 for c in celdas))
