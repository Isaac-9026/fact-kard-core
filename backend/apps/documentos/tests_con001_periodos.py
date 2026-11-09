"""
Regresión CON-001: la captura asignaba el "último período abierto" cuando la fecha
caía en un período cerrado o fuera de todos, y convertía fechas inválidas en "hoy".
La confirmación tampoco revalidaba fecha vs período.
"""
from datetime import date

from django.test import TestCase

from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.documentos.models import Documento, DocumentoCaptura
from apps.empresas.models import Periodo
from apps.kardex.models import Movimiento


class CapturaPeriodoTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()
        self.homologar_sku()

    def _docs(self):
        return Documento.objects.filter(empresa=self.empresa).count()

    def test_fecha_dentro_de_periodo_abierto_genera_borrador(self):
        resp = self.generar_borrador(self.subir_xml(fecha='2026-01-15'))
        self.assertEqual(resp.status_code, 201, resp.data)
        doc = Documento.objects.get(pk=resp.data['documento_id'])
        self.assertEqual(doc.periodo, self.enero)
        self.assertEqual(doc.fecha_emision, date(2026, 1, 15))

    def test_fecha_de_periodo_cerrado_rechazada_sin_fallback(self):
        antes = self._docs()
        resp = self.generar_borrador(self.subir_xml(fecha='2025-12-20'))
        self.assertEqual(resp.status_code, 400)
        self.assertIn('2025-12', str(resp.data))
        self.assertIn('CERRADO', str(resp.data))
        self.assertEqual(self._docs(), antes)
        self.assertFalse(Movimiento.objects.filter(empresa=self.empresa).exists())

    def test_fecha_fuera_de_todos_los_periodos_rechazada(self):
        antes = self._docs()
        resp = self.generar_borrador(self.subir_xml(fecha='2026-03-05'))
        self.assertEqual(resp.status_code, 400)
        self.assertIn('No existe un período contable ABIERTO', str(resp.data))
        self.assertEqual(self._docs(), antes)

    def test_fecha_invalida_rechazada_y_no_convertida_en_hoy(self):
        captura_id = self.subir_xml(fecha='2026-02-30')
        captura = DocumentoCaptura.objects.get(pk=captura_id)
        self.assertEqual(
            captura.campos.get(seccion='CABECERA', nombre_campo='fecha_emision').valor_extraido, '2026-02-30',
        )
        antes = self._docs()
        resp = self.generar_borrador(captura_id)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('no es válida', str(resp.data))
        self.assertEqual(self._docs(), antes)

    def test_fecha_vacia_rechazada(self):
        resp = self.generar_borrador(self.subir_xml(fecha=''))
        self.assertEqual(resp.status_code, 400)
        self.assertIn('obligatoria', str(resp.data))

    def test_ocr_sin_fecha_no_inventa_hoy(self):
        from apps.documentos.captura_services import extraer_ocr_basico
        datos = extraer_ocr_basico(b'', 'x.pdf', 'FACTURA F001-123 RUC 20555000111 TOTAL: 118.00')
        valor, confianza = datos['cabecera']['fecha_emision']
        self.assertEqual(valor, '')
        self.assertEqual(str(confianza), '0.0000')


class ConfirmacionRevalidaPeriodoTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()

    def _borrador_revisado(self):
        doc_id = self.crear(self.payload('COMPRA', [self.linea('COMPRA')])).data['id']
        self.revisar(doc_id)
        return doc_id

    def test_documento_manipulado_con_fecha_fuera_del_periodo_no_se_confirma(self):
        doc_id = self._borrador_revisado()
        # Manipulación directa: período ABIERTO pero fecha de un período CERRADO.
        Documento.objects.filter(pk=doc_id).update(fecha_emision=date(2025, 12, 15))

        resp = self.confirmar(doc_id, esperado=400)

        self.assertIn('no pertenece al período asignado', str(resp.data))
        self.assertEqual(Documento.objects.get(pk=doc_id).estado, 'BORRADOR')
        self.assertFalse(self.movimientos().exists())
        self.assertIsNone(self.saldo())

    def test_fecha_dentro_del_periodo_pero_cubierta_por_periodo_cerrado_superpuesto(self):
        doc_id = self._borrador_revisado()
        # Un período cerrado que se superpone (posible porque CON-015 aún no restringe rangos).
        Periodo.objects.filter(pk=self.diciembre.pk).update(fecha_fin=date(2026, 1, 12))

        resp = self.confirmar(doc_id, esperado=400)

        self.assertIn('2025-12', str(resp.data))
        self.assertEqual(Documento.objects.get(pk=doc_id).estado, 'BORRADOR')
        self.assertFalse(self.movimientos().exists())

    def test_periodo_cerrado_despues_de_crear_no_se_confirma(self):
        doc_id = self._borrador_revisado()
        Periodo.objects.filter(pk=self.enero.pk).update(estado='CERRADO')
        self.confirmar(doc_id, esperado=400)
        self.assertEqual(Documento.objects.get(pk=doc_id).estado, 'BORRADOR')
        self.assertFalse(self.movimientos().exists())

    def test_documento_valido_se_confirma_y_genera_movimiento(self):
        doc_id = self._borrador_revisado()
        self.confirmar(doc_id)
        self.assertEqual(Documento.objects.get(pk=doc_id).estado, 'CONFIRMADO')
        self.assertEqual(self.movimientos().count(), 1)

    def test_anulacion_con_fecha_manipulada_fuera_del_periodo_rechazada(self):
        doc_id = self._borrador_revisado()
        self.confirmar(doc_id)
        Documento.objects.filter(pk=doc_id).update(fecha_emision=date(2025, 12, 15))
        self.anular(doc_id, esperado=400)
        self.assertEqual(Documento.objects.get(pk=doc_id).estado, 'CONFIRMADO')
        self.assertEqual(self.movimientos().count(), 1)
