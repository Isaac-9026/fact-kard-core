from datetime import date
from decimal import Decimal
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.auditoria.models import Auditoria
from apps.catalogos.models import Moneda, TipoCambio, TipoComprobante, TipoOperacion, UnidadMedida, TipoExistencia
from apps.documentos.models import Documento, DocumentoDetalle, DocumentoCaptura, CapturaCampo
from apps.empresas.models import Empresa, Establecimiento, Periodo, ConfigIgvPeriodo
from apps.inventario.models import Almacen, Producto, ProductoUnidad, ProductoEquivalencia, Tercero
from apps.kardex.models import Incidencia
from apps.usuarios.models import Usuario, UsuarioEmpresa


class DocumentosIntegridadTest(TestCase):
    def setUp(self):
        self.moneda = Moneda.objects.create(codigo='PEN', nombre='Soles')
        self.empresa = Empresa.objects.create(
            ruc='20600000001',
            razon_social='DOCS TEST S.A.C.',
            moneda_base_codigo=self.moneda
        )
        self.establecimiento = Establecimiento.objects.create(
            empresa=self.empresa,
            codigo_sunat='0000',
            nombre='SEDE CENTRAL'
        )
        self.almacen = Almacen.objects.create(
            empresa=self.empresa,
            establecimiento=self.establecimiento,
            codigo='ALM-01',
            nombre='ALMACEN CENTRAL'
        )
        self.periodo = Periodo.objects.create(
            empresa=self.empresa,
            anio=2026,
            mes=2,
            orden=202602,
            fecha_inicio='2026-02-01',
            fecha_fin='2026-02-28'
        )
        self.tipo_factura = TipoComprobante.objects.create(
            codigo_sunat='01',
            descripcion='FACTURA',
            es_nota=False,
            efecto_nota='NINGUNO'
        )
        self.tipo_nc = TipoComprobante.objects.create(
            codigo_sunat='07',
            descripcion='NOTA DE CREDITO',
            es_nota=True,
            efecto_nota='CREDITO'
        )
        self.tipo_op_compra = TipoOperacion.objects.create(
            codigo_interno='COMPRA_NACIONAL',
            codigo_sunat='02',
            descripcion='COMPRA NACIONAL',
            naturaleza='ENTRADA',
            es_interna=False,
            afecta_kardex=True,
            origen_requerido='DOCUMENTO'
        )
        self.tercero = Tercero.objects.create(
            empresa=self.empresa,
            tipo_documento='6',
            numero_documento='20500000002',
            razon_social='PROVEEDOR CENTRAL S.A.C.',
            es_proveedor=True
        )
        self.tipo_existencia = TipoExistencia.objects.create(
            codigo='01',
            descripcion='MERCADERIA'
        )
        self.und = UnidadMedida.objects.create(codigo='NIU', descripcion='UNIDAD')
        self.producto = Producto.objects.create(
            empresa=self.empresa,
            codigo_interno='P-TEST',
            descripcion='PRODUCTO DOC TEST',
            tipo_existencia_codigo=self.tipo_existencia
        )
        self.prod_unidad = ProductoUnidad.objects.create(
            producto=self.producto,
            unidad_codigo=self.und,
            factor_a_base=Decimal('1.00000000'),
            es_base=True
        )

    def test_creacion_documento_y_unicidad_normalizada(self):
        doc = Documento.objects.create(
            empresa=self.empresa,
            clase='COMPRA',
            periodo=self.periodo,
            tercero=self.tercero,
            ruc_emisor='20500000002',
            tipo_comprobante=self.tipo_factura,
            serie=' F001 ',
            serie_normalizada='F001',
            numero=' 000123 ',
            numero_normalizado='00000123',
            fecha_emision='2026-02-10',
            moneda_codigo=self.moneda,
            subtotal=Decimal('100.00000000'),
            igv=Decimal('18.00000000'),
            total=Decimal('118.00000000'),
            origen_captura='MANUAL',
            estado='BORRADOR',
            estado_revision='PENDIENTE'
        )
        self.assertIsNotNone(doc.id)
        self.assertEqual(doc.serie_normalizada, 'F001')
        self.assertEqual(doc.numero_normalizado, '00000123')

        # Duplicado con misma serie y numero normalizado debe violar uq_documento_emisor_comprobante
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Documento.objects.create(
                    empresa=self.empresa,
                    clase='COMPRA',
                    periodo=self.periodo,
                    tercero=self.tercero,
                    ruc_emisor='20500000002',
                    tipo_comprobante=self.tipo_factura,
                    serie='F-001',
                    serie_normalizada='F001',
                    numero='123',
                    numero_normalizado='00000123',
                    fecha_emision='2026-02-11',
                    moneda_codigo=self.moneda
                )

    def test_documento_check_constraints(self):
        # Clase inválida
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Documento.objects.create(
                    empresa=self.empresa,
                    clase='OTRA_CLASE',
                    periodo=self.periodo,
                    ruc_emisor='20500000002',
                    tipo_comprobante=self.tipo_factura,
                    serie_normalizada='F001',
                    numero_normalizado='00000001',
                    fecha_emision='2026-02-10',
                    moneda_codigo=self.moneda
                )

        # Origen captura inválido
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Documento.objects.create(
                    empresa=self.empresa,
                    clase='COMPRA',
                    periodo=self.periodo,
                    ruc_emisor='20500000002',
                    tipo_comprobante=self.tipo_factura,
                    serie_normalizada='F001',
                    numero_normalizado='00000002',
                    fecha_emision='2026-02-10',
                    moneda_codigo=self.moneda,
                    origen_captura='WHATSAPP'
                )

        # Estado inválido
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Documento.objects.create(
                    empresa=self.empresa,
                    clase='COMPRA',
                    periodo=self.periodo,
                    ruc_emisor='20500000002',
                    tipo_comprobante=self.tipo_factura,
                    serie_normalizada='F001',
                    numero_normalizado='00000003',
                    fecha_emision='2026-02-10',
                    moneda_codigo=self.moneda,
                    estado='PROCESADO'
                )

        # Estado revision inválido
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Documento.objects.create(
                    empresa=self.empresa,
                    clase='COMPRA',
                    periodo=self.periodo,
                    ruc_emisor='20500000002',
                    tipo_comprobante=self.tipo_factura,
                    serie_normalizada='F001',
                    numero_normalizado='00000004',
                    fecha_emision='2026-02-10',
                    moneda_codigo=self.moneda,
                    estado_revision='APROBADO'
                )

    def test_documento_origen_relacion_autoreferencial(self):
        doc_factura = Documento.objects.create(
            empresa=self.empresa,
            clase='COMPRA',
            periodo=self.periodo,
            tercero=self.tercero,
            ruc_emisor='20500000002',
            tipo_comprobante=self.tipo_factura,
            serie_normalizada='F001',
            numero_normalizado='00000100',
            fecha_emision='2026-02-10',
            moneda_codigo=self.moneda
        )
        doc_nc = Documento.objects.create(
            empresa=self.empresa,
            clase='COMPRA',
            periodo=self.periodo,
            tercero=self.tercero,
            ruc_emisor='20500000002',
            tipo_comprobante=self.tipo_nc,
            serie_normalizada='FC01',
            numero_normalizado='00000005',
            fecha_emision='2026-02-12',
            moneda_codigo=self.moneda,
            documento_origen=doc_factura
        )
        self.assertEqual(doc_nc.documento_origen, doc_factura)
        self.assertIn(doc_nc, doc_factura.documentos_derivados.all())

    def test_documento_detalle_y_constraints(self):
        doc = Documento.objects.create(
            empresa=self.empresa,
            clase='COMPRA',
            periodo=self.periodo,
            tercero=self.tercero,
            ruc_emisor='20500000002',
            tipo_comprobante=self.tipo_factura,
            serie_normalizada='F001',
            numero_normalizado='00000200',
            fecha_emision='2026-02-15',
            moneda_codigo=self.moneda
        )
        det1 = DocumentoDetalle.objects.create(
            documento=doc,
            linea=1,
            producto=self.producto,
            producto_unidad=self.prod_unidad,
            almacen=self.almacen,
            tipo_operacion=self.tipo_op_compra,
            cantidad_original=Decimal('10.00000000'),
            factor_conversion=Decimal('1.00000000'),
            cantidad_base=Decimal('10.00000000'),
            precio_unitario=Decimal('25.00000000'),
            igv=Decimal('4.50000000'),
            porcentaje_credito_fiscal_aplicado=Decimal('100.0000'),
            costo_unitario_pen=Decimal('25.00000000'),
            es_bonificacion=False
        )
        self.assertEqual(det1.linea, 1)
        self.assertEqual(doc.detalles.count(), 1)

        # UniqueConstraint: documento + linea
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                DocumentoDetalle.objects.create(
                    documento=doc,
                    linea=1,
                    producto=self.producto,
                    almacen=self.almacen,
                    tipo_operacion=self.tipo_op_compra
                )

        # CheckConstraint: cantidad_original >= 0
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                DocumentoDetalle.objects.create(
                    documento=doc,
                    linea=2,
                    producto=self.producto,
                    almacen=self.almacen,
                    tipo_operacion=self.tipo_op_compra,
                    cantidad_original=Decimal('-5.00000000')
                )

        # CheckConstraint: factor_conversion > 0
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                DocumentoDetalle.objects.create(
                    documento=doc,
                    linea=3,
                    producto=self.producto,
                    almacen=self.almacen,
                    tipo_operacion=self.tipo_op_compra,
                    factor_conversion=Decimal('0.00000000')
                )

        # CheckConstraint: porcentaje_credito_fiscal_aplicado BETWEEN 0 AND 100
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                DocumentoDetalle.objects.create(
                    documento=doc,
                    linea=4,
                    producto=self.producto,
                    almacen=self.almacen,
                    tipo_operacion=self.tipo_op_compra,
                    porcentaje_credito_fiscal_aplicado=Decimal('105.0000')
                )

    def test_documento_detalle_con_equivalencia_y_detalle_origen(self):
        equiv = ProductoEquivalencia.objects.create(
            empresa=self.empresa,
            tercero=self.tercero,
            codigo_externo='EQ-PROV-1',
            producto_unidad=self.prod_unidad,
            factor_conversion=Decimal('1.00000000')
        )
        doc = Documento.objects.create(
            empresa=self.empresa,
            clase='COMPRA',
            periodo=self.periodo,
            tercero=self.tercero,
            ruc_emisor='20500000002',
            tipo_comprobante=self.tipo_factura,
            serie_normalizada='F001',
            numero_normalizado='00000300',
            fecha_emision='2026-02-18',
            moneda_codigo=self.moneda
        )
        det_padre = DocumentoDetalle.objects.create(
            documento=doc,
            linea=1,
            producto=self.producto,
            almacen=self.almacen,
            tipo_operacion=self.tipo_op_compra,
            equivalencia=equiv,
            cantidad_original=Decimal('50.00000000')
        )
        det_hijo = DocumentoDetalle.objects.create(
            documento=doc,
            linea=2,
            producto=self.producto,
            almacen=self.almacen,
            tipo_operacion=self.tipo_op_compra,
            detalle_origen=det_padre,
            cantidad_original=Decimal('10.00000000')
        )
        self.assertEqual(det_padre.equivalencia, equiv)
        self.assertEqual(det_hijo.detalle_origen, det_padre)
        self.assertIn(det_hijo, det_padre.detalles_derivados.all())


class DocumentosApiTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.moneda_pen = Moneda.objects.create(codigo='PEN', nombre='Soles')
        self.moneda_usd = Moneda.objects.create(codigo='USD', nombre='Dólares Americanos')

        self.empresa = Empresa.objects.create(
            ruc='20100070970',
            razon_social='EMPRESA FISCAL S.A.C.',
            moneda_base_codigo=self.moneda_pen
        )
        self.empresa_otra = Empresa.objects.create(
            ruc='20999999999',
            razon_social='OTRA EMPRESA S.A.C.',
            moneda_base_codigo=self.moneda_pen
        )

        self.usuario = Usuario.objects.create(
            username='contadora_demo',
            email='contadora@test.com',
            es_admin_global=False,
            activo=True
        )
        UsuarioEmpresa.objects.create(
            usuario=self.usuario,
            empresa=self.empresa,
            rol='ADMIN',
            activo=True
        )
        self.client.force_authenticate(user=self.usuario)

        self.establecimiento = Establecimiento.objects.create(
            empresa=self.empresa,
            codigo_sunat='0000',
            nombre='CENTRAL'
        )
        self.almacen = Almacen.objects.create(
            empresa=self.empresa,
            establecimiento=self.establecimiento,
            codigo='ALM-01',
            nombre='ALMACEN GENERAL'
        )
        self.almacen_otra = Almacen.objects.create(
            empresa=self.empresa_otra,
            establecimiento=Establecimiento.objects.create(
                empresa=self.empresa_otra,
                codigo_sunat='0000',
                nombre='SEDE OTRA'
            ),
            codigo='ALM-OTRA',
            nombre='ALMACEN AJENO'
        )

        self.periodo_abierto = Periodo.objects.create(
            empresa=self.empresa,
            anio=2026,
            mes=1,
            orden=202601,
            fecha_inicio='2026-01-01',
            fecha_fin='2026-01-31',
            estado='ABIERTO'
        )
        self.periodo_cerrado = Periodo.objects.create(
            empresa=self.empresa,
            anio=2025,
            mes=12,
            orden=202512,
            fecha_inicio='2025-12-01',
            fecha_fin='2025-12-31',
            estado='CERRADO'
        )

        self.tipo_existencia = TipoExistencia.objects.create(codigo='01', descripcion='MERCADERIA')
        self.und = UnidadMedida.objects.create(codigo='NIU', descripcion='UNIDAD')
        self.caja = UnidadMedida.objects.create(codigo='BX', descripcion='CAJA')

        self.producto = Producto.objects.create(
            empresa=self.empresa,
            codigo_interno='PROD-A',
            descripcion='PRODUCTO A',
            tipo_existencia_codigo=self.tipo_existencia
        )
        self.pu_und = ProductoUnidad.objects.create(
            producto=self.producto,
            unidad_codigo=self.und,
            factor_a_base=Decimal('1.00000000'),
            es_base=True
        )
        self.pu_caja = ProductoUnidad.objects.create(
            producto=self.producto,
            unidad_codigo=self.caja,
            factor_a_base=Decimal('12.00000000'),
            es_base=False
        )

        self.tercero_prov = Tercero.objects.create(
            empresa=self.empresa,
            tipo_documento='6',
            numero_documento='20601234567',
            razon_social='PROVEEDOR LOGISTICO S.A.C.',
            es_proveedor=True
        )

        self.tipo_factura = TipoComprobante.objects.create(
            codigo_sunat='01',
            descripcion='FACTURA',
            es_nota=False,
            efecto_nota='NINGUNO'
        )
        self.tipo_nc = TipoComprobante.objects.create(
            codigo_sunat='07',
            descripcion='NOTA DE CREDITO',
            es_nota=True,
            efecto_nota='CREDITO'
        )

        self.tipo_op_compra = TipoOperacion.objects.create(
            codigo_interno='COMPRA_LOCAL',
            codigo_sunat='02',
            descripcion='COMPRA NACIONAL',
            naturaleza='ENTRADA',
            es_interna=False,
            afecta_kardex=True,
            origen_requerido='DOCUMENTO'
        )

        # Tipo de cambio para 2026-01-10 (viernes)
        self.tc_enero_10 = TipoCambio.objects.create(
            moneda_codigo=self.moneda_usd,
            fecha_publicacion=date(2026, 1, 10),
            venta=Decimal('3.75000000'),
            compra=Decimal('3.74000000'),
            fuente='SBS'
        )
        # Tipo de cambio posterior para 2026-01-20
        self.tc_enero_20 = TipoCambio.objects.create(
            moneda_codigo=self.moneda_usd,
            fecha_publicacion=date(2026, 1, 20),
            venta=Decimal('3.82000000'),
            compra=Decimal('3.81000000'),
            fuente='SBS'
        )

    def headers(self, empresa_id=None):
        return {'HTTP_X_EMPRESA_ID': str(empresa_id or self.empresa.id)}

    def test_creacion_factura_compra_pen_totales_y_costo(self):
        url = reverse('documento-list-create')
        data = {
            'clase': 'COMPRA',
            'periodo': self.periodo_abierto.id,
            'tercero': self.tercero_prov.id,
            'tipo_comprobante': self.tipo_factura.id,
            'serie': ' f001 ',
            'numero': ' 000456 ',
            'fecha_emision': '2026-01-10',
            'moneda_codigo': 'PEN',
            'detalles': [
                {
                    'producto': self.producto.id,
                    'producto_unidad': self.pu_caja.id,
                    'almacen': self.almacen.id,
                    'tipo_operacion': self.tipo_op_compra.id,
                    'cantidad_original': '10.00000000',
                    'precio_unitario': '120.00000000',
                    'igv': '216.00000000',
                    'es_bonificacion': False
                }
            ]
        }

        response = self.client.post(url, data, format='json', **self.headers())
        self.assertEqual(response.status_code, 201)

        doc = Documento.objects.get(id=response.data['id'])
        self.assertEqual(doc.serie_normalizada, 'F001')
        self.assertEqual(doc.numero_normalizado, '456')
        self.assertEqual(doc.moneda_codigo_id, 'PEN')
        self.assertIsNone(doc.tipo_cambio)
        self.assertIsNone(doc.monto_tc)
        self.assertEqual(doc.estado, 'BORRADOR')
        self.assertEqual(doc.estado_revision, 'PENDIENTE')
        self.assertEqual(doc.subtotal, Decimal('1200.00000000'))
        self.assertEqual(doc.igv, Decimal('216.00000000'))
        self.assertEqual(doc.total, Decimal('1416.00000000'))

        det = doc.detalles.first()
        self.assertEqual(det.factor_conversion, Decimal('12.00000000'))
        self.assertEqual(det.cantidad_base, Decimal('120.00000000'))
        self.assertEqual(det.porcentaje_credito_fiscal_aplicado, Decimal('100.0000'))
        # Con 100% crédito fiscal, el IGV es recuperable, no forma parte del costo:
        # Costo total = 1200 / 120 = 10 PEN/unidad base
        self.assertEqual(det.costo_unitario_pen, Decimal('10.00000000'))

    def test_creacion_conserva_fecha_emision_calendario(self):
        periodo_octubre = Periodo.objects.create(
            empresa=self.empresa,
            anio=2026,
            mes=10,
            orden=202610,
            fecha_inicio=date(2026, 10, 1),
            fecha_fin=date(2026, 10, 31),
            estado='ABIERTO',
        )
        response = self.client.post(
            reverse('documento-list-create'),
            {
                'clase': 'COMPRA',
                'periodo': periodo_octubre.id,
                'tercero': self.tercero_prov.id,
                'tipo_comprobante': self.tipo_factura.id,
                'serie': 'F004',
                'numero': '21',
                'fecha_emision': '2026-10-21',
                'moneda_codigo': 'PEN',
                'detalles': [
                    {
                        'producto': self.producto.id,
                        'producto_unidad': self.pu_und.id,
                        'almacen': self.almacen.id,
                        'tipo_operacion': self.tipo_op_compra.id,
                        'cantidad_original': '50.00000000',
                        'precio_unitario': '12.00000000',
                        'igv': '108.00000000',
                        'es_bonificacion': False,
                    }
                ],
            },
            format='json',
            **self.headers(),
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['fecha_emision'], '2026-10-21')

        documento = Documento.objects.get(id=response.data['id'])
        self.assertEqual(documento.fecha_emision, date(2026, 10, 21))
        self.assertEqual(documento.estado, 'BORRADOR')

    def test_creacion_factura_compra_usd_con_igv_prorrata_y_nulo(self):
        url = reverse('documento-list-create')

        # 1. Caso IGV PRORRATA (80% recuperable, 20% al costo)
        ConfigIgvPeriodo.objects.create(
            empresa=self.empresa,
            periodo=self.periodo_abierto,
            metodo='PRORRATA',
            porcentaje_recuperable=Decimal('80.0000')
        )

        data = {
            'clase': 'COMPRA',
            'periodo': self.periodo_abierto.id,
            'tercero': self.tercero_prov.id,
            'tipo_comprobante': self.tipo_factura.id,
            'serie': 'F002',
            'numero': '10',
            'fecha_emision': '2026-01-10',
            'moneda_codigo': 'USD',
            'detalles': [
                {
                    'producto': self.producto.id,
                    'producto_unidad': self.pu_und.id,
                    'almacen': self.almacen.id,
                    'tipo_operacion': self.tipo_op_compra.id,
                    'cantidad_original': '100.00000000',
                    'precio_unitario': '10.00000000',
                    'igv': '180.00000000',
                    'es_bonificacion': False
                }
            ]
        }

        response = self.client.post(url, data, format='json', **self.headers())
        self.assertEqual(response.status_code, 201)

        doc = Documento.objects.get(id=response.data['id'])
        self.assertEqual(doc.monto_tc, Decimal('3.75000000'))

        det = doc.detalles.first()
        self.assertEqual(det.porcentaje_credito_fiscal_aplicado, Decimal('80.0000'))
        # Costo USD:
        # valor = 100 * 10 = 1000 USD
        # igv no recuperable = 180 * (20%) = 36 USD
        # total USD = 1036 USD
        # total PEN = 1036 * 3.75 = 3885.00000000
        # costo unitario PEN = 3885 / 100 = 38.85000000
        self.assertEqual(det.costo_unitario_pen, Decimal('38.85000000'))

    def test_linea_con_bonificacion_costo_cero(self):
        url = reverse('documento-list-create')
        data = {
            'clase': 'COMPRA',
            'periodo': self.periodo_abierto.id,
            'tercero': self.tercero_prov.id,
            'tipo_comprobante': self.tipo_factura.id,
            'serie': 'F003',
            'numero': '20',
            'fecha_emision': '2026-01-10',
            'moneda_codigo': 'PEN',
            'detalles': [
                {
                    'producto': self.producto.id,
                    'producto_unidad': self.pu_und.id,
                    'almacen': self.almacen.id,
                    'tipo_operacion': self.tipo_op_compra.id,
                    'cantidad_original': '5.00000000',
                    'precio_unitario': '0.00000000',
                    'igv': '0.00000000',
                    'es_bonificacion': True
                }
            ]
        }

        response = self.client.post(url, data, format='json', **self.headers())
        self.assertEqual(response.status_code, 201)

        doc = Documento.objects.get(id=response.data['id'])
        det = doc.detalles.first()
        self.assertTrue(det.es_bonificacion)
        self.assertEqual(det.costo_unitario_pen, Decimal('0.00000000'))

    def test_nota_credito_usd_hereda_tc_documento_origen(self):
        # 1. Factura emitida el 10 de enero con TC 3.75
        factura = Documento.objects.create(
            empresa=self.empresa,
            clase='COMPRA',
            periodo=self.periodo_abierto,
            tercero=self.tercero_prov,
            ruc_emisor='20601234567',
            tipo_comprobante=self.tipo_factura,
            serie_normalizada='F001',
            numero_normalizado='100',
            fecha_emision='2026-01-10',
            moneda_codigo=self.moneda_usd,
            tipo_cambio=self.tc_enero_10,
            fecha_tc=date(2026, 1, 10),
            monto_tc=Decimal('3.75000000'),
            fuente_tc='SBS',
            subtotal=Decimal('500.00000000'),
            igv=Decimal('90.00000000'),
            total=Decimal('590.00000000'),
            # CON-007: una nota solo se admite sobre un documento de origen CONFIRMADO.
            estado='CONFIRMADO',
        )
        det_factura = DocumentoDetalle.objects.create(
            documento=factura,
            linea=1,
            producto=self.producto,
            producto_unidad=self.pu_und,
            almacen=self.almacen,
            tipo_operacion=self.tipo_op_compra,
            cantidad_original=Decimal('50.00000000'),
            factor_conversion=Decimal('1.00000000'),
            cantidad_base=Decimal('50.00000000'),
            precio_unitario=Decimal('10.00000000'),
            costo_unitario_pen=Decimal('37.50000000')
        )

        # 2. Nota de Crédito emitida el 20 de enero (cuando el TC SBS del día es 3.82)
        # CON-007: la NC de compra devuelve al proveedor (SALIDA); antes este test usaba
        # una operación ENTRADA, que sumaba stock en vez de devolverlo.
        tipo_op_devolucion = TipoOperacion.objects.create(
            codigo_interno='DEVOLUCION_COMPRA', codigo_sunat='06', descripcion='DEVOLUCION A PROVEEDOR',
            naturaleza='SALIDA', es_interna=False, afecta_kardex=True, origen_requerido='MOV_ORIGEN',
        )
        url = reverse('documento-list-create')
        data_nc = {
            'clase': 'COMPRA',
            'periodo': self.periodo_abierto.id,
            'tercero': self.tercero_prov.id,
            'tipo_comprobante': self.tipo_nc.id,
            'serie': 'FC01',
            'numero': '5',
            'fecha_emision': '2026-01-20',
            'moneda_codigo': 'USD',
            'documento_origen': factura.id,
            'detalles': [
                {
                    'producto': self.producto.id,
                    'producto_unidad': self.pu_und.id,
                    'almacen': self.almacen.id,
                    'tipo_operacion': tipo_op_devolucion.id,
                    'cantidad_original': '10.00000000',
                    'precio_unitario': '10.00000000',
                    'igv': '18.00000000',
                    'detalle_origen': det_factura.id
                }
            ]
        }

        response = self.client.post(url, data_nc, format='json', **self.headers())
        self.assertEqual(response.status_code, 201)

        nc = Documento.objects.get(id=response.data['id'])
        # Regla contable oficial: la NC hereda el TC de la factura de origen (3.75), NO el de su fecha (3.82)
        self.assertEqual(nc.monto_tc, Decimal('3.75000000'))
        self.assertEqual(nc.fecha_tc, date(2026, 1, 10))
        self.assertEqual(nc.documento_origen, factura)

        det_nc = nc.detalles.first()
        self.assertEqual(det_nc.detalle_origen, det_factura)

    def test_rechazo_duplicado_y_almacen_otra_empresa(self):
        url = reverse('documento-list-create')

        # 1. Crear primer comprobante
        data_1 = {
            'clase': 'COMPRA',
            'periodo': self.periodo_abierto.id,
            'tercero': self.tercero_prov.id,
            'tipo_comprobante': self.tipo_factura.id,
            'serie': 'F001',
            'numero': '00000099',
            'fecha_emision': '2026-01-10',
            'moneda_codigo': 'PEN',
            'detalles': [
                {
                    'producto': self.producto.id,
                    'producto_unidad': self.pu_und.id,
                    'almacen': self.almacen.id,
                    'tipo_operacion': self.tipo_op_compra.id,
                    'cantidad_original': '1.00000000',
                    'precio_unitario': '10.00000000',
                    'igv': '1.80',  # Bloque 3: línea gravada
                }
            ]
        }
        resp1 = self.client.post(url, data_1, format='json', **self.headers())
        self.assertEqual(resp1.status_code, 201)

        # 2. Intentar duplicado con formato equivalente 'f001' y '99'
        data_dup = {
            'clase': 'COMPRA',
            'periodo': self.periodo_abierto.id,
            'tercero': self.tercero_prov.id,
            'tipo_comprobante': self.tipo_factura.id,
            'serie': ' f001 ',
            'numero': '99',
            'fecha_emision': '2026-01-11',
            'moneda_codigo': 'PEN',
            'detalles': [
                {
                    'producto': self.producto.id,
                    'producto_unidad': self.pu_und.id,
                    'almacen': self.almacen.id,
                    'tipo_operacion': self.tipo_op_compra.id,
                    'cantidad_original': '2.00000000',
                    'precio_unitario': '10.00000000',
                }
            ]
        }
        resp_dup = self.client.post(url, data_dup, format='json', **self.headers())
        self.assertEqual(resp_dup.status_code, 400)

        # 3. Intentar con almacén de otra empresa
        data_ajeno = {
            'clase': 'COMPRA',
            'periodo': self.periodo_abierto.id,
            'tercero': self.tercero_prov.id,
            'tipo_comprobante': self.tipo_factura.id,
            'serie': 'F001',
            'numero': '101',
            'fecha_emision': '2026-01-10',
            'moneda_codigo': 'PEN',
            'detalles': [
                {
                    'producto': self.producto.id,
                    'producto_unidad': self.pu_und.id,
                    'almacen': self.almacen_otra.id,
                    'tipo_operacion': self.tipo_op_compra.id,
                    'cantidad_original': '1.00000000',
                    'precio_unitario': '10.00000000',
                }
            ]
        }
        resp_ajeno = self.client.post(url, data_ajeno, format='json', **self.headers())
        self.assertEqual(resp_ajeno.status_code, 400)

    def test_flujo_revisar_documento_y_auditoria(self):
        doc = Documento.objects.create(
            empresa=self.empresa,
            clase='COMPRA',
            periodo=self.periodo_abierto,
            tercero=self.tercero_prov,
            ruc_emisor='20601234567',
            tipo_comprobante=self.tipo_factura,
            serie_normalizada='F010',
            numero_normalizado='1',
            fecha_emision='2026-01-10',
            moneda_codigo=self.moneda_pen,
            estado='BORRADOR',
            estado_revision='PENDIENTE'
        )
        self.assertEqual(doc.estado_revision, 'PENDIENTE')

        url_revisar = reverse('documento-revisar', args=[doc.id])

        # 1. Pasar a EN_REVISION
        resp_rev = self.client.post(url_revisar, {'estado_revision': 'EN_REVISION'}, format='json', **self.headers())
        self.assertEqual(resp_rev.status_code, 200)
        doc.refresh_from_db()
        self.assertEqual(doc.estado_revision, 'EN_REVISION')
        self.assertEqual(doc.revisado_por, self.usuario)

        # 2. Pasar a REVISADO
        resp_ok = self.client.post(url_revisar, {'estado_revision': 'REVISADO'}, format='json', **self.headers())
        self.assertEqual(resp_ok.status_code, 200)
        doc.refresh_from_db()
        self.assertEqual(doc.estado_revision, 'REVISADO')

        # 3. Confirmar documento
        url_confirmar = reverse('documento-confirmar', args=[doc.id])
        resp_conf = self.client.post(url_confirmar, {}, format='json', **self.headers())
        self.assertEqual(resp_conf.status_code, 200)
        doc.refresh_from_db()
        self.assertEqual(doc.estado, 'CONFIRMADO')

        # 4. Verificar auditoría registrada
        auditorias = Auditoria.objects.filter(empresa_id=self.empresa.id, entidad='DOCUMENTO', registro_id=doc.id)
        self.assertTrue(auditorias.filter(accion='ACTUALIZAR').exists())
        self.assertTrue(auditorias.filter(accion='CONFIRMAR').exists())

    def test_bloqueo_confirmacion_si_no_esta_revisado_o_periodo_cerrado(self):
        doc_no_revisado = Documento.objects.create(
            empresa=self.empresa,
            clase='COMPRA',
            periodo=self.periodo_abierto,
            tercero=self.tercero_prov,
            ruc_emisor='20601234567',
            tipo_comprobante=self.tipo_factura,
            serie_normalizada='F011',
            numero_normalizado='1',
            fecha_emision='2026-01-10',
            moneda_codigo=self.moneda_pen,
            estado='BORRADOR',
            estado_revision='PENDIENTE'
        )
        url_conf_1 = reverse('documento-confirmar', args=[doc_no_revisado.id])
        resp_1 = self.client.post(url_conf_1, {}, format='json', **self.headers())
        self.assertEqual(resp_1.status_code, 400)

        # Documento en período cerrado
        doc_cerrado = Documento.objects.create(
            empresa=self.empresa,
            clase='COMPRA',
            periodo=self.periodo_cerrado,
            tercero=self.tercero_prov,
            ruc_emisor='20601234567',
            tipo_comprobante=self.tipo_factura,
            serie_normalizada='F012',
            numero_normalizado='1',
            fecha_emision='2025-12-10',
            moneda_codigo=self.moneda_pen,
            estado='BORRADOR',
            estado_revision='REVISADO'
        )
        url_conf_2 = reverse('documento-confirmar', args=[doc_cerrado.id])
        resp_2 = self.client.post(url_conf_2, {}, format='json', **self.headers())
        self.assertEqual(resp_2.status_code, 400)


class DocumentoCapturaIntegridadTest(TestCase):
    def setUp(self):
        self.moneda = Moneda.objects.create(codigo='PEN', nombre='Soles')
        self.empresa = Empresa.objects.create(
            ruc='20600000099',
            razon_social='CAPTURA TEST S.A.C.',
            moneda_base_codigo=self.moneda
        )
        self.usuario = Usuario.objects.create(
            username='user_captura',
            email='captura@test.com',
            password_hash='pbkdf2_test'
        )

    def test_documento_captura_tipos_validos(self):
        for tipo in ['XML', 'PDF', 'IMAGEN', 'ESCANER']:
            captura = DocumentoCaptura.objects.create(
                empresa=self.empresa,
                tipo=tipo,
                ruta_archivo=f'/uploads/{tipo.lower()}/archivo.{tipo.lower()}',
                hash_sha256='e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
                subido_por=self.usuario
            )
            self.assertEqual(captura.estado_proceso, 'PENDIENTE')
            self.assertEqual(captura.tipo, tipo)

    def test_documento_captura_tipo_invalido_viola_check(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DocumentoCaptura.objects.create(
                    empresa=self.empresa,
                    tipo='WORD',
                    ruta_archivo='/uploads/word/archivo.docx'
                )

    def test_captura_campo_secciones_validas(self):
        captura = DocumentoCaptura.objects.create(
            empresa=self.empresa,
            tipo='XML',
            ruta_archivo='/uploads/xml/doc.xml'
        )
        campo_cab = CapturaCampo.objects.create(
            documento_captura=captura,
            seccion='CABECERA',
            nombre_campo='ruc_emisor',
            valor_extraido='20123456789',
            confianza=Decimal('99.9500')
        )
        campo_det = CapturaCampo.objects.create(
            documento_captura=captura,
            seccion='DETALLE',
            numero_linea=1,
            nombre_campo='descripcion',
            valor_extraido='ITEM 1',
            confianza=Decimal('85.0000')
        )
        self.assertEqual(campo_cab.seccion, 'CABECERA')
        self.assertEqual(campo_det.seccion, 'DETALLE')

    def test_captura_campo_seccion_invalida_viola_check(self):
        captura = DocumentoCaptura.objects.create(
            empresa=self.empresa,
            tipo='XML',
            ruta_archivo='/uploads/xml/doc.xml'
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CapturaCampo.objects.create(
                    documento_captura=captura,
                    seccion='PIE_PAGINA',
                    nombre_campo='total'
                )

    def test_captura_campo_confianza_valida_y_nula(self):
        captura = DocumentoCaptura.objects.create(
            empresa=self.empresa,
            tipo='PDF',
            ruta_archivo='/uploads/pdf/doc.pdf'
        )
        # Nula
        c1 = CapturaCampo.objects.create(
            documento_captura=captura,
            seccion='CABECERA',
            nombre_campo='fecha',
            confianza=None
        )
        # En límites 0 y 100
        c2 = CapturaCampo.objects.create(
            documento_captura=captura,
            seccion='CABECERA',
            nombre_campo='serie',
            confianza=Decimal('0.0000')
        )
        c3 = CapturaCampo.objects.create(
            documento_captura=captura,
            seccion='CABECERA',
            nombre_campo='numero',
            confianza=Decimal('100.0000')
        )
        self.assertIsNone(c1.confianza)
        self.assertEqual(c2.confianza, Decimal('0.0000'))
        self.assertEqual(c3.confianza, Decimal('100.0000'))

    def test_captura_campo_confianza_invalida_viola_check(self):
        captura = DocumentoCaptura.objects.create(
            empresa=self.empresa,
            tipo='PDF',
            ruta_archivo='/uploads/pdf/doc.pdf'
        )
        # Menor a 0
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CapturaCampo.objects.create(
                    documento_captura=captura,
                    seccion='CABECERA',
                    nombre_campo='total',
                    confianza=Decimal('-0.0100')
                )
        # Mayor a 100
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CapturaCampo.objects.create(
                    documento_captura=captura,
                    seccion='CABECERA',
                    nombre_campo='total',
                    confianza=Decimal('100.0100')
                )

    def test_introspeccion_todas_las_tablas_sql_existen(self):
        import re
        from pathlib import Path
        from django.db import connection
        ruta_docs = Path(__file__).resolve().parents[3] / 'docs' / 'FACT_KARD_BD_COMPLETA_SQL.md'
        with open(ruta_docs, encoding='utf-8') as f:
            content = f.read()
        sql_tables = set(re.findall(r'CREATE TABLE (\w+)', content, re.IGNORECASE))
        db_tables = set(connection.introspection.table_names())
        missing = sql_tables - db_tables
        self.assertEqual(len(missing), 0, f"Faltan tablas oficiales en la BD: {missing}")


XML_FACTURA_PRUEBA = b"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
    <cbc:UBLVersionID>2.1</cbc:UBLVersionID>
    <cbc:CustomizationID>2.0</cbc:CustomizationID>
    <cbc:ID>F001-00000088</cbc:ID>
    <cbc:IssueDate>2026-02-10</cbc:IssueDate>
    <cbc:InvoiceTypeCode listID="0101">01</cbc:InvoiceTypeCode>
    <cbc:DocumentCurrencyCode>PEN</cbc:DocumentCurrencyCode>
    <cac:AccountingSupplierParty>
        <cac:Party>
            <cac:PartyIdentification>
                <cbc:ID schemeID="6">20555666777</cbc:ID>
            </cac:PartyIdentification>
            <cac:PartyLegalEntity>
                <cbc:RegistrationName>DISTRIBUIDORA PROV SAC</cbc:RegistrationName>
            </cac:PartyLegalEntity>
        </cac:Party>
    </cac:AccountingSupplierParty>
    <cac:AccountingCustomerParty>
        <cac:Party>
            <cac:PartyIdentification>
                <cbc:ID schemeID="6">20600000001</cbc:ID>
            </cac:PartyIdentification>
            <cac:PartyLegalEntity>
                <cbc:RegistrationName>DOCS TEST SAC</cbc:RegistrationName>
            </cac:PartyLegalEntity>
        </cac:Party>
    </cac:AccountingCustomerParty>
    <cac:TaxTotal>
        <cbc:TaxAmount currencyID="PEN">18.00</cbc:TaxAmount>
    </cac:TaxTotal>
    <cac:LegalMonetaryTotal>
        <cbc:LineExtensionAmount currencyID="PEN">100.00</cbc:LineExtensionAmount>
        <cbc:PayableAmount currencyID="PEN">118.00</cbc:PayableAmount>
    </cac:LegalMonetaryTotal>
    <cac:InvoiceLine>
        <cbc:ID>1</cbc:ID>
        <cbc:InvoicedQuantity unitCode="NIU">10.00</cbc:InvoicedQuantity>
        <cbc:LineExtensionAmount currencyID="PEN">100.00</cbc:LineExtensionAmount>
        <cac:Item>
            <cbc:Description>TALADRO ELECTRICO 500W</cbc:Description>
            <cac:SellersItemIdentification>
                <cbc:ID>SKU-EXT-999</cbc:ID>
            </cac:SellersItemIdentification>
        </cac:Item>
        <cac:Price>
            <cbc:PriceAmount currencyID="PEN">10.00</cbc:PriceAmount>
        </cac:Price>
    </cac:InvoiceLine>
</Invoice>
"""


class DocumentoCapturaFlujoCompletoTest(TestCase):
    def setUp(self):
        self.moneda = Moneda.objects.create(codigo='PEN', nombre='Soles')
        self.empresa = Empresa.objects.create(
            ruc='20600000001',
            razon_social='DOCS TEST S.A.C.',
            moneda_base_codigo=self.moneda,
        )
        self.establecimiento = Establecimiento.objects.create(
            empresa=self.empresa,
            codigo_sunat='0000',
            nombre='SEDE CENTRAL',
        )
        self.almacen = Almacen.objects.create(
            empresa=self.empresa,
            establecimiento=self.establecimiento,
            codigo='ALM-01',
            nombre='ALMACEN PRINCIPAL',
        )
        self.periodo = Periodo.objects.create(
            empresa=self.empresa,
            anio=2026,
            mes=2,
            orden=202602,
            fecha_inicio='2026-02-01',
            fecha_fin='2026-02-28',
            estado='ABIERTO',
        )
        self.tipo_factura = TipoComprobante.objects.create(
            codigo_sunat='01',
            descripcion='FACTURA',
            es_nota=False,
            efecto_nota='NINGUNO',
        )
        self.tipo_op_compra = TipoOperacion.objects.create(
            codigo_interno='COMPRA',
            codigo_sunat='02',
            descripcion='COMPRA NACIONAL',
            naturaleza='ENTRADA',
            es_interna=False,
            afecta_kardex=True,
            origen_requerido='DOCUMENTO',
        )
        self.tipo_existencia = TipoExistencia.objects.create(
            codigo='01',
            descripcion='MERCADERIA',
        )
        self.und = UnidadMedida.objects.create(codigo='NIU', descripcion='UNIDAD')
        self.producto = Producto.objects.create(
            empresa=self.empresa,
            codigo_interno='P-TALADRO',
            descripcion='TALADRO ELECTRICO 500W INTERNO',
            tipo_existencia_codigo=self.tipo_existencia,
        )
        self.prod_unidad = ProductoUnidad.objects.create(
            producto=self.producto,
            unidad_codigo=self.und,
            factor_a_base=Decimal('1.00000000'),
            es_base=True,
        )
        self.usuario = Usuario.objects.create(
            username='user_doc_test',
            email='doctest@factkard.pe',
            password_hash='pbkdf2_test',
        )
        UsuarioEmpresa.objects.create(
            usuario=self.usuario,
            empresa=self.empresa,
            rol='ADMIN',
            activo=True,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.usuario)

    def headers(self):
        return {'HTTP_X_EMPRESA_ID': str(self.empresa.id)}

    def test_subir_xml_ubl_crea_captura_y_campos_con_confianza_100(self):
        url = reverse('documento-captura-subir')
        archivo = SimpleUploadedFile("factura_F001_88.xml", XML_FACTURA_PRUEBA, content_type="text/xml")

        resp = self.client.post(
            url,
            {'archivo': archivo, 'tipo': 'XML'},
            format='multipart',
            **self.headers()
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data['tipo'], 'XML')
        self.assertEqual(resp.data['estado_proceso'], 'PROCESADO')
        self.assertTrue(resp.data['fue_creado_nuevo'])

        captura_id = resp.data['id']
        captura = DocumentoCaptura.objects.get(pk=captura_id)
        self.assertEqual(captura.tipo, 'XML')

        # Verificar campos cabecera
        c_ruc = captura.campos.get(seccion='CABECERA', nombre_campo='ruc_emisor')
        self.assertEqual(c_ruc.valor_extraido, '20555666777')
        self.assertEqual(c_ruc.confianza, Decimal('100.0000'))

        c_total = captura.campos.get(seccion='CABECERA', nombre_campo='total')
        self.assertEqual(Decimal(c_total.valor_extraido), Decimal('118.00000000'))

        # Verificar campos detalle
        c_sku = captura.campos.get(seccion='DETALLE', numero_linea=1, nombre_campo='codigo_externo')
        self.assertEqual(c_sku.valor_extraido, 'SKU-EXT-999')
        self.assertEqual(c_sku.confianza, Decimal('100.0000'))

    def test_subir_archivo_identico_reutiliza_captura_sin_duplicar(self):
        url = reverse('documento-captura-subir')
        archivo1 = SimpleUploadedFile("factura_1.xml", XML_FACTURA_PRUEBA, content_type="text/xml")
        resp1 = self.client.post(url, {'archivo': archivo1, 'tipo': 'XML'}, format='multipart', **self.headers())
        self.assertEqual(resp1.status_code, 201)
        self.assertTrue(resp1.data['fue_creado_nuevo'])

        # Subir nuevamente el mismo archivo
        archivo2 = SimpleUploadedFile("factura_1_duplicado.xml", XML_FACTURA_PRUEBA, content_type="text/xml")
        resp2 = self.client.post(url, {'archivo': archivo2, 'tipo': 'XML'}, format='multipart', **self.headers())
        self.assertEqual(resp2.status_code, 200)
        self.assertFalse(resp2.data['fue_creado_nuevo'])
        self.assertEqual(resp1.data['id'], resp2.data['id'])
        self.assertEqual(DocumentoCaptura.objects.filter(empresa=self.empresa).count(), 1)

    def test_corregir_campo_captura_guarda_usuario_y_auditoria(self):
        # 1. Subir captura
        url_subir = reverse('documento-captura-subir')
        archivo = SimpleUploadedFile("factura_test.xml", XML_FACTURA_PRUEBA, content_type="text/xml")
        resp_subir = self.client.post(url_subir, {'archivo': archivo, 'tipo': 'XML'}, format='multipart', **self.headers())
        captura_id = resp_subir.data['id']

        # 2. Corregir campo
        captura = DocumentoCaptura.objects.get(pk=captura_id)
        campo = captura.campos.get(seccion='CABECERA', nombre_campo='serie')
        self.assertEqual(campo.valor_extraido, 'F001')

        url_corregir = reverse('captura-campo-corregir', args=[captura_id])
        resp_corregir = self.client.patch(
            url_corregir,
            {'campo_id': campo.id, 'valor_corregido': 'F002'},
            format='json',
            **self.headers()
        )
        self.assertEqual(resp_corregir.status_code, 200)
        self.assertEqual(resp_corregir.data['valor_corregido'], 'F002')

        campo.refresh_from_db()
        self.assertEqual(campo.valor_corregido, 'F002')
        self.assertEqual(campo.corregido_por, self.usuario)

        # Auditoría
        aud = Auditoria.objects.filter(
            entidad='CAPTURA_CAMPO',
            registro_id=campo.id,
            accion='CORREGIR_CAMPO_CAPTURA',
        ).first()
        self.assertIsNotNone(aud)

    def test_generar_borrador_sin_equivalencia_crea_incidencia_bloqueante(self):
        # 1. Subir XML
        url_subir = reverse('documento-captura-subir')
        archivo = SimpleUploadedFile("factura_sin_homologar.xml", XML_FACTURA_PRUEBA, content_type="text/xml")
        resp_subir = self.client.post(url_subir, {'archivo': archivo, 'tipo': 'XML'}, format='multipart', **self.headers())
        captura_id = resp_subir.data['id']

        # 2. Generar borrador
        url_borrador = reverse('documento-captura-generar-borrador', args=[captura_id])
        resp_borrador = self.client.post(url_borrador, {}, format='json', **self.headers())
        self.assertEqual(resp_borrador.status_code, 201)
        self.assertEqual(resp_borrador.data['estado'], 'BORRADOR')
        self.assertEqual(resp_borrador.data['estado_revision'], 'PENDIENTE')
        self.assertEqual(resp_borrador.data['lineas_sin_homologar'], 1)

        doc_id = resp_borrador.data['documento_id']
        doc = Documento.objects.get(pk=doc_id)
        self.assertEqual(doc.estado, 'BORRADOR')
        self.assertEqual(doc.estado_revision, 'PENDIENTE')
        self.assertEqual(doc.origen_captura, 'XML')

        # La línea no tiene producto asignado
        det = doc.detalles.first()
        self.assertIsNone(det.producto)

        # Incidencia bloqueante generada
        inc = Incidencia.objects.filter(
            empresa=self.empresa,
            documento=doc,
            tipo='PRODUCTO_SIN_HOMOLOGAR',
        ).first()
        self.assertIsNotNone(inc)
        self.assertTrue(inc.bloquea_cierre)
        self.assertEqual(inc.estado, 'PENDIENTE')

    def test_generar_borrador_con_equivalencia_previa_asocia_producto(self):
        # 1. Crear tercero y equivalencia previa confirmada
        tercero = Tercero.objects.create(
            empresa=self.empresa,
            tipo_documento='6',
            numero_documento='20555666777',
            razon_social='DISTRIBUIDORA PROV SAC',
            es_proveedor=True,
        )
        ProductoEquivalencia.objects.create(
            empresa=self.empresa,
            tercero=tercero,
            codigo_externo='SKU-EXT-999',
            descripcion_externa='TALADRO ELECTRICO 500W',
            unidad_externa_codigo=self.und,
            producto_unidad=self.prod_unidad,
            factor_conversion=Decimal('2.00000000'),
            confirmado_por=self.usuario,
            confirmado_en=timezone.now(),
            activa=True,
        )

        # 2. Subir XML y generar borrador
        url_subir = reverse('documento-captura-subir')
        archivo = SimpleUploadedFile("factura_homologada.xml", XML_FACTURA_PRUEBA, content_type="text/xml")
        resp_subir = self.client.post(url_subir, {'archivo': archivo, 'tipo': 'XML'}, format='multipart', **self.headers())
        captura_id = resp_subir.data['id']

        url_borrador = reverse('documento-captura-generar-borrador', args=[captura_id])
        resp_borrador = self.client.post(url_borrador, {}, format='json', **self.headers())
        self.assertEqual(resp_borrador.status_code, 201)
        self.assertEqual(resp_borrador.data['lineas_sin_homologar'], 0)

        doc = Documento.objects.get(pk=resp_borrador.data['documento_id'])
        det = doc.detalles.first()
        self.assertEqual(det.producto, self.producto)
        self.assertEqual(det.factor_conversion, Decimal('2.00000000'))
        # 10 cantidad original * 2 factor = 20 cantidad base
        self.assertEqual(det.cantidad_base, Decimal('20.00000000'))

        # No debe haber incidencias
        self.assertFalse(Incidencia.objects.filter(documento=doc).exists())

    def test_subir_captura_ocr_asigna_confianzas_entre_0_y_100(self):
        url = reverse('documento-captura-subir')
        archivo_pdf = SimpleUploadedFile("factura_escaneada.pdf", b"%PDF-1.4 dummy", content_type="application/pdf")
        texto_ocr = "FACTURA F001-00000999 RUC: 20111222333 TOTAL: S/ 236.00"

        resp = self.client.post(
            url,
            {'archivo': archivo_pdf, 'tipo': 'PDF', 'texto_ocr': texto_ocr},
            format='multipart',
            **self.headers()
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data['tipo'], 'PDF')

        captura = DocumentoCaptura.objects.get(pk=resp.data['id'])
        for campo in captura.campos.all():
            self.assertIsNotNone(campo.confianza)
            self.assertGreaterEqual(campo.confianza, Decimal('0'))
            self.assertLessEqual(campo.confianza, Decimal('100'))
