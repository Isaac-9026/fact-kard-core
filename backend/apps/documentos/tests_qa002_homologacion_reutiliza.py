"""
QA-002 — una equivalencia registrada al homologar el XML 1 debe reutilizarse sola en el XML 2.

Clave: empresa + proveedor + código del proveedor (o descripción) + unidad. Se compara sin
distinguir mayúsculas ni espacios repetidos/saltos de línea; el marcador '—' que guardaba la
pantalla cuando el ítem no traía código cuenta como "sin código". No se crean productos ni
equivalencias duplicadas.
"""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.catalogos.models import UnidadMedida
from apps.documentos.fixtures_bloque2 import Bloque2Fixture, construir_xml_ubl
from apps.inventario.models import Producto, ProductoEquivalencia


class HomologacionReutilizaTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()

    def equivalencia_ui(self, esperado=201, **datos):
        """Como la pantalla de homologación (POST de la API)."""
        payload = {'tercero': self.proveedor.id, 'codigo_externo': 'SKU-QA-1', 'descripcion_externa': 'ITEM XML QA',
                   'unidad_externa_codigo': 'NIU', 'producto_unidad': self.pu.id, 'factor_conversion': '1', 'activa': True}
        payload.update(datos)
        resp = self.client.post(reverse('producto-equivalencia-list-create'), payload, format='json', **self.headers)
        self.assertEqual(resp.status_code, esperado, resp.data)
        return resp

    def borrador(self, numero, **kwargs):
        resp = self.generar_borrador(self.subir_xml(numero=numero, **kwargs))
        self.assertEqual(resp.status_code, 201, resp.data)
        return resp.data

    def test_xml1_homologa_y_xml2_reutiliza_automaticamente(self):
        productos = Producto.objects.filter(empresa=self.empresa).count()
        primero = self.borrador('601')
        self.assertEqual(primero['lineas_sin_homologar'], 1)
        # El usuario homologa (código escrito en minúsculas y con espacios: se normaliza).
        self.equivalencia_ui(codigo_externo='  sku-qa-1 ')
        segundo = self.borrador('602', lineas=[{'codigo': 'SKU-QA-1', 'descripcion': 'ITEM XML QA', 'cantidad': '4', 'precio': '10.00'}])
        self.assertEqual(segundo['lineas_sin_homologar'], 0)
        detalle = self.client.get(reverse('documento-detail', args=[segundo['documento_id']]), **self.headers).data['detalles'][0]
        self.assertEqual(detalle['producto'], self.producto.id)
        self.assertEqual(Producto.objects.filter(empresa=self.empresa).count(), productos)   # sin productos nuevos
        self.assertEqual(ProductoEquivalencia.objects.filter(empresa=self.empresa).count(), 1)  # sin duplicados
        self.assertEqual(ProductoEquivalencia.objects.get().codigo_externo, 'sku-qa-1')  # guardado sin espacios

    def test_sin_codigo_reutiliza_por_descripcion_aunque_cambien_espacios_y_mayusculas(self):
        # La pantalla anterior guardaba '—' como código cuando el ítem no traía código.
        self.equivalencia_ui(codigo_externo='—', descripcion_externa='Item XML QA')
        self.assertIsNone(ProductoEquivalencia.objects.get().codigo_externo)
        datos = self.borrador('603', lineas=[{'codigo': '', 'descripcion': 'ITEM   XML\n  QA', 'cantidad': '2', 'precio': '10.00'}])
        self.assertEqual(datos['lineas_sin_homologar'], 0)

    def test_misma_clave_no_se_duplica_aunque_cambien_espacios_o_mayusculas(self):
        self.equivalencia_ui()
        resp = self.equivalencia_ui(codigo_externo=' Sku-Qa-1', esperado=400)
        self.assertIn('Ya existe una equivalencia activa', str(resp.data))

    def test_unidad_distinta_no_se_reutiliza_y_lo_explica(self):
        UnidadMedida.objects.create(codigo='BX', descripcion='CAJA')
        self.equivalencia_ui(unidad_externa_codigo='BX', factor_conversion='12')
        datos = self.borrador('604')  # el XML trae NIU
        self.assertEqual(datos['lineas_sin_homologar'], 1)
        from apps.kardex.models import Incidencia
        self.assertIn('unidad BX', Incidencia.objects.filter(tipo='PRODUCTO_SIN_HOMOLOGAR').latest('id').descripcion)
        # Una equivalencia por unidad: la de NIU sí se puede registrar y se usa.
        self.equivalencia_ui()
        self.assertEqual(self.borrador('605')['lineas_sin_homologar'], 0)

    def test_equivalencia_de_otro_proveedor_no_se_usa(self):
        self.equivalencia_ui(tercero=self.proveedor_2.id)
        self.assertEqual(self.borrador('606')['lineas_sin_homologar'], 1)

    def test_codigo_del_proveedor_es_sellers_item_identification(self):
        self.equivalencia_ui()
        xml = construir_xml_ubl(numero='607', emisor=self.RUC_PROVEEDOR, receptor=self.empresa.ruc).replace(
            '<cac:SellersItemIdentification>',
            '<cac:BuyersItemIdentification><cbc:ID>COD-COMPRADOR</cbc:ID></cac:BuyersItemIdentification>'
            '<cac:SellersItemIdentification>',
        )
        archivo = SimpleUploadedFile('comprobante_607.xml', xml.encode(), content_type='text/xml')
        captura = self.client.post(reverse('documento-captura-subir'), {'archivo': archivo, 'tipo': 'XML'},
                                   format='multipart', **self.headers).data['id']
        resp = self.generar_borrador(captura)
        self.assertEqual(resp.status_code, 201, resp.data)
        self.assertEqual(resp.data['lineas_sin_homologar'], 0)

    def test_sugerir_usa_la_misma_comparacion(self):
        self.equivalencia_ui()
        resp = self.client.get(reverse('producto-equivalencia-sugerir'),
                               {'tercero_id': self.proveedor.id, 'codigo_externo': ' sku-qa-1 '}, **self.headers)
        self.assertTrue(resp.data['encontrado'])
