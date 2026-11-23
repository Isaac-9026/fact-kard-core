from datetime import date
from decimal import Decimal

from django.urls import reverse

from apps.documentos.models import Documento, DocumentoDetalle
from apps.empresas.models import Periodo
from apps.reportes.dashboard_graficos import generar_graficos_dashboard
from apps.reportes.tests_costo_ventas import CostoVentasBase

D = Decimal


class DashboardGraficosTests(CostoVentasBase):
    def setUp(self):
        super().setUp()
        self.saldo_inicial('3', '30')
        self.compra_confirmada('100', '10', fecha='2026-01-05')
        self.venta_id = self.documento_confirmado('VENTA', [self.linea('VENTA', '53', '15')], fecha='2026-01-20')
        self.compra_confirmada('10', '12', fecha='2026-02-05', periodo=self.febrero)

    def datos(self, **kwargs):
        return generar_graficos_dashboard(empresa_id=self.empresa.id, **kwargs)

    def test_periodo_por_defecto_es_el_ultimo_con_actividad(self):
        datos = self.datos()
        self.assertEqual(datos['periodo']['id'], self.febrero.id)
        self.assertEqual([s['periodo']['etiqueta'] for s in datos['serie_mensual']], ['2026-01', '2026-02'])

    def test_serie_mensual_ventas_costo_y_margen(self):
        enero, febrero = self.datos()['serie_mensual']
        self.assertEqual(D(enero['ventas']), D('795'))
        self.assertEqual(D(enero['costo_venta']), D('530'))
        self.assertEqual(D(enero['margen']), D('265'))
        self.assertEqual(enero['margen_pct'], '33.33')
        self.assertEqual(D(enero['compras']), D('1000'))
        self.assertEqual(enero['comprobantes'], 1)
        self.assertEqual(D(febrero['ventas']), D('0'))
        self.assertEqual(D(febrero['compras']), D('120'))
        self.assertIsNone(febrero['margen_pct'])

    def test_kpis_con_variacion_frente_al_mes_anterior(self):
        kpis = self.datos()['kpis']
        self.assertEqual(D(kpis['compras']['actual']), D('120'))
        self.assertEqual(D(kpis['compras']['anterior']), D('1000'))
        self.assertEqual(kpis['compras']['variacion_pct'], '-88.00')
        self.assertEqual(kpis['ventas']['variacion_pct'], '-100.00')
        enero = self.datos(periodo_id=self.enero.id)['kpis']
        self.assertIsNone(enero['ventas']['anterior'])
        self.assertIsNone(enero['ventas']['variacion_pct'])
        self.assertEqual(enero['margen_pct'], '33.33')

    def test_mejor_mes(self):
        mejor = self.datos()['mejor_mes']
        self.assertEqual(mejor['periodo']['id'], self.enero.id)
        self.assertEqual(D(mejor['ventas']), D('795'))

    def test_productos_con_costo_de_venta_y_margen(self):
        datos = self.datos(periodo_id=self.enero.id)
        self.assertEqual(len(datos['productos']), 1)
        fila = datos['productos'][0]
        self.assertEqual(fila['producto']['id'], self.producto.id)
        self.assertEqual(D(fila['unidades']), D('53'))
        self.assertEqual(D(fila['ventas']), D('795'))
        self.assertEqual(D(fila['costo_venta']), D('530'))
        self.assertEqual(D(fila['costo_unitario']), D('10'))
        self.assertEqual(D(fila['margen']), D('265'))
        self.assertEqual(datos['participacion'], [{'nombre': self.producto.descripcion, 'ventas': fila['ventas'], 'porcentaje': '100.00'}])

    def test_nota_de_credito_resta_ventas(self):
        self.documento_confirmado(
            'VENTA', [self.linea('DEVOLUCION_VENTA', '3', '15',
                                 detalle_origen=DocumentoDetalle.objects.get(documento_id=self.venta_id).id)],
            tipo=self.nota_credito, fecha='2026-01-25', origen=Documento.objects.get(pk=self.venta_id),
        )
        enero = self.datos(periodo_id=self.enero.id)
        self.assertEqual(D(enero['kpis']['ventas']['actual']), D('750'))
        self.assertEqual(enero['kpis']['comprobantes'], 1)
        self.assertEqual(D(enero['productos'][0]['ventas']), D('750'))

    def otro_producto_con_venta(self):
        otro = self.crear_producto('P-OTRO')
        self.documento_confirmado('COMPRA', [self.linea('COMPRA', '5', '20', producto=otro)], fecha='2026-01-06')
        self.documento_confirmado('VENTA', [self.linea('VENTA', '1', '205', producto=otro)], fecha='2026-01-21')
        return otro

    def test_filtro_por_producto(self):
        self.otro_producto_con_venta()
        enero = self.datos(periodo_id=self.enero.id, producto_id=self.producto.id)
        self.assertEqual(enero['producto']['id'], self.producto.id)
        self.assertEqual(D(enero['kpis']['ventas']['actual']), D('795'))
        self.assertEqual(D(enero['kpis']['costo_venta']['actual']), D('530'))
        self.assertEqual(D(enero['kpis']['compras']['actual']), D('1000'))
        self.assertEqual(enero['kpis']['comprobantes'], 1)
        self.assertEqual([f['producto']['id'] for f in enero['productos']], [self.producto.id])
        self.assertEqual(D(enero['inventario']['valor_total']), D('620'))
        self.assertEqual(enero['inventario']['productos_con_stock'], 1)
        self.assertEqual([s['nombre'] for s in enero['participacion']], [self.producto.descripcion, 'Resto de productos'])
        self.assertEqual(enero['participacion'][0]['porcentaje'], '79.50')

    def test_sin_filtro_suma_todos_los_productos(self):
        self.otro_producto_con_venta()
        total = self.datos(periodo_id=self.enero.id)
        self.assertIsNone(total['producto'])
        self.assertEqual(D(total['kpis']['ventas']['actual']), D('1000'))
        self.assertEqual(D(total['kpis']['compras']['actual']), D('1100'))
        self.assertEqual(len(total['productos']), 2)

    def test_serie_limita_los_ultimos_meses(self):
        serie = self.datos(meses=1)['serie_mensual']
        self.assertEqual([s['periodo']['etiqueta'] for s in serie], ['2026-02'])
        serie = self.datos(periodo_id=self.enero.id)['serie_mensual']
        self.assertEqual([s['periodo']['etiqueta'] for s in serie], ['2026-01'])

    def test_inventario_por_valor_actual(self):
        inventario = self.datos()['inventario']
        self.assertEqual(D(inventario['valor_total']), D('620'))
        self.assertEqual(inventario['productos_con_stock'], 1)
        fila = inventario['top_productos'][0]
        self.assertEqual(D(fila['cantidad']), D('60'))
        self.assertEqual(D(fila['valor']), D('620'))

    def test_dias_de_stock_al_ritmo_de_venta_del_mes(self):
        fila = self.datos(periodo_id=self.enero.id)['inventario']['top_productos'][0]
        self.assertEqual(fila['dias_stock'], '35')
        fila = self.datos(periodo_id=self.febrero.id)['inventario']['top_productos'][0]
        self.assertIsNone(fila['dias_stock'])

    def test_empresa_sin_periodos(self):
        datos = generar_graficos_dashboard(empresa_id=self.otra_empresa.id)
        self.assertIsNone(datos['periodo'])
        self.assertIsNone(datos['kpis'])
        self.assertEqual(datos['serie_mensual'], [])

    def test_endpoint(self):
        resp = self.client.get(reverse('dashboard-graficos'), {'periodo_id': self.febrero.id, 'meses': 3}, **self.headers)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['moneda'], 'PEN')
        self.assertEqual(len(resp.data['serie_mensual']), 2)

    def test_validaciones(self):
        url = reverse('dashboard-graficos')
        otro = Periodo.objects.create(empresa=self.otra_empresa, anio=2026, mes=1, orden=202601,
                                      fecha_inicio=date(2026, 1, 1), fecha_fin=date(2026, 1, 31))
        for params, campo in (({'periodo_id': otro.id}, 'periodo_id'), ({'meses': 13}, 'meses'),
                              ({'meses': 0}, 'meses'), ({'periodo_id': 'x'}, 'periodo_id'),
                              ({'producto_id': 999999}, 'producto_id')):
            with self.subTest(params=params):
                resp = self.client.get(url, params, **self.headers)
                self.assertEqual(resp.status_code, 400)
                self.assertIn(campo, resp.data)

    def test_no_mezcla_empresas(self):
        resp = self.client.get(reverse('dashboard-graficos'), HTTP_X_EMPRESA_ID=str(self.otra_empresa.id))
        self.assertEqual(resp.status_code, 403)
