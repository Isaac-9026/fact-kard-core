"""Importación Excel — paso 4: cuadro de diferencias costo Excel vs costo del Kardex."""
import io
from decimal import Decimal

from django.test import SimpleTestCase
from django.urls import reverse
from openpyxl import load_workbook
from rest_framework.exceptions import NotFound, ValidationError

from apps.documentos.importacion_kardex_confirmar import anular_lote_importacion, confirmar_importacion_kardex
from apps.documentos.importacion_kardex_diferencias import clasificar, diferencias_lote_json
from apps.documentos.tests_importacion_kardex import OPC, ImportacionKardexBase, compra, devolucion, excel, venta
from apps.usuarios.models import Usuario, UsuarioEmpresa


class ClasificarTests(SimpleTestCase):
    def test_semaforo(self):
        casos = [
            (Decimal('10'), Decimal('10.01'), 'VERDE'),
            (Decimal('10'), Decimal('9.99'), 'VERDE'),
            (Decimal('10'), Decimal('10.5'), 'AMBAR'),     # 5 % justo
            (Decimal('10'), Decimal('10.51'), 'ROJO'),
            (Decimal('0.1'), Decimal('0.105'), 'VERDE'),   # 5 % pero dentro del redondeo
            (Decimal('0'), Decimal('10'), 'ROJO'),
            (None, Decimal('10'), 'ROJO'),
            (Decimal('10'), None, 'ROJO'),
        ]
        for excel_cu, sistema_cu, esperado in casos:
            with self.subTest(excel=excel_cu, sistema=sistema_cu):
                self.assertEqual(clasificar(excel_cu, sistema_cu)[0], esperado)
        self.assertEqual(clasificar(Decimal('10'), Decimal('10.3'))[1], Decimal('3'))


class DiferenciasLoteTests(ImportacionKardexBase):
    con_stock = False

    def importar(self):
        archivo = excel([
            compra('011004', 3, 'F035', 1081, 20, 10),
            compra('011049', 3, 'F035', 1082, 10, 4),
            venta('011004', 5, 3, 'BS01', 1, 5, 10.5, ('',)),     # Kardex 10 → 4.76 %: ámbar
            venta('011004', 6, 3, 'BS01', 2, 2, 12, ('',)),       # Kardex 10 → 16.7 %: rojo
            venta('011049', 6, 3, 'BS01', 3, 1, 4.004, ('',)),    # Kardex 4 → redondeo: verde
            venta('011004', 7, 1, 'FS01', 9, 2, 10, ('',)),
            devolucion('011004', 7, 'B001', 3, 2) + [''],         # costo 0 en el Excel: rojo
        ], OPC)
        return confirmar_importacion_kardex(
            empresa_id=self.empresa.id, usuario=self.usuario, archivos=[('kardex.xlsx', archivo)],
        )['lote']

    def linea(self, datos, comprobante):
        return next(l for l in datos['lineas'] if l['comprobante'] == comprobante)

    def test_compara_cada_linea_y_resume(self):
        lote = self.importar()
        d = diferencias_lote_json(self.empresa.id, lote)
        self.assertEqual(len(d['lineas']), 7)
        compra_ = self.linea(d, 'F035-1081')
        self.assertEqual((compra_['nivel'], compra_['costo_unitario_excel'], compra_['costo_unitario_sistema']),
                         ('VERDE', '10.0000', '10.0000'))
        self.assertEqual(compra_['cantidad'], '20')
        ambar = self.linea(d, 'BS01-1')
        self.assertEqual((ambar['nivel'], ambar['porcentaje'], ambar['diferencia_unitaria']), ('AMBAR', '4.76', '-0.5000'))
        self.assertEqual((ambar['costo_total_excel'], ambar['costo_total_sistema'], ambar['diferencia_total']),
                         ('52.50', '50.00', '-2.50'))
        rojo = self.linea(d, 'BS01-2')
        self.assertEqual((rojo['nivel'], rojo['porcentaje'], rojo['diferencia_total']), ('ROJO', '16.67', '-4.00'))
        self.assertEqual(self.linea(d, 'BS01-3')['nivel'], 'VERDE')
        nota = self.linea(d, 'B001-3')
        self.assertEqual((nota['nivel'], nota['porcentaje'], nota['operacion']), ('ROJO', None, 'Devolución'))
        self.assertIn('costo 0', nota['motivo'])
        r = d['resumen']
        self.assertEqual((r['lineas'], r['verde'], r['ambar'], r['rojo']), (7, 4, 1, 2))
        # -2.50 (ámbar) - 4.00 (rojo) - 0.004 (verde) + 20.00 (nota sin costo en el Excel)
        self.assertEqual(r['diferencia_neta'], '13.50')
        self.assertEqual(r['diferencia_absoluta'], '26.50')
        self.assertEqual([p['codigo'] for p in d['productos']], ['011004', '011049'])

    def test_filtros_por_producto_y_nivel(self):
        lote = self.importar()
        d = diferencias_lote_json(self.empresa.id, lote, producto_id=str(self.p2.id))
        self.assertEqual({l['producto_codigo'] for l in d['lineas']}, {'011049'})
        self.assertEqual(d['resumen']['lineas'], 2)
        self.assertEqual(len(d['productos']), 2)
        d = diferencias_lote_json(self.empresa.id, lote, nivel='ROJO')
        self.assertEqual({l['comprobante'] for l in d['lineas']}, {'BS01-2', 'B001-3'})
        self.assertEqual((d['resumen']['rojo'], d['resumen']['verde']), (2, 0))

    def test_lote_anulado_no_tiene_cuadro(self):
        lote = self.importar()
        anular_lote_importacion(empresa_id=self.empresa.id, lote_id=lote, usuario=self.usuario, motivo='Prueba anular')
        with self.assertRaises(ValidationError):
            diferencias_lote_json(self.empresa.id, lote)
        self.assertEqual(self.client.get(reverse('importacion-lote-diferencias', args=[lote]), **self.headers).status_code, 400)

    def test_lote_de_otra_empresa_no_existe(self):
        lote = self.importar()
        with self.assertRaises(NotFound):
            diferencias_lote_json(self.empresa.id + 999, lote)

    def test_endpoints_json_excel_y_permisos(self):
        lote = self.importar()
        url = reverse('importacion-lote-diferencias', args=[lote])
        r = self.client.get(url, {'nivel': 'AMBAR'}, **self.headers)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual([l['comprobante'] for l in r.data['lineas']], ['BS01-1'])
        self.assertEqual(self.client.get(url, {'nivel': 'AZUL'}, **self.headers).status_code, 400)
        self.assertEqual(self.client.get(reverse('importacion-lote-diferencias', args=[999999]), **self.headers).status_code, 404)

        x = self.client.get(reverse('importacion-lote-diferencias-excel', args=[lote]), **self.headers)
        self.assertEqual(x.status_code, 200)
        self.assertIn('diferencias_lote_', x['Content-Disposition'])
        hoja = load_workbook(io.BytesIO(x.content)).active
        filas = [list(f) for f in hoja.iter_rows(values_only=True)]
        encabezado = next(i for i, f in enumerate(filas) if f[0] == 'Fecha')
        datos = filas[encabezado + 1:]
        self.assertEqual(len(datos), 7)
        rojo = next(f for f in datos if f[1] == 'BS01-2')
        self.assertEqual((rojo[6], rojo[7], rojo[12]), (12, 10, -4))
        self.assertTrue(rojo[13].startswith('Error B'))

        usuario = Usuario.objects.create(username='usuario_dif', email='d@test.pe', password_hash='x')
        UsuarioEmpresa.objects.create(usuario=usuario, empresa=self.empresa, rol='USUARIO')
        self.client.force_authenticate(user=usuario)
        self.assertEqual(self.client.get(url, **self.headers).status_code, 403)

    def test_excel_neutraliza_formulas(self):
        self.p1.descripcion = '=HYPERLINK("http://x","clic")'
        self.p1.save(update_fields=['descripcion'])
        lote = self.importar()
        x = self.client.get(reverse('importacion-lote-diferencias-excel', args=[lote]), **self.headers)
        hoja = load_workbook(io.BytesIO(x.content)).active
        celdas = [c for f in hoja.iter_rows() for c in f if isinstance(c.value, str) and c.value.startswith('=')]
        self.assertTrue(celdas)
        self.assertTrue(all(c.data_type == 's' for c in celdas))
