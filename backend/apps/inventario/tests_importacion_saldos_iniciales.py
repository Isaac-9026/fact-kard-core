import io
from decimal import Decimal
from datetime import date
from django.test import TestCase
from django.urls import reverse
from openpyxl import Workbook, load_workbook
from rest_framework import status
from rest_framework.test import APIClient

from apps.catalogos.models import Moneda, TipoExistencia, TipoOperacion, UnidadMedida
from apps.empresas.models import Empresa, Establecimiento, Periodo
from apps.inventario.models import Almacen, Producto, ProductoUnidad, SaldoInicial
from apps.kardex.models import Movimiento, SaldoCppActual, StockAlmacen
from apps.usuarios.models import Usuario, UsuarioEmpresa


class ImportacionSaldosInicialesExcelTest(TestCase):
    def setUp(self):
        self.moneda = Moneda.objects.create(codigo='PEN', nombre='Soles')
        self.empresa = Empresa.objects.create(
            ruc='20601234567',
            razon_social='EMPRESA SALDOS TEST S.A.C.',
            moneda_base_codigo=self.moneda,
        )
        self.establecimiento = Establecimiento.objects.create(
            empresa=self.empresa,
            codigo_sunat='0000',
            nombre='PRINCIPAL',
        )
        self.almacen = Almacen.objects.create(
            empresa=self.empresa,
            establecimiento=self.establecimiento,
            codigo='ALM-01',
            nombre='ALMACÉN CENTRAL',
            activo=True,
        )
        self.periodo = Periodo.objects.create(
            empresa=self.empresa,
            anio=2026,
            mes=1,
            orden=202601,
            fecha_inicio=date(2026, 1, 1),
            fecha_fin=date(2026, 1, 31),
            estado='ABIERTO',
        )
        self.usuario = Usuario.objects.create(
            username='admin_saldos',
            email='admin@saldos.pe',
            password_hash='dummyhash',
        )
        UsuarioEmpresa.objects.create(
            usuario=self.usuario,
            empresa=self.empresa,
            rol='ADMIN',
        )

        self.tipo_op_saldo = TipoOperacion.objects.create(
            codigo_interno='SALDO_INICIAL',
            codigo_sunat='16',
            descripcion='SALDO INICIAL',
            naturaleza='ENTRADA',
            es_interna=True,
            afecta_kardex=True,
            origen_requerido='SALDO_INICIAL',
            activo=True,
        )

        self.tipo_01 = TipoExistencia.objects.create(codigo='01', descripcion='MERCADERIAS')
        self.und_niu = UnidadMedida.objects.create(codigo='NIU', descripcion='UNIDADES')
        self.und_kgm = UnidadMedida.objects.create(codigo='KGM', descripcion='KILOGRAMOS')

        # Productos de prueba
        self.prod_arroz = Producto.objects.create(
            empresa=self.empresa,
            codigo_interno='SKU-ARROZ',
            descripcion='ARROZ EXTRA COSTAL 50KG',
            tipo_existencia_codigo=self.tipo_01,
            estado='ACTIVO',
        )
        ProductoUnidad.objects.create(
            producto=self.prod_arroz,
            unidad_codigo=self.und_kgm,
            factor_a_base=Decimal('1.00000000'),
            es_base=True,
        )

        self.prod_aceite = Producto.objects.create(
            empresa=self.empresa,
            codigo_interno='SKU-ACEITE',
            descripcion='ACEITE VEGETAL 1 LITRO',
            tipo_existencia_codigo=self.tipo_01,
            estado='ACTIVO',
        )
        ProductoUnidad.objects.create(
            producto=self.prod_aceite,
            unidad_codigo=self.und_niu,
            factor_a_base=Decimal('1.00000000'),
            es_base=True,
        )

        self.client = APIClient()
        self.client.force_authenticate(user=self.usuario)

    def headers(self):
        return {'HTTP_X_EMPRESA_ID': str(self.empresa.id)}

    def _crear_excel_bytes(self, filas):
        wb = Workbook()
        ws = wb.active
        ws.title = 'Saldos_Iniciales'
        ws.append([
            'CODIGO_INTERNO',
            'DESCRIPCION_REFERENCIAL',
            'CANTIDAD',
            'COSTO_UNITARIO_PEN',
            'VALOR_TOTAL_PEN',
        ])
        for f in filas:
            ws.append(f)
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        buf.name = 'saldos_test.xlsx'
        return buf

    def test_plantilla_saldos_iniciales_excel_incluye_catalogo_empresa(self):
        url = reverse('saldo-inicial-plantilla-excel')
        resp = self.client.get(url, **self.headers())
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(
            resp['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )

        wb = load_workbook(io.BytesIO(resp.content))
        self.assertIn('Saldos_Iniciales', wb.sheetnames)
        self.assertIn('Catalogo_Productos_Activos', wb.sheetnames)

        ws_cat = wb['Catalogo_Productos_Activos']
        codigos = [row[0] for row in ws_cat.iter_rows(values_only=True) if row and row[0]]
        self.assertIn('SKU-ARROZ', codigos)
        self.assertIn('SKU-ACEITE', codigos)

    def test_importar_saldos_iniciales_previsualizar_y_confirmar_con_kardex(self):
        url = reverse('saldo-inicial-importar-excel')

        # 3 Filas:
        # 1. SKU-ARROZ: cantidad=100, costo_unitario=18.50 (sin valor_total explícito)
        # 2. SKU-ACEITE: cantidad=50, valor_total=410.00 (sin costo_unitario explícito)
        # 3. SKU-INEXISTENTE: debe marcarse con error
        filas = [
            ['SKU-ARROZ', 'Arroz ref', 100, 18.50, None],
            ['SKU-ACEITE', 'Aceite ref', 50, None, 410.00],
            ['SKU-INEXISTENTE', 'Producto no registrado', 10, 5.0, 50.0],
        ]
        archivo_pre = self._crear_excel_bytes(filas)

        # 1. Modo PREVISUALIZAR
        resp_pre = self.client.post(
            url,
            {
                'archivo': archivo_pre,
                'periodo': self.periodo.id,
                'almacen': self.almacen.id,
                'modo': 'PREVISUALIZAR',
            },
            format='multipart',
            **self.headers(),
        )
        self.assertEqual(resp_pre.status_code, status.HTTP_200_OK)
        data_pre = resp_pre.data
        self.assertEqual(data_pre['modo'], 'PREVISUALIZAR')
        self.assertEqual(data_pre['resumen']['total_filas'], 3)
        self.assertEqual(data_pre['resumen']['validas'], 2)
        self.assertEqual(data_pre['resumen']['nuevos'], 2)
        self.assertEqual(data_pre['resumen']['con_error'], 1)

        # Verificar que en previsualizar NO se insertó nada en la BD
        self.assertEqual(SaldoInicial.objects.filter(empresa=self.empresa).count(), 0)

        # 2. Modo CONFIRMAR con auto_confirmar=True
        archivo_conf = self._crear_excel_bytes(filas)
        resp_conf = self.client.post(
            url,
            {
                'archivo': archivo_conf,
                'periodo': self.periodo.id,
                'almacen': self.almacen.id,
                'modo': 'CONFIRMAR',
                'auto_confirmar': 'true',
            },
            format='multipart',
            **self.headers(),
        )
        self.assertEqual(resp_conf.status_code, status.HTTP_200_OK, resp_conf.data)
        data_conf = resp_conf.data
        self.assertEqual(data_conf['modo'], 'CONFIRMAR')
        self.assertEqual(data_conf['resumen']['creados'], 2)
        self.assertEqual(data_conf['resumen']['confirmados_kardex'], 2)
        self.assertEqual(data_conf['resumen']['omitidos_por_error'], 1)

        # Verificar que los 2 saldos quedaron en estado CONFIRMADO
        saldos = SaldoInicial.objects.filter(empresa=self.empresa)
        self.assertEqual(saldos.count(), 2)
        self.assertTrue(all(s.estado == 'CONFIRMADO' for s in saldos))

        # Verificar SaldoInicial de Arroz
        si_arroz = saldos.get(producto=self.prod_arroz)
        self.assertEqual(si_arroz.cantidad, Decimal('100.00000000'))
        self.assertEqual(si_arroz.valor_pen, Decimal('1850.00000000'))
        self.assertEqual(si_arroz.cpp_inicial, Decimal('18.50000000'))

        # Verificar impacto en Kardex (Movimiento Op 16)
        mov_arroz = Movimiento.objects.filter(
            empresa=self.empresa,
            producto=self.prod_arroz,
            tipo_operacion__codigo_interno='SALDO_INICIAL',
        ).first()
        self.assertIsNotNone(mov_arroz)
        self.assertEqual(mov_arroz.naturaleza, 'ENTRADA')
        self.assertEqual(mov_arroz.prioridad_dia, 1)
        self.assertEqual(mov_arroz.cantidad_base, Decimal('100.00000000'))

        # Verificar SaldoCppActual y StockAlmacen
        saldo_cpp_arroz = SaldoCppActual.objects.get(empresa=self.empresa, producto=self.prod_arroz)
        self.assertEqual(saldo_cpp_arroz.cantidad_total, Decimal('100.00000000'))
        self.assertEqual(saldo_cpp_arroz.valor_total_pen, Decimal('1850.00000000'))
        self.assertEqual(saldo_cpp_arroz.cpp_pen, Decimal('18.50000000'))

        stock_alm_arroz = StockAlmacen.objects.get(empresa=self.empresa, almacen=self.almacen, producto=self.prod_arroz)
        self.assertEqual(stock_alm_arroz.cantidad_actual, Decimal('100.00000000'))

    def test_importar_saldos_iniciales_rechaza_producto_ya_confirmado(self):
        url = reverse('saldo-inicial-importar-excel')

        # Crear y confirmar previamente un saldo inicial para el arroz
        SaldoInicial.objects.create(
            empresa=self.empresa,
            periodo=self.periodo,
            almacen=self.almacen,
            producto=self.prod_arroz,
            cantidad=Decimal('80.00000000'),
            valor_pen=Decimal('1600.00000000'),
            cpp_inicial=Decimal('20.00000000'),
            estado='CONFIRMADO',
            creado_por=self.usuario,
        )

        filas = [
            ['SKU-ARROZ', 'Intento sobreescribir confirmado', 100, 15.0, 1500.0],
            ['SKU-ACEITE', 'Aceite nuevo', 30, 8.0, 240.0],
        ]
        archivo = self._crear_excel_bytes(filas)

        resp = self.client.post(
            url,
            {
                'archivo': archivo,
                'periodo': self.periodo.id,
                'almacen': self.almacen.id,
                'modo': 'CONFIRMAR',
                'auto_confirmar': 'true',
            },
            format='multipart',
            **self.headers(),
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.data
        self.assertEqual(data['resumen']['creados'], 1)  # Solo Aceite
        self.assertEqual(data['resumen']['omitidos_por_error'], 1)  # Arroz rechazado

        # Comprobar que el saldo confirmado del arroz no fue alterado
        si_arroz = SaldoInicial.objects.get(empresa=self.empresa, producto=self.prod_arroz)
        self.assertEqual(si_arroz.cantidad, Decimal('80.00000000'))
        self.assertEqual(si_arroz.valor_pen, Decimal('1600.00000000'))
        self.assertEqual(si_arroz.estado, 'CONFIRMADO')
