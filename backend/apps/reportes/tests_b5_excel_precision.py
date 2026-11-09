"""
Bloque 5 — Excel del Kardex: los importes se escriben como Decimal (sin float) y, si
superan los 15 dígitos significativos de Excel, se redondean con ROUND_HALF_UP.
"""
import io
import zipfile
from decimal import Decimal

import openpyxl
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.reportes.excel_exporter import _num

D = Decimal


class NumeroExcelTests(SimpleTestCase):
    def test_valores_decimales_sensibles(self):
        casos = {
            D('0.30000000'): D('0.3'),
            D('2.67500000'): D('2.675'),
            D('0.66666667'): D('0.66666667'),
            D('1234567.12345678'): D('1234567.12345678'),   # 15 dígitos: exacto
            D('0.00000001'): D('1E-8'),
            D('123456789012.12345678'): D('123456789012.123'),  # 20 → 15 dígitos, HALF_UP
        }
        for entrada, esperado in casos.items():
            with self.subTest(entrada=entrada):
                self.assertEqual(_num(entrada), esperado)
                self.assertIsInstance(_num(entrada), Decimal)
        self.assertEqual(_num(D('0E-8')), D('0'))
        self.assertIsNone(_num(None))
        self.assertEqual(_num(None, cero=True), D('0'))
        self.assertEqual(_num(D('2.0000005')), D('2.0000005'))
        self.assertEqual(_num(D('0.1234567890123456789')), D('0.123456789012346'))  # half-up


class ExcelKardexPrecisionTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()

    def test_excel_conserva_los_importes_exactos(self):
        self.compra_confirmada('1', '1', fecha='2026-01-08')
        self.compra_confirmada('2', '0.5', fecha='2026-01-09')
        self.documento_confirmado('VENTA', [self.linea('VENTA', '1', '30')], fecha='2026-01-10')
        resp = self.client.get(reverse('kardex-excel-export'), {'producto_id': self.producto.id}, **self.headers)
        api = self.client.get(reverse('kardex-report'), {'producto_id': self.producto.id}, **self.headers).data
        ws = openpyxl.load_workbook(io.BytesIO(resp.content))['Kardex Valorizado']
        for i, fila in enumerate(api['movimientos']):
            for col, campo in ((12, 'saldo_cantidad'), (13, 'cpp'), (14, 'saldo_valor')):
                with self.subTest(fila=i, campo=campo):
                    # El número leído de Excel, llevado a texto corto, es el Decimal de la API.
                    self.assertEqual(D(repr(ws.cell(row=8 + i, column=col).value)), D(fila[campo]))
        # En el XML no aparece ruido binario (p. ej. 1.3333330000000001).
        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            xml = z.read('xl/worksheets/sheet1.xml').decode()
        self.assertIn('<v>1.333333</v>', xml)
        self.assertNotIn('00000001</v>', xml)
