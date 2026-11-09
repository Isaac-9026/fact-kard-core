"""
Bloque 10 — B10-07: sin filtro de producto, el resumen del Kardex de un período solo sumaba
los productos con movimientos dentro del período. Un producto con saldo arrastrado y sin
movimientos en el período quedaba fuera de "Stock total" y "Saldo valorizado" (pantalla y
Excel). Ej.: período sin movimientos → saldo 0 aunque la empresa tenga inventario.
"""
from datetime import date
from decimal import Decimal as D

from django.test import TestCase
from django.urls import reverse

from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.empresas.models import Periodo


class SaldoEmpresaPorPeriodoTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()
        self.febrero = Periodo.objects.create(
            empresa=self.empresa, anio=2026, mes=2, orden=202602,
            fecha_inicio=date(2026, 2, 1), fecha_fin=date(2026, 2, 28), estado='ABIERTO',
        )
        self.documento_confirmado('COMPRA', [self.linea('COMPRA', '10', '10')], fecha='2026-01-10')
        self.documento_confirmado('COMPRA', [self.linea('COMPRA', '5', '20', producto=self.producto_2)], fecha='2026-01-11')

    def resumen(self, **filtros):
        resp = self.client.get(reverse('kardex-report'), filtros, **self.headers)
        self.assertEqual(resp.status_code, 200)
        return resp.data['resumen']

    def test_periodo_sin_movimientos_arrastra_el_saldo_de_la_empresa(self):
        r = self.resumen(periodo_id=self.febrero.id)
        self.assertEqual((D(r['saldo_inicial_cantidad']), D(r['saldo_inicial_valor'])), (D('15'), D('200')))
        self.assertEqual((D(r['saldo_final_cantidad']), D(r['saldo_final_valor'])), (D('15'), D('200')))
        self.assertEqual(r['total_registros'], 0)

    def test_producto_sin_movimientos_en_el_periodo_sigue_en_el_saldo(self):
        self.documento_confirmado('COMPRA', [self.linea('COMPRA', '1', '20', producto=self.producto_2)],
                                  fecha='2026-02-05', periodo=self.febrero)
        r = self.resumen(periodo_id=self.febrero.id)
        self.assertEqual((D(r['saldo_inicial_cantidad']), D(r['saldo_inicial_valor'])), (D('15'), D('200')))
        self.assertEqual((D(r['saldo_final_cantidad']), D(r['saldo_final_valor'])), (D('16'), D('220')))
        self.assertIsNone(r['cpp_final'])  # dos productos: no hay un CPP único

    def test_con_almacen_y_por_producto_sin_cambios(self):
        r = self.resumen(periodo_id=self.febrero.id, almacen_id=self.almacen.id)
        self.assertEqual(D(r['saldo_final_cantidad']), D('15'))
        r = self.resumen(periodo_id=self.febrero.id, producto_id=self.producto.id)
        self.assertEqual((D(r['saldo_final_cantidad']), D(r['saldo_final_valor']), D(r['cpp_final'])), (D('10'), D('100'), D('10')))

    def test_sin_inicio_no_cambia(self):
        r = self.resumen()
        self.assertEqual((D(r['saldo_final_cantidad']), D(r['saldo_final_valor'])), (D('15'), D('200')))
