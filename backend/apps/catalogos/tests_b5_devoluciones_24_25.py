"""
Bloque 5 — decisión 05/06 frente a 24/25 (Tabla 12, Anexo 3 de la R.S. 169-2015/SUNAT).

La tabla trae ambos pares y no existe una nota oficial que dé prioridad a 24/25:
05 DEVOLUCION RECIBIDA / 06 DEVOLUCION ENTREGADA son válidos y correctos en dirección
para la devolución del cliente y al proveedor. Sin justificación contable clara no se
cambian (cambiarlos alteraría el código de períodos ya informados). 24/25 quedan como
alternativa pendiente de decisión del contador.
"""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.catalogos.models import TipoOperacion
from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.documentos.models import Documento, DocumentoDetalle
from apps.kardex.models import Movimiento
from apps.reportes.formato131_service import generar_formato_131


class SeedNoUsa24_25Tests(TestCase):
    def test_devoluciones_mantienen_05_06_y_24_25_no_se_usan(self):
        call_command('seed_catalogos_sunat', stdout=StringIO())
        self.assertEqual(TipoOperacion.objects.get(codigo_interno='DEVOLUCION_VENTA').codigo_sunat, '05')
        self.assertEqual(TipoOperacion.objects.get(codigo_interno='DEVOLUCION_COMPRA').codigo_sunat, '06')
        self.assertFalse(TipoOperacion.objects.filter(codigo_sunat__in=('24', '25')).exists())


class CodigosDevolucionReportesTests(Bloque2Fixture, TestCase):
    """Compra, venta y devoluciones (parcial y total) en Kardex y Formato 13.1."""

    def setUp(self):
        self.crear_base()

    def nota(self, clase, operacion, origen_id, cantidad, fecha):
        detalle = DocumentoDetalle.objects.get(documento_id=origen_id)
        return self.documento_confirmado(
            clase, [self.linea(operacion, cantidad, '10', detalle_origen=detalle.id)],
            tipo=self.nota_credito, origen=Documento.objects.get(pk=origen_id), fecha=fecha,
        )

    def test_codigos_en_kardex_y_13_1(self):
        compra = self.compra_confirmada('10', '10')
        venta = self.documento_confirmado('VENTA', [self.linea('VENTA', '4', '30')], fecha='2026-01-12')
        dev_compra = self.nota('COMPRA', 'DEVOLUCION_COMPRA', compra, '2', '2026-01-13')
        dev_venta_total = self.nota('VENTA', 'DEVOLUCION_VENTA', venta, '4', '2026-01-14')
        kardex = {f['id']: f['tipo_operacion_codigo'] for f in self.client.get(
            reverse('kardex-report'), {'producto_id': self.producto.id}, **self.headers).data['movimientos']}
        f131 = {m['movimiento_id']: m['tipo_operacion'] for m in
                generar_formato_131(empresa_id=self.empresa.id, periodo_id=self.enero.id)['reportes'][0]['movimientos']}
        for nombre, doc, codigo, naturaleza in (
            ('compra', compra, '02', 'ENTRADA'), ('venta', venta, '01', 'SALIDA'),
            ('devolución al proveedor', dev_compra, '06', 'SALIDA'),
            ('devolución total del cliente', dev_venta_total, '05', 'ENTRADA'),
        ):
            with self.subTest(nombre):
                mov = Movimiento.objects.get(documento_detalle__documento_id=doc)
                self.assertEqual(mov.naturaleza, naturaleza)
                self.assertEqual((kardex[mov.id], f131[mov.id]), (codigo, codigo))
                self.assertNotIn(kardex[mov.id], ('24', '25'))
