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
        self.assertEqual(wb.sheetnames, ['Saldo_inicial', 'Catalogo_Productos_Activos'])
        ws = wb['Saldo_inicial']
        self.assertEqual([c.value for c in ws[1]], ['Código', 'FECHA', 'Tipo de Operación', 'SALDO FINAL', None, None])
        self.assertEqual([c.value for c in ws[2]][3:], ['Cantidad', 'Costo Unitario', 'Costo Total'])
        self.assertEqual(sorted(str(r) for r in ws.merged_cells.ranges), ['A1:A2', 'B1:B2', 'C1:C2', 'D1:F1'])
        filas = [r for r in ws.iter_rows(min_row=3, values_only=True)]
        self.assertEqual([(f[0], f[2]) for f in filas], [('SKU-ACEITE', 'Saldo Anterior'), ('SKU-ARROZ', 'Saldo Anterior')])

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

        # 2. Con una fila con error no se graba nada (todo o nada)
        rechazo = self.client.post(
            url,
            {'archivo': self._crear_excel_bytes(filas), 'periodo': self.periodo.id, 'almacen': self.almacen.id,
             'modo': 'CONFIRMAR', 'auto_confirmar': 'true'},
            format='multipart', **self.headers(),
        )
        self.assertEqual(rechazo.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(SaldoInicial.objects.filter(empresa=self.empresa).count(), 0)

        # 3. Corregido el archivo, CONFIRMAR con auto_confirmar=True
        filas = filas[:2]
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
        self.assertEqual(data_conf['resumen']['omitidos_por_error'], 0)

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
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)  # nada se graba
        self.assertFalse(SaldoInicial.objects.filter(empresa=self.empresa, producto=self.prod_aceite).exists())

        # Comprobar que el saldo confirmado del arroz no fue alterado
        si_arroz = SaldoInicial.objects.get(empresa=self.empresa, producto=self.prod_arroz)
        self.assertEqual(si_arroz.cantidad, Decimal('80.00000000'))
        self.assertEqual(si_arroz.valor_pen, Decimal('1600.00000000'))
        self.assertEqual(si_arroz.estado, 'CONFIRMADO')


class ImportacionSaldosFormatoClienteTest(ImportacionSaldosInicialesExcelTest):
    """Formato del resumen de saldos del cliente: Código | FECHA | Tipo de Operación | SALDO FINAL (3 columnas)."""

    # Reutiliza el setUp de la clase base sin repetir sus pruebas.
    test_plantilla_saldos_iniciales_excel_incluye_catalogo_empresa = None
    test_importar_saldos_iniciales_previsualizar_y_confirmar_con_kardex = None
    test_importar_saldos_iniciales_rechaza_producto_ya_confirmado = None

    def setUp(self):
        super().setUp()
        self.prod_cero = Producto.objects.create(
            empresa=self.empresa, codigo_interno='011014', descripcion='PRODUCTO SIN SALDO',
            tipo_existencia_codigo=self.tipo_01, estado='ACTIVO',
        )
        self.prod_grande = Producto.objects.create(
            empresa=self.empresa, codigo_interno='021006', descripcion='PRODUCTO A GRANEL',
            tipo_existencia_codigo=self.tipo_01, estado='ACTIVO',
        )
        for p in (self.prod_cero, self.prod_grande):
            ProductoUnidad.objects.create(producto=p, unidad_codigo=self.und_kgm, factor_a_base=Decimal('1'), es_base=True)

    def excel_cliente(self, filas):
        wb = Workbook()
        ws = wb.active
        ws.title = 'Hoja2'
        ws.append(['Código', 'FECHA', 'Tipo de Operación', 'SALDO FINAL', None, None])
        ws.append([None, None, None, 'Cantidad', 'Costo Unitario', 'Costo Total'])
        for rango in ('A1:A2', 'B1:B2', 'C1:C2', 'D1:F1'):
            ws.merge_cells(rango)
        for f in filas:
            ws.append(f)
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        buf.name = 'saldos_cliente.xlsx'
        return buf

    def subir(self, archivo, modo='PREVISUALIZAR'):
        return self.client.post(
            reverse('saldo-inicial-importar-excel'),
            {'archivo': archivo, 'periodo': self.periodo.id, 'almacen': self.almacen.id, 'modo': modo, 'auto_confirmar': 'true'},
            format='multipart', **self.headers(),
        )

    def filas_reales(self):
        # Casos tomados del resumen real del cliente.
        return [
            ['SKU-ARROZ', date(2022, 12, 30), 'Saldo Anterior', 63.376, 34.77655, 2203.99904708],
            ['011014', date(2022, 7, 22), 'Saldo Anterior', 0, 0, 2.25e-06],          # saldo cero con residuo
            ['032120', date(2022, 12, 1), 'Saldo Anterior', 0, 0, -2e-07],            # cero, código que no existe
            ['021006', date(2022, 12, 31), 'Saldo Anterior', 93023.395, 2.50285, 232823.986786],  # redondeo del costo
        ]

    def test_previsualiza_el_formato_del_cliente(self):
        r = self.subir(self.excel_cliente(self.filas_reales()))
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)
        res = r.data['resumen']
        self.assertEqual((res['total_filas'], res['nuevos'], res['omitidos'], res['con_error']), (4, 2, 2, 0))
        filas = {f['codigo_interno']: f for f in r.data['filas']}
        self.assertEqual(filas['SKU-ARROZ']['numero_fila'], 3)
        self.assertEqual(filas['SKU-ARROZ']['valor_pen'], '2203.99904708')
        self.assertEqual(filas['SKU-ARROZ']['cpp_inicial'], '34.776557')
        self.assertEqual(filas['021006']['estado_fila'], 'NUEVO')
        self.assertEqual(filas['021006']['valor_pen'], '232823.98678600')
        self.assertEqual(filas['011014']['estado_fila'], 'OMITIDO')
        self.assertEqual(filas['032120']['estado_fila'], 'OMITIDO')
        self.assertEqual(res['valor_total_pen'], '235027.99')

    def test_confirma_y_omite_los_saldos_cero(self):
        r = self.subir(self.excel_cliente(self.filas_reales()), modo='CONFIRMAR')
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)
        self.assertEqual((r.data['resumen']['creados'], r.data['resumen']['omitidos']), (2, 2))
        self.assertEqual(
            set(SaldoInicial.objects.filter(empresa=self.empresa).values_list('producto__codigo_interno', 'estado')),
            {('SKU-ARROZ', 'CONFIRMADO'), ('021006', 'CONFIRMADO')},
        )
        cpp = SaldoCppActual.objects.get(empresa=self.empresa, producto=self.prod_grande)
        self.assertEqual(cpp.valor_total_pen, Decimal('232823.98678600'))

    def test_errores_reales_se_detectan(self):
        filas = [
            ['SKU-ARROZ', None, 'Saldo Anterior', 10, 5, 80],            # 10 × 5 = 50, no 80
            ['011014', None, 'Saldo Anterior', 0, 0, 25.5],              # cantidad 0 con valor
            ['SKU-ACEITE', None, 'Saldo Anterior', -3, 2, -6],
            ['NO-EXISTE', None, 'Saldo Anterior', 4, 1, 4],
        ]
        r = self.subir(self.excel_cliente(filas))
        estados = {f['codigo_interno']: f['estado_fila'] for f in r.data['filas']}
        self.assertEqual(set(estados.values()), {'ERROR'})
        self.assertEqual(r.data['resumen']['con_error'], 4)
        self.assertEqual(self.subir(self.excel_cliente(filas), modo='CONFIRMAR').status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(SaldoInicial.objects.filter(empresa=self.empresa).exists())

    def test_la_plantilla_descargada_se_vuelve_a_importar(self):
        resp = self.client.get(reverse('saldo-inicial-plantilla-excel'), **self.headers())
        wb = load_workbook(io.BytesIO(resp.content))
        ws = wb['Saldo_inicial']
        for fila in ws.iter_rows(min_row=3):
            if fila[0].value == 'SKU-ARROZ':
                fila[3].value, fila[4].value, fila[5].value = 100, 18.5, 1850
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        buf.name = 'plantilla.xlsx'
        r = self.subir(buf)
        self.assertEqual(r.status_code, status.HTTP_200_OK, r.data)
        res = r.data['resumen']
        self.assertEqual((res['nuevos'], res['omitidos'], res['con_error']), (1, 3, 0))
