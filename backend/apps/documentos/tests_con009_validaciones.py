"""
Regresión CON-009: los detalles llegaban como diccionarios libres; negativos,
texto, NaN, Infinity o factor 0 se aceptaban o provocaban HTTP 500, y el IGV
enviado por el frontend se guardaba sin validar.
"""
from decimal import Decimal

from django.test import TestCase

from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.documentos.models import Documento
from apps.documentos.services import crear_documento


class DetalleTipadoApiTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()

    def _rechazado(self, **campos):
        linea = self.linea('COMPRA', '10', '10')
        linea.update(campos)
        resp = self.crear(self.payload('COMPRA', [linea]), esperado=None)
        self.assertEqual(resp.status_code, 400, getattr(resp, 'data', resp.content))
        self.assertFalse(Documento.objects.filter(empresa=self.empresa).exists())
        return resp

    def test_cantidad_negativa(self):
        self._rechazado(cantidad_original='-1')

    def test_cantidad_cero_en_compra(self):
        resp = self._rechazado(cantidad_original='0', igv='0')
        self.assertIn('mayor que cero', str(resp.data))

    def test_precio_negativo(self):
        self._rechazado(precio_unitario='-10')

    def test_igv_negativo(self):
        self._rechazado(igv='-18')

    def test_nan(self):
        for campo in ('cantidad_original', 'precio_unitario', 'igv'):
            with self.subTest(campo=campo):
                self._rechazado(**{campo: 'NaN'})

    def test_infinity(self):
        for valor in ('Infinity', '-Infinity', 'inf'):
            with self.subTest(valor=valor):
                self._rechazado(precio_unitario=valor)

    def test_texto_invalido(self):
        for campo in ('cantidad_original', 'precio_unitario', 'igv'):
            with self.subTest(campo=campo):
                self._rechazado(**{campo: 'diez'})
        self._rechazado(almacen='ALM')
        self._rechazado(tipo_operacion='abc')

    def test_factor_cero_y_negativo(self):
        for factor in ('0', '-2'):
            with self.subTest(factor=factor):
                self._rechazado(producto_unidad=None, factor_conversion=factor)

    def test_igv_arbitrario_rechazado(self):
        resp = self._rechazado(igv='99.00')
        self.assertIn('no corresponde a la base', str(resp.data))

    def test_detalles_vacios_o_ausentes(self):
        data = self.payload('COMPRA', [])
        self.assertEqual(self.crear(data, esperado=None).status_code, 400)
        data.pop('detalles')
        self.assertEqual(self.crear(data, esperado=None).status_code, 400)

    def test_detalle_valido_pasa_y_recalcula_totales(self):
        resp = self.crear(self.payload('COMPRA', [self.linea('COMPRA', '10', '12.5')]))
        doc = Documento.objects.get(pk=resp.data['id'])
        self.assertEqual(doc.subtotal, Decimal('125.00000000'))
        self.assertEqual(doc.igv, Decimal('22.50000000'))
        self.assertEqual(doc.total, Decimal('147.50000000'))

    def test_igv_con_8_decimales_del_frontend_dentro_de_tolerancia(self):
        # El frontend calcula cant × precio × 0.18 con 8 decimales.
        self.crear(self.payload('COMPRA', [self.linea('COMPRA', '3', '3.33', igv='1.79820000')]))

    def test_igv_cero_exonerado_permitido(self):
        # Bloque 3: el IGV 0 requiere afectación explícita (ver tests_b3_afectacion_igv).
        self.crear(self.payload('COMPRA', [self.linea('COMPRA', '10', '10', igv='0', afectacion_igv='EXONERADO')]))

    def test_bonificacion_no_valida_tasa(self):
        self.crear(self.payload('COMPRA', [self.linea('COMPRA', '2', '0', igv='3.60', es_bonificacion=True)]))

    def test_ajuste_de_valor_admite_cantidad_cero_con_igv_sobre_el_precio(self):
        compra = self.compra_confirmada('10', '10')
        from apps.documentos.models import DocumentoDetalle
        detalle = DocumentoDetalle.objects.get(documento_id=compra)
        data = self.payload(
            'COMPRA', [self.linea('NC_DESCUENTO_COMPRA', '0', '50', igv='9.00', detalle_origen=detalle.id)],
            tipo=self.nota_credito, origen=Documento.objects.get(pk=compra), fecha='2026-01-15',
        )
        self.crear(data)


class ServicioDirectoTests(Bloque2Fixture, TestCase):
    """Defensa en profundidad: crear_documento también se llama sin serializer."""

    def setUp(self):
        self.crear_base()

    def _crear(self, **campos):
        linea = {
            'producto_id': self.producto.id, 'almacen_id': self.almacen.id,
            'tipo_operacion_id': self.op['COMPRA'].id, 'cantidad_original': '10', 'precio_unitario': '10',
            'igv': '18.00',  # Bloque 3: línea gravada por defecto → IGV 18 %
        }
        linea.update(campos)
        return crear_documento(
            empresa_id=self.empresa.id, usuario_id=self.usuario.id,
            datos_cabecera={
                'clase': 'COMPRA', 'periodo_id': self.enero.id, 'tercero_id': self.proveedor.id,
                'tipo_comprobante_id': self.factura.id, 'serie': 'F001', 'numero': '77',
                'fecha_emision': '2026-01-10', 'moneda_codigo': 'PEN',
            },
            detalles_datos=[linea],
        )

    def test_valores_invalidos_lanzan_validation_error_no_500(self):
        from rest_framework.exceptions import ValidationError
        for campos in (
            {'cantidad_original': 'NaN'}, {'precio_unitario': 'Infinity'}, {'igv': 'abc'},
            {'factor_conversion': '0'}, {'cantidad_original': None},
        ):
            with self.subTest(campos=campos), self.assertRaises(ValidationError):
                self._crear(**campos)
        self.assertFalse(Documento.objects.filter(empresa=self.empresa).exists())

    def test_linea_valida(self):
        self.assertEqual(self._crear().detalles.get().cantidad_base, Decimal('10.00000000'))
