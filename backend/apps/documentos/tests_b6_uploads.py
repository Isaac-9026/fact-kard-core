"""Bloque 6 — controles mínimos de archivos de captura."""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.documentos.fixtures_bloque2 import Bloque2Fixture, construir_xml_ubl
from apps.documentos.models import DocumentoCaptura
from apps.documentos.uploads import nombre_seguro


class UploadsTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()

    def subir(self, nombre, contenido, tipo, mime):
        return self.client.post(reverse('documento-captura-subir'),
                                {'archivo': SimpleUploadedFile(nombre, contenido, content_type=mime), 'tipo': tipo},
                                format='multipart', **self.headers)

    def assert_rechazo(self, resp, texto):
        self.assertEqual(resp.status_code, 400, getattr(resp, 'data', None))
        self.assertIn(texto, str(resp.data))
        self.assertFalse(DocumentoCaptura.objects.filter(empresa=self.empresa).exists())

    def test_archivos_validos(self):
        xml = construir_xml_ubl(numero='1').encode()
        self.assertEqual(self.subir('../../etc/fact ura?.xml', xml, 'XML', 'text/xml').status_code, 201)
        self.assertEqual(self.subir('scan.PDF', b'%PDF-1.7 x', 'ESCANER', 'application/octet-stream').status_code, 201)
        self.assertEqual(self.subir('foto.png', b'\x89PNG\r\n\x1a\n' + b'0' * 10, 'IMAGEN', 'image/png').status_code, 201)
        rutas = set(DocumentoCaptura.objects.values_list('ruta_archivo', flat=True))
        self.assertIn('uploads/xml/fact_ura.xml', rutas)  # sin rutas ni caracteres peligrosos
        self.assertIn('uploads/escaner/scan.pdf', rutas)

    @override_settings(CAPTURA_MAX_BYTES=1024)
    def test_tamano_maximo(self):
        self.assert_rechazo(self.subir('grande.pdf', b'%PDF' + b'0' * 2000, 'PDF', 'application/pdf'), 'tamaño máximo')

    def test_archivo_vacio(self):
        self.assert_rechazo(self.subir('vacio.pdf', b'', 'PDF', 'application/pdf'), 'archivo')

    def test_extension_no_permitida(self):
        self.assert_rechazo(self.subir('malo.exe', b'%PDF-1.4', 'PDF', 'application/pdf'), 'no permitida')
        self.assert_rechazo(self.subir('foto.png', b'\x89PNG\r\n\x1a\n', 'XML', 'image/png'), 'no permitida')

    def test_mime_que_no_corresponde(self):
        self.assert_rechazo(self.subir('doc.pdf', b'%PDF-1.4', 'PDF', 'text/html'), 'MIME')

    def test_contenido_que_no_corresponde_a_la_extension(self):
        self.assert_rechazo(self.subir('falso.pdf', b'MZ\x90\x00 ejecutable', 'PDF', 'application/pdf'), 'contenido')

    def test_xml_con_entidades_rechazado(self):
        xml = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><Invoice>&a;</Invoice>'
        self.assert_rechazo(self.subir('bomba.xml', xml, 'XML', 'text/xml'), 'DOCTYPE')

    def test_nombre_seguro(self):
        self.assertEqual(nombre_seguro('C:\\Users\\x\\Factura Enero (1).PDF'), 'Factura_Enero_1.pdf')
        self.assertEqual(nombre_seguro('../../../etc/passwd.xml'), 'passwd.xml')
        self.assertNotIn('/', nombre_seguro('/tmp/../.xml'))
        self.assertLessEqual(len(nombre_seguro('a' * 500 + '.pdf')), 84)
