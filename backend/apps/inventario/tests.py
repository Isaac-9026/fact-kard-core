from decimal import Decimal
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.auditoria.models import Auditoria
from apps.catalogos.models import Moneda, TipoExistencia, UnidadMedida, TipoOperacion
from apps.empresas.models import Empresa, Establecimiento, Periodo
from apps.inventario.models import (
    Almacen, Tercero, Producto, ProductoUnidad,
    ProductoEquivalencia, SaldoInicial, NotaInterna, NotaInternaDetalle
)
from apps.usuarios.models import Usuario, UsuarioEmpresa


class InventarioModelTest(TestCase):
    def setUp(self):
        self.moneda = Moneda.objects.create(codigo='PEN', nombre='Soles')
        self.empresa = Empresa.objects.create(
            ruc='20100070970',
            razon_social='EMPRESA MODELO S.A.C.',
            moneda_base_codigo=self.moneda
        )
        self.establecimiento = Establecimiento.objects.create(
            empresa=self.empresa,
            codigo_sunat='0000',
            nombre='PRINCIPAL'
        )
        self.tipo_existencia = TipoExistencia.objects.create(
            codigo='01',
            descripcion='MERCADERIAS'
        )
        self.und = UnidadMedida.objects.create(codigo='NIU', descripcion='UNIDADES')
        self.caja = UnidadMedida.objects.create(codigo='BX', descripcion='CAJAS')

    def test_crear_almacen_y_unique_constraint(self):
        alm = Almacen.objects.create(
            empresa=self.empresa,
            establecimiento=self.establecimiento,
            codigo='ALM01',
            nombre='ALMACEN CENTRAL'
        )
        self.assertEqual(alm.codigo, 'ALM01')
        self.assertTrue(alm.activo)

        # Mismo código en la misma empresa debe fallar
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Almacen.objects.create(
                    empresa=self.empresa,
                    establecimiento=self.establecimiento,
                    codigo='ALM01',
                    nombre='OTRO ALMACEN'
                )

    def test_tercero_constraints(self):
        # Debe tener es_cliente o es_proveedor en True
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Tercero.objects.create(
                    empresa=self.empresa,
                    tipo_documento='6',
                    numero_documento='20601111111',
                    razon_social='CLIENTE INVALIDO',
                    es_cliente=False,
                    es_proveedor=False
                )

        # Tercero válido
        tercero = Tercero.objects.create(
            empresa=self.empresa,
            tipo_documento='6',
            numero_documento='20601111111',
            razon_social='PROVEEDOR CENTRAL S.A.C.',
            es_proveedor=True
        )
        self.assertEqual(tercero.estado, 'ACTIVO')

        # Duplicado en la misma empresa debe fallar
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Tercero.objects.create(
                    empresa=self.empresa,
                    tipo_documento='6',
                    numero_documento='20601111111',
                    razon_social='OTRO NOMBRE',
                    es_cliente=True
                )

    def test_producto_y_uq_producto_unidad_base(self):
        prod = Producto.objects.create(
            empresa=self.empresa,
            codigo_interno='PROD-001',
            descripcion='PRODUCTO DE PRUEBA',
            tipo_existencia_codigo=self.tipo_existencia
        )

        # 1. Crear unidad base (es_base=True)
        pu_base = ProductoUnidad.objects.create(
            producto=prod,
            unidad_codigo=self.und,
            factor_a_base=Decimal('1.00000000'),
            es_base=True
        )
        self.assertTrue(pu_base.es_base)

        # 2. Crear segunda unidad derivada (es_base=False, factor 12)
        pu_caja = ProductoUnidad.objects.create(
            producto=prod,
            unidad_codigo=self.caja,
            factor_a_base=Decimal('12.00000000'),
            es_base=False
        )
        self.assertFalse(pu_caja.es_base)

        # 3. Intentar agregar una SEGUNDA unidad con es_base=True al mismo producto
        # Debe fallar obligatoriamente por el índice parcial único uq_producto_unidad_base
        und_paquete = UnidadMedida.objects.create(codigo='PK', descripcion='PAQUETES')
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                ProductoUnidad.objects.create(
                    producto=prod,
                    unidad_codigo=und_paquete,
                    factor_a_base=Decimal('6.00000000'),
                    es_base=True
                )

    def test_producto_unidad_factor_check_constraint(self):
        prod = Producto.objects.create(
            empresa=self.empresa,
            codigo_interno='PROD-002',
            descripcion='PRODUCTO FACTOR CERO',
            tipo_existencia_codigo=self.tipo_existencia
        )
        # Factor a base debe ser estrictamente > 0
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                ProductoUnidad.objects.create(
                    producto=prod,
                    unidad_codigo=self.und,
                    factor_a_base=Decimal('0.00000000'),
                    es_base=True
                )


class InventarioApiTest(TestCase):
    def setUp(self):
        self.moneda = Moneda.objects.create(codigo='PEN', nombre='Soles')
        self.tipo_existencia = TipoExistencia.objects.create(
            codigo='01', descripcion='MERCADERÍAS'
        )
        self.niu = UnidadMedida.objects.create(codigo='NIU', descripcion='UNIDAD')
        self.pack = UnidadMedida.objects.create(codigo='PK', descripcion='PAQUETE')
        self.caja = UnidadMedida.objects.create(codigo='BX', descripcion='CAJA')
        self.empresa_a = Empresa.objects.create(
            ruc='20600000001',
            razon_social='EMPRESA A S.A.C.',
            moneda_base_codigo=self.moneda,
        )
        self.empresa_b = Empresa.objects.create(
            ruc='20600000002',
            razon_social='EMPRESA B S.A.C.',
            moneda_base_codigo=self.moneda,
        )
        self.establecimiento_a = Establecimiento.objects.create(
            empresa=self.empresa_a, codigo_sunat='0001', nombre='PRINCIPAL A'
        )
        self.establecimiento_b = Establecimiento.objects.create(
            empresa=self.empresa_b, codigo_sunat='0001', nombre='PRINCIPAL B'
        )
        self.admin = Usuario.objects.create(
            username='admin_inv', email='admin_inv@factkard.pe', password_hash='hash'
        )
        self.usuario = Usuario.objects.create(
            username='usuario_inv', email='usuario_inv@factkard.pe', password_hash='hash'
        )
        UsuarioEmpresa.objects.create(
            usuario=self.admin, empresa=self.empresa_a, rol='ADMIN'
        )
        UsuarioEmpresa.objects.create(
            usuario=self.admin, empresa=self.empresa_b, rol='ADMIN'
        )
        UsuarioEmpresa.objects.create(
            usuario=self.usuario, empresa=self.empresa_a, rol='USUARIO'
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def headers(self, empresa):
        return {'HTTP_X_EMPRESA_ID': str(empresa.id)}

    def crear_producto_api(self, codigo='P001'):
        return self.client.post(
            reverse('producto-list-create'),
            {
                'codigo_interno': codigo,
                'descripcion': f'PRODUCTO {codigo}',
                'tipo_existencia_codigo': self.tipo_existencia.codigo,
                'unidad_base_codigo': self.niu.codigo,
            },
            format='json',
            **self.headers(self.empresa_a),
        )

    def test_terceros_aislados_por_empresa(self):
        tercero_a = Tercero.objects.create(
            empresa=self.empresa_a,
            tipo_documento='6',
            numero_documento='20601111111',
            razon_social='TERCERO A',
            es_cliente=True,
        )
        tercero_b = Tercero.objects.create(
            empresa=self.empresa_b,
            tipo_documento='6',
            numero_documento='20602222222',
            razon_social='TERCERO B',
            es_proveedor=True,
        )

        response = self.client.get(
            reverse('tercero-list-create'), **self.headers(self.empresa_b)
        )

        self.assertEqual(response.status_code, 200)
        ids = {item['id'] for item in response.data}
        self.assertEqual(ids, {tercero_b.id})
        self.assertNotIn(tercero_a.id, ids)

    def test_almacenes_aislados_por_empresa(self):
        almacen_a = Almacen.objects.create(
            empresa=self.empresa_a,
            establecimiento=self.establecimiento_a,
            codigo='A01',
            nombre='ALMACÉN A',
        )
        almacen_b = Almacen.objects.create(
            empresa=self.empresa_b,
            establecimiento=self.establecimiento_b,
            codigo='B01',
            nombre='ALMACÉN B',
        )

        response = self.client.get(
            reverse('almacen-list-create'), **self.headers(self.empresa_b)
        )

        self.assertEqual(response.status_code, 200)
        ids = {item['id'] for item in response.data}
        self.assertEqual(ids, {almacen_b.id})
        self.assertNotIn(almacen_a.id, ids)

    def test_productos_aislados_por_empresa(self):
        producto_a = Producto.objects.create(
            empresa=self.empresa_a,
            codigo_interno='A001',
            descripcion='PRODUCTO A',
            tipo_existencia_codigo=self.tipo_existencia,
        )
        producto_b = Producto.objects.create(
            empresa=self.empresa_b,
            codigo_interno='B001',
            descripcion='PRODUCTO B',
            tipo_existencia_codigo=self.tipo_existencia,
        )

        response = self.client.get(
            reverse('producto-list-create'), **self.headers(self.empresa_b)
        )

        self.assertEqual(response.status_code, 200)
        ids = {item['id'] for item in response.data}
        self.assertEqual(ids, {producto_b.id})
        self.assertNotIn(producto_a.id, ids)

    def test_almacen_rechaza_establecimiento_de_otra_empresa(self):
        response = self.client.post(
            reverse('almacen-list-create'),
            {
                'establecimiento': self.establecimiento_b.id,
                'codigo': 'CRUZADO',
                'nombre': 'NO DEBE CREARSE',
                'activo': True,
            },
            format='json',
            **self.headers(self.empresa_a),
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Almacen.objects.filter(codigo='CRUZADO').exists())

    def test_crear_producto_genera_exactamente_una_unidad_base(self):
        response = self.crear_producto_api()

        self.assertEqual(response.status_code, 201)
        producto = Producto.objects.get(pk=response.data['id'])
        unidades_base = ProductoUnidad.objects.filter(producto=producto, es_base=True)
        self.assertEqual(unidades_base.count(), 1)
        self.assertEqual(unidades_base.get().unidad_codigo_id, 'NIU')
        self.assertEqual(unidades_base.get().factor_a_base, Decimal('1.00000000'))
        self.assertTrue(Auditoria.objects.filter(
            empresa=self.empresa_a,
            entidad='PRODUCTO',
            registro_id=producto.id,
        ).exists())

    def test_agregar_unidades_secundarias_pack_y_caja(self):
        producto_id = self.crear_producto_api().data['id']
        url = reverse('producto-unidad-list-create', args=[producto_id])

        pack_response = self.client.post(
            url,
            {'unidad_codigo': 'PK', 'factor_a_base': '6.00000000', 'es_base': False},
            format='json',
            **self.headers(self.empresa_a),
        )
        caja_response = self.client.post(
            url,
            {'unidad_codigo': 'BX', 'factor_a_base': '24.00000000', 'es_base': False},
            format='json',
            **self.headers(self.empresa_a),
        )

        self.assertEqual(pack_response.status_code, 201)
        self.assertEqual(caja_response.status_code, 201)
        self.assertEqual(
            ProductoUnidad.objects.get(pk=pack_response.data['id']).factor_a_base,
            Decimal('6.00000000'),
        )
        self.assertEqual(
            ProductoUnidad.objects.get(pk=caja_response.data['id']).factor_a_base,
            Decimal('24.00000000'),
        )

    def test_rechaza_segunda_unidad_base(self):
        producto_id = self.crear_producto_api().data['id']

        response = self.client.post(
            reverse('producto-unidad-list-create', args=[producto_id]),
            {'unidad_codigo': 'PK', 'factor_a_base': '1.00000000', 'es_base': True},
            format='json',
            **self.headers(self.empresa_a),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            ProductoUnidad.objects.filter(producto_id=producto_id, es_base=True).count(),
            1,
        )

    def test_usuario_no_admin_puede_leer_pero_no_escribir(self):
        producto = Producto.objects.create(
            empresa=self.empresa_a,
            codigo_interno='LECTURA',
            descripcion='SOLO LECTURA',
            tipo_existencia_codigo=self.tipo_existencia,
        )
        self.client.force_authenticate(user=self.usuario)

        get_response = self.client.get(
            reverse('producto-list-create'), **self.headers(self.empresa_a)
        )
        post_response = self.client.post(
            reverse('tercero-list-create'),
            {
                'tipo_documento': '6',
                'numero_documento': '20603333333',
                'razon_social': 'NO AUTORIZADO',
                'es_cliente': True,
            },
            format='json',
            **self.headers(self.empresa_a),
        )
        patch_response = self.client.patch(
            reverse('producto-detail', args=[producto.id]),
            {'descripcion': 'CAMBIO NO AUTORIZADO'},
            format='json',
            **self.headers(self.empresa_a),
        )

        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(post_response.status_code, 403)
        self.assertEqual(patch_response.status_code, 403)

    def test_filtros_y_busqueda_de_terceros(self):
        Tercero.objects.create(
            empresa=self.empresa_a,
            tipo_documento='6',
            numero_documento='20604444444',
            razon_social='COMERCIAL ANDINA',
            nombre_comercial='ANDINA',
            es_cliente=True,
        )
        Tercero.objects.create(
            empresa=self.empresa_a,
            tipo_documento='6',
            numero_documento='20605555555',
            razon_social='SUMINISTROS DEL SUR',
            es_proveedor=True,
        )

        response = self.client.get(
            reverse('tercero-list-create'),
            {'tipo': 'cliente', 'search': 'ANDINA'},
            **self.headers(self.empresa_a),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['numero_documento'], '20604444444')

    def test_empresa_inactiva_no_permite_operar(self):
        self.empresa_a.estado = 'INACTIVA'
        self.empresa_a.save(update_fields=['estado'])

        get_response = self.client.get(
            reverse('producto-list-create'), **self.headers(self.empresa_a)
        )
        post_response = self.client.post(
            reverse('almacen-list-create'),
            {
                'establecimiento': self.establecimiento_a.id,
                'codigo': 'INACTIVO',
                'nombre': 'NO DEBE CREARSE',
                'activo': True,
            },
            format='json',
            **self.headers(self.empresa_a),
        )

        # Bloque 24: una empresa INACTIVA queda en solo lectura (consulta permitida, escritura 403).
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual(post_response.status_code, 403)
        self.assertIn('INACTIVA', str(post_response.data['detail']))
        self.assertFalse(Almacen.objects.filter(codigo='INACTIVO').exists())


class InventarioMigracion4Test(TestCase):
    def setUp(self):
        self.moneda = Moneda.objects.create(codigo='PEN', nombre='Soles')
        self.empresa = Empresa.objects.create(
            ruc='20555555555',
            razon_social='TEST MIGRACION 4 S.A.C.',
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
            nombre='ALMACEN GENERAL'
        )
        self.tipo_existencia = TipoExistencia.objects.create(
            codigo='01',
            descripcion='MERCADERIA'
        )
        self.und = UnidadMedida.objects.create(codigo='NIU', descripcion='UNIDAD')
        self.caja = UnidadMedida.objects.create(codigo='BX', descripcion='CAJA')
        self.producto = Producto.objects.create(
            empresa=self.empresa,
            codigo_interno='P-001',
            descripcion='PRODUCTO PRUEBA',
            tipo_existencia_codigo=self.tipo_existencia
        )
        self.prod_unidad = ProductoUnidad.objects.create(
            producto=self.producto,
            unidad_codigo=self.und,
            factor_a_base=Decimal('1.00000000'),
            es_base=True
        )
        self.tercero = Tercero.objects.create(
            empresa=self.empresa,
            tipo_documento='6',
            numero_documento='20111111111',
            razon_social='PROVEEDOR TEST',
            es_proveedor=True
        )
        self.periodo = Periodo.objects.create(
            empresa=self.empresa,
            anio=2026,
            mes=1,
            orden=202601,
            fecha_inicio='2026-01-01',
            fecha_fin='2026-01-31'
        )
        self.tipo_op_interna = TipoOperacion.objects.create(
            codigo_interno='AJUSTE_MERMA',
            descripcion='MERMA DE INVENTARIO',
            naturaleza='SALIDA',
            es_interna=True,
            afecta_kardex=True,
            origen_requerido='NOTA_INTERNA'
        )

    def test_producto_equivalencia_constraints(self):
        eq = ProductoEquivalencia.objects.create(
            empresa=self.empresa,
            tercero=self.tercero,
            codigo_externo='EXT-999',
            descripcion_externa='CODIGO PROVEEDOR',
            unidad_externa_codigo=self.caja,
            producto_unidad=self.prod_unidad,
            factor_conversion=Decimal('12.00000000'),
            activa=True
        )
        self.assertEqual(eq.factor_conversion, Decimal('12.00000000'))

        # CheckConstraint: factor_conversion > 0
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                ProductoEquivalencia.objects.create(
                    empresa=self.empresa,
                    tercero=self.tercero,
                    producto_unidad=self.prod_unidad,
                    factor_conversion=Decimal('0.00000000')
                )

    def test_saldo_inicial_constraints(self):
        si = SaldoInicial.objects.create(
            empresa=self.empresa,
            periodo=self.periodo,
            almacen=self.almacen,
            producto=self.producto,
            cantidad=Decimal('100.00000000'),
            valor_pen=Decimal('1500.00000000'),
            cpp_inicial=Decimal('15.00000000'),
            estado='BORRADOR'
        )
        self.assertEqual(si.estado, 'BORRADOR')

        # UniqueConstraint: empresa, periodo, almacen, producto
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                SaldoInicial.objects.create(
                    empresa=self.empresa,
                    periodo=self.periodo,
                    almacen=self.almacen,
                    producto=self.producto,
                    cantidad=Decimal('50.00000000'),
                    valor_pen=Decimal('750.00000000')
                )

        # CheckConstraint: cantidad >= 0
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                SaldoInicial.objects.create(
                    empresa=self.empresa,
                    periodo=self.periodo,
                    almacen=self.almacen,
                    producto=Producto.objects.create(
                        empresa=self.empresa,
                        codigo_interno='P-NEG',
                        descripcion='PRODUCTO NEG',
                        tipo_existencia_codigo=self.tipo_existencia
                    ),
                    cantidad=Decimal('-1.00000000'),
                    valor_pen=Decimal('100.00000000')
                )

        # CheckConstraint: estado IN ('BORRADOR', 'CONFIRMADO')
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                SaldoInicial.objects.create(
                    empresa=self.empresa,
                    periodo=self.periodo,
                    almacen=self.almacen,
                    producto=Producto.objects.create(
                        empresa=self.empresa,
                        codigo_interno='P-INV',
                        descripcion='PRODUCTO ESTADO INVALIDO',
                        tipo_existencia_codigo=self.tipo_existencia
                    ),
                    cantidad=Decimal('10.00000000'),
                    valor_pen=Decimal('100.00000000'),
                    estado='ANULADO'
                )

    def test_nota_interna_y_detalle_constraints(self):
        ni = NotaInterna.objects.create(
            empresa=self.empresa,
            almacen=self.almacen,
            periodo=self.periodo,
            tipo_operacion=self.tipo_op_interna,
            fecha='2026-01-15',
            motivo='Merma de prueba en almacén',
            estado='BORRADOR'
        )
        detalle = NotaInternaDetalle.objects.create(
            nota_interna=ni,
            producto=self.producto,
            cantidad_base=Decimal('5.00000000'),
            costo_unitario_pen=Decimal('15.00000000'),
            valor_ajuste_pen=Decimal('75.00000000')
        )
        self.assertEqual(ni.detalles.count(), 1)
        self.assertEqual(detalle.cantidad_base, Decimal('5.00000000'))

        # CheckConstraint: estado IN ('BORRADOR', 'CONFIRMADO', 'ANULADO')
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                NotaInterna.objects.create(
                    empresa=self.empresa,
                    almacen=self.almacen,
                    periodo=self.periodo,
                    tipo_operacion=self.tipo_op_interna,
                    fecha='2026-01-15',
                    motivo='Test estado invalido',
                    estado='PENDIENTE'
                )

        # CheckConstraint: cantidad_base >= 0
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                NotaInternaDetalle.objects.create(
                    nota_interna=ni,
                    producto=self.producto,
                    cantidad_base=Decimal('-0.50000000')
                )


class OperacionesInternasApiTest(TestCase):
    def setUp(self):
        moneda = Moneda.objects.create(codigo='PEN', nombre='Soles')
        tipo_existencia = TipoExistencia.objects.create(
            codigo='01', descripcion='MERCADERÍA'
        )
        unidad = UnidadMedida.objects.create(codigo='NIU', descripcion='UNIDAD')
        self.empresa_a = Empresa.objects.create(
            ruc='20610000001', razon_social='OPERACIONES A', moneda_base_codigo=moneda,
        )
        self.empresa_b = Empresa.objects.create(
            ruc='20610000002', razon_social='OPERACIONES B', moneda_base_codigo=moneda,
        )
        establecimiento_a = Establecimiento.objects.create(
            empresa=self.empresa_a, codigo_sunat='0001', nombre='SEDE A',
        )
        establecimiento_b = Establecimiento.objects.create(
            empresa=self.empresa_b, codigo_sunat='0001', nombre='SEDE B',
        )
        self.almacen_a = Almacen.objects.create(
            empresa=self.empresa_a, establecimiento=establecimiento_a,
            codigo='A01', nombre='ALMACÉN A',
        )
        self.almacen_b = Almacen.objects.create(
            empresa=self.empresa_b, establecimiento=establecimiento_b,
            codigo='B01', nombre='ALMACÉN B',
        )
        self.producto_a = Producto.objects.create(
            empresa=self.empresa_a, codigo_interno='PA', descripcion='PRODUCTO A',
            tipo_existencia_codigo=tipo_existencia,
        )
        self.producto_a2 = Producto.objects.create(
            empresa=self.empresa_a, codigo_interno='PA2', descripcion='PRODUCTO A2',
            tipo_existencia_codigo=tipo_existencia,
        )
        self.producto_b = Producto.objects.create(
            empresa=self.empresa_b, codigo_interno='PB', descripcion='PRODUCTO B',
            tipo_existencia_codigo=tipo_existencia,
        )
        for producto in (self.producto_a, self.producto_a2, self.producto_b):
            ProductoUnidad.objects.create(
                producto=producto, unidad_codigo=unidad,
                factor_a_base=Decimal('1.00000000'), es_base=True,
            )
        self.periodo_a = Periodo.objects.create(
            empresa=self.empresa_a, anio=2026, mes=1, orden=202601,
            fecha_inicio='2026-01-01', fecha_fin='2026-01-31', estado='ABIERTO',
        )
        self.periodo_cerrado = Periodo.objects.create(
            empresa=self.empresa_a, anio=2026, mes=2, orden=202602,
            fecha_inicio='2026-02-01', fecha_fin='2026-02-28', estado='CERRADO',
        )
        self.periodo_b = Periodo.objects.create(
            empresa=self.empresa_b, anio=2026, mes=1, orden=202601,
            fecha_inicio='2026-01-01', fecha_fin='2026-01-31', estado='ABIERTO',
        )
        self.tipos = {}
        configuracion_tipos = {
            'MERMA': 'SALIDA',
            'DESMEDRO': 'SALIDA',
            'CONSUMO_INTERNO': 'SALIDA',
            'RETIRO': 'SALIDA',
            'AJUSTE_INGRESO': 'ENTRADA',
            'AJUSTE_SALIDA': 'SALIDA',
            'AJUSTE_VALOR_MANUAL': 'AJUSTE_VALOR',
        }
        for codigo, naturaleza in configuracion_tipos.items():
            self.tipos[codigo] = TipoOperacion.objects.create(
                codigo_interno=codigo, descripcion=codigo.replace('_', ' '),
                naturaleza=naturaleza, es_interna=True,
                origen_requerido='NOTA_INTERNA', activo=True,
            )
        self.tipo_no_interno = TipoOperacion.objects.create(
            codigo_interno='NO_INTERNO', descripcion='NO INTERNO',
            naturaleza='SALIDA', es_interna=False,
            origen_requerido='NOTA_INTERNA', activo=True,
        )
        self.tipo_otro_origen = TipoOperacion.objects.create(
            codigo_interno='OTRO_ORIGEN', descripcion='OTRO ORIGEN',
            naturaleza='SALIDA', es_interna=True,
            origen_requerido='DOCUMENTO', activo=True,
        )
        self.admin = Usuario.objects.create(
            username='admin_ops', email='admin_ops@factkard.pe', password_hash='hash',
        )
        self.usuario = Usuario.objects.create(
            username='usuario_ops', email='usuario_ops@factkard.pe', password_hash='hash',
        )
        UsuarioEmpresa.objects.create(
            usuario=self.admin, empresa=self.empresa_a, rol='ADMIN',
        )
        UsuarioEmpresa.objects.create(
            usuario=self.usuario, empresa=self.empresa_a, rol='USUARIO',
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def headers(self):
        return {'HTTP_X_EMPRESA_ID': str(self.empresa_a.id)}

    def saldo_payload(self, **cambios):
        payload = {
            'periodo': self.periodo_a.id,
            'almacen': self.almacen_a.id,
            'producto': self.producto_a.id,
            'cantidad': '3.00000000',
            'valor_pen': '10.00000000',
        }
        payload.update(cambios)
        return payload

    def nota_payload(self, tipo='MERMA', detalles=None, **cambios):
        payload = {
            'almacen': self.almacen_a.id,
            'periodo': self.periodo_a.id,
            'tipo_operacion': self.tipos[tipo].id,
            'fecha': '2026-01-15',
            'motivo': 'Regularización interna',
            'responsable': 'Jefe de almacén',
            'observacion': 'Conteo físico',
            'archivo_sustento': 'sustentos/nota-001.pdf',
            'detalles': detalles or [{
                'producto': self.producto_a.id,
                'cantidad_base': '2.00000000',
                'costo_unitario_pen': None,
                'valor_ajuste_pen': None,
            }],
        }
        payload.update(cambios)
        return payload

    def crear_nota_modelo(self, estado='BORRADOR', tipo='MERMA', costo=None):
        nota = NotaInterna.objects.create(
            empresa=self.empresa_a, almacen=self.almacen_a,
            periodo=self.periodo_a, tipo_operacion=self.tipos[tipo],
            fecha='2026-01-15', motivo='Nota existente', estado=estado,
            creado_por=self.admin,
        )
        NotaInternaDetalle.objects.create(
            nota_interna=nota, producto=self.producto_a,
            cantidad_base=Decimal('1.00000000'), costo_unitario_pen=costo,
        )
        return nota

    def test_crear_saldo_inicial_correctamente(self):
        response = self.client.post(
            reverse('saldo-inicial-list-create'), self.saldo_payload(),
            format='json', **self.headers(),
        )
        self.assertEqual(response.status_code, 201)
        saldo = SaldoInicial.objects.get(pk=response.data['id'])
        self.assertEqual(saldo.empresa, self.empresa_a)
        self.assertEqual(saldo.estado, 'BORRADOR')
        self.assertEqual(saldo.creado_por, self.admin)
        self.assertTrue(Auditoria.objects.filter(
            entidad='SALDO_INICIAL', registro_id=saldo.id,
        ).exists())

    def test_cpp_inicial_decimal_exacto(self):
        response = self.client.post(
            reverse('saldo-inicial-list-create'), self.saldo_payload(),
            format='json', **self.headers(),
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            SaldoInicial.objects.get(pk=response.data['id']).cpp_inicial,
            Decimal('3.33333300'),
        )

    def test_cpp_inicial_cantidad_cero(self):
        response = self.client.post(
            reverse('saldo-inicial-list-create'),
            self.saldo_payload(cantidad='0.00000000'),
            format='json', **self.headers(),
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Decimal(response.data['cpp_inicial']), Decimal('0.00000000'))

    def test_saldo_inicial_duplicado_rechazado(self):
        url = reverse('saldo-inicial-list-create')
        self.client.post(url, self.saldo_payload(), format='json', **self.headers())
        response = self.client.post(
            url, self.saldo_payload(), format='json', **self.headers(),
        )
        self.assertEqual(response.status_code, 400)

    def test_saldo_inicial_periodo_cerrado_rechazado(self):
        response = self.client.post(
            reverse('saldo-inicial-list-create'),
            self.saldo_payload(periodo=self.periodo_cerrado.id),
            format='json', **self.headers(),
        )
        self.assertEqual(response.status_code, 400)

    def test_saldo_inicial_producto_otra_empresa_rechazado(self):
        response = self.client.post(
            reverse('saldo-inicial-list-create'),
            self.saldo_payload(producto=self.producto_b.id),
            format='json', **self.headers(),
        )
        self.assertEqual(response.status_code, 400)

    def test_saldo_inicial_almacen_otra_empresa_rechazado(self):
        response = self.client.post(
            reverse('saldo-inicial-list-create'),
            self.saldo_payload(almacen=self.almacen_b.id),
            format='json', **self.headers(),
        )
        self.assertEqual(response.status_code, 400)

    def test_saldo_inicial_periodo_otra_empresa_rechazado(self):
        response = self.client.post(
            reverse('saldo-inicial-list-create'),
            self.saldo_payload(periodo=self.periodo_b.id),
            format='json', **self.headers(),
        )
        self.assertEqual(response.status_code, 400)

    def test_saldo_inicial_confirmado_no_puede_editarse(self):
        saldo = SaldoInicial.objects.create(
            empresa=self.empresa_a, periodo=self.periodo_a, almacen=self.almacen_a,
            producto=self.producto_a, cantidad=Decimal('1'), valor_pen=Decimal('5'),
            cpp_inicial=Decimal('5'), estado='CONFIRMADO', creado_por=self.admin,
        )
        response = self.client.patch(
            reverse('saldo-inicial-detail', args=[saldo.id]),
            {'valor_pen': '8.00000000'}, format='json', **self.headers(),
        )
        self.assertEqual(response.status_code, 400)

    def test_usuario_no_puede_escribir_saldo_inicial(self):
        self.client.force_authenticate(user=self.usuario)
        response = self.client.post(
            reverse('saldo-inicial-list-create'), self.saldo_payload(),
            format='json', **self.headers(),
        )
        self.assertEqual(response.status_code, 403)

    def test_usuario_crea_merma_sin_costos_manuales(self):
        self.client.force_authenticate(user=self.usuario)
        response = self.client.post(
            reverse('nota-interna-list-create'), self.nota_payload(),
            format='json', **self.headers(),
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['estado'], 'BORRADOR')

    def test_nota_interna_conserva_fecha_ingresada_dentro_del_periodo(self):
        from datetime import date

        periodo_octubre = Periodo.objects.create(
            empresa=self.empresa_a,
            anio=2026,
            mes=10,
            orden=202610,
            fecha_inicio=date(2026, 10, 1),
            fecha_fin=date(2026, 10, 31),
            estado='ABIERTO',
        )
        response = self.client.post(
            reverse('nota-interna-list-create'),
            self.nota_payload(
                periodo=periodo_octubre.id,
                fecha='2026-10-21',
                detalles=[{
                    'producto': self.producto_a.id,
                    'cantidad_base': '5.00000000',
                    'costo_unitario_pen': None,
                    'valor_ajuste_pen': None,
                }],
            ),
            format='json',
            **self.headers(),
        )

        self.assertEqual(response.status_code, 201)
        nota = NotaInterna.objects.get(pk=response.data['id'])
        self.assertEqual(nota.fecha, date(2026, 10, 21))
        self.assertNotEqual(nota.fecha, date(2026, 10, 1))

    def test_transferencia_conserva_fecha_calendario_ingresada(self):
        from datetime import date
        from apps.inventario.models import Transferencia

        periodo_octubre = Periodo.objects.create(
            empresa=self.empresa_a,
            anio=2026,
            mes=10,
            orden=202610,
            fecha_inicio=date(2026, 10, 1),
            fecha_fin=date(2026, 10, 31),
            estado='ABIERTO',
        )
        almacen_destino = Almacen.objects.create(
            empresa=self.empresa_a,
            establecimiento=self.almacen_a.establecimiento,
            codigo='A02',
            nombre='ALMACÉN DESTINO',
        )

        response = self.client.post(
            reverse('transferencia-list-create'),
            {
                'almacen_origen': self.almacen_a.id,
                'almacen_destino': almacen_destino.id,
                'fecha': '2026-10-21',
                'detalles': [{
                    'producto': self.producto_a.id,
                    'cantidad_base': '10.00000000',
                }],
            },
            format='json',
            **self.headers(),
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['fecha'], '2026-10-21')
        transferencia = Transferencia.objects.get(pk=response.data['id'])
        self.assertEqual(transferencia.fecha, date(2026, 10, 21))

    def test_nota_interna_crea_multiples_detalles(self):
        detalles = [
            {'producto': self.producto_a.id, 'cantidad_base': '2.00000000'},
            {'producto': self.producto_a2.id, 'cantidad_base': '4.00000000'},
        ]
        response = self.client.post(
            reverse('nota-interna-list-create'),
            self.nota_payload(detalles=detalles), format='json', **self.headers(),
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(NotaInternaDetalle.objects.filter(
            nota_interna_id=response.data['id'],
        ).count(), 2)

    def test_usuario_con_costo_manual_recibe_403(self):
        self.client.force_authenticate(user=self.usuario)
        payload = self.nota_payload(detalles=[{
            'producto': self.producto_a.id, 'cantidad_base': '1.00000000',
            'costo_unitario_pen': '12.50000000', 'valor_ajuste_pen': None,
        }])
        response = self.client.post(
            reverse('nota-interna-list-create'), payload,
            format='json', **self.headers(),
        )
        self.assertEqual(response.status_code, 403)

    def test_usuario_con_valor_ajuste_manual_recibe_403(self):
        self.client.force_authenticate(user=self.usuario)
        payload = self.nota_payload(detalles=[{
            'producto': self.producto_a.id, 'cantidad_base': '0.00000000',
            'costo_unitario_pen': None, 'valor_ajuste_pen': '25.00000000',
        }])
        response = self.client.post(
            reverse('nota-interna-list-create'), payload,
            format='json', **self.headers(),
        )
        self.assertEqual(response.status_code, 403)

    def test_usuario_ajuste_ingreso_recibe_403(self):
        self.client.force_authenticate(user=self.usuario)
        response = self.client.post(
            reverse('nota-interna-list-create'),
            self.nota_payload(tipo='AJUSTE_INGRESO'),
            format='json', **self.headers(),
        )
        self.assertEqual(response.status_code, 403)

    def test_usuario_ajuste_valor_manual_recibe_403(self):
        self.client.force_authenticate(user=self.usuario)
        response = self.client.post(
            reverse('nota-interna-list-create'),
            self.nota_payload(tipo='AJUSTE_VALOR_MANUAL'),
            format='json', **self.headers(),
        )
        self.assertEqual(response.status_code, 403)

    def test_admin_puede_crear_ajuste_manual(self):
        payload = self.nota_payload(
            tipo='AJUSTE_VALOR_MANUAL',
            detalles=[{
                'producto': self.producto_a.id,
                'cantidad_base': '0.00000000',
                'valor_ajuste_pen': '30.00000000',
            }],
        )
        response = self.client.post(
            reverse('nota-interna-list-create'), payload,
            format='json', **self.headers(),
        )
        self.assertEqual(response.status_code, 201)

    def test_nota_producto_otra_empresa_rechazado(self):
        payload = self.nota_payload(detalles=[{
            'producto': self.producto_b.id, 'cantidad_base': '1.00000000',
        }])
        response = self.client.post(
            reverse('nota-interna-list-create'), payload,
            format='json', **self.headers(),
        )
        self.assertEqual(response.status_code, 400)

    def test_nota_almacen_otra_empresa_rechazado(self):
        response = self.client.post(
            reverse('nota-interna-list-create'),
            self.nota_payload(almacen=self.almacen_b.id),
            format='json', **self.headers(),
        )
        self.assertEqual(response.status_code, 400)

    def test_nota_periodo_otra_empresa_rechazado(self):
        response = self.client.post(
            reverse('nota-interna-list-create'),
            self.nota_payload(periodo=self.periodo_b.id),
            format='json', **self.headers(),
        )
        self.assertEqual(response.status_code, 400)

    def test_nota_periodo_cerrado_rechazado(self):
        response = self.client.post(
            reverse('nota-interna-list-create'),
            self.nota_payload(periodo=self.periodo_cerrado.id, fecha='2026-02-15'),
            format='json', **self.headers(),
        )
        self.assertEqual(response.status_code, 400)

    def test_nota_fecha_fuera_del_periodo_rechazada(self):
        response = self.client.post(
            reverse('nota-interna-list-create'),
            self.nota_payload(fecha='2026-02-01'),
            format='json', **self.headers(),
        )
        self.assertEqual(response.status_code, 400)

    def test_nota_sin_detalles_rechazada(self):
        payload = self.nota_payload()
        payload['detalles'] = []
        response = self.client.post(
            reverse('nota-interna-list-create'), payload,
            format='json', **self.headers(),
        )
        self.assertEqual(response.status_code, 400)

    def test_nota_tipo_operacion_no_interno_rechazado(self):
        response = self.client.post(
            reverse('nota-interna-list-create'),
            self.nota_payload(tipo_operacion=self.tipo_no_interno.id),
            format='json', **self.headers(),
        )
        self.assertEqual(response.status_code, 400)

    def test_nota_tipo_operacion_otro_origen_rechazado(self):
        response = self.client.post(
            reverse('nota-interna-list-create'),
            self.nota_payload(tipo_operacion=self.tipo_otro_origen.id),
            format='json', **self.headers(),
        )
        self.assertEqual(response.status_code, 400)

    def test_nota_borrador_puede_anularse(self):
        nota = self.crear_nota_modelo()
        response = self.client.post(
            reverse('nota-interna-anular', args=[nota.id]), {},
            format='json', **self.headers(),
        )
        self.assertEqual(response.status_code, 200)
        nota.refresh_from_db()
        self.assertEqual(nota.estado, 'ANULADO')

    def test_nota_confirmada_no_puede_anularse(self):
        nota = self.crear_nota_modelo(estado='CONFIRMADO')
        response = self.client.post(
            reverse('nota-interna-anular', args=[nota.id]), {},
            format='json', **self.headers(),
        )
        self.assertEqual(response.status_code, 400)

    def test_auditoria_creacion_y_anulacion_nota(self):
        crear = self.client.post(
            reverse('nota-interna-list-create'), self.nota_payload(),
            format='json', **self.headers(),
        )
        self.assertEqual(crear.status_code, 201)
        anular = self.client.post(
            reverse('nota-interna-anular', args=[crear.data['id']]), {},
            format='json', **self.headers(),
        )
        self.assertEqual(anular.status_code, 200)
        auditorias = Auditoria.objects.filter(
            entidad='NOTA_INTERNA', registro_id=crear.data['id'],
        )
        self.assertEqual(auditorias.count(), 2)
        anulacion = auditorias.get(accion='ANULAR_NOTA_INTERNA')
        self.assertEqual(anulacion.valor_anterior['estado'], 'BORRADOR')
        self.assertEqual(anulacion.valor_nuevo['estado'], 'ANULADO')



    def test_nota_borrador_puede_eliminarse_fisicamente(self):
        nota = self.crear_nota_modelo()
        response = self.client.delete(
            reverse('nota-interna-detail', args=[nota.id]),
            **self.headers(),
        )
        self.assertEqual(response.status_code, 204)
        self.assertFalse(NotaInterna.objects.filter(pk=nota.id).exists())

    def test_nota_confirmada_no_puede_eliminarse_fisicamente(self):
        nota = self.crear_nota_modelo(tipo='AJUSTE_INGRESO', costo=Decimal('10.00000000'))
        from apps.inventario.services import confirmar_nota_interna
        confirmar_nota_interna(nota_id=nota.id, empresa_id=self.empresa_a.id, usuario=self.admin)
        response = self.client.delete(
            reverse('nota-interna-detail', args=[nota.id]),
            **self.headers(),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('No se puede eliminar físicamente', response.data.get('estado', ''))

    def test_nota_confirmada_anular_con_extorno_exitoso(self):
        nota = self.crear_nota_modelo(tipo='AJUSTE_INGRESO', costo=Decimal('10.00000000'))
        from apps.inventario.services import confirmar_nota_interna
        confirmar_nota_interna(nota_id=nota.id, empresa_id=self.empresa_a.id, usuario=self.admin)

        response = self.client.post(
            reverse('nota-interna-anular', args=[nota.id]),
            {'motivo': 'Error de digitación en ajuste de ingreso'},
            format='json', **self.headers(),
        )
        self.assertEqual(response.status_code, 200)
        nota.refresh_from_db()
        self.assertEqual(nota.estado, 'ANULADO')

        # Verificar que se generó un extorno en Movimiento
        from apps.kardex.models import Movimiento
        extornos = Movimiento.objects.filter(
            empresa_id=self.empresa_a.id,
            es_extorno=True,
            movimiento_extornado__nota_interna_detalle__nota_interna_id=nota.id,
        )
        self.assertTrue(extornos.exists())

    def test_confirmar_nota_interna_endpoint(self):
        nota = self.crear_nota_modelo(tipo='AJUSTE_INGRESO', costo=Decimal('15.00000000'))
        response = self.client.post(
            reverse('nota-interna-confirmar', args=[nota.id]),
            **self.headers(),
        )
        self.assertEqual(response.status_code, 200)
        nota.refresh_from_db()
        self.assertEqual(nota.estado, 'CONFIRMADO')

    def test_saldo_inicial_borrador_puede_eliminarse_fisicamente(self):
        saldo = SaldoInicial.objects.create(
            empresa=self.empresa_a,
            periodo=self.periodo_a,
            almacen=self.almacen_a,
            producto=self.producto_a,
            cantidad=Decimal('10.00000000'),
            valor_pen=Decimal('100.00000000'),
            cpp_inicial=Decimal('10.000000'),
            estado='BORRADOR',
        )
        response = self.client.delete(
            reverse('saldo-inicial-detail', args=[saldo.id]),
            **self.headers(),
        )
        self.assertEqual(response.status_code, 204)
        self.assertFalse(SaldoInicial.objects.filter(pk=saldo.id).exists())

    def test_saldo_inicial_confirmado_no_puede_eliminarse_fisicamente(self):
        saldo = SaldoInicial.objects.create(
            empresa=self.empresa_a,
            periodo=self.periodo_a,
            almacen=self.almacen_a,
            producto=self.producto_a,
            cantidad=Decimal('10.00000000'),
            valor_pen=Decimal('100.00000000'),
            cpp_inicial=Decimal('10.000000'),
            estado='CONFIRMADO',
        )
        response = self.client.delete(
            reverse('saldo-inicial-detail', args=[saldo.id]),
            **self.headers(),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('No se puede eliminar físicamente', response.data.get('estado', ''))

    def test_filtro_estado_activos_y_todos_notas(self):
        # Crear una en borrador
        nota_borrador = self.crear_nota_modelo(estado='BORRADOR')
        # Crear una y anularla
        nota_anulada = self.crear_nota_modelo(estado='BORRADOR')
        self.client.post(
            reverse('nota-interna-anular', args=[nota_anulada.id]), {},
            format='json', **self.headers(),
        )

        # Filtro ACTIVOS debe retornar borrador pero NO anulada
        resp_activos = self.client.get(
            reverse('nota-interna-list-create') + '?estado=ACTIVOS',
            **self.headers(),
        )
        self.assertEqual(resp_activos.status_code, 200)
        ids_activos = [n['id'] for n in resp_activos.data]
        self.assertIn(nota_borrador.id, ids_activos)
        self.assertNotIn(nota_anulada.id, ids_activos)

        # Filtro TODOS debe retornar ambas
        resp_todos = self.client.get(
            reverse('nota-interna-list-create') + '?estado=TODOS',
            **self.headers(),
        )
        self.assertEqual(resp_todos.status_code, 200)
        ids_todos = [n['id'] for n in resp_todos.data]
        self.assertIn(nota_borrador.id, ids_todos)
        self.assertIn(nota_anulada.id, ids_todos)

    def test_filtro_estado_activos_y_todos_saldos(self):
        saldo_borrador = SaldoInicial.objects.create(
            empresa=self.empresa_a,
            periodo=self.periodo_a,
            almacen=self.almacen_a,
            producto=self.producto_a,
            cantidad=Decimal('5.00000000'),
            valor_pen=Decimal('50.00000000'),
            cpp_inicial=Decimal('10.000000'),
            estado='BORRADOR',
        )
        resp_activos = self.client.get(
            reverse('saldo-inicial-list-create') + '?estado=ACTIVOS',
            **self.headers(),
        )
        self.assertEqual(resp_activos.status_code, 200)
        ids = [s['id'] for s in resp_activos.data]
        self.assertIn(saldo_borrador.id, ids)

        resp_todos = self.client.get(
            reverse('saldo-inicial-list-create') + '?estado=TODOS',
            **self.headers(),
        )
        self.assertEqual(resp_todos.status_code, 200)
        ids = [s['id'] for s in resp_todos.data]
        self.assertIn(saldo_borrador.id, ids)



class ProductoEquivalenciaApiTest(TestCase):
    def setUp(self):
        self.moneda = Moneda.objects.create(codigo='PEN', nombre='Soles')
        self.empresa = Empresa.objects.create(
            ruc='20600000088', razon_social='EQUIV TEST S.A.C.', moneda_base_codigo=self.moneda,
        )
        self.usuario = Usuario.objects.create(
            username='user_equiv', email='equiv@factkard.pe', password_hash='hash',
        )
        UsuarioEmpresa.objects.create(
            usuario=self.usuario, empresa=self.empresa, rol='ADMIN',
        )
        self.tercero = Tercero.objects.create(
            empresa=self.empresa, tipo_documento='6', numero_documento='20555666777',
            razon_social='PROVEEDOR INDUSTRIAL S.A.C.', es_proveedor=True,
        )
        tipo_ex = TipoExistencia.objects.create(codigo='01', descripcion='MERCADERIA')
        self.und = UnidadMedida.objects.create(codigo='NIU', descripcion='UNIDAD')
        self.producto = Producto.objects.create(
            empresa=self.empresa, codigo_interno='P-EQ-01', descripcion='PRODUCTO HOMOLOGABLE',
            tipo_existencia_codigo=tipo_ex,
        )
        self.prod_und = ProductoUnidad.objects.create(
            producto=self.producto, unidad_codigo=self.und,
            factor_a_base=Decimal('1.00000000'), es_base=True,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.usuario)

    def headers(self):
        return {'HTTP_X_EMPRESA_ID': str(self.empresa.id)}

    def test_crear_equivalencia_guarda_confirmacion_humana_y_auditoria(self):
        url = reverse('producto-equivalencia-list-create')
        payload = {
            'tercero': self.tercero.id,
            'codigo_externo': 'PROV-ITEM-100',
            'descripcion_externa': 'ITEM DEL PROVEEDOR 100',
            'unidad_externa_codigo': 'NIU',
            'producto_unidad': self.prod_und.id,
            'factor_conversion': '2.50000000',
            'activa': True,
        }
        resp = self.client.post(url, payload, format='json', **self.headers())
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data['codigo_externo'], 'PROV-ITEM-100')
        self.assertEqual(resp.data['confirmado_por_username'], self.usuario.username)
        self.assertIsNotNone(resp.data['confirmado_en'])

        # Verificar auditoría
        aud = Auditoria.objects.filter(
            entidad='PRODUCTO_EQUIVALENCIA',
            registro_id=resp.data['id'],
            accion='CREAR_PRODUCTO_EQUIVALENCIA',
        ).first()
        self.assertIsNotNone(aud)

    def test_sugerir_equivalencia_proveedor_sugerida_vs_sin_homologar(self):
        # 1. Crear equivalencia confirmada
        ProductoEquivalencia.objects.create(
            empresa=self.empresa,
            tercero=self.tercero,
            codigo_externo='SKU-PROV-A',
            descripcion_externa='TORNILLO ACERO 2 PULG',
            unidad_externa_codigo=self.und,
            producto_unidad=self.prod_und,
            factor_conversion=Decimal('1.00000000'),
            confirmado_por=self.usuario,
            confirmado_en=timezone.now(),
            activa=True,
        )

        url_sugerir = reverse('producto-equivalencia-sugerir')

        # 2. Consultar con código existente
        resp_ok = self.client.get(
            f"{url_sugerir}?tercero_id={self.tercero.id}&codigo_externo=SKU-PROV-A",
            **self.headers()
        )
        self.assertEqual(resp_ok.status_code, 200)
        self.assertTrue(resp_ok.data['encontrado'])
        self.assertEqual(resp_ok.data['sugerencia']['codigo_externo'], 'SKU-PROV-A')

        # 3. Consultar con código inexistente
        resp_no = self.client.get(
            f"{url_sugerir}?tercero_id={self.tercero.id}&codigo_externo=SKU-DESCONOCIDO",
            **self.headers()
        )
        self.assertEqual(resp_no.status_code, 200)
        self.assertFalse(resp_no.data['encontrado'])
        self.assertEqual(resp_no.data['estado'], 'PRODUCTO_SIN_HOMOLOGAR')

