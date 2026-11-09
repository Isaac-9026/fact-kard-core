"""
Bloque 4 — correspondencia de los tipos de operación con la Tabla 12 de SUNAT.

Fuente oficial: Tabla 12 "Tipo de operación", Anexo 3 de la R.S. 169-2015/SUNAT
(https://www.sunat.gob.pe/legislacion/superin/2015/anexo3-rs169-2015.pdf).

Interpretación usada:
- 05 DEVOLUCION RECIBIDA es una ENTRADA y se usa para la devolución del cliente
  (DEVOLUCION_VENTA); 06 DEVOLUCION ENTREGADA es una SALIDA y se usa para la devolución
  al proveedor (DEVOLUCION_COMPRA). No están invertidos.
- 24/25 (devolución del cliente / al proveedor) son alternativas más específicas de la
  misma tabla; su adopción es una decisión contable pendiente, no una corrección.
- 22/23 (identificación errónea) corrigen un bien mal identificado, no anulan un
  comprobante → los extornos por anulación siguen en 99 OTROS.
"""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.catalogos.models import TipoOperacion
from apps.documentos.fixtures_bloque2 import CODIGOS_SUNAT, Bloque2Fixture
from apps.documentos.models import Documento, DocumentoDetalle
from apps.kardex.models import Movimiento
from apps.reportes.formato131_service import generar_formato_131

# Extracto de la Tabla 12 oficial: solo los códigos relevantes para este sistema.
TABLA_12 = {
    '01': 'VENTA NACIONAL', '02': 'COMPRA NACIONAL',
    '05': 'DEVOLUCION RECIBIDA', '06': 'DEVOLUCION ENTREGADA',
    '10': 'SALIDA A PRODUCCION', '11': 'SALIDA POR TRANSFERENCIA ENTRE ALMACENES',
    '12': 'RETIRO', '13': 'MERMAS', '14': 'DESMEDROS', '16': 'SALDO INICIAL',
    '21': 'ENTRADA POR TRANSFERENCIA ENTRE ALMACENES',
    '22': 'ENTRADA POR IDENTIFICACION ERRONEA', '23': 'SALIDA POR IDENTIFICACION ERRONEA',
    '24': 'ENTRADA POR DEVOLUCION DEL CLIENTE', '25': 'SALIDA POR DEVOLUCION AL PROVEEDOR',
    '99': 'OTROS',
}
# Naturaleza que exige cada código direccional de la tabla.
DIRECCION = {
    '01': 'SALIDA', '02': 'ENTRADA', '05': 'ENTRADA', '06': 'SALIDA', '10': 'SALIDA', '11': 'SALIDA', '12': 'SALIDA',
    '13': 'SALIDA', '14': 'SALIDA', '16': 'ENTRADA', '21': 'ENTRADA',
    '22': 'ENTRADA', '23': 'SALIDA', '24': 'ENTRADA', '25': 'SALIDA',
}
ESPERADO = {
    'COMPRA': '02', 'VENTA': '01', 'DEVOLUCION_VENTA': '05', 'DEVOLUCION_COMPRA': '06',
    'SALDO_INICIAL': '16', 'TRANSFERENCIA_SALIDA': '11', 'TRANSFERENCIA_ENTRADA': '21',
    'MERMA': '13', 'DESMEDRO': '14',
    'EXTORNO_ENTRADA': '99', 'EXTORNO_SALIDA': '99', 'EXTORNO_AJUSTE_VALOR': '99',
}


class SeedTabla12Tests(TestCase):
    def setUp(self):
        call_command('seed_catalogos_sunat', stdout=StringIO())

    def test_codigos_esperados_por_operacion(self):
        for interno, codigo in ESPERADO.items():
            with self.subTest(interno=interno):
                self.assertEqual(TipoOperacion.objects.get(codigo_interno=interno).codigo_sunat, codigo)

    def test_todo_codigo_del_seed_existe_en_la_tabla_y_respeta_su_direccion(self):
        for tipo in TipoOperacion.objects.all():
            with self.subTest(tipo=tipo.codigo_interno):
                self.assertIn(tipo.codigo_sunat, TABLA_12, 'código fuera del extracto oficial de la Tabla 12')
                if tipo.codigo_sunat in DIRECCION:
                    self.assertEqual(tipo.naturaleza, DIRECCION[tipo.codigo_sunat])

    def test_devoluciones_no_estan_invertidas(self):
        venta = TipoOperacion.objects.get(codigo_interno='DEVOLUCION_VENTA')
        compra = TipoOperacion.objects.get(codigo_interno='DEVOLUCION_COMPRA')
        self.assertEqual((venta.naturaleza, TABLA_12[venta.codigo_sunat]), ('ENTRADA', 'DEVOLUCION RECIBIDA'))
        self.assertEqual((compra.naturaleza, TABLA_12[compra.codigo_sunat]), ('SALIDA', 'DEVOLUCION ENTREGADA'))

    def test_extornos_no_usan_identificacion_erronea(self):
        for tipo in TipoOperacion.objects.filter(codigo_interno__startswith='EXTORNO_'):
            with self.subTest(tipo=tipo.codigo_interno):
                self.assertNotIn(tipo.codigo_sunat, ('22', '23'))
                self.assertEqual(tipo.codigo_sunat, '99')
                self.assertTrue(tipo.descripcion.startswith('EXTORNO POR ANULACION'))

    def test_fixture_de_pruebas_usa_los_mismos_codigos_que_el_seed(self):
        for interno, codigo in CODIGOS_SUNAT.items():
            with self.subTest(interno=interno):
                self.assertEqual(TipoOperacion.objects.get(codigo_interno=interno).codigo_sunat, codigo)


class CodigosEnReportesTests(Bloque2Fixture, TestCase):
    """Código mostrado en Kardex y 13.1 para cada operación."""

    def setUp(self):
        self.crear_base()

    def codigos(self, documento_id):
        movs = Movimiento.objects.filter(documento_detalle__documento_id=documento_id).values_list('id', flat=True)
        kardex = self.client.get(reverse('kardex-report'), {'producto_id': self.producto.id}, **self.headers).data
        f131 = generar_formato_131(empresa_id=self.empresa.id, periodo_id=self.enero.id)['reportes'][0]['movimientos']
        return ({f['tipo_operacion_codigo'] for f in kardex['movimientos'] if f['id'] in movs},
                {m['tipo_operacion'] for m in f131 if m['movimiento_id'] in movs})

    def nota(self, clase, operacion, origen_id, cantidad):
        detalle = DocumentoDetalle.objects.get(documento_id=origen_id)
        return self.documento_confirmado(
            clase, [self.linea(operacion, cantidad, '10', detalle_origen=detalle.id)],
            tipo=self.nota_credito, origen=Documento.objects.get(pk=origen_id), fecha='2026-01-15',
        )

    def test_matriz_compra_venta_devoluciones(self):
        compra = self.compra_confirmada('10', '10')
        venta = self.documento_confirmado('VENTA', [self.linea('VENTA', '4', '30')], fecha='2026-01-12')
        dev_compra = self.nota('COMPRA', 'DEVOLUCION_COMPRA', compra, '2')
        dev_venta = self.nota('VENTA', 'DEVOLUCION_VENTA', venta, '1')
        for nombre, doc, codigo in (('compra', compra, '02'), ('venta', venta, '01'),
                                    ('devolución compra', dev_compra, '06'), ('devolución venta', dev_venta, '05')):
            with self.subTest(nombre):
                self.assertEqual(self.codigos(doc), ({codigo}, {codigo}))

    def test_matriz_extornos(self):
        compra = self.compra_confirmada('10', '10')
        venta = self.documento_confirmado('VENTA', [self.linea('VENTA', '4', '30')], fecha='2026-01-12')
        nc_compra = self.nota('COMPRA', 'DEVOLUCION_COMPRA', compra, '2')
        nc_venta = self.nota('VENTA', 'DEVOLUCION_VENTA', venta, '1')
        casos = (
            (nc_venta, 'EXTORNO_SALIDA'), (nc_compra, 'EXTORNO_ENTRADA'),
            (venta, 'EXTORNO_ENTRADA'), (compra, 'EXTORNO_SALIDA'),
        )
        descripciones = {
            'EXTORNO_ENTRADA': 'EXTORNO POR ANULACION (ENTRADA)', 'EXTORNO_SALIDA': 'EXTORNO POR ANULACION (SALIDA)',
        }
        for interno, descripcion in descripciones.items():  # las del seed
            TipoOperacion.objects.filter(codigo_interno=interno).update(descripcion=descripcion)
        for doc, tipo_esperado in casos:
            self.anular(doc)
        f131 = {m['movimiento_id']: m for m in
                generar_formato_131(empresa_id=self.empresa.id, periodo_id=self.enero.id)['reportes'][0]['movimientos']}
        kardex = {f['id']: f for f in self.client.get(reverse('kardex-report'), {'producto_id': self.producto.id},
                                                      **self.headers).data['movimientos']}
        for doc, tipo_esperado in casos:
            with self.subTest(tipo=tipo_esperado, documento=doc):
                extorno = Movimiento.objects.select_related('tipo_operacion').get(
                    movimiento_extornado__documento_detalle__documento_id=doc,
                )
                self.assertEqual(extorno.tipo_operacion.codigo_interno, tipo_esperado)
                self.assertEqual(kardex[extorno.id]['tipo_operacion_codigo'], '99')
                self.assertEqual(kardex[extorno.id]['tipo_operacion_descripcion'], descripciones[tipo_esperado])
                self.assertEqual(f131[extorno.id]['tipo_operacion'], '99')
                self.assertEqual(f131[extorno.id]['tipo_operacion_interno'], tipo_esperado)
