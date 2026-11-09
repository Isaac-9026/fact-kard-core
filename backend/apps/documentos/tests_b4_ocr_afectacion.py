"""
Bloque 4 — el OCR asumía gravado 18 %: subtotal = total / 1.18 y, sin total, inventaba
118.00; el borrador calculaba IGV 18 % para cualquier línea sin datos. Ahora solo se
clasifica con evidencia del texto; si no la hay, la línea queda pendiente (campo con
confianza 0) y no se genera ningún documento hasta la revisión manual.
"""
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.documentos.captura_services import extraer_ocr_basico
from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.documentos.models import CapturaCampo, Documento, DocumentoCaptura, DocumentoDetalle

D = Decimal


class OcrAfectacionTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()
        self.cabecera = f'FACTURA F001-{{n}} RUC {self.RUC_PROVEEDOR} CLIENTE RUC {self.empresa.ruc} FECHA 2026-01-10 MONEDA S/\n'

    def subir_ocr(self, texto, n):
        archivo = SimpleUploadedFile(f'ocr_{n}.pdf', b'%PDF-1.4 qa', content_type='application/pdf')
        resp = self.client.post(reverse('documento-captura-subir'),
                                {'archivo': archivo, 'tipo': 'PDF', 'texto_ocr': self.cabecera.format(n=n) + texto},
                                format='multipart', **self.headers)
        self.assertEqual(resp.status_code, 201, resp.data)
        return resp.data['id']

    def campo(self, captura_id, nombre):
        return CapturaCampo.objects.get(documento_captura_id=captura_id, seccion='DETALLE', nombre_campo=nombre)

    # 1
    def test_ocr_con_igv_explicito_es_gravado(self):
        captura = self.subir_ocr('1 SKU-OCR-1 TALADRO 100.00 100.00\nOP. GRAVADA: 100.00 IGV 18%: 18.00 TOTAL: 118.00', 501)
        self.assertEqual(self.campo(captura, 'afectacion_igv').valor_extraido, 'GRAVADO')
        resp = self.generar_borrador(captura)
        self.assertEqual(resp.status_code, 201, resp.data)
        det = DocumentoDetalle.objects.get(documento_id=resp.data['documento_id'])
        self.assertEqual((det.afectacion_igv, det.igv, det.precio_unitario), ('GRAVADO', D('18'), D('100')))

    # 2
    def test_ocr_exonerado_con_evidencia(self):
        captura = self.subir_ocr('1 SKU-OCR-1 TALADRO 100.00 100.00\nOP. EXONERADA: 100.00 TOTAL: 100.00', 502)
        self.assertEqual(self.campo(captura, 'afectacion_igv').valor_extraido, 'EXONERADO')
        resp = self.generar_borrador(captura)
        self.assertEqual(resp.status_code, 201, resp.data)
        det = DocumentoDetalle.objects.get(documento_id=resp.data['documento_id'])
        self.assertEqual((det.afectacion_igv, det.igv, det.precio_unitario), ('EXONERADO', D('0'), D('100')))

    # 3 y 5
    def test_ocr_ambiguo_queda_pendiente_y_no_genera_documento(self):
        captura = self.subir_ocr('1 SKU-OCR-1 TALADRO 118.00 118.00\nTOTAL: 118.00', 503)
        afectacion = self.campo(captura, 'afectacion_igv')
        self.assertEqual((afectacion.valor_extraido, afectacion.confianza), ('', D('0')))
        resp = self.generar_borrador(captura)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('afectacion_igv', str(resp.data))
        self.assertFalse(Documento.objects.filter(empresa=self.empresa).exists())
        self.assertIsNone(DocumentoCaptura.objects.get(pk=captura).documento_id)

        # Revisión manual: el usuario indica la afectación y el importe; recién entonces se genera.
        url = reverse('captura-campo-corregir', args=[captura])
        for nombre, valor in (('afectacion_igv', 'EXONERADO'), ('precio_unitario', '118.00'), ('valor_total', '118.00')):
            r = self.client.patch(url, {'campo_id': self.campo(captura, nombre).id, 'valor_corregido': valor},
                                  format='json', **self.headers)
            self.assertEqual(r.status_code, 200, r.data)
        resp = self.generar_borrador(captura)
        self.assertEqual(resp.status_code, 201, resp.data)
        det = DocumentoDetalle.objects.get(documento_id=resp.data['documento_id'])
        self.assertEqual((det.afectacion_igv, det.igv), ('EXONERADO', D('0')))
        self.assertEqual(Documento.objects.get(pk=resp.data['documento_id']).estado, 'BORRADOR')

    # 4
    def test_nunca_asume_18_por_ciento_sin_fundamento(self):
        for texto in ('TOTAL: 118.00', 'TOTAL: 236.00', 'SIN IMPORTES'):
            with self.subTest(texto=texto):
                datos = extraer_ocr_basico(b'', 'x.pdf', self.cabecera.format(n=1) + texto)
                linea = datos['detalles'][0]
                self.assertEqual(linea['afectacion_igv'], '')
                self.assertEqual(linea['igv'], '')
                self.assertEqual(datos['cabecera']['igv'], ('', D('0.0000')))
                self.assertNotEqual(datos['cabecera']['subtotal'][0], '100.00000000')
        sin_total = extraer_ocr_basico(b'', 'x.pdf', self.cabecera.format(n=1))
        self.assertEqual(sin_total['cabecera']['total'], ('', D('0.0000')))  # antes: 118.00 inventado

    def test_exonerado_e_inafecto_a_la_vez_es_ambiguo(self):
        datos = extraer_ocr_basico(b'', 'x.pdf', self.cabecera.format(n=1) + 'OP. EXONERADA: 50.00 OP. INAFECTA: 50.00 TOTAL: 100.00')
        self.assertEqual(datos['detalles'][0]['afectacion_igv'], '')

    def test_subtotal_no_se_confunde_con_total(self):
        datos = extraer_ocr_basico(b'', 'x.pdf', self.cabecera.format(n=1) + 'SUB TOTAL: 100.00 IGV: 18.00 TOTAL: 118.00')
        self.assertEqual(datos['cabecera']['total'][0], '118.00000000')
        self.assertEqual(datos['cabecera']['subtotal'][0], '100.00000000')

    def test_xml_sin_afectacion_ni_igv_en_linea_ni_documento_es_pendiente(self):
        self.homologar_sku()
        lineas = [{'codigo': 'SKU-QA-1', 'descripcion': 'ITEM', 'cantidad': '10', 'precio': '10.00',
                   'afectacion': '', 'igv': '0.00'}]
        resp = self.generar_borrador(self.subir_xml(numero='601', lineas=lineas))
        self.assertEqual(resp.status_code, 400)
        self.assertIn('afectacion_igv', str(resp.data))
