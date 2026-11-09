"""
QA2-001 — integración XML1 → homologar → XML2 (mismo proveedor + SKU + unidad).

Flujo real de la pantalla: se sube el XML1 de un proveedor NUEVO, se homologa la línea desde la
vista previa (antes o después del borrador), y luego se sube un XML2 distinto. El XML2 debe
mostrar la equivalencia aplicada y 0 líneas pendientes en cuanto se sube, y su borrador no debe
tener líneas sin homologar. Sin equivalencias ni productos nuevos.

Antes: la vista previa no resolvía nada (la regla solo corría al generar el borrador, así que
la pantalla mostraba "Homologar" en cada línea) y el proveedor recién existía tras el borrador
del XML1 (homologando antes, el modal no lo tenía y la equivalencia quedaba con otro proveedor).
"""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.documentos.fixtures_bloque2 import Bloque2Fixture, construir_xml_ubl
from apps.empresas.models import Periodo
from apps.inventario.models import Producto, ProductoEquivalencia, Tercero

RUC_NUEVO = '20888000101'


class Xml2ReutilizaEquivalenciaTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()

    def subir(self, numero, *, codigo='ABC-01', descripcion='TORNILLO HEXAGONAL 3/8', unidad='NIU', emisor=RUC_NUEVO, empresa=None, headers=None):
        xml = construir_xml_ubl(
            serie='F201', numero=numero, emisor=emisor, emisor_nombre='PROVEEDOR NUEVO SAC',
            receptor=(empresa or self.empresa).ruc, receptor_nombre=(empresa or self.empresa).razon_social,
            lineas=[{'codigo': codigo, 'descripcion': descripcion, 'cantidad': '5', 'precio': '2.00'}],
        ).replace('unitCode="NIU"', f'unitCode="{unidad}"')
        archivo = SimpleUploadedFile(f'F201-{numero}.xml', xml.encode(), content_type='text/xml')
        resp = self.client.post(reverse('documento-captura-subir'), {'archivo': archivo, 'tipo': 'XML'},
                                format='multipart', **(headers or self.headers))
        self.assertIn(resp.status_code, (200, 201), resp.data)
        return resp.data

    def detalle(self, captura_id, headers=None):
        resp = self.client.get(reverse('documento-captura-detail', args=[captura_id]), **(headers or self.headers))
        self.assertEqual(resp.status_code, 200)
        return resp.data['homologacion']

    def homologar(self, captura_id, esperado=201, **extra):
        datos = {'captura': captura_id, 'codigo_externo': 'ABC-01', 'descripcion_externa': 'TORNILLO HEXAGONAL 3/8',
                 'unidad_externa_codigo': 'NIU', 'producto_unidad': self.pu.id, 'factor_conversion': '1', 'activa': True, **extra}
        resp = self.client.post(reverse('producto-equivalencia-list-create'), datos, format='json', **self.headers)
        self.assertEqual(resp.status_code, esperado, resp.data)
        return resp

    def conteos(self):
        return (ProductoEquivalencia.objects.filter(empresa=self.empresa).count(),
                Producto.objects.filter(empresa=self.empresa).count(),
                Tercero.objects.filter(empresa=self.empresa, numero_documento=RUC_NUEVO).count())

    # ------------------------------------------------------------------------------------

    def test_xml1_homologa_antes_del_borrador_y_xml2_se_aplica_al_subir(self):
        productos = Producto.objects.filter(empresa=self.empresa).count()
        xml1 = self.subir('101')
        h1 = xml1['homologacion']  # la respuesta de la subida ya trae la vista previa
        self.assertEqual(h1['pendientes_homologacion'], 1)
        self.assertEqual(h1['proveedor']['documento'], RUC_NUEVO)
        self.assertIsNone(h1['proveedor']['tercero_id'])  # proveedor nuevo: aún no existe
        self.assertEqual(h1['lineas'][0]['estado'], 'PENDIENTE')

        # Homologar desde la línea del XML1: el proveedor del comprobante se registra al guardar
        # (la pantalla envía tercero=null y la captura).
        eq = self.homologar(xml1['id'], tercero=None).data
        proveedor = Tercero.objects.get(empresa=self.empresa, numero_documento=RUC_NUEVO)
        self.assertTrue(proveedor.es_proveedor)
        self.assertEqual(eq['tercero'], proveedor.id)
        self.assertTrue(ProductoEquivalencia.objects.get(pk=eq['id']).activa)
        self.assertEqual(self.detalle(xml1['id'])['pendientes_homologacion'], 0)

        # XML2 distinto: mismo proveedor + SKU + unidad.
        xml2 = self.subir('102')
        self.assertNotEqual(xml2['id'], xml1['id'])
        h2 = xml2['homologacion']
        self.assertEqual(h2['pendientes_homologacion'], 0)
        linea = h2['lineas'][0]
        self.assertEqual((linea['estado'], linea['equivalencia_id'], linea['producto_id']), ('HOMOLOGADA', eq['id'], self.producto.id))
        self.assertEqual((linea['criterio'], linea['codigo_normalizado'], linea['unidad_normalizada']), ('codigo', 'ABC-01', 'NIU'))
        self.assertEqual(h2['proveedor']['tercero_id'], proveedor.id)

        borrador = self.generar_borrador(xml2['id'])
        self.assertEqual(borrador.status_code, 201, borrador.data)
        self.assertEqual(borrador.data['lineas_sin_homologar'], 0)
        self.assertEqual(self.conteos(), (1, productos, 1))  # sin equivalencias, productos ni proveedores nuevos

    def test_xml1_homologa_despues_del_borrador_y_xml2_se_aplica(self):
        xml1 = self.subir('201')
        self.assertEqual(self.generar_borrador(xml1['id']).data['lineas_sin_homologar'], 1)
        proveedor = Tercero.objects.get(empresa=self.empresa, numero_documento=RUC_NUEVO)
        self.homologar(xml1['id'], tercero=proveedor.id)
        h2 = self.subir('202')['homologacion']
        self.assertEqual(h2['pendientes_homologacion'], 0)

    def test_normaliza_espacios_mayusculas_y_unidad(self):
        xml1 = self.subir('301')
        self.homologar(xml1['id'], codigo_externo='  abc-01 ')
        h2 = self.subir('302', codigo=' Abc-01  ', unidad='niu')['homologacion']
        self.assertEqual(h2['pendientes_homologacion'], 0)

    def test_descripcion_solo_si_no_hay_codigo(self):
        xml1 = self.subir('401')
        self.homologar(xml1['id'])
        # Otro código con la misma descripción: NO se toma por descripción.
        h = self.subir('402', codigo='ZZZ-99')['homologacion']
        self.assertEqual((h['pendientes_homologacion'], h['lineas'][0]['criterio']), (1, 'codigo'))
        # Sin código: fallback por descripción, solo contra equivalencias sin código.
        h = self.subir('403', codigo='')['homologacion']
        self.assertEqual(h['pendientes_homologacion'], 1)
        self.homologar(self.subir('404', codigo='')['id'], codigo_externo='', descripcion_externa='tornillo  hexagonal 3/8')
        h = self.subir('405', codigo='')['homologacion']
        self.assertEqual((h['pendientes_homologacion'], h['lineas'][0]['criterio']), (0, 'descripcion'))

    def test_otra_unidad_queda_pendiente_y_lo_explica(self):
        xml1 = self.subir('501')
        self.homologar(xml1['id'])
        h = self.subir('502', unidad='BX')['homologacion']
        self.assertEqual(h['pendientes_homologacion'], 1)
        self.assertIn('unidad NIU', h['lineas'][0]['motivo'])

    def test_no_se_duplica_y_proveedor_equivocado_se_rechaza(self):
        xml1 = self.subir('601')
        self.homologar(xml1['id'])
        resp = self.homologar(xml1['id'], esperado=400, codigo_externo='abc-01')
        self.assertIn('Ya existe una equivalencia activa', str(resp.data))
        resp = self.homologar(self.subir('602')['id'], esperado=400, tercero=self.proveedor.id, codigo_externo='OTRO')
        self.assertIn('no es el emisor del comprobante', str(resp.data))
        self.assertEqual(ProductoEquivalencia.objects.filter(empresa=self.empresa).count(), 1)

    def test_multiempresa_la_equivalencia_de_otra_empresa_no_se_aplica(self):
        xml1 = self.subir('701')
        self.homologar(xml1['id'])
        # La otra empresa recibe un XML del mismo proveedor y SKU: no ve la equivalencia.
        from apps.usuarios.models import UsuarioEmpresa
        UsuarioEmpresa.objects.get_or_create(usuario=self.usuario, empresa=self.otra_empresa, defaults={'rol': 'ADMIN'})
        Periodo.objects.create(empresa=self.otra_empresa, anio=2026, mes=1, orden=202601,
                               fecha_inicio='2026-01-01', fecha_fin='2026-01-31', estado='ABIERTO')
        otros = {'HTTP_X_EMPRESA_ID': str(self.otra_empresa.id)}
        h = self.subir('702', empresa=self.otra_empresa, headers=otros)['homologacion']
        self.assertEqual(h['pendientes_homologacion'], 1)
        self.assertIsNone(h['proveedor']['tercero_id'])
        # La captura de una empresa no sirve para registrar equivalencias en otra.
        prod = self.client.post(reverse('producto-list-create'), {'codigo_interno': 'P-OTRA', 'descripcion': 'OTRA',
                                'tipo_existencia_codigo': '01', 'unidad_base_codigo': 'NIU'}, format='json', **otros)
        self.assertEqual(prod.status_code, 201, prod.data)
        pu_otra = Producto.objects.get(pk=prod.data['id']).unidades.get(es_base=True).id
        resp = self.client.post(reverse('producto-equivalencia-list-create'),
                                {'captura': xml1['id'], 'codigo_externo': 'ABC-01', 'unidad_externa_codigo': 'NIU',
                                 'producto_unidad': pu_otra, 'factor_conversion': '1'}, format='json', **otros)
        self.assertEqual(resp.status_code, 400)
        self.assertIn('Captura no encontrada para esta empresa', str(resp.data))
        self.assertEqual(ProductoEquivalencia.objects.filter(empresa=self.otra_empresa).count(), 0)
