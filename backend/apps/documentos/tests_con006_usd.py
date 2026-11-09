"""
Regresión CON-006: una captura en USD sin tipo de cambio guardaba el costo en USD
dentro de costo_unitario_pen (el error del TC se tragaba con `except Exception`).
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.documentos.models import Documento, DocumentoCaptura, DocumentoDetalle


class CapturaUsdTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()
        self.homologar_sku()

    def test_usd_con_tc_convierte_costo_a_pen(self):
        self.crear_tc(date(2026, 1, 9), '3.75000000')  # viernes; captura del sábado 10 usa este TC
        resp = self.generar_borrador(self.subir_xml(fecha='2026-01-10', moneda='USD'))
        self.assertEqual(resp.status_code, 201, resp.data)

        doc = Documento.objects.get(pk=resp.data['documento_id'])
        self.assertEqual(doc.moneda_codigo_id, 'USD')
        self.assertEqual(doc.monto_tc, Decimal('3.75000000'))
        self.assertEqual(doc.fecha_tc, date(2026, 1, 9))
        linea = doc.detalles.get()
        # 10 unidades × 10.00 USD × 3.75 = 375.00 PEN → 37.50 PEN por unidad (IGV 100 % recuperable)
        self.assertEqual(linea.costo_unitario_pen, Decimal('37.50000000'))

    def test_usd_sin_tc_rechaza_el_borrador_y_conserva_la_captura(self):
        captura_id = self.subir_xml(fecha='2026-01-10', moneda='USD')

        resp = self.generar_borrador(captura_id)

        self.assertEqual(resp.status_code, 400)
        self.assertIn('tipo de cambio', str(resp.data))
        self.assertFalse(Documento.objects.filter(empresa=self.empresa).exists())
        self.assertFalse(DocumentoDetalle.objects.filter(documento__empresa=self.empresa).exists())
        captura = DocumentoCaptura.objects.get(pk=captura_id)
        self.assertIsNone(captura.documento_id)
        self.assertEqual(captura.estado_proceso, 'PROCESADO')

    def test_usd_sin_tc_nunca_deja_costo_usd_como_pen(self):
        resp = self.generar_borrador(self.subir_xml(fecha='2026-01-10', moneda='USD'))
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(
            DocumentoDetalle.objects.filter(
                documento__empresa=self.empresa, costo_unitario_pen=Decimal('10.00000000'),
            ).exists()
        )

    def test_reintento_tras_registrar_tc_funciona(self):
        captura_id = self.subir_xml(fecha='2026-01-10', moneda='USD')
        self.assertEqual(self.generar_borrador(captura_id).status_code, 400)
        self.crear_tc(date(2026, 1, 10), '3.80000000')
        resp = self.generar_borrador(captura_id)
        self.assertEqual(resp.status_code, 201, resp.data)
        linea = Documento.objects.get(pk=resp.data['documento_id']).detalles.get()
        self.assertEqual(linea.costo_unitario_pen, Decimal('38.00000000'))

    def test_pen_no_exige_tc(self):
        resp = self.generar_borrador(self.subir_xml(fecha='2026-01-10', moneda='PEN'))
        self.assertEqual(resp.status_code, 201, resp.data)
        doc = Documento.objects.get(pk=resp.data['documento_id'])
        self.assertIsNone(doc.monto_tc)
        self.assertEqual(doc.detalles.get().costo_unitario_pen, Decimal('10.00000000'))

    def test_moneda_no_soportada_rechazada_en_vez_de_asumir_pen(self):
        resp = self.generar_borrador(self.subir_xml(fecha='2026-01-10', moneda='EUR'))
        self.assertEqual(resp.status_code, 400)
        self.assertIn('EUR', str(resp.data))
        self.assertFalse(Documento.objects.filter(empresa=self.empresa).exists())


class ConfirmacionUsdTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()

    def test_documento_manual_usd_sin_tc_rechazado_al_crear(self):
        resp = self.crear(self.payload('COMPRA', [self.linea('COMPRA')], moneda='USD'), esperado=400)
        self.assertIn('tipo de cambio', str(resp.data))
        self.assertFalse(Documento.objects.filter(empresa=self.empresa).exists())

    def test_documento_usd_sin_tc_no_se_confirma_aunque_se_haya_manipulado(self):
        self.crear_tc(date(2026, 1, 10), '3.75000000')
        doc_id = self.crear(self.payload('COMPRA', [self.linea('COMPRA')], moneda='USD')).data['id']
        self.revisar(doc_id)
        Documento.objects.filter(pk=doc_id).update(monto_tc=None, tipo_cambio=None)

        resp = self.confirmar(doc_id, esperado=400)

        self.assertIn('tipo de cambio', str(resp.data))
        self.assertEqual(Documento.objects.get(pk=doc_id).estado, 'BORRADOR')
        self.assertFalse(self.movimientos().exists())

    def test_documento_usd_con_tc_confirma_con_costo_en_pen(self):
        self.crear_tc(date(2026, 1, 10), '3.75000000')
        doc_id = self.crear(self.payload('COMPRA', [self.linea('COMPRA', '10', '10')], moneda='USD')).data['id']
        self.revisar(doc_id)
        self.confirmar(doc_id)
        mov = self.movimientos().get()
        self.assertEqual(mov.valorizacion.costo_unitario_pen, Decimal('37.50000000'))
        self.assertEqual(self.saldo().valor_total_pen, Decimal('375.00000000'))

    def test_documento_manual_en_moneda_no_soportada_rechazado(self):
        from apps.catalogos.models import Moneda
        Moneda.objects.create(codigo='EUR', nombre='Euros')
        resp = self.crear(self.payload('COMPRA', [self.linea('COMPRA')], moneda='EUR'), esperado=400)
        self.assertIn('EUR', str(resp.data))
