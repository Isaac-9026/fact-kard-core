"""
Bloque 5 — OCR: varias líneas, sin valores inventados (tipo, serie, moneda, razón social,
ítem) y sin 18 % supuesto; lo ambiguo va a revisión manual sin crear documento.
"""
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.documentos.captura_services import extraer_ocr_basico
from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.documentos.models import Documento, DocumentoDetalle

D = Decimal


class OcrLineasTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()
        self.cab = f'FACTURA F001-{{n}} RUC {self.RUC_PROVEEDOR} CLIENTE RUC {self.empresa.ruc} FECHA 2026-01-10 S/\n'

    def subir(self, cuerpo, n):
        archivo = SimpleUploadedFile(f'b5_{n}.pdf', f'%PDF {n}'.encode(), content_type='application/pdf')
        resp = self.client.post(reverse('documento-captura-subir'),
                                {'archivo': archivo, 'tipo': 'PDF', 'texto_ocr': self.cab.format(n=n) + cuerpo},
                                format='multipart', **self.headers)
        self.assertEqual(resp.status_code, 201, resp.data)
        return resp.data['id']

    def test_varias_lineas_gravadas(self):
        cuerpo = ('2 SKU-A1 TORNILLO 3/8 1.50 3.00\n'
                  '4 CABLE N14 2.25 9.00\n'
                  'OP. GRAVADA: 12.00 IGV 18%: 2.16 TOTAL: 14.16')
        datos = extraer_ocr_basico(b'', 'x.pdf', self.cab.format(n=1) + cuerpo)
        self.assertEqual([(d['codigo_externo'], d['descripcion'], d['valor_total']) for d in datos['detalles']],
                         [('SKU-A1', 'TORNILLO 3/8', D('3')), ('', 'CABLE N14', D('9'))])
        resp = self.generar_borrador(self.subir(cuerpo, 801))
        self.assertEqual(resp.status_code, 201, resp.data)
        lineas = DocumentoDetalle.objects.filter(documento_id=resp.data['documento_id']).order_by('linea')
        self.assertEqual([(l.afectacion_igv, l.igv) for l in lineas], [('GRAVADO', D('0.54')), ('GRAVADO', D('1.62'))])

    def test_lineas_que_no_cuadran_con_el_subtotal_van_a_revision(self):
        cuerpo = '2 SKU-A1 TORNILLO 1.50 3.00\nOP. GRAVADA: 50.00 IGV: 9.00 TOTAL: 59.00'
        datos = extraer_ocr_basico(b'', 'x.pdf', self.cab.format(n=1) + cuerpo)
        self.assertEqual((datos['detalles'][0]['descripcion'], datos['detalles'][0]['confianza']), ('', D('0')))
        resp = self.generar_borrador(self.subir(cuerpo, 802))
        self.assertEqual(resp.status_code, 400)
        self.assertIn('sin código ni descripción', str(resp.data))
        self.assertFalse(Documento.objects.filter(empresa=self.empresa).exists())

    def test_igv_que_no_corresponde_a_todas_las_lineas_va_a_revision(self):
        # IGV 0.54 solo cubre la primera línea (la otra sería exonerada): ambiguo.
        cuerpo = '2 SKU-A1 TORNILLO 1.50 3.00\n4 CABLE N14 2.25 9.00\nIGV: 0.54 TOTAL: 12.54'
        resp = self.generar_borrador(self.subir(cuerpo, 803))
        self.assertEqual(resp.status_code, 400)
        self.assertIn("campo 'igv'", str(resp.data))
        self.assertFalse(Documento.objects.filter(empresa=self.empresa).exists())

    def test_no_inventa_tipo_serie_moneda_ni_razon_social(self):
        datos = extraer_ocr_basico(b'', 'x.pdf', f'RUC {self.RUC_PROVEEDOR} RUC {self.empresa.ruc} TOTAL 10.00')
        cab = datos['cabecera']
        for campo in ('tipo_comprobante', 'serie', 'numero', 'moneda', 'razon_social_emisor'):
            with self.subTest(campo=campo):
                self.assertEqual(cab[campo], ('', D('0.0000')))

    def test_sin_serie_no_genera_borrador(self):
        self.cab = f'FACTURA RUC {self.RUC_PROVEEDOR} CLIENTE RUC {self.empresa.ruc} FECHA 2026-01-10 S/ {{n}}\n'
        resp = self.generar_borrador(self.subir('1 SKU-A1 TORNILLO 10.00 10.00\nOP. EXONERADA: 10.00 TOTAL: 10.00', 804))
        self.assertEqual(resp.status_code, 400)
        self.assertIn('serie', str(resp.data))
