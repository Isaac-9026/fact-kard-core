import io
from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from openpyxl import Workbook, load_workbook
from rest_framework import status
from rest_framework.test import APIClient

from apps.catalogos.models import Moneda, TipoExistencia, UnidadMedida
from apps.documentos.models import DocumentoCaptura
from apps.empresas.models import Empresa, Establecimiento
from apps.inventario.models import Producto, ProductoEquivalencia, ProductoUnidad, Tercero
from apps.usuarios.models import Usuario, UsuarioEmpresa


class ImportacionYAltaRapidaApiTest(TestCase):
    def setUp(self):
        self.moneda = Moneda.objects.create(codigo='PEN', nombre='Soles')
        self.empresa = Empresa.objects.create(
            ruc='20601234565',
            razon_social='EMPRESA IMPORT TEST S.A.C.',
            moneda_base_codigo=self.moneda,
        )
        self.establecimiento = Establecimiento.objects.create(
            empresa=self.empresa,
            codigo_sunat='0000',
            nombre='PRINCIPAL',
        )
        self.usuario = Usuario.objects.create(
            username='admin_import',
            email='admin@import.pe',
            password_hash='dummyhash',
        )
        UsuarioEmpresa.objects.create(
            usuario=self.usuario,
            empresa=self.empresa,
            rol='ADMIN',
        )

        # Catálogos base
        self.tipo_01 = TipoExistencia.objects.create(codigo='01', descripcion='MERCADERIAS')
        self.tipo_02 = TipoExistencia.objects.create(codigo='02', descripcion='MATERIAS PRIMAS')
        self.und_niu = UnidadMedida.objects.create(codigo='NIU', descripcion='UNIDADES')
        self.und_kgm = UnidadMedida.objects.create(codigo='KGM', descripcion='KILOGRAMOS')
        self.und_bx = UnidadMedida.objects.create(codigo='BX', descripcion='CAJAS')

        # Proveedor
        self.proveedor = Tercero.objects.create(
            empresa=self.empresa,
            tipo_documento='6',
            numero_documento='20100070970',
            razon_social='PROVEEDOR INDUSTRIAL S.A.C.',
            es_proveedor=True,
        )

        # Producto pre-existente
        self.producto_existente = Producto.objects.create(
            empresa=self.empresa,
            codigo_interno='SKU-EXISTENTE-01',
            descripcion='PRODUCTO YA REGISTRADO',
            tipo_existencia_codigo=self.tipo_01,
            afectacion_igv_defecto='GRAVADO',
            precio_venta_sugerido=Decimal('50.00000000'),
        )
        self.pu_existente = ProductoUnidad.objects.create(
            producto=self.producto_existente,
            unidad_codigo=self.und_niu,
            factor_a_base=Decimal('1.00000000'),
            es_base=True,
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.usuario)

    def headers(self):
        return {'HTTP_X_EMPRESA_ID': str(self.empresa.id)}

    def test_alta_rapida_crea_producto_unidad_y_equivalencia(self):
        """
        PARTE 1: Verifica que en 1 sola petición POST a /api/v1/inventario/equivalencias/alta-rapida/
        se crea el Producto (con código autogenerado PROD-0001), su ProductoUnidad base
        (es_base=True) y la ProductoEquivalencia confirmada y activa.
        """
        url = reverse('producto-equivalencia-alta-rapida')
        payload = {
            'tercero': self.proveedor.id,
            'codigo_interno': '',  # Debe autogenerar PROD-0001
            'descripcion': 'PAPEL FOTOCOPIA A4 75GR',
            'tipo_existencia_codigo': '01',
            'unidad_base_codigo': 'NIU',
            'afectacion_igv_defecto': 'GRAVADO',
            'precio_venta_sugerido': '18.50',
            'codigo_externo': 'EXT-SKU-99',
            'descripcion_externa': 'RESMA PAPEL A4',
            'unidad_externa_codigo': 'BX',
            'factor_conversion': '10.00000000',
        }

        resp = self.client.post(url, payload, format='json', **self.headers())
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)

        # 1. Comprobar que Producto se creó con código autogenerado
        prod_data = resp.data['producto']
        self.assertEqual(prod_data['codigo_interno'], 'PROD-0001')
        self.assertEqual(prod_data['descripcion'], 'PAPEL FOTOCOPIA A4 75GR')
        self.assertEqual(prod_data['afectacion_igv_defecto'], 'GRAVADO')

        producto_db = Producto.objects.get(empresa=self.empresa, codigo_interno='PROD-0001')
        self.assertEqual(producto_db.descripcion, 'PAPEL FOTOCOPIA A4 75GR')

        # 2. Comprobar que ProductoUnidad base se creó
        pu_base = ProductoUnidad.objects.filter(producto=producto_db, es_base=True).first()
        self.assertIsNotNone(pu_base)
        self.assertEqual(pu_base.unidad_codigo_id, 'NIU')
        self.assertEqual(pu_base.factor_a_base, Decimal('1.00000000'))

        # 3. Comprobar que ProductoEquivalencia se creó
        equiv_db = ProductoEquivalencia.objects.filter(
            empresa=self.empresa,
            tercero=self.proveedor,
            codigo_externo='EXT-SKU-99',
        ).first()
        self.assertIsNotNone(equiv_db)
        self.assertTrue(equiv_db.activa)
        self.assertEqual(equiv_db.producto_unidad_id, pu_base.id)
        self.assertEqual(equiv_db.factor_conversion, Decimal('10.00000000'))
        self.assertEqual(equiv_db.confirmado_por, self.usuario)

    def test_alta_rapida_con_captura_auto_crea_proveedor(self):
        """
        Verifica que enviando solo 'captura' y sin 'tercero', alta-rápida determine o cree
        al proveedor y asocie la equivalencia.
        """
        from apps.documentos.models import CapturaCampo

        captura = DocumentoCaptura.objects.create(
            empresa=self.empresa,
            tipo='XML',
            ruta_archivo='facturas/2026/11/factura_test.xml',
            estado_proceso='PENDIENTE',
        )
        CapturaCampo.objects.create(
            documento_captura=captura,
            seccion='CABECERA',
            nombre_campo='tipo_comprobante',
            valor_extraido='01',
        )
        CapturaCampo.objects.create(
            documento_captura=captura,
            seccion='CABECERA',
            nombre_campo='ruc_emisor',
            valor_extraido='20555666777',
        )
        CapturaCampo.objects.create(
            documento_captura=captura,
            seccion='CABECERA',
            nombre_campo='razon_social_emisor',
            valor_extraido='NUEVO PROVEEDOR DETECTADO S.A.C.',
        )
        CapturaCampo.objects.create(
            documento_captura=captura,
            seccion='CABECERA',
            nombre_campo='ruc_cliente',
            valor_extraido=self.empresa.ruc,
        )
        url = reverse('producto-equivalencia-alta-rapida')
        payload = {
            'captura': captura.id,
            'codigo_interno': 'PROD-MANUAL-01',
            'descripcion': 'CABLE RED CAT6 UTP',
            'codigo_externo': 'CABLE-C6',
        }

        resp = self.client.post(url, payload, format='json', **self.headers())
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED, resp.data)

        # Proveedor debió crearse automáticamente con RUC 20555666777
        prov_creado = Tercero.objects.filter(empresa=self.empresa, numero_documento='20555666777').first()
        self.assertIsNotNone(prov_creado)
        self.assertEqual(prov_creado.razon_social, 'NUEVO PROVEEDOR DETECTADO S.A.C.')

        # Equivalencia debe apuntar al proveedor creado
        equiv = ProductoEquivalencia.objects.filter(empresa=self.empresa, tercero=prov_creado).first()
        self.assertIsNotNone(equiv)
        self.assertEqual(equiv.codigo_externo, 'CABLE-C6')

    def test_descargar_plantilla_productos_excel(self):
        """
        PARTE 2: Verifica que GET /api/v1/inventario/productos/plantilla-excel/
        retorna 200 OK y un archivo Excel válido con las hojas 'Productos' y 'Catalogos_SUNAT'.
        """
        url = reverse('producto-plantilla-excel')
        resp = self.client.get(url, **self.headers())
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(
            resp['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )

        wb = load_workbook(io.BytesIO(resp.content))
        self.assertIn('Productos', wb.sheetnames)
        self.assertIn('Catalogos_SUNAT', wb.sheetnames)

        ws_prod = wb['Productos']
        headers = [cell.value for cell in ws_prod[1]]
        self.assertEqual(headers[0], 'CODIGO_INTERNO')
        self.assertEqual(headers[1], 'DESCRIPCION')
        self.assertEqual(headers[2], 'TIPO_EXISTENCIA_CODIGO')
        self.assertEqual(headers[3], 'UNIDAD_BASE_CODIGO')

        ws_cat = wb['Catalogos_SUNAT']
        self.assertIn('TABLA 5', str(ws_cat['A1'].value))

    def test_importar_productos_excel_previsualizar_y_confirmar(self):
        """
        PARTE 2: Crea un Excel en memoria con:
          - Fila 1: encabezados
          - Fila 2: producto nuevo con sinónimos ('UND' -> 'NIU', 'MERCADERIA' -> '01', '10' -> 'GRAVADO')
          - Fila 3: producto existente a actualizar
          - Fila 4: producto con error (unidad inexistente)
        Verifica PREVISUALIZAR (no guarda) y luego CONFIRMAR (ejecuta atómicamente).
        """
        wb = Workbook()
        ws = wb.active
        ws.title = 'Productos'

        ws.append([
            'CODIGO_INTERNO',
            'DESCRIPCION',
            'TIPO_EXISTENCIA_CODIGO',
            'UNIDAD_BASE_CODIGO',
            'AFECTACION_IGV',
            'PRECIO_VENTA_SUGERIDO',
        ])
        # Fila 2: NUEVO con sinónimos
        ws.append(['', 'ACEITE VEGETAL 1L', 'MERCADERIA', 'UND', '10', '9.50'])
        # Fila 3: ACTUALIZAR producto existente
        ws.append(['SKU-EXISTENTE-01', 'PRODUCTO ACTUALIZADO DESCRIPCION', '01', 'NIU', 'EXONERADO', '55.00'])
        # Fila 4: ERROR (unidad inválida)
        ws.append(['PROD-ERR', 'PRODUCTO CON UNIDAD RARA', '01', 'UNIDAD_INEXISTENTE_99', 'GRAVADO', '10'])

        excel_io = io.BytesIO()
        wb.save(excel_io)
        excel_io.seek(0)

        url = reverse('producto-importar-excel')

        # 1. MODO PREVISUALIZAR
        excel_io.name = 'test_import.xlsx'
        resp_prev = self.client.post(
            url,
            {'archivo': excel_io, 'modo': 'PREVISUALIZAR'},
            format='multipart',
            **self.headers(),
        )
        self.assertEqual(resp_prev.status_code, status.HTTP_200_OK, resp_prev.data)
        self.assertEqual(resp_prev.data['total_filas'], 3)
        self.assertEqual(resp_prev.data['nuevos'], 1)
        self.assertEqual(resp_prev.data['actualizables'], 1)
        self.assertEqual(resp_prev.data['errores'], 1)

        # En modo previsualizar, el producto nuevo NO debe existir en la BD todavía
        self.assertFalse(Producto.objects.filter(descripcion='ACEITE VEGETAL 1L').exists())

        # 2. MODO CONFIRMAR
        excel_io.seek(0)
        resp_conf = self.client.post(
            url,
            {'archivo': excel_io, 'modo': 'CONFIRMAR'},
            format='multipart',
            **self.headers(),
        )
        self.assertEqual(resp_conf.status_code, status.HTTP_200_OK, resp_conf.data)
        self.assertEqual(resp_conf.data['creados'], 1)
        self.assertEqual(resp_conf.data['actualizados'], 1)
        self.assertEqual(resp_conf.data['omitidos_por_error'], 1)

        # Comprobar que en BD el producto nuevo se creó con su unidad base
        nuevo_prod = Producto.objects.filter(descripcion='ACEITE VEGETAL 1L').first()
        self.assertIsNotNone(nuevo_prod)
        self.assertEqual(nuevo_prod.tipo_existencia_codigo_id, '01')
        self.assertEqual(nuevo_prod.afectacion_igv_defecto, 'GRAVADO')
        self.assertEqual(nuevo_prod.precio_venta_sugerido, Decimal('9.50'))

        pu_nuevo = ProductoUnidad.objects.filter(producto=nuevo_prod, es_base=True).first()
        self.assertIsNotNone(pu_nuevo)
        self.assertEqual(pu_nuevo.unidad_codigo_id, 'NIU')

        # Comprobar que el producto existente se actualizó
        self.producto_existente.refresh_from_db()
        self.assertEqual(self.producto_existente.descripcion, 'PRODUCTO ACTUALIZADO DESCRIPCION')
        self.assertEqual(self.producto_existente.afectacion_igv_defecto, 'EXONERADO')
        self.assertEqual(self.producto_existente.precio_venta_sugerido, Decimal('55.00'))
