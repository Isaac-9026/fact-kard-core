"""
Bloque 3 — afectación del IGV por línea.
Antes (CON-009 provisional): se aceptaba IGV 0 o 18 % en cualquier línea, sin saber
si era gravada, exonerada, inafecta o gratuita.
"""
from decimal import Decimal
from importlib import import_module

from django.apps import apps as django_apps
from django.test import TestCase

from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.documentos.models import Documento, DocumentoDetalle


class AfectacionIgvApiTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()

    def registrar(self, esperado=201, **linea):
        igv = linea.pop('igv')
        resp = self.crear(self.payload('COMPRA', [self.linea('COMPRA', '10', '10', igv=igv, **linea)]), esperado=esperado)
        return resp

    def detalle(self, resp):
        return DocumentoDetalle.objects.get(documento_id=resp.data['id'])

    def assert_rechazo(self, texto, **linea):
        resp = self.registrar(esperado=400, **linea)
        self.assertIn(texto, str(resp.data))
        self.assertFalse(Documento.objects.filter(empresa=self.empresa).exists())

    # 1
    def test_gravado_18_valido(self):
        det = self.detalle(self.registrar(igv='18.00', afectacion_igv='GRAVADO'))
        self.assertEqual(det.afectacion_igv, 'GRAVADO')
        self.assertEqual(det.igv, Decimal('18.00000000'))

    def test_sin_afectacion_se_trata_como_gravado(self):
        self.assertEqual(self.detalle(self.registrar(igv='18.00')).afectacion_igv, 'GRAVADO')

    # 2
    def test_gravado_con_igv_0_rechazado(self):
        self.assert_rechazo('no corresponde a la base gravada', igv='0', afectacion_igv='GRAVADO')
        self.assert_rechazo('no corresponde a la base gravada', igv='0')

    # 3
    def test_exonerado_con_igv_0_valido(self):
        det = self.detalle(self.registrar(igv='0', afectacion_igv='EXONERADO'))
        self.assertEqual(det.afectacion_igv, 'EXONERADO')
        self.assertEqual(det.costo_unitario_pen, Decimal('10.00000000'))

    # 4
    def test_exonerado_con_igv_rechazado(self):
        self.assert_rechazo('no lleva IGV', igv='18.00', afectacion_igv='EXONERADO')

    # 5
    def test_inafecto_con_igv_0_valido(self):
        self.assertEqual(self.detalle(self.registrar(igv='0', afectacion_igv='INAFECTO')).afectacion_igv, 'INAFECTO')

    def test_inafecto_con_igv_rechazado(self):
        self.assert_rechazo('no lleva IGV', igv='0.50', afectacion_igv='INAFECTO')

    def test_exportacion_sin_igv(self):
        self.assertEqual(self.detalle(self.registrar(igv='0', codigo_afectacion_igv='40')).afectacion_igv, 'EXPORTACION')

    # 6
    def test_gratuito_valido(self):
        for igv in ('0', '18.00'):
            with self.subTest(igv=igv):
                det = self.detalle(self.registrar(igv=igv, afectacion_igv='GRATUITO'))
                self.assertEqual(det.afectacion_igv, 'GRATUITO')

    def test_bonificacion_conserva_logica_previa(self):
        resp = self.crear(self.payload('COMPRA', [self.linea('COMPRA', '2', '0', igv='3.60', es_bonificacion=True)]))
        det = self.detalle(resp)
        self.assertEqual(det.afectacion_igv, 'GRATUITO')
        self.assertEqual(det.costo_unitario_pen, Decimal('0E-8'))

    def test_bonificacion_no_puede_declararse_gravada(self):
        resp = self.crear(self.payload('COMPRA', [self.linea('COMPRA', '2', '5', igv='1.80', es_bonificacion=True,
                                                             afectacion_igv='GRAVADO')]), esperado=400)
        self.assertIn('GRATUITO', str(resp.data))

    # 7
    def test_payload_manipulado_rechazado(self):
        casos = [
            ({'igv': '1.00'}, 'no corresponde a la base gravada'),                       # IGV rebajado
            ({'igv': '18.00', 'afectacion_igv': 'INAFECTO'}, 'no lleva IGV'),             # etiqueta falsa
            ({'igv': '0', 'afectacion_igv': 'EXENTO'}, 'afectacion_igv'),                 # valor fuera de lista
            ({'igv': '0', 'codigo_afectacion_igv': '99'}, 'Catálogo 07'),                # código inventado
            ({'igv': '0', 'codigo_afectacion_igv': '20', 'afectacion_igv': 'GRAVADO'}, 'no coincide'),
            ({'igv': '0', 'codigo_afectacion_igv': '17'}, 'IVAP'),                       # no soportado
        ]
        for linea, texto in casos:
            with self.subTest(linea=linea):
                self.assert_rechazo(texto, **linea)

    def test_codigo_sunat_se_guarda_y_deriva_la_afectacion(self):
        for codigo, afectacion in (('10', 'GRAVADO'), ('20', 'EXONERADO'), ('30', 'INAFECTO'), ('15', 'GRATUITO'),
                                   ('21', 'GRATUITO'), ('31', 'GRATUITO')):
            with self.subTest(codigo=codigo):
                igv = '18.00' if afectacion == 'GRAVADO' else '0'
                det = self.detalle(self.registrar(igv=igv, codigo_afectacion_igv=codigo))
                self.assertEqual((det.afectacion_igv, det.codigo_afectacion_igv), (afectacion, codigo))

    def test_api_devuelve_la_afectacion(self):
        resp = self.registrar(igv='0', afectacion_igv='INAFECTO')
        self.assertEqual(resp.data['detalles'][0]['afectacion_igv'], 'INAFECTO')


class AfectacionIgvCapturaTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()
        self.homologar_sku()

    def capturar(self, numero, lineas):
        return self.generar_borrador(self.subir_xml(numero=numero, lineas=lineas))

    def test_xml_exonerado_toma_igv_y_codigo_del_comprobante(self):
        resp = self.capturar('801', [{'codigo': 'SKU-QA-1', 'descripcion': 'ITEM XML QA', 'cantidad': '10',
                                      'precio': '10.00', 'afectacion': '20'}])
        self.assertEqual(resp.status_code, 201, resp.data)
        det = DocumentoDetalle.objects.get(documento_id=resp.data['documento_id'])
        self.assertEqual((det.afectacion_igv, det.codigo_afectacion_igv, det.igv), ('EXONERADO', '20', Decimal('0E-8')))

    def test_xml_gravado(self):
        resp = self.capturar('802', [{'codigo': 'SKU-QA-1', 'descripcion': 'ITEM XML QA', 'cantidad': '10',
                                      'precio': '10.00'}])
        self.assertEqual(resp.status_code, 201, resp.data)
        det = DocumentoDetalle.objects.get(documento_id=resp.data['documento_id'])
        self.assertEqual((det.afectacion_igv, det.igv), ('GRAVADO', Decimal('18.00000000')))

    def test_xml_inconsistente_rechazado_sin_documento(self):
        resp = self.capturar('803', [{'codigo': 'SKU-QA-1', 'descripcion': 'ITEM XML QA', 'cantidad': '10',
                                      'precio': '10.00', 'afectacion': '30', 'igv': '18.00'}])
        self.assertEqual(resp.status_code, 400)
        self.assertIn('no lleva IGV', str(resp.data))
        self.assertFalse(Documento.objects.filter(empresa=self.empresa, origen_captura='XML').exists())


class MigracionAfectacionTests(Bloque2Fixture, TestCase):
    """La migración 0003 solo clasifica lo que puede afirmarse con los datos guardados."""

    def setUp(self):
        self.crear_base()

    def test_clasificacion_de_lineas_existentes(self):
        compra = self.compra_confirmada('10', '10')
        bonif = self.documento_confirmado('COMPRA', [self.linea('COMPRA', '1', '0', igv='0', es_bonificacion=True)])
        exon = self.documento_confirmado('COMPRA', [self.linea('COMPRA', '1', '10', igv='0', afectacion_igv='EXONERADO')])
        DocumentoDetalle.objects.update(afectacion_igv=None)  # estado previo a la migración

        migracion = import_module('apps.documentos.migrations.0003_detalle_afectacion_igv')
        migracion.clasificar_lineas_existentes(django_apps, None)

        valor = lambda d: DocumentoDetalle.objects.get(documento_id=d).afectacion_igv  # noqa: E731
        self.assertEqual(valor(compra), 'GRAVADO')
        self.assertEqual(valor(bonif), 'GRATUITO')
        self.assertIsNone(valor(exon))  # IGV 0 histórico: ambiguo, no se inventa
