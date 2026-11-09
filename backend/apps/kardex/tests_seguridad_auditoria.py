import datetime
from decimal import Decimal

from django.test import TestCase
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.catalogos.models import Moneda, TipoCambio, TipoComprobante, TipoExistencia, TipoOperacion, UnidadMedida
from apps.documentos.captura_services import generar_borrador_desde_captura
from apps.documentos.models import CapturaCampo, Documento, DocumentoCaptura, DocumentoDetalle
from apps.documentos.services import crear_documento
from apps.empresas.models import ConfigEmpresa, ConfigIgvPeriodo, Empresa, Establecimiento, Periodo
from apps.empresas.services import cerrar_periodo, reabrir_periodo
from apps.inventario.models import Almacen, Producto, ProductoEquivalencia, ProductoUnidad, Tercero
from apps.kardex.models import Movimiento, SaldoCppActual, StockAlmacen, ValorizacionMovimiento
from apps.kardex.services import anular_documento_motor, confirmar_documento_motor, ejecutar_recalculo_producto
from apps.reportes.formato131_service import generar_formato_131
from apps.usuarios.models import Usuario, UsuarioEmpresa


class AuditoriaSeguridadKardexTest(TestCase):
    def setUp(self):
        self.moneda_pen = Moneda.objects.create(codigo='PEN', nombre='Soles')
        self.moneda_usd = Moneda.objects.create(codigo='USD', nombre='Dólares Americanos')

        self.empresa = Empresa.objects.create(
            ruc='20600000001',
            razon_social='EMPRESA AUDITORIA SAC',
            moneda_base_codigo=self.moneda_pen,
        )
        self.config_empresa = ConfigEmpresa.objects.create(
            empresa=self.empresa,
            tolerancia_residuo_pen=Decimal('0.05000000'),
            decimales_calculo=6,
        )
        self.establecimiento = Establecimiento.objects.create(
            empresa=self.empresa, codigo_sunat='0000', nombre='Principal'
        )
        self.almacen = Almacen.objects.create(
            empresa=self.empresa, establecimiento=self.establecimiento, codigo='ALM01', nombre='Almacen General'
        )
        self.tipo_existencia = TipoExistencia.objects.create(codigo='01', descripcion='Mercadería')
        self.und_base = UnidadMedida.objects.create(codigo='NIU', descripcion='Unidad')
        self.und_caja = UnidadMedida.objects.create(codigo='BX', descripcion='Caja')

        self.producto = Producto.objects.create(
            empresa=self.empresa,
            codigo_interno='PROD-01',
            descripcion='Producto Test F1',
            tipo_existencia_codigo=self.tipo_existencia,
        )
        self.prod_unidad_caja = ProductoUnidad.objects.create(
            producto=self.producto,
            unidad_codigo=self.und_caja,
            factor_a_base=Decimal('12.00000000'),
            es_base=False,
        )

        self.periodo_enero = Periodo.objects.create(
            empresa=self.empresa,
            anio=2026,
            mes=1,
            orden=202601,
            fecha_inicio=datetime.date(2026, 1, 1),
            fecha_fin=datetime.date(2026, 1, 31),
            estado='ABIERTO',
        )
        self.periodo_febrero = Periodo.objects.create(
            empresa=self.empresa,
            anio=2026,
            mes=2,
            orden=202602,
            fecha_inicio=datetime.date(2026, 2, 1),
            fecha_fin=datetime.date(2026, 2, 28),
            estado='ABIERTO',
        )

        self.usuario_admin = Usuario.objects.create(
            username='admin_seguridad',
            email='admin@seguridad.pe',
            password_hash='hash',
            es_admin_global=True,
            activo=True,
        )
        self.usuario_operador = Usuario.objects.create(
            username='operador_seguridad',
            email='operador@seguridad.pe',
            password_hash='hash',
            es_admin_global=False,
            activo=True,
        )
        UsuarioEmpresa.objects.create(
            usuario=self.usuario_admin, empresa=self.empresa, rol='ADMIN', activo=True
        )
        UsuarioEmpresa.objects.create(
            usuario=self.usuario_operador, empresa=self.empresa, rol='USUARIO', activo=True
        )

        # Configurar Tipos de Operación
        for codigo, naturaleza, origen in (
            ('COMPRA', 'ENTRADA', 'DOCUMENTO'),
            ('VENTA', 'SALIDA', 'DOCUMENTO'),
            ('NC_COMPRA', 'AJUSTE_VALOR', 'DOCUMENTO'),
            ('EXTORNO_ENTRADA', 'ENTRADA', 'MOV_EXTORNADO'),
            ('EXTORNO_SALIDA', 'SALIDA', 'MOV_EXTORNADO'),
            ('AJUSTE_VALOR_EXTORNO', 'AJUSTE_VALOR', 'MOV_EXTORNADO'),
            ('RESIDUO_AUTOMATICO', 'AJUSTE_VALOR', 'MOTOR'),
            ('SALDO_INICIAL', 'ENTRADA', 'SALDO_INICIAL'),
        ):
            TipoOperacion.objects.get_or_create(
                codigo_interno=codigo,
                defaults={
                    'descripcion': codigo,
                    'naturaleza': naturaleza,
                    'es_interna': False if codigo in ('COMPRA', 'VENTA', 'NC_COMPRA') else True,
                    'afecta_kardex': True,
                    'origen_requerido': origen,
                }
            )

        self.tipo_factura = TipoComprobante.objects.create(
            codigo_sunat='01', descripcion='FACTURA', es_nota=False, efecto_nota='NINGUNO'
        )
        self.tipo_nc = TipoComprobante.objects.create(
            codigo_sunat='07', descripcion='NOTA DE CREDITO', es_nota=True, efecto_nota='CREDITO'
        )

        self.tercero = Tercero.objects.create(
            empresa=self.empresa,
            tipo_documento='6',
            numero_documento='20555777888',
            razon_social='PROVEEDOR CENTRAL SAC',
            es_proveedor=True,
        )

        self.saldo_cpp = SaldoCppActual.objects.create(
            empresa=self.empresa,
            producto=self.producto,
            cantidad_total=Decimal('100.00000000'),
            valor_total_pen=Decimal('1000.00000000'),
            cpp_pen=Decimal('10.00000000'),
        )
        self.stock = StockAlmacen.objects.create(
            empresa=self.empresa,
            almacen=self.almacen,
            producto=self.producto,
            cantidad_actual=Decimal('100.00000000'),
        )

        self.tc = TipoCambio.objects.create(
            moneda_codigo=self.moneda_usd,
            fecha_publicacion=datetime.date(2026, 1, 15),
            compra=Decimal('3.75000000'),
            venta=Decimal('3.80000000'),
            fuente='SBS',
        )

    def test_c02_crear_documento_valida_rango_estricto_periodo(self):
        """C-02: La fecha de emisión no puede salirse del rango [fecha_inicio, fecha_fin] del período contable."""
        tipo_op = TipoOperacion.objects.get(codigo_interno='COMPRA')
        # Fecha en febrero pero periodo es enero -> Debe rechazar con ValidationError
        datos_cabecera = {
            'clase': 'COMPRA',
            'periodo_id': self.periodo_enero.id,
            'tercero_id': self.tercero.id,
            'tipo_comprobante_id': self.tipo_factura.id,
            'serie': 'F001',
            'numero': '00001001',
            'fecha_emision': datetime.date(2026, 2, 5),  # Fuera de enero
            'moneda_codigo': 'PEN',
        }
        detalles = [{
            'linea': 1,
            'producto_id': self.producto.id,
            'almacen_id': self.almacen.id,
            'tipo_operacion_id': tipo_op.id,
            'cantidad_original': Decimal('10'),
            'precio_unitario': Decimal('20'),
        }]

        with self.assertRaises(ValidationError) as ctx:
            crear_documento(
                empresa_id=self.empresa.id,
                usuario_id=self.usuario_admin.id,
                datos_cabecera=datos_cabecera,
                detalles_datos=detalles,
            )
        self.assertIn('fecha_emision', str(ctx.exception))

    def test_c03_recalculo_bloqueado_en_periodo_cerrado(self):
        """C-03: Prohibir que ejecutar_recalculo_producto altere movimientos de un período CERRADO."""
        # Cerrar el período de enero
        self.periodo_enero.estado = 'CERRADO'
        self.periodo_enero.save()

        # Intentar ejecutar recálculo con fecha_desde dentro de enero cerrado
        with self.assertRaises(ValidationError) as ctx:
            ejecutar_recalculo_producto(
                empresa_id=self.empresa.id,
                producto_id=self.producto.id,
                fecha_desde=datetime.date(2026, 1, 10),
                usuario_id=self.usuario_admin.id,
            )
        self.assertIn('períodos cerrados', str(ctx.exception))

    def test_c04_captura_costo_unitario_pen_con_usd_factor_y_prorrata(self):
        """C-04: generar_borrador_desde_captura aplica TC venta, factor conversión y prorrata IGV."""
        # Prorrata al 80% de crédito fiscal
        ConfigIgvPeriodo.objects.create(
            empresa=self.empresa,
            periodo=self.periodo_enero,
            metodo='PRORRATA',
            porcentaje_recuperable=Decimal('80.0000'),
        )

        # Equivalencia con factor de caja = 12 unidades
        ProductoEquivalencia.objects.create(
            empresa=self.empresa,
            tercero=self.tercero,
            codigo_externo='SKU-USD-BOX',
            descripcion_externa='Caja de 12 Unidades USD',
            unidad_externa_codigo=self.und_caja,
            producto_unidad=self.prod_unidad_caja,
            factor_conversion=Decimal('12.00000000'),
            confirmado_por=self.usuario_admin,
            confirmado_en=datetime.datetime.now(datetime.timezone.utc),
            activa=True,
        )

        captura = DocumentoCaptura.objects.create(
            empresa=self.empresa,
            tipo='XML',
            ruta_archivo='dummy.xml',
            hash_sha256='fase1hash1234567890abcdef',
            estado_proceso='PROCESADO',
            subido_por=self.usuario_admin,
        )

        # Factura en USD: 2 cajas a $100 c/u = $200 subtotal. IGV = $36. Total = $236
        # TC SBS Venta = 3.80
        # Factor = 12 -> Cantidad base = 2 * 12 = 24 unidades
        # IGV no recuperable (20%) = $36 * 0.20 = $7.20
        # Costo línea en USD = $200 + $7.20 = $207.20
        # Costo línea en PEN = $207.20 * 3.80 = 787.36 PEN
        # Costo unitario base PEN = 787.36 / 24 = 32.80666667 PEN
        # Crear campos de cabecera en CapturaCampo
        campos_cabecera = [
            ('ruc_emisor', self.tercero.numero_documento),
            ('razon_social_emisor', self.tercero.razon_social),
            # Bloque 3: la clase se decide por el RUC receptor (la empresa activa = compra).
            ('ruc_cliente', self.empresa.ruc),
            ('serie', 'F001'),
            ('numero', '00002002'),
            ('tipo_comprobante', '01'),
            ('fecha_emision', '2026-01-20'),
            ('moneda', 'USD'),
            ('subtotal', '200.00'),
            ('igv', '36.00'),
            ('total', '236.00'),
        ]
        for nombre, valor in campos_cabecera:
            CapturaCampo.objects.create(
                documento_captura=captura,
                seccion='CABECERA',
                nombre_campo=nombre,
                valor_extraido=valor,
                confianza=Decimal('99.0000'),
            )

        # Crear campos de detalle en CapturaCampo
        campos_detalle = [
            ('codigo_externo', 'SKU-USD-BOX'),
            ('descripcion', 'Caja de 12 Unidades USD'),
            ('unidad_medida', 'BX'),
            ('cantidad', '2.00'),
            ('precio_unitario', '100.00'),
            ('valor_total', '200.00'),
        ]
        for nombre, valor in campos_detalle:
            CapturaCampo.objects.create(
                documento_captura=captura,
                seccion='DETALLE',
                numero_linea=1,
                nombre_campo=nombre,
                valor_extraido=valor,
                confianza=Decimal('99.0000'),
            )

        res = generar_borrador_desde_captura(
            captura_id=captura.id,
            empresa_id=self.empresa.id,
            usuario=self.usuario_admin,
        )

        doc = Documento.objects.get(pk=res['documento_id'])
        self.assertEqual(doc.moneda_codigo.codigo, 'USD')
        self.assertEqual(doc.monto_tc, Decimal('3.80000000'))

        det = doc.detalles.first()
        self.assertEqual(det.factor_conversion, Decimal('12.00000000'))
        self.assertEqual(det.cantidad_base, Decimal('24.00000000'))
        self.assertEqual(det.porcentaje_credito_fiscal_aplicado, Decimal('80.0000'))

        # Validar costo unitario en PEN exacto
        # Valor línea = 2 * 100 = 200
        # IGV línea = 200 * 0.18 = 36
        # IGV no recuperable = 36 * (100 - 80) / 100 = 7.20
        # Costo línea doc = 200 + 7.20 = 207.20
        # Costo línea pen = 207.20 * 3.80 = 787.36
        # Costo unitario pen = 787.36 / 24 = 32.80666667
        esperado = Decimal('32.80666667')
        self.assertEqual(det.costo_unitario_pen, esperado)

    def test_c05_extorno_ajuste_valor_anular_documento(self):
        """C-05: Anular una NC de ajuste de valor revierte el valor de inventario mediante extorno sin tocar cantidad."""
        tipo_op_nc = TipoOperacion.objects.get(codigo_interno='NC_COMPRA')

        # Partimos con saldo: 100 unid, 1000 PEN, CPP 10.00
        # CON-007: toda nota referencia un documento de origen CONFIRMADO del mismo tercero.
        factura_origen = Documento.objects.create(
            empresa=self.empresa, clase='COMPRA', periodo=self.periodo_enero, tercero=self.tercero,
            ruc_emisor=self.tercero.numero_documento, tipo_comprobante=self.tipo_factura,
            serie='F001', serie_normalizada='F001', numero='00000049', numero_normalizado='49',
            fecha_emision=datetime.date(2026, 1, 5), moneda_codigo=self.moneda_pen,
            subtotal=Decimal('1000.00000000'), igv=Decimal('180.00000000'), total=Decimal('1180.00000000'),
            estado='CONFIRMADO', estado_revision='REVISADO', creado_por=self.usuario_admin,
        )
        # Creamos una Nota de Crédito comercial de ajuste de valor por S/ 200
        doc_nc = Documento.objects.create(
            documento_origen=factura_origen,
            empresa=self.empresa,
            clase='COMPRA',
            periodo=self.periodo_enero,
            tercero=self.tercero,
            ruc_emisor=self.tercero.numero_documento,
            tipo_comprobante=self.tipo_nc,
            serie='FC01',
            serie_normalizada='FC01',
            numero='00000050',
            numero_normalizado='50',
            fecha_emision=datetime.date(2026, 1, 10),
            moneda_codigo=self.moneda_pen,
            subtotal=Decimal('200.00000000'),
            igv=Decimal('36.00000000'),
            total=Decimal('236.00000000'),
            estado='BORRADOR',
            estado_revision='REVISADO',
            creado_por=self.usuario_admin,
        )
        DocumentoDetalle.objects.create(
            documento=doc_nc,
            linea=1,
            producto=self.producto,
            almacen=self.almacen,
            tipo_operacion=tipo_op_nc,
            afecta_kardex_aplicado=True,
            descripcion_original='Ajuste valor descuento',
            cantidad_original=Decimal('0.00000000'),
            factor_conversion=Decimal('1.00000000'),
            cantidad_base=Decimal('0.00000000'),
            precio_unitario=Decimal('200.00000000'),
            igv=Decimal('36.00000000'),
            costo_unitario_pen=Decimal('0.00000000'),
        )

        # Confirmar la NC en kardex: reduce el valor en 200 PEN (1000 -> 800)
        confirmar_documento_motor(
            documento_id=doc_nc.id,
            empresa_id=self.empresa.id,
            usuario_id=self.usuario_admin.id,
        )
        self.saldo_cpp.refresh_from_db()
        self.assertEqual(self.saldo_cpp.cantidad_total, Decimal('100.00000000'))
        self.assertEqual(self.saldo_cpp.valor_total_pen, Decimal('800.00000000'))
        self.assertEqual(self.saldo_cpp.cpp_pen, Decimal('8.00000000'))

        # Ahora anulamos el comprobante con anular_documento_motor
        anular_documento_motor(
            documento_id=doc_nc.id,
            empresa_id=self.empresa.id,
            usuario_id=self.usuario_admin.id,
            motivo='Error en emisión de nota de crédito',
        )

        # El extorno debe revertir los 200 PEN exactamente: 800 -> 1000 PEN, CPP 8.00 -> 10.00
        self.saldo_cpp.refresh_from_db()
        self.assertEqual(self.saldo_cpp.cantidad_total, Decimal('100.00000000'))
        self.assertEqual(self.saldo_cpp.valor_total_pen, Decimal('1000.00000000'))
        self.assertEqual(self.saldo_cpp.cpp_pen, Decimal('10.00000000'))

    def test_a02_usuario_rol_no_admin_restringido_en_escrituras_sensibles(self):
        """A-02: Un usuario con rol USUARIO no puede modificar config, crear establecimientos, periodos, ni confirmar/anular documentos."""
        client = APIClient()
        client.force_authenticate(user=self.usuario_operador)
        headers = {'HTTP_X_EMPRESA_ID': str(self.empresa.id)}

        # 1. Modificar configuración de empresa -> 403
        resp_config = client.patch('/api/empresas/config/', {'tolerancia_residuo_pen': '0.99'}, format='json', **headers)
        self.assertEqual(resp_config.status_code, 403)

        # 2. Crear establecimiento -> 403
        resp_estab = client.post('/api/empresas/establecimientos/', {'codigo_sunat': '0001', 'nombre': 'SUCURSAL'}, format='json', **headers)
        self.assertEqual(resp_estab.status_code, 403)

        # 3. Crear período -> 403
        resp_per = client.post(
            '/api/empresas/periodos/',
            {'anio': 2026, 'mes': 3, 'fecha_inicio': '2026-03-01', 'fecha_fin': '2026-03-31'},
            format='json',
            **headers
        )
        self.assertEqual(resp_per.status_code, 403)

        # 4. Confirmar documento -> 403
        doc = Documento.objects.create(
            empresa=self.empresa,
            clase='COMPRA',
            periodo=self.periodo_enero,
            tercero=self.tercero,
            ruc_emisor=self.tercero.numero_documento,
            tipo_comprobante=self.tipo_factura,
            serie='F001',
            serie_normalizada='F001',
            numero='00009999',
            numero_normalizado='9999',
            fecha_emision=datetime.date(2026, 1, 20),
            moneda_codigo=self.moneda_pen,
            subtotal=Decimal('100.00'),
            igv=Decimal('18.00'),
            total=Decimal('118.00'),
            estado='BORRADOR',
            estado_revision='REVISADO',
            creado_por=self.usuario_admin,
        )
        resp_conf = client.post(f'/api/documentos/{doc.id}/confirmar/', {}, format='json', **headers)
        self.assertEqual(resp_conf.status_code, 403)

        # 5. Anular documento -> 403
        resp_anul = client.post(f'/api/documentos/{doc.id}/anular/', {'motivo': 'Prueba anulación'}, format='json', **headers)
        self.assertEqual(resp_anul.status_code, 403)

    def test_a03_config_igv_periodo_rechaza_periodo_otra_empresa(self):
        """A-03: Asignar un período de otra empresa a ConfigIgvPeriodo es rechazado."""
        empresa_b = Empresa.objects.create(
            ruc='20600000002',
            razon_social='EMPRESA B SAC',
            moneda_base_codigo=self.moneda_pen,
        )
        periodo_b = Periodo.objects.create(
            empresa=empresa_b,
            anio=2026,
            mes=1,
            orden=202601,
            fecha_inicio=datetime.date(2026, 1, 1),
            fecha_fin=datetime.date(2026, 1, 31),
            estado='ABIERTO',
        )
        client = APIClient()
        client.force_authenticate(user=self.usuario_admin)
        headers = {'HTTP_X_EMPRESA_ID': str(self.empresa.id)}

        payload = {
            'periodo': periodo_b.id,
            'metodo': 'TOTAL',
        }
        resp = client.post('/api/empresas/config-igv/', payload, format='json', **headers)
        self.assertEqual(resp.status_code, 400)

    def test_a05_operacion_incompatible_con_clase_documento_rechazada(self):
        """A-05: Un comprobante de compra no puede utilizar operaciones de SALIDA (ej. VENTA)."""
        tipo_op_venta = TipoOperacion.objects.get(codigo_interno='VENTA')
        datos_cabecera = {
            'clase': 'COMPRA',
            'periodo_id': self.periodo_enero.id,
            'tercero_id': self.tercero.id,
            'tipo_comprobante_id': self.tipo_factura.id,
            'serie': 'F001',
            'numero': '00008888',
            'fecha_emision': datetime.date(2026, 1, 15),
            'moneda_codigo': 'PEN',
        }
        detalles = [{
            'linea': 1,
            'producto_id': self.producto.id,
            'almacen_id': self.almacen.id,
            'tipo_operacion_id': tipo_op_venta.id,  # Operación SALIDA en compra
            'cantidad_original': Decimal('5'),
            'precio_unitario': Decimal('10'),
        }]
        with self.assertRaises(ValidationError) as ctx:
            crear_documento(
                empresa_id=self.empresa.id,
                usuario_id=self.usuario_admin.id,
                datos_cabecera=datos_cabecera,
                detalles_datos=detalles,
            )
        self.assertIn('detalles', str(ctx.exception))

    def test_a06_normalizacion_unificada_y_prevencion_duplicados_xml(self):
        """A-06: Comprobante registrado manualmente y luego por XML con ceros extra detecta duplicado."""
        tipo_op = TipoOperacion.objects.get(codigo_interno='COMPRA')
        # Crear documento manual con número '00000777' (normalizado a '777')
        crear_documento(
            empresa_id=self.empresa.id,
            usuario_id=self.usuario_admin.id,
            datos_cabecera={
                'clase': 'COMPRA',
                'periodo_id': self.periodo_enero.id,
                'tercero_id': self.tercero.id,
                'tipo_comprobante_id': self.tipo_factura.id,
                'serie': 'F001',
                'numero': '00000777',
                'fecha_emision': datetime.date(2026, 1, 15),
                'moneda_codigo': 'PEN',
            },
            detalles_datos=[{
                'linea': 1,
                'producto_id': self.producto.id,
                'almacen_id': self.almacen.id,
                'tipo_operacion_id': tipo_op.id,
                'cantidad_original': Decimal('1'),
                'precio_unitario': Decimal('100'),
                'igv': Decimal('18.00'),  # Bloque 3: línea gravada
            }],
        )

        # Ahora intentar importar un XML con el mismo número pero formato '00000777'
        captura = DocumentoCaptura.objects.create(
            empresa=self.empresa,
            tipo='XML',
            ruta_archivo='factura_dup.xml',
            hash_sha256='hashduplicado777',
            estado_proceso='PROCESADO',
            subido_por=self.usuario_admin,
        )
        for nombre, valor in [
            ('ruc_emisor', self.tercero.numero_documento),
            ('razon_social_emisor', self.tercero.razon_social),
            # Bloque 3: la clase se decide por el RUC receptor (la empresa activa = compra).
            ('ruc_cliente', self.empresa.ruc),
            ('serie', 'F001'),
            ('numero', '00000777'),
            ('tipo_comprobante', '01'),
            ('fecha_emision', '2026-01-15'),
            ('moneda', 'PEN'),
            ('subtotal', '100.00'),
            ('igv', '18.00'),
            ('total', '118.00'),
        ]:
            CapturaCampo.objects.create(
                documento_captura=captura,
                seccion='CABECERA',
                nombre_campo=nombre,
                valor_extraido=valor,
                confianza=Decimal('100.0000'),
            )

        CapturaCampo.objects.create(
            documento_captura=captura,
            seccion='DETALLE',
            numero_linea=1,
            nombre_campo='cantidad',
            valor_extraido='1.00',
            confianza=Decimal('100.0000'),
        )

        with self.assertRaises(ValidationError) as ctx:
            generar_borrador_desde_captura(
                captura_id=captura.id,
                empresa_id=self.empresa.id,
                usuario=self.usuario_admin,
            )
        self.assertIn('Ya existe un comprobante', str(ctx.exception))

    def test_a07_reapertura_periodo_marca_cierre_no_vigente(self):
        """A-07: Al reabrir un período cerrado, su snapshot oficial CierrePeriodo pasa a vigente=False."""
        cierre, _ = cerrar_periodo(
            empresa_id=self.empresa.id,
            periodo_id=self.periodo_enero.id,
            usuario=self.usuario_admin,
        )
        self.assertTrue(cierre.vigente)

        reabrir_periodo(
            empresa_id=self.empresa.id,
            periodo_id=self.periodo_enero.id,
            usuario=self.usuario_admin,
            motivo='Corrección tributaria auditoría',
        )
        cierre.refresh_from_db()
        self.assertFalse(cierre.vigente)

    def test_a07_formato131_incluye_producto_con_stock_sin_movimientos(self):
        """A-07: Un producto con saldo físico previo debe figurar en el Formato 13.1 aunque no tenga movimientos en el mes."""
        prod2 = Producto.objects.create(
            empresa=self.empresa,
            codigo_interno='PROD-SIN-MOV',
            descripcion='Producto Stock Estático',
            tipo_existencia_codigo=self.tipo_existencia,
        )
        ProductoUnidad.objects.create(
            producto=prod2,
            unidad_codigo=self.und_base,
            factor_a_base=Decimal('1.00000000'),
            es_base=True,
        )
        # Crear saldo en enero previo a febrero
        SaldoCppActual.objects.create(
            empresa=self.empresa,
            producto=prod2,
            cantidad_total=Decimal('50.00000000'),
            valor_total_pen=Decimal('500.00000000'),
            cpp_pen=Decimal('10.00000000'),
        )
        StockAlmacen.objects.create(
            empresa=self.empresa,
            almacen=self.almacen,
            producto=prod2,
            cantidad_actual=Decimal('50.00000000'),
        )
        # Movimiento de entrada en enero
        tipo_op = TipoOperacion.objects.get(codigo_interno='SALDO_INICIAL')
        mov = Movimiento.objects.create(
            empresa=self.empresa,
            producto=prod2,
            almacen=self.almacen,
            periodo=self.periodo_enero,
            tipo_operacion=tipo_op,
            fecha_movimiento=datetime.date(2026, 1, 1),
            prioridad_dia=1,
            secuencia=1,
            naturaleza='ENTRADA',
            cantidad_base=Decimal('50.00000000'),
        )
        ValorizacionMovimiento.objects.create(
            movimiento=mov,
            costo_unitario_pen=Decimal('10.00000000'),
            valor_movimiento_pen=Decimal('500.00000000'),
            saldo_cantidad_empresa=Decimal('50.00000000'),
            saldo_valor_empresa=Decimal('500.00000000'),
            cpp_empresa=Decimal('10.00000000'),
        )

        # Generar Formato 13.1 para FEBRERO (en febrero no hay movimientos de prod2)
        resultado = generar_formato_131(
            empresa_id=self.empresa.id,
            periodo_id=self.periodo_febrero.id,
        )
        codigos_reportados = [r['cabecera']['codigo_existencia'] for r in resultado['reportes']]
        self.assertIn('PROD-SIN-MOV', codigos_reportados)

        reporte_prod2 = next(r for r in resultado['reportes'] if r['cabecera']['codigo_existencia'] == 'PROD-SIN-MOV')
        self.assertEqual(reporte_prod2['saldo_inicial'], '50.00000000')
        self.assertEqual(len(reporte_prod2['movimientos']), 0)
        self.assertEqual(reporte_prod2['saldo_final']['cantidad'], '50.00000000')
