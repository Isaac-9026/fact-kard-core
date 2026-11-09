"""
Bloque 4 — la tasa del IGV deja de ser una constante: se lee de
ConfigEmpresa.tasa_igv_pct (18.00 por defecto) desde una única función.
"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.documentos.afectacion_igv import tasa_igv
from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.documentos.models import Documento, DocumentoDetalle
from apps.empresas.models import TASA_IGV_POR_DEFECTO_PCT, ConfigEmpresa

D = Decimal


class IgvConfigurableTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()

    def registrar(self, esperado=201, **linea):
        igv = linea.pop('igv')
        return self.crear(self.payload('COMPRA', [self.linea('COMPRA', '10', '10', igv=igv, **linea)]), esperado=esperado)

    def configurar(self, pct):
        ConfigEmpresa.objects.filter(empresa=self.empresa).update(tasa_igv_pct=D(pct))

    # 1
    def test_tasa_por_defecto_18(self):
        self.assertEqual(TASA_IGV_POR_DEFECTO_PCT, D('18.00'))
        self.assertEqual(ConfigEmpresa.objects.get(empresa=self.empresa).tasa_igv_pct, D('18.00'))
        self.assertEqual(tasa_igv(self.empresa.id), D('0.18'))
        self.assertEqual(tasa_igv(self.otra_empresa.id), D('0.18'))  # sin ConfigEmpresa
        self.registrar(igv='18.00')

    # 2
    def test_gravado_valido_con_tasa_configurada(self):
        self.configurar('10.00')
        resp = self.registrar(igv='10.00', afectacion_igv='GRAVADO')
        self.assertEqual(DocumentoDetalle.objects.get(documento_id=resp.data['id']).igv, D('10.00000000'))

    # 3
    def test_igv_que_no_corresponde_a_la_tasa_rechazado(self):
        self.configurar('10.00')
        resp = self.registrar(esperado=400, igv='18.00')
        self.assertIn('10 % = 10.00', str(resp.data))
        self.assertFalse(Documento.objects.filter(empresa=self.empresa).exists())

    # 4-6
    def test_exonerado_inafecto_y_gratuito_no_dependen_de_la_tasa(self):
        self.configurar('10.00')
        self.registrar(igv='0', afectacion_igv='EXONERADO')
        self.registrar(igv='0', afectacion_igv='INAFECTO')
        self.registrar(igv='0', afectacion_igv='EXPORTACION')
        self.registrar(igv='18.00', afectacion_igv='GRATUITO')
        resp = self.registrar(esperado=400, igv='10.00', afectacion_igv='EXONERADO')
        self.assertIn('no lleva IGV', str(resp.data))

    def test_config_api_admin_y_rango(self):
        url = reverse('empresa-config')
        resp = self.client.patch(url, {'tasa_igv_pct': '10.00'}, format='json', **self.headers)
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(resp.data['tasa_igv_pct'], '10.00')
        for invalida in ('0', '-1', '100.01', 'abc'):
            with self.subTest(invalida=invalida):
                r = self.client.patch(url, {'tasa_igv_pct': invalida}, format='json', **self.headers)
                self.assertEqual(r.status_code, 400)
        self.assertEqual(tasa_igv(self.empresa.id), D('0.10'))
        from apps.auditoria.models import Auditoria
        auditoria = Auditoria.objects.get(empresa_id=self.empresa.id, accion='CAMBIAR_TASA_IGV')
        self.assertEqual((auditoria.valor_anterior, auditoria.valor_nuevo),
                         ({'tasa_igv_pct': '18.00'}, {'tasa_igv_pct': '10.00'}))

    def test_captura_xml_valida_con_la_tasa_configurada(self):
        self.configurar('10.00')
        self.homologar_sku()
        lineas = [{'codigo': 'SKU-QA-1', 'descripcion': 'ITEM XML QA', 'cantidad': '10', 'precio': '10.00', 'igv': '10.00'}]
        resp = self.generar_borrador(self.subir_xml(numero='991', lineas=lineas))
        self.assertEqual(resp.status_code, 201, resp.data)
        lineas[0]['igv'] = '18.00'
        resp = self.generar_borrador(self.subir_xml(numero='992', lineas=lineas))
        self.assertEqual(resp.status_code, 400)
