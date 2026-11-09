"""
Bloque 14 — homologación de productos: una sola equivalencia ACTIVA por proveedor y código
externo (o descripción, si el proveedor no envía código). Antes se podían registrar dos; la
captura tomaba cualquiera y la línea podía ir a un producto distinto.
"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.inventario.models import ProductoEquivalencia, Tercero


class EquivalenciaUnicaTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()
        self.pu2 = self.producto_2.unidades.get(es_base=True)

    def crear(self, codigo='SKU-77', descripcion='ARTICULO 77', pu=None, tercero=None, esperado=201, **extra):
        datos = {'tercero': (tercero or self.proveedor).id, 'codigo_externo': codigo, 'descripcion_externa': descripcion,
                 'unidad_externa_codigo': 'NIU', 'producto_unidad': (pu or self.pu).id, 'factor_conversion': '1', 'activa': True, **extra}
        resp = self.client.post(reverse('producto-equivalencia-list-create'), datos, format='json', **self.headers)
        self.assertEqual(resp.status_code, esperado, resp.data)
        return resp

    def test_no_se_registra_otra_activa_con_el_mismo_codigo(self):
        self.crear()
        resp = self.crear(codigo='sku-77', pu=self.pu2, esperado=400)  # mismo código sin importar mayúsculas
        self.assertIn('Ya existe una equivalencia activa para este proveedor', str(resp.data['codigo_externo']))
        self.assertIn('P-B2', str(resp.data['codigo_externo']))
        self.assertEqual(ProductoEquivalencia.objects.filter(empresa=self.empresa, activa=True).count(), 1)

    def test_sin_codigo_no_se_repite_la_descripcion(self):
        self.crear(codigo='', descripcion='Tornillo 3/8')
        self.crear(codigo='', descripcion='TORNILLO 3/8', pu=self.pu2, esperado=400)

    def test_otro_proveedor_u_otro_codigo_si(self):
        self.crear()
        self.crear(codigo='SKU-88', pu=self.pu2)
        self.crear(tercero=self.proveedor_2)

    def test_desactivar_y_registrar_una_nueva(self):
        eq = self.crear().data['id']
        resp = self.client.patch(reverse('producto-equivalencia-detail', args=[eq]), {'activa': False}, format='json', **self.headers)
        self.assertEqual(resp.status_code, 200, resp.data)
        self.crear(pu=self.pu2)
        # Reactivar la antigua dejaría dos activas: se rechaza.
        resp = self.client.patch(reverse('producto-equivalencia-detail', args=[eq]), {'activa': True}, format='json', **self.headers)
        self.assertEqual(resp.status_code, 400)

    def test_editar_la_misma_equivalencia_no_choca_consigo_misma(self):
        eq = self.crear().data['id']
        resp = self.client.patch(reverse('producto-equivalencia-detail', args=[eq]), {'factor_conversion': '12'}, format='json', **self.headers)
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertEqual(ProductoEquivalencia.objects.get(pk=eq).factor_conversion, Decimal('12.00000000'))

    def test_otra_empresa_es_independiente(self):
        self.crear()
        ProductoEquivalencia.objects.create(
            empresa=self.otra_empresa, tercero=Tercero.objects.create(
                empresa=self.otra_empresa, tipo_documento='6', numero_documento=self.RUC_PROVEEDOR, razon_social='P', es_proveedor=True),
            codigo_externo='SKU-77', descripcion_externa='X', unidad_externa_codigo=self.und, producto_unidad=self.pu,
            factor_conversion=Decimal('1'), activa=True,
        )
        self.assertEqual(ProductoEquivalencia.objects.filter(codigo_externo='SKU-77', activa=True).count(), 2)
        self.crear(codigo='SKU-99')  # la de la otra empresa no bloquea nada aquí
