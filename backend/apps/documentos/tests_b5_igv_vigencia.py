"""
Bloque 5 — la tasa del IGV tiene vigencia por fecha (TasaIgvVigencia). Una operación usa
la tasa vigente en su fecha; un cambio no altera documentos ya registrados.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.auditoria.models import Auditoria
from apps.documentos.afectacion_igv import tasa_igv
from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.documentos.models import DocumentoDetalle
from apps.empresas.models import ConfigEmpresa, TasaIgvVigencia

D = Decimal


class IgvVigenciaTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()
        self.url = reverse('empresa-config')

    def cambiar(self, tasa, desde, esperado=200):
        resp = self.client.patch(self.url, {'tasa_igv_pct': tasa, 'tasa_igv_vigente_desde': desde},
                                 format='json', **self.headers)
        self.assertEqual(resp.status_code, esperado, resp.data)
        return resp

    def registrar(self, fecha, igv, esperado=201):
        return self.crear(self.payload('COMPRA', [self.linea('COMPRA', '10', '10', igv=igv)], fecha=fecha),
                          esperado=esperado)

    def test_tasa_actual_por_defecto(self):
        self.assertFalse(TasaIgvVigencia.objects.exists())
        self.assertEqual(tasa_igv(self.empresa.id), D('0.18'))
        self.assertEqual(tasa_igv(self.empresa.id, date(2026, 1, 10)), D('0.18'))

    def test_cambio_de_tasa_con_vigencia_y_tasa_historica(self):
        anterior = self.registrar('2026-01-10', '18.00')
        resp = self.cambiar('10.00', '2026-01-15')
        self.assertEqual(resp.data['tasas_igv'], [
            {'vigente_desde': '1900-01-01', 'tasa_pct': '18.00'},
            {'vigente_desde': '2026-01-15', 'tasa_pct': '10.00'},
        ])
        self.assertEqual(tasa_igv(self.empresa.id, date(2026, 1, 14)), D('0.18'))  # histórica
        self.assertEqual(tasa_igv(self.empresa.id, date(2026, 1, 15)), D('0.10'))
        self.assertEqual(tasa_igv(self.empresa.id), D('0.10'))                    # actual
        self.assertEqual(ConfigEmpresa.objects.get(empresa=self.empresa).tasa_igv_pct, D('10.00'))
        # Documentos anteriores mantienen su cálculo.
        self.assertEqual(DocumentoDetalle.objects.get(documento_id=anterior.data['id']).igv, D('18.00000000'))
        # Operación histórica (antes del cambio) se valida con 18 %; posterior, con 10 %.
        self.registrar('2026-01-12', '18.00')
        self.registrar('2026-01-12', '10.00', esperado=400)
        self.registrar('2026-01-20', '10.00')
        resp = self.registrar('2026-01-20', '18.00', esperado=400)
        self.assertIn('10 %', str(resp.data))
        auditoria = Auditoria.objects.get(empresa_id=self.empresa.id, accion='CAMBIAR_TASA_IGV')
        self.assertEqual(auditoria.motivo, 'Vigente desde 2026-01-15')

    def test_segundo_cambio_y_misma_fecha_actualiza(self):
        self.cambiar('10.00', '2026-01-15')
        self.cambiar('12.00', '2026-01-15')
        self.cambiar('18.00', '2026-01-25')
        self.assertEqual(list(TasaIgvVigencia.objects.values_list('vigente_desde', 'tasa_pct')), [
            (date(1900, 1, 1), D('18.00')), (date(2026, 1, 15), D('12.00')), (date(2026, 1, 25), D('18.00')),
        ])
        self.assertEqual(tasa_igv(self.empresa.id, date(2026, 1, 20)), D('0.12'))

    def test_no_se_cambia_la_tasa_de_un_periodo_cerrado(self):
        resp = self.cambiar('10.00', '2025-12-15', esperado=400)  # diciembre está CERRADO en el fixture
        self.assertIn('período cerrado', str(resp.data))
        self.assertFalse(TasaIgvVigencia.objects.exists())

    def test_captura_usa_la_tasa_de_su_fecha(self):
        self.cambiar('10.00', '2026-01-15')
        self.homologar_sku()
        lineas = [{'codigo': 'SKU-QA-1', 'descripcion': 'ITEM', 'cantidad': '10', 'precio': '10.00', 'igv': '18.00'}]
        resp = self.generar_borrador(self.subir_xml(numero='701', fecha='2026-01-10', lineas=lineas))
        self.assertEqual(resp.status_code, 201, resp.data)
        resp = self.generar_borrador(self.subir_xml(numero='702', fecha='2026-01-20', lineas=lineas))
        self.assertEqual(resp.status_code, 400)
