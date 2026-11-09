"""
QA-001 — NC de devolución física: la pantalla necesita elegir la línea del comprobante de
origen (`detalle_origen`) y saber cuánto queda por devolver. El detalle del comprobante expone
`cantidad_devuelta` y `cantidad_disponible_devolucion` (cantidad base, notas confirmadas).
"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.documentos.models import Documento, DocumentoDetalle

D = Decimal


class DevolucionLineaOrigenTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()
        self.compra_confirmada('20', '10', fecha='2026-01-05')
        self.venta = self.documento_confirmado('VENTA', [self.linea('VENTA', '10', '30')], fecha='2026-01-08')
        self.linea_venta = DocumentoDetalle.objects.get(documento_id=self.venta)

    def detalle_origen(self):
        resp = self.client.get(reverse('documento-detail', args=[self.venta]), **self.headers)
        self.assertEqual(resp.status_code, 200)
        return resp.data['detalles'][0]

    def nc_devolucion(self, cantidad, esperado=201):
        data = self.payload('VENTA', [self.linea('DEVOLUCION_VENTA', cantidad, '30', detalle_origen=self.linea_venta.id)],
                            tipo=self.nota_credito, origen=Documento.objects.get(pk=self.venta), fecha='2026-01-09')
        return self.crear(data, esperado=esperado)

    def test_detalle_informa_lo_disponible_para_devolver(self):
        linea = self.detalle_origen()
        self.assertEqual((D(linea['cantidad_devuelta']), D(linea['cantidad_disponible_devolucion'])), (D('0'), D('10')))
        self.assertEqual(linea['tipo_operacion_naturaleza'], 'SALIDA')
        nc = self.nc_devolucion('3')
        self.revisar(nc.data['id'])
        self.confirmar(nc.data['id'])
        linea = self.detalle_origen()
        self.assertEqual((D(linea['cantidad_devuelta']), D(linea['cantidad_disponible_devolucion'])), (D('3'), D('7')))

    def test_devolucion_con_detalle_origen_mueve_el_kardex(self):
        stock_antes = self.stock()
        nc = self.nc_devolucion('4')
        self.revisar(nc.data['id'])
        self.confirmar(nc.data['id'])
        self.assertEqual(self.stock(), stock_antes + D('4'))

    def test_no_se_puede_devolver_mas_de_lo_disponible(self):
        nc = self.nc_devolucion('8')
        self.revisar(nc.data['id'])
        self.confirmar(nc.data['id'])
        resp = self.nc_devolucion('3', esperado=None)
        if resp.status_code == 201:  # la validación de cantidad puede ocurrir al confirmar
            self.revisar(resp.data['id'])
            resp = self.client.post(reverse('documento-confirmar', args=[resp.data['id']]), format='json', **self.headers)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('solo quedan 2', str(resp.data))

    def test_devolucion_sin_linea_de_origen_se_rechaza_y_nc_descuento_no_la_necesita(self):
        data = self.payload('VENTA', [self.linea('DEVOLUCION_VENTA', '1', '30')], tipo=self.nota_credito,
                            origen=Documento.objects.get(pk=self.venta), fecha='2026-01-09')
        resp = self.crear(data, esperado=400)
        self.assertIn('detalle_origen', str(resp.data))
        descuento = self.payload('VENTA', [self.linea('NC_VENTA_SIN_DEVOLUCION', '1', '5')], tipo=self.nota_credito,
                                 origen=Documento.objects.get(pk=self.venta), fecha='2026-01-09')
        self.crear(descuento, esperado=201)
