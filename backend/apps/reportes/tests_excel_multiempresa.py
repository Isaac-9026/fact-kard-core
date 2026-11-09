"""
Regresión SEC-003: el Excel del Kardex resolvía período, producto y almacén por pk
sin filtrar por empresa y mostraba en el encabezado datos de otro tenant.
"""
import io

from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook
from rest_framework.test import APIClient

from apps.catalogos.models import Moneda, TipoExistencia
from apps.empresas.models import Empresa, Establecimiento, Periodo
from apps.inventario.models import Almacen, Producto
from apps.usuarios.models import Usuario, UsuarioEmpresa


def _crear_empresa(ruc, nombre, moneda, sufijo, tipo_existencia):
    empresa = Empresa.objects.create(ruc=ruc, razon_social=nombre, moneda_base_codigo=moneda)
    establecimiento = Establecimiento.objects.create(
        empresa=empresa, codigo_sunat='0000', nombre=f'SEDE {sufijo}',
    )
    almacen = Almacen.objects.create(
        empresa=empresa, establecimiento=establecimiento,
        codigo=f'ALM-{sufijo}', nombre=f'ALMACEN SECRETO {sufijo}',
    )
    producto = Producto.objects.create(
        empresa=empresa, codigo_interno=f'COD-{sufijo}',
        descripcion=f'PRODUCTO CONFIDENCIAL {sufijo}', tipo_existencia_codigo=tipo_existencia,
    )
    periodo = Periodo.objects.create(
        empresa=empresa, anio=2026, mes=10, orden=202610,
        fecha_inicio='2026-10-01', fecha_fin='2026-10-31', estado='ABIERTO',
    )
    return empresa, almacen, producto, periodo


class ExcelKardexMultiempresaTests(TestCase):
    def setUp(self):
        pen = Moneda.objects.create(codigo='PEN', nombre='Soles')
        tipo = TipoExistencia.objects.create(codigo='01', descripcion='MERCADERIA')
        (self.empresa_a, self.almacen_a, self.producto_a, self.periodo_a) = _crear_empresa(
            '20100000001', 'EMPRESA A S.A.C.', pen, 'A', tipo,
        )
        (self.empresa_b, self.almacen_b, self.producto_b, self.periodo_b) = _crear_empresa(
            '20100000002', 'EMPRESA B S.A.C.', pen, 'B', tipo,
        )
        # El período de B se crea con otro mes para que su etiqueta sea distinguible.
        self.periodo_b.mes = 9
        self.periodo_b.orden = 202609
        self.periodo_b.fecha_inicio = '2026-09-01'
        self.periodo_b.fecha_fin = '2026-09-30'
        self.periodo_b.save()

        usuario = Usuario.objects.create(
            username='usuario_a_excel', email='excel_a@test.pe', password_hash='x',
        )
        UsuarioEmpresa.objects.create(usuario=usuario, empresa=self.empresa_a, rol='USUARIO')
        self.client = APIClient()
        self.client.force_authenticate(user=usuario)
        self.url = reverse('kardex-excel-export')
        self.headers = {'HTTP_X_EMPRESA_ID': str(self.empresa_a.id)}

    def _assert_rechazado_sin_fuga(self, params, campo):
        respuesta = self.client.get(self.url, params, **self.headers)
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn(campo, respuesta.data)
        contenido = respuesta.content.decode('utf-8')
        for dato_ajeno in (
            'COD-B', 'PRODUCTO CONFIDENCIAL B', 'ALM-B', 'ALMACEN SECRETO B', '2026-09', 'EMPRESA B',
        ):
            self.assertNotIn(dato_ajeno, contenido)

    def test_producto_de_otra_empresa_es_rechazado(self):
        self._assert_rechazado_sin_fuga({'producto_id': self.producto_b.id}, 'producto_id')

    def test_almacen_de_otra_empresa_es_rechazado(self):
        self._assert_rechazado_sin_fuga({'almacen_id': self.almacen_b.id}, 'almacen_id')

    def test_periodo_de_otra_empresa_es_rechazado(self):
        self._assert_rechazado_sin_fuga({'periodo_id': self.periodo_b.id}, 'periodo_id')

    def test_id_inexistente_es_rechazado(self):
        self._assert_rechazado_sin_fuga({'producto_id': 999999}, 'producto_id')

    def test_filtros_propios_siguen_funcionando(self):
        respuesta = self.client.get(
            self.url,
            {
                'producto_id': self.producto_a.id,
                'almacen_id': self.almacen_a.id,
                'periodo_id': self.periodo_a.id,
            },
            **self.headers,
        )
        self.assertEqual(respuesta.status_code, 200)
        libro = load_workbook(io.BytesIO(respuesta.content))
        encabezado = libro['Kardex Valorizado']['A3'].value
        self.assertIn('2026-10', encabezado)
        self.assertIn('COD-A - PRODUCTO CONFIDENCIAL A', encabezado)
        self.assertIn('ALM-A - ALMACEN SECRETO A', encabezado)
        self.assertNotIn('CONFIDENCIAL B', encabezado)
        self.assertNotIn('SECRETO B', encabezado)
