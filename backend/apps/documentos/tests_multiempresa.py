"""
Regresión SEC-004 y SEC-005: crear_documento aceptaba ProductoUnidad y
DocumentoDetalle (detalle_origen) de otra empresa porque los buscaba solo por id.
"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.catalogos.models import Moneda, TipoComprobante, TipoExistencia, TipoOperacion, UnidadMedida
from apps.documentos.models import Documento, DocumentoDetalle
from apps.empresas.models import Empresa, Establecimiento, Periodo
from apps.inventario.models import Almacen, Producto, ProductoUnidad, Tercero
from apps.usuarios.models import Usuario, UsuarioEmpresa


class DocumentosMultiempresaTests(TestCase):
    def setUp(self):
        self.pen = Moneda.objects.create(codigo='PEN', nombre='Soles')
        self.tipo_existencia = TipoExistencia.objects.create(codigo='01', descripcion='MERCADERIA')
        self.und = UnidadMedida.objects.create(codigo='NIU', descripcion='UNIDAD')
        self.caja = UnidadMedida.objects.create(codigo='BX', descripcion='CAJA')
        self.tipo_factura = TipoComprobante.objects.create(
            codigo_sunat='01', descripcion='FACTURA', es_nota=False, efecto_nota='NINGUNO',
        )
        self.tipo_nc = TipoComprobante.objects.create(
            codigo_sunat='07', descripcion='NOTA DE CREDITO', es_nota=True, efecto_nota='CREDITO',
        )
        self.tipo_op_compra = TipoOperacion.objects.create(
            codigo_interno='COMPRA_LOCAL', codigo_sunat='02', descripcion='COMPRA NACIONAL',
            naturaleza='ENTRADA', es_interna=False, afecta_kardex=True, origen_requerido='DOCUMENTO',
        )
        # CON-007: una NC de compra devuelve al proveedor (SALIDA con detalle_origen).
        self.tipo_op_devolucion = TipoOperacion.objects.create(
            codigo_interno='DEVOLUCION_COMPRA', codigo_sunat='06', descripcion='DEVOLUCION A PROVEEDOR',
            naturaleza='SALIDA', es_interna=False, afecta_kardex=True, origen_requerido='MOV_ORIGEN',
        )

        self.a = self._crear_empresa('20100000011', 'EMPRESA A S.A.C.', 'A')
        self.b = self._crear_empresa('20100000022', 'EMPRESA B S.A.C.', 'B')

        self.usuario = Usuario.objects.create(
            username='admin_a_docs', email='docs_a@test.pe', password_hash='x',
        )
        UsuarioEmpresa.objects.create(usuario=self.usuario, empresa=self.a['empresa'], rol='ADMIN')
        self.client = APIClient()
        self.client.force_authenticate(user=self.usuario)
        self.url = reverse('documento-list-create')
        self.headers = {'HTTP_X_EMPRESA_ID': str(self.a['empresa'].id)}

        # Factura de B con una línea: su detalle no debe poder referenciarse desde A.
        self.factura_b, self.detalle_b = self._crear_factura(self.b, serie='FB01')
        self.factura_a, self.detalle_a = self._crear_factura(self.a, serie='FA01')

    def _crear_empresa(self, ruc, nombre, sufijo):
        empresa = Empresa.objects.create(ruc=ruc, razon_social=nombre, moneda_base_codigo=self.pen)
        establecimiento = Establecimiento.objects.create(
            empresa=empresa, codigo_sunat='0000', nombre=f'SEDE {sufijo}',
        )
        almacen = Almacen.objects.create(
            empresa=empresa, establecimiento=establecimiento, codigo=f'ALM-{sufijo}', nombre=f'ALM {sufijo}',
        )
        producto = Producto.objects.create(
            empresa=empresa, codigo_interno=f'PROD-{sufijo}', descripcion=f'PRODUCTO {sufijo}',
            tipo_existencia_codigo=self.tipo_existencia,
        )
        pu_base = ProductoUnidad.objects.create(
            producto=producto, unidad_codigo=self.und, factor_a_base=Decimal('1.00000000'), es_base=True,
        )
        pu_caja = ProductoUnidad.objects.create(
            producto=producto, unidad_codigo=self.caja, factor_a_base=Decimal('24.00000000'), es_base=False,
        )
        periodo = Periodo.objects.create(
            empresa=empresa, anio=2026, mes=1, orden=202601,
            fecha_inicio='2026-01-01', fecha_fin='2026-01-31', estado='ABIERTO',
        )
        tercero = Tercero.objects.create(
            empresa=empresa, tipo_documento='6', numero_documento=f'2060000000{1 if sufijo == "A" else 2}',
            razon_social=f'PROVEEDOR {sufijo}', es_proveedor=True,
        )
        return {
            'empresa': empresa, 'almacen': almacen, 'producto': producto,
            'pu_base': pu_base, 'pu_caja': pu_caja, 'periodo': periodo, 'tercero': tercero,
        }

    def _crear_factura(self, datos, serie):
        factura = Documento.objects.create(
            empresa=datos['empresa'], clase='COMPRA', periodo=datos['periodo'], tercero=datos['tercero'],
            ruc_emisor=datos['tercero'].numero_documento, tipo_comprobante=self.tipo_factura,
            serie=serie, serie_normalizada=serie, numero='1', numero_normalizado='1',
            fecha_emision='2026-01-10', moneda_codigo=self.pen, subtotal=Decimal('100'),
            igv=Decimal('18'), total=Decimal('118'),
            estado='CONFIRMADO',  # CON-007: las notas solo se emiten sobre documentos CONFIRMADOS.
        )
        detalle = DocumentoDetalle.objects.create(
            documento=factura, linea=1, producto=datos['producto'], producto_unidad=datos['pu_base'],
            almacen=datos['almacen'], tipo_operacion=self.tipo_op_compra,
            cantidad_original=Decimal('10'), factor_conversion=Decimal('1'), cantidad_base=Decimal('10'),
            precio_unitario=Decimal('10'), costo_unitario_pen=Decimal('10'),
        )
        return factura, detalle

    def _linea(self, **extra):
        linea = {
            'producto': self.a['producto'].id,
            'producto_unidad': self.a['pu_base'].id,
            'almacen': self.a['almacen'].id,
            'tipo_operacion': self.tipo_op_compra.id,
            'cantidad_original': '2.00000000',
            'precio_unitario': '10.00000000',
            'igv': '3.60000000',
        }
        linea.update(extra)
        return {k: v for k, v in linea.items() if v is not None}

    def _documento(self, linea, *, tipo=None, numero='100', documento_origen=None):
        data = {
            'clase': 'COMPRA',
            'periodo': self.a['periodo'].id,
            'tercero': self.a['tercero'].id,
            'tipo_comprobante': (tipo or self.tipo_factura).id,
            'serie': 'F001',
            'numero': numero,
            'fecha_emision': '2026-01-15',
            'moneda_codigo': 'PEN',
            'detalles': [linea],
        }
        if documento_origen is not None:
            data['documento_origen'] = documento_origen.id
        return data

    def _post(self, data):
        return self.client.post(self.url, data, format='json', **self.headers)

    def _assert_sin_documento_nuevo(self, antes):
        self.assertEqual(Documento.objects.filter(empresa=self.a['empresa']).count(), antes)
        self.assertFalse(
            DocumentoDetalle.objects.filter(documento__empresa=self.a['empresa'])
            .filter(producto_unidad__producto__empresa=self.b['empresa']).exists()
        )
        self.assertFalse(
            DocumentoDetalle.objects.filter(documento__empresa=self.a['empresa'])
            .filter(detalle_origen__documento__empresa=self.b['empresa']).exists()
        )

    # ---- SEC-004 ---------------------------------------------------------

    def test_sec004_unidad_de_otra_empresa_con_producto_propio_rechazada(self):
        antes = Documento.objects.filter(empresa=self.a['empresa']).count()
        respuesta = self._post(self._documento(self._linea(producto_unidad=self.b['pu_caja'].id)))
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn('no pertenece a la empresa activa', str(respuesta.data))
        self._assert_sin_documento_nuevo(antes)

    def test_sec004_unidad_de_otra_empresa_sin_producto_rechazada(self):
        antes = Documento.objects.filter(empresa=self.a['empresa']).count()
        linea = self._linea(producto_unidad=self.b['pu_caja'].id)
        linea.pop('producto')
        respuesta = self._post(self._documento(linea))
        self.assertEqual(respuesta.status_code, 400)
        self.assertNotIn('BX', str(respuesta.data))
        self._assert_sin_documento_nuevo(antes)

    def test_sec004_unidad_propia_sin_producto_rechazada_con_mensaje_claro(self):
        antes = Documento.objects.filter(empresa=self.a['empresa']).count()
        linea = self._linea(producto_unidad=self.a['pu_caja'].id)
        linea.pop('producto')
        respuesta = self._post(self._documento(linea))
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn('Debe indicar el producto', str(respuesta.data))
        self._assert_sin_documento_nuevo(antes)

    def test_sec004_unidad_propia_coherente_sigue_funcionando(self):
        respuesta = self._post(self._documento(self._linea(producto_unidad=self.a['pu_caja'].id)))
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        detalle = Documento.objects.get(pk=respuesta.data['id']).detalles.get()
        self.assertEqual(detalle.producto_unidad, self.a['pu_caja'])
        self.assertEqual(detalle.cantidad_base, Decimal('48.00000000'))

    # ---- SEC-005 ---------------------------------------------------------

    def test_sec005_detalle_origen_de_otra_empresa_en_nota_rechazado(self):
        antes = Documento.objects.filter(empresa=self.a['empresa']).count()
        respuesta = self._post(self._documento(
            self._linea(detalle_origen=self.detalle_b.id, tipo_operacion=self.tipo_op_devolucion.id),
            tipo=self.tipo_nc, numero='200', documento_origen=self.factura_a,
        ))
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn('no pertenece a la empresa activa', str(respuesta.data))
        self._assert_sin_documento_nuevo(antes)

    def test_sec005_detalle_origen_en_factura_normal_rechazado(self):
        antes = Documento.objects.filter(empresa=self.a['empresa']).count()
        for detalle in (self.detalle_b, self.detalle_a):
            with self.subTest(empresa_del_detalle=detalle.documento.empresa_id):
                respuesta = self._post(self._documento(self._linea(detalle_origen=detalle.id)))
                self.assertEqual(respuesta.status_code, 400)
                self.assertIn('solo se admite en Notas', str(respuesta.data))
        self._assert_sin_documento_nuevo(antes)

    def test_sec005_detalle_de_otro_documento_propio_rechazado(self):
        otra_factura_a, otro_detalle_a = self._crear_factura(self.a, serie='FA02')
        antes = Documento.objects.filter(empresa=self.a['empresa']).count()
        respuesta = self._post(self._documento(
            self._linea(detalle_origen=otro_detalle_a.id, tipo_operacion=self.tipo_op_devolucion.id),
            tipo=self.tipo_nc, numero='201', documento_origen=self.factura_a,
        ))
        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(Documento.objects.filter(empresa=self.a['empresa']).count(), antes)

    def test_sec005_nota_con_detalle_origen_propio_sigue_funcionando(self):
        respuesta = self._post(self._documento(
            self._linea(detalle_origen=self.detalle_a.id, tipo_operacion=self.tipo_op_devolucion.id),
            tipo=self.tipo_nc, numero='202', documento_origen=self.factura_a,
        ))
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        nota = Documento.objects.get(pk=respuesta.data['id'])
        self.assertEqual(nota.detalles.get().detalle_origen, self.detalle_a)
