"""
Regresión BE-005: el motor elegía el tipo del extorno con `.first()` entre tipos de
la naturaleza opuesta; con el seed real un extorno de devolución salía como
SALDO_INICIAL y uno de compra como VENTA. Kardex y 13.1 mostraban "MOV-<id>".
"""
from django.test import TestCase
from django.urls import reverse

from apps.catalogos.models import TipoOperacion
from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.documentos.models import Documento, DocumentoDetalle
from apps.kardex.models import Movimiento
from apps.reportes.formato131_service import generar_formato_131

TIPOS_INCORRECTOS = {'SALDO_INICIAL', 'VENTA', 'COMPRA', 'DEVOLUCION_VENTA', 'DEVOLUCION_COMPRA'}


class ExtornosTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()

    # ---- helpers -------------------------------------------------------------

    def extorno_de(self, documento_id):
        original = Movimiento.objects.get(documento_detalle__documento_id=documento_id)
        return original, Movimiento.objects.select_related('tipo_operacion').get(movimiento_extornado=original)

    def fila_kardex(self, movimiento_id):
        resp = self.client.get(reverse('kardex-report'), {'producto_id': self.producto.id}, **self.headers)
        self.assertEqual(resp.status_code, 200)
        return next(f for f in resp.data['movimientos'] if f['id'] == movimiento_id)

    def fila_131(self, movimiento_id):
        data = generar_formato_131(empresa_id=self.empresa.id, periodo_id=self.enero.id)
        return next(m for r in data['reportes'] for m in r['movimientos'] if m['movimiento_id'] == movimiento_id)

    def assert_extorno(self, documento_id, *, tipo_esperado, naturaleza, operacion_original):
        documento = Documento.objects.select_related('tipo_comprobante').get(pk=documento_id)
        original, extorno = self.extorno_de(documento_id)
        # Tipo y naturaleza
        self.assertEqual(extorno.tipo_operacion.codigo_interno, tipo_esperado)
        self.assertNotIn(extorno.tipo_operacion.codigo_interno, TIPOS_INCORRECTOS)
        self.assertEqual(extorno.naturaleza, naturaleza)
        self.assertEqual(extorno.tipo_operacion.codigo_sunat, '99')
        self.assertTrue(extorno.es_extorno)
        # Referencia al movimiento original
        self.assertEqual(extorno.movimiento_extornado_id, original.id)
        self.assertEqual(original.tipo_operacion.codigo_interno, operacion_original)
        # Kardex
        fila = self.fila_kardex(extorno.id)
        comprobante = f"{documento.tipo_comprobante.codigo_sunat} {documento.serie_normalizada}-{documento.numero_normalizado}"
        self.assertEqual(fila['tipo_operacion_codigo'], '99')
        self.assertIn('EXTORNO', fila['tipo_operacion_descripcion'])
        self.assertEqual(fila['documento_referencia'], f'EXTORNO {comprobante}')
        self.assertTrue(fila['es_extorno'])
        self.assertEqual(fila['movimiento_extornado_id'], original.id)
        self.assertEqual(fila['operacion_extornada_codigo'], operacion_original)
        self.assertEqual(fila['naturaleza'], naturaleza)
        # Formato 13.1
        fila_131 = self.fila_131(extorno.id)
        self.assertEqual(fila_131['tipo_operacion'], '99')
        self.assertEqual(fila_131['tipo_operacion_interno'], tipo_esperado)
        self.assertTrue(fila_131['es_extorno'])
        self.assertEqual(fila_131['movimiento_extornado_id'], original.id)
        self.assertEqual(fila_131['operacion_extornada'], operacion_original)
        self.assertEqual(fila_131['documento'], {
            'tipo_documento': documento.tipo_comprobante.codigo_sunat,
            'serie': documento.serie_normalizada,
            'numero': documento.numero_normalizado,
        })
        return original, extorno

    def nota(self, clase, operacion, origen_id, cantidad, precio, tipo=None):
        detalle = DocumentoDetalle.objects.get(documento_id=origen_id)
        return self.documento_confirmado(
            clase, [self.linea(operacion, cantidad, precio, detalle_origen=detalle.id)],
            tipo=tipo or self.nota_credito, origen=Documento.objects.get(pk=origen_id), fecha='2026-01-15',
        )

    # ---- casos ---------------------------------------------------------------

    def test_anulacion_de_compra(self):
        compra = self.compra_confirmada('10', '10')
        self.anular(compra)
        _, extorno = self.assert_extorno(compra, tipo_esperado='EXTORNO_SALIDA', naturaleza='SALIDA',
                                         operacion_original='COMPRA')
        self.assertEqual(extorno.cantidad_base, 10)

    def test_anulacion_de_venta(self):
        self.compra_confirmada('10', '10')
        venta = self.documento_confirmado('VENTA', [self.linea('VENTA', '4', '30')], fecha='2026-01-12')
        self.anular(venta)
        self.assert_extorno(venta, tipo_esperado='EXTORNO_ENTRADA', naturaleza='ENTRADA',
                            operacion_original='VENTA')

    def test_anulacion_de_nc_compra_devolucion_no_sale_como_saldo_inicial(self):
        compra = self.compra_confirmada('10', '10')
        nc = self.nota('COMPRA', 'DEVOLUCION_COMPRA', compra, '3', '10')
        self.anular(nc)
        self.assert_extorno(nc, tipo_esperado='EXTORNO_ENTRADA', naturaleza='ENTRADA',
                            operacion_original='DEVOLUCION_COMPRA')
        self.assertEqual(self.stock(), 10)

    def test_anulacion_de_nc_venta_devolucion(self):
        self.compra_confirmada('10', '10')
        venta = self.documento_confirmado('VENTA', [self.linea('VENTA', '4', '30')], fecha='2026-01-12')
        nc = self.nota('VENTA', 'DEVOLUCION_VENTA', venta, '2', '30')
        self.anular(nc)
        self.assert_extorno(nc, tipo_esperado='EXTORNO_SALIDA', naturaleza='SALIDA',
                            operacion_original='DEVOLUCION_VENTA')
        self.assertEqual(self.stock(), 6)

    def test_anulacion_de_nc_descuento_es_extorno_de_ajuste_de_valor(self):
        compra = self.compra_confirmada('10', '10')
        nc = self.nota('COMPRA', 'NC_DESCUENTO_COMPRA', compra, '1', '20')
        self.assertEqual(self.saldo().valor_total_pen, 80)
        self.anular(nc)
        self.assert_extorno(nc, tipo_esperado='EXTORNO_AJUSTE_VALOR', naturaleza='AJUSTE_VALOR',
                            operacion_original='NC_DESCUENTO_COMPRA')
        self.assertEqual(self.saldo().valor_total_pen, 100)

    def test_catalogo_sin_tipos_de_extorno_los_crea_explicitamente(self):
        TipoOperacion.objects.filter(codigo_interno__startswith='EXTORNO_').delete()
        compra = self.compra_confirmada('10', '10')
        self.anular(compra)
        _, extorno = self.extorno_de(compra)
        self.assertEqual(extorno.tipo_operacion.codigo_interno, 'EXTORNO_SALIDA')
        self.assertEqual(extorno.tipo_operacion.codigo_sunat, '99')
        self.assertEqual(extorno.tipo_operacion.origen_requerido, 'MOV_EXTORNADO')

    def test_tipo_de_extorno_mal_configurado_bloquea_la_anulacion(self):
        TipoOperacion.objects.filter(codigo_interno='EXTORNO_SALIDA').update(naturaleza='ENTRADA')
        compra = self.compra_confirmada('10', '10')
        resp = self.anular(compra, esperado=400)
        self.assertIn('EXTORNO_SALIDA', str(resp.data))
        self.assertEqual(Documento.objects.get(pk=compra).estado, 'CONFIRMADO')
        self.assertEqual(self.movimientos().count(), 1)
