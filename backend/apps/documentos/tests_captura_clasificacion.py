"""
Bloque 3 — clasificación de comprobantes capturados.
Antes: toda captura se creaba como COMPRA y las notas buscaban NC_COMPRA/ND_COMPRA
(inexistentes en el seed) y caían en "cualquier" ajuste de valor.
"""
from decimal import Decimal

from django.test import TestCase

from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.documentos.models import Documento, DocumentoCaptura
from apps.kardex.models import Incidencia

CLIENTE = '20666000111'


class CapturaClasificacionTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()
        self.homologar_sku()
        self._n = 900

    # ---- helpers -------------------------------------------------------------

    def capturar(self, **kwargs):
        self._n += 1
        return self.generar_borrador(self.subir_xml(numero=str(self._n), **kwargs))

    def venta_propia(self, **kwargs):
        lineas = [{'codigo': 'P-B2', 'descripcion': 'PRODUCTO P-B2', 'cantidad': '4', 'precio': '30.00'}]
        kwargs.setdefault('lineas', lineas)
        return self.capturar(emisor=self.empresa.ruc, emisor_nombre='EMPRESA B2', receptor=CLIENTE,
                             receptor_nombre='CLIENTE B2', **kwargs)

    def doc(self, resp):
        self.assertEqual(resp.status_code, 201, resp.data)
        return Documento.objects.select_related('tipo_comprobante', 'documento_origen').get(pk=resp.data['documento_id'])

    def referencia(self, documento_id):
        d = Documento.objects.get(pk=documento_id)
        return f'{d.serie_normalizada}-{d.numero_normalizado}'

    def assert_rechazo_sin_documento(self, resp, texto):
        self.assertEqual(resp.status_code, 400, getattr(resp, 'data', None))
        self.assertIn(texto, str(resp.data))
        self.assertFalse(Documento.objects.filter(empresa=self.empresa, origen_captura='XML').exists())

    # ---- comprobantes -------------------------------------------------------

    def test_factura_de_compra(self):
        doc = self.doc(self.capturar())
        self.assertEqual(doc.clase, 'COMPRA')
        self.assertEqual(doc.tercero, self.proveedor)
        self.assertEqual(doc.ruc_emisor, self.RUC_PROVEEDOR)
        linea = doc.detalles.get()
        self.assertEqual(linea.tipo_operacion.codigo_interno, 'COMPRA')
        self.assertEqual(linea.costo_unitario_pen, Decimal('10.00000000'))

    def test_factura_de_venta(self):
        self.compra_confirmada('10', '10')
        doc = self.doc(self.venta_propia())
        self.assertEqual(doc.clase, 'VENTA')
        self.assertEqual(doc.ruc_emisor, self.empresa.ruc)
        self.assertEqual(doc.tercero.numero_documento, CLIENTE)
        linea = doc.detalles.get()
        self.assertEqual(linea.tipo_operacion.codigo_interno, 'VENTA')
        self.assertEqual(linea.producto, self.producto)  # homologado por código interno propio
        self.assertIsNone(linea.costo_unitario_pen)  # el costo lo pone el motor (CPP), no el precio
        self.revisar(doc.id)
        self.confirmar(doc.id)
        self.assertEqual(self.stock(), Decimal('6'))
        self.assertEqual(self.saldo().valor_total_pen, Decimal('60.00000000'))

    def test_nc_de_compra_devolucion(self):
        compra = self.compra_confirmada('10', '10')
        doc = self.doc(self.capturar(tipo='07', serie='FC01', motivo='07', referencia=self.referencia(compra),
                                     lineas=[{'codigo': 'SKU-QA-1', 'descripcion': 'ITEM XML QA',
                                              'cantidad': '3', 'precio': '10.00'}]))
        self.assertEqual(doc.clase, 'COMPRA')
        self.assertEqual(doc.tipo_comprobante.codigo_sunat, '07')
        self.assertEqual(doc.documento_origen_id, compra)
        linea = doc.detalles.get()
        self.assertEqual(linea.tipo_operacion.codigo_interno, 'DEVOLUCION_COMPRA')
        self.assertEqual(linea.detalle_origen.documento_id, compra)
        self.revisar(doc.id)
        self.confirmar(doc.id)
        self.assertEqual(self.stock(), Decimal('7'))

    def test_nc_de_compra_descuento_es_ajuste_de_valor(self):
        compra = self.compra_confirmada('10', '10')
        doc = self.doc(self.capturar(tipo='07', serie='FC01', motivo='04', referencia=self.referencia(compra)))
        self.assertEqual(doc.detalles.get().tipo_operacion.codigo_interno, 'NC_DESCUENTO_COMPRA')

    def test_nc_de_venta_devolucion(self):
        self.compra_confirmada('10', '10')
        venta = self.documento_confirmado('VENTA', [self.linea('VENTA', '4', '30')], fecha='2026-01-12')
        doc = self.doc(self.venta_propia(tipo='07', serie='FC01', motivo='07', referencia=self.referencia(venta),
                                         fecha='2026-01-14',
                                         lineas=[{'codigo': 'P-B2', 'descripcion': 'P-B2', 'cantidad': '1', 'precio': '30.00'}]))
        self.assertEqual(doc.clase, 'VENTA')
        self.assertEqual(doc.documento_origen_id, venta)
        linea = doc.detalles.get()
        self.assertEqual(linea.tipo_operacion.codigo_interno, 'DEVOLUCION_VENTA')
        self.assertEqual(linea.detalle_origen.documento_id, venta)
        self.revisar(doc.id)
        self.confirmar(doc.id)
        self.assertEqual(self.stock(), Decimal('7'))

    def test_nd_de_compra(self):
        compra = self.compra_confirmada('10', '10')
        doc = self.doc(self.capturar(tipo='08', serie='FD01', motivo='02', referencia=self.referencia(compra),
                                     lineas=[{'codigo': 'SKU-QA-1', 'descripcion': 'ITEM XML QA',
                                              'cantidad': '1', 'precio': '20.00'}]))
        self.assertEqual(doc.clase, 'COMPRA')
        linea = doc.detalles.get()
        self.assertEqual(linea.tipo_operacion.codigo_interno, 'ND_CARGO_COMPRA')
        self.assertTrue(linea.afecta_kardex_aplicado)

    def test_nd_de_venta_no_afecta_kardex(self):
        self.compra_confirmada('10', '10')
        venta = self.documento_confirmado('VENTA', [self.linea('VENTA', '4', '30')], fecha='2026-01-12')
        doc = self.doc(self.venta_propia(tipo='08', serie='FD01', motivo='01', referencia=self.referencia(venta),
                                         fecha='2026-01-14'))
        self.assertEqual(doc.clase, 'VENTA')
        linea = doc.detalles.get()
        self.assertEqual(linea.tipo_operacion.codigo_interno, 'ND_CARGO_VENTA')
        self.assertFalse(linea.afecta_kardex_aplicado)

    # ---- casos que no deben adivinarse --------------------------------------

    def test_nota_sin_origen_identificable_queda_bloqueada_con_incidencia(self):
        doc = self.doc(self.capturar(tipo='07', serie='FC01', motivo='07', referencia='F999-123'))
        self.assertIsNone(doc.documento_origen_id)
        self.assertTrue(Incidencia.objects.filter(documento=doc, tipo='DOCUMENTO_ORIGEN_PENDIENTE',
                                                  bloquea_cierre=True).exists())
        self.revisar(doc.id)
        resp = self.confirmar(doc.id, esperado=400)
        self.assertIn('documento de origen', str(resp.data))

    def test_nc_con_motivo_no_determinable_rechazada(self):
        for motivo in ('01', '03', '10', None):
            with self.subTest(motivo=motivo):
                resp = self.capturar(tipo='07', serie='FC01', motivo=motivo, referencia='F001-1')
                self.assert_rechazo_sin_documento(resp, 'Regístrela manualmente')

    def test_nd_de_compra_por_intereses_rechazada(self):
        resp = self.capturar(tipo='08', serie='FD01', motivo='01', referencia='F001-1')
        self.assert_rechazo_sin_documento(resp, 'no corresponde a un mayor costo')

    def test_emisor_y_receptor_ajenos_a_la_empresa(self):
        resp = self.capturar(receptor='20777000777')
        self.assert_rechazo_sin_documento(resp, 'no corresponde a la empresa activa')

    def test_receptor_no_indicado(self):
        resp = self.capturar(receptor=None)
        self.assert_rechazo_sin_documento(resp, 'receptor (no indicado)')

    def test_emisor_y_receptor_iguales_a_la_empresa(self):
        resp = self.capturar(emisor=self.empresa.ruc, receptor=self.empresa.ruc)
        self.assert_rechazo_sin_documento(resp, 'misma empresa')

    def test_tipo_de_comprobante_no_reconocido(self):
        resp = self.capturar(tipo='12')
        self.assert_rechazo_sin_documento(resp, "Tipo de comprobante '12' no reconocido")

    def test_falta_tipo_en_catalogo_no_usa_otro(self):
        from apps.catalogos.models import TipoOperacion
        TipoOperacion.objects.filter(codigo_interno='ND_CARGO_VENTA').delete()
        self.compra_confirmada('10', '10')
        venta = self.documento_confirmado('VENTA', [self.linea('VENTA', '4', '30')], fecha='2026-01-12')
        resp = self.venta_propia(tipo='08', serie='FD01', motivo='02', referencia=self.referencia(venta),
                                 fecha='2026-01-14')
        self.assert_rechazo_sin_documento(resp, "Falta el tipo de operación 'ND_CARGO_VENTA'")

    def test_la_captura_se_conserva_tras_un_rechazo(self):
        self._n += 1
        captura_id = self.subir_xml(numero=str(self._n), tipo='12')
        self.assertEqual(self.generar_borrador(captura_id).status_code, 400)
        captura = DocumentoCaptura.objects.get(pk=captura_id)
        self.assertIsNone(captura.documento_id)
        self.assertTrue(captura.campos.exists())
