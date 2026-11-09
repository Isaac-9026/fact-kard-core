"""
Bloque 3 — revisión cruzada: para un producto y un período CERRADO,
saldo final Kardex = saldo final Formato 13.1 = CierrePeriodoDetalle
en cantidad, costo unitario y valor total.

Cada escenario incluye compras de 1 × 1.00 y 2 × 0.50 (CPP 0.666667 a 6 decimales) para
que cantidad × CPP difiera del valor contable real y la comparación no sea trivial.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.documentos.models import Documento, DocumentoDetalle
from apps.empresas.models import CierrePeriodoDetalle, Periodo
from apps.empresas.services import cerrar_periodo
from apps.reportes.formato131_service import generar_formato_131
from apps.reportes.services import consultar_kardex_valorizado

D = Decimal


class ConciliacionCruzadaTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()
        self.febrero = Periodo.objects.create(
            empresa=self.empresa, anio=2026, mes=2, orden=202602,
            fecha_inicio=date(2026, 2, 1), fecha_fin=date(2026, 2, 28), estado='ABIERTO',
        )

    # ---- helpers -------------------------------------------------------------

    def base_con_redondeo(self):
        self.compra_confirmada('1', '1', fecha='2026-01-08')
        return self.compra_confirmada('2', '0.5', fecha='2026-01-09')

    def venta(self, cantidad, fecha='2026-01-20'):
        return self.documento_confirmado('VENTA', [self.linea('VENTA', cantidad, '30')], fecha=fecha)

    def nota(self, clase, operacion, origen_id, cantidad, precio, fecha='2026-01-22'):
        detalle = DocumentoDetalle.objects.get(documento_id=origen_id)
        return self.documento_confirmado(
            clase, [self.linea(operacion, cantidad, precio, detalle_origen=detalle.id)],
            tipo=self.nota_credito, origen=Documento.objects.get(pk=origen_id), fecha=fecha,
        )

    def conciliar(self, esperado_cantidad, esperado_valor):
        cierre, _ = cerrar_periodo(empresa_id=self.empresa.id, periodo_id=self.enero.id, usuario=self.usuario)
        # Operaciones posteriores al cierre no deben alterar ninguna de las tres fuentes.
        self.documento_confirmado('COMPRA', [self.linea('COMPRA', '7', '13')], fecha='2026-02-03', periodo=self.febrero)

        detalle = CierrePeriodoDetalle.objects.get(cierre_periodo=cierre, producto=self.producto)
        kardex = consultar_kardex_valorizado(
            empresa_id=self.empresa.id, producto_id=self.producto.id, periodo_id=self.enero.id,
        )['resumen']
        f131 = next(
            r for r in generar_formato_131(empresa_id=self.empresa.id, periodo_id=self.enero.id)['reportes']
            if r['cabecera']['producto_id'] == self.producto.id
        )['saldo_final']

        filas = {
            'cierre': (detalle.saldo_cantidad, detalle.cpp_pen, detalle.saldo_valor_pen),
            'kardex': (kardex['saldo_final_cantidad'], kardex['cpp_final'], kardex['saldo_final_valor']),
            '13.1': (D(f131['cantidad']), D(f131['costo_unitario']), D(f131['costo_total'])),
        }
        for fuente, (cantidad, cu, valor) in filas.items():
            with self.subTest(fuente=fuente):
                self.assertEqual(cantidad, D(esperado_cantidad))
                self.assertEqual(valor, D(esperado_valor))
                self.assertEqual(cu, filas['cierre'][1])
        return filas

    # ---- escenarios ----------------------------------------------------------

    def test_1_compra_y_venta(self):
        self.base_con_redondeo()
        self.venta('2')
        # 2.00 − 2 × 0.666667 = 0.666666 (cantidad × CPP daría 0.666667)
        self.conciliar('1', '0.66666600')

    def test_2_devoluciones(self):
        compra = self.base_con_redondeo()
        venta = self.venta('2')
        self.nota('VENTA', 'DEVOLUCION_VENTA', venta, '1', '30')       # vuelve 1 × 0.666667
        self.nota('COMPRA', 'DEVOLUCION_COMPRA', compra, '1', '0.5')   # sale 1 × 0.50
        self.conciliar('1', '0.83333300')  # 0.666666 + 0.666667 − 0.50

    def test_3_ajuste_de_valor(self):
        compra = self.base_con_redondeo()
        self.nota('COMPRA', 'NC_DESCUENTO_COMPRA', compra, '1', '0.10')  # −0.10 de valor
        self.conciliar('3', '1.90000000')

    def test_4_anulacion_extorno(self):
        self.base_con_redondeo()
        venta = self.venta('2')
        self.venta('1', fecha='2026-01-21')
        self.anular(venta)
        self.conciliar('2', '1.33333300')  # 2.00 − 0.666667

    def test_5_movimiento_retroactivo_antes_del_cierre(self):
        self.compra_confirmada('1', '1', fecha='2026-01-08')
        self.venta('1', fecha='2026-01-20')
        self.compra_confirmada('2', '0.5', fecha='2026-01-05')  # retroactiva: la venta pasa a CPP 0.666667
        self.conciliar('2', '1.33333300')

    def test_periodo_siguiente_sin_movimientos_arranca_y_termina_en_el_cierre(self):
        compra = self.base_con_redondeo()
        self.nota('COMPRA', 'NC_DESCUENTO_COMPRA', compra, '1', '0.10')
        cerrar_periodo(empresa_id=self.empresa.id, periodo_id=self.enero.id, usuario=self.usuario)
        r = next(r for r in generar_formato_131(empresa_id=self.empresa.id, periodo_id=self.febrero.id)['reportes']
                 if r['cabecera']['producto_id'] == self.producto.id)
        esperado = {'cantidad': '3.00000000', 'costo_unitario': '0.63333300', 'costo_total': '1.90000000'}
        self.assertEqual(r['movimientos'], [])
        self.assertEqual(r['saldo_inicial_valorizado'], esperado)
        self.assertEqual(r['saldo_final'], esperado)  # antes: 3 × 0.633333 = 1.89999900
        kardex = consultar_kardex_valorizado(empresa_id=self.empresa.id, producto_id=self.producto.id,
                                             periodo_id=self.febrero.id)['resumen']
        self.assertEqual((kardex['saldo_inicial_valor'], kardex['saldo_final_valor']), (D('1.9'), D('1.9')))
