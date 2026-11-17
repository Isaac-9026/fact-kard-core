"""
Pruebas automatizadas para la carga por lote de comprobantes XML y archivos ZIP.
Verifica:
- Tolerancia a fallos parciales (nuevos, duplicados y errores en la misma petición).
- Descompresión segura y filtrado de archivos no-XML en paquetes ZIP.
"""
import io
import zipfile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.documentos.fixtures_bloque2 import Bloque2Fixture, construir_xml_ubl
from apps.documentos.models import DocumentoCaptura


class CargaLoteXmlTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()

    def _crear_xml(self, serie='F001', numero='00000001', emisor='20888000101'):
        return construir_xml_ubl(
            serie=serie,
            numero=numero,
            emisor=emisor,
            emisor_nombre='PROVEEDOR LOTE SAC',
            receptor=self.empresa.ruc,
            receptor_nombre=self.empresa.razon_social,
            lineas=[{'codigo': 'ITEM-01', 'descripcion': 'PRODUCTO LOTE', 'cantidad': '2', 'precio': '10.00'}],
        )

    def test_subir_lote_xml_multiples_archivos_y_duplicados(self):
        # 1. Pre-crear una captura para que actúe como duplicado
        xml_dup = self._crear_xml(serie='F001', numero='00000001')
        file_dup = SimpleUploadedFile('F001-00000001.xml', xml_dup.encode(), content_type='application/xml')
        resp_pre = self.client.post(
            reverse('documento-captura-subir'),
            {'archivo': file_dup, 'tipo': 'XML'},
            format='multipart',
            **self.headers,
        )
        self.assertEqual(resp_pre.status_code, 201)
        captura_pre_id = resp_pre.data['id']

        # 2. Preparar los 3 archivos para el lote:
        # - xml_nuevo (nuevo comprobante)
        # - xml_dup_again (el mismo contenido que ya existe)
        # - xml_corrupto (XML mal formado / inválido)
        xml_nuevo = self._crear_xml(serie='F001', numero='00000002')
        xml_corrupto = "Este no es un XML válido <<<>>>"

        f_nuevo = SimpleUploadedFile('F001-00000002.xml', xml_nuevo.encode(), content_type='application/xml')
        f_dup = SimpleUploadedFile('F001-00000001_copia.xml', xml_dup.encode(), content_type='application/xml')
        f_err = SimpleUploadedFile('corrupto.xml', xml_corrupto.encode(), content_type='application/xml')

        resp = self.client.post(
            reverse('documento-captura-subir-lote-xml'),
            {'archivos': [f_nuevo, f_dup, f_err]},
            format='multipart',
            **self.headers,
        )

        self.assertEqual(resp.status_code, 201)
        data = resp.data
        self.assertEqual(data['total_procesados'], 3)
        self.assertEqual(data['nuevos'], 1)
        self.assertEqual(data['duplicados'], 1)
        self.assertEqual(data['errores'], 1)
        self.assertIsNotNone(data['ultima_captura_id'])

        # Verificar estados individuales
        estados = {r['nombre_archivo']: r['estado'] for r in data['resultados']}
        self.assertEqual(estados['F001-00000002.xml'], 'NUEVO')
        self.assertEqual(estados['F001-00000001_copia.xml'], 'DUPLICADO_REUTILIZADO')
        self.assertEqual(estados['corrupto.xml'], 'ERROR')

        # Verificar que la captura duplicada reutiliza la original
        res_dup = next(r for r in data['resultados'] if r['nombre_archivo'] == 'F001-00000001_copia.xml')
        self.assertEqual(res_dup['captura_id'], captura_pre_id)

    def test_subir_lote_xml_desde_archivo_zip(self):
        xml_1 = self._crear_xml(serie='F001', numero='00000010')
        xml_2 = self._crear_xml(serie='F001', numero='00000020')

        # Crear zip en memoria con 2 XMLs válidos y 1 archivo ignorado (.txt y __MACOSX)
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, 'w') as zf:
            zf.writestr('comprobantes/F001-00000010.xml', xml_1)
            zf.writestr('comprobantes/F001-00000020.xml', xml_2)
            zf.writestr('comprobantes/leeme.txt', 'Archivo de instrucciones que debe ser ignorado.')
            zf.writestr('__MACOSX/._F001-00000010.xml', 'Mac metadata ignorada')

        zip_buf.seek(0)
        zip_file = SimpleUploadedFile('lote_facturas.zip', zip_buf.read(), content_type='application/zip')

        resp = self.client.post(
            reverse('documento-captura-subir-lote-xml'),
            {'archivos': [zip_file]},
            format='multipart',
            **self.headers,
        )

        self.assertEqual(resp.status_code, 201)
        data = resp.data
        self.assertEqual(data['total_procesados'], 2)
        self.assertEqual(data['nuevos'], 2)
        self.assertEqual(data['duplicados'], 0)
        self.assertEqual(data['errores'], 0)

        # Verificar que se crearon en BD
        self.assertEqual(DocumentoCaptura.objects.filter(empresa=self.empresa).count(), 2)
