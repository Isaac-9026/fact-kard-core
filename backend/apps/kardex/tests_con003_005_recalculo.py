"""
Regresión del recálculo retroactivo (ejecutar_recalculo_producto):

- CON-003: el extorno (ENTRADA) de una venta anulada conservaba el costo viejo
  aunque la venta se recalculara → residuo valorizado.
- CON-004: una devolución de venta leía la valorización precargada (vieja) de la
  venta original en lugar de su costo recalculado.
- CON-005: los RESIDUO_AUTOMATICO se re-aplicaban con su importe histórico y no se
  reevaluaba el residuo cuando la cantidad volvía a 0.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.documentos.models import Documento, DocumentoDetalle
from apps.kardex.models import Incidencia, Movimiento, ValorizacionMovimiento
from apps.kardex.services import aplicar_movimiento, ejecutar_recalculo_producto

Q8 = Decimal('0.00000001')


class RecalculoBase(Bloque2Fixture):
    def setUp(self):
        self.crear_base()

    def valor(self, movimiento):
        return ValorizacionMovimiento.objects.get(movimiento=movimiento).valor_movimiento_pen

    def costo(self, movimiento):
        return ValorizacionMovimiento.objects.get(movimiento=movimiento).costo_unitario_pen

    def mov_de(self, documento_id):
        return Movimiento.objects.get(documento_detalle__documento_id=documento_id)

    def assert_saldo_coherente(self):
        """El saldo final debe coincidir con la última valorización en el orden oficial."""
        ultimo = self.movimientos().order_by('fecha_movimiento', 'prioridad_dia', 'secuencia', 'id').last()
        val = ValorizacionMovimiento.objects.get(movimiento=ultimo)
        saldo = self.saldo()
        self.assertEqual(saldo.cantidad_total, val.saldo_cantidad_empresa)
        self.assertEqual(saldo.valor_total_pen, val.saldo_valor_empresa)
        self.assertEqual(saldo.cantidad_total, self.stock())


class ExtornoVentaTrasRecalculoTests(RecalculoBase, TestCase):
    """CON-003"""

    def test_venta_anulada_y_compra_retroactiva_neutralizan_exactamente(self):
        self.compra_confirmada('10', '10', fecha='2026-01-10')
        venta = self.documento_confirmado('VENTA', [self.linea('VENTA', '4', '30')], fecha='2026-01-12')
        self.anular(venta)
        mov_venta = self.mov_de(venta)
        extorno = Movimiento.objects.get(movimiento_extornado=mov_venta)
        self.assertEqual(self.valor(mov_venta) - self.valor(extorno), Decimal('0'))

        # Compra retroactiva ANTERIOR a la venta: cambia su CPP de 10 a 15.
        self.compra_confirmada('10', '20', fecha='2026-01-05')

        self.assertEqual(self.costo(mov_venta), Decimal('15.00000000'))
        # Venta (SALIDA) + extorno (ENTRADA) con signos: −valor_venta + valor_extorno = 0
        self.assertEqual(self.valor(extorno) - self.valor(mov_venta), Decimal('0'))
        self.assertEqual(self.costo(extorno), self.costo(mov_venta))
        saldo = self.saldo()
        self.assertEqual(saldo.cantidad_total, Decimal('20.00000000'))
        self.assertEqual(saldo.valor_total_pen, Decimal('300.00000000'))  # 100 + 200: la venta anulada no dejó residuo
        self.assertEqual(saldo.cpp_pen, Decimal('15.00000000'))
        self.assert_saldo_coherente()

    def test_extorno_de_compra_sigue_al_costo_de_la_compra(self):
        compra = self.compra_confirmada('10', '10', fecha='2026-01-10')
        self.compra_confirmada('5', '30', fecha='2026-01-20')
        self.anular(compra)
        self.compra_confirmada('10', '12', fecha='2026-01-03')

        mov_compra = self.mov_de(compra)
        extorno = Movimiento.objects.get(movimiento_extornado=mov_compra)
        self.assertEqual(self.valor(extorno), self.valor(mov_compra))
        saldo = self.saldo()
        self.assertEqual(saldo.cantidad_total, Decimal('15.00000000'))
        self.assertEqual(saldo.valor_total_pen, Decimal('270.00000000'))  # 120 + 150
        self.assert_saldo_coherente()


class DevolucionVentaTrasRecalculoTests(RecalculoBase, TestCase):
    """CON-004"""

    def test_devolucion_usa_el_costo_recalculado_de_la_venta(self):
        self.compra_confirmada('10', '10', fecha='2026-01-10')
        venta = self.documento_confirmado('VENTA', [self.linea('VENTA', '6', '30')], fecha='2026-01-12')
        detalle_venta = DocumentoDetalle.objects.get(documento_id=venta)
        nc = self.documento_confirmado(
            'VENTA', [self.linea('DEVOLUCION_VENTA', '2', '30', detalle_origen=detalle_venta.id)],
            tipo=self.nota_credito, origen=Documento.objects.get(pk=venta), fecha='2026-01-15',
        )
        self.assertEqual(self.costo(self.mov_de(nc)), Decimal('10.00000000'))

        # Compra retroactiva anterior a la venta: CPP de la venta pasa a 15.
        self.compra_confirmada('10', '20', fecha='2026-01-05')

        mov_venta, mov_nc = self.mov_de(venta), self.mov_de(nc)
        self.assertEqual(self.costo(mov_venta), Decimal('15.00000000'))
        self.assertEqual(self.costo(mov_nc), Decimal('15.00000000'))
        self.assertEqual(self.valor(mov_nc), Decimal('30.00000000'))
        saldo = self.saldo()
        self.assertEqual(saldo.cantidad_total, Decimal('16.00000000'))
        self.assertEqual(saldo.valor_total_pen, Decimal('240.00000000'))  # 300 − 90 + 30
        self.assertEqual(saldo.cpp_pen, Decimal('15.00000000'))
        self.assert_saldo_coherente()

    def test_devolucion_compra_usa_costo_de_la_compra_original(self):
        compra = self.compra_confirmada('10', '10', fecha='2026-01-10')
        detalle = DocumentoDetalle.objects.get(documento_id=compra)
        nc = self.documento_confirmado(
            'COMPRA', [self.linea('DEVOLUCION_COMPRA', '4', '10', detalle_origen=detalle.id)],
            tipo=self.nota_credito, origen=Documento.objects.get(pk=compra), fecha='2026-01-15',
        )
        self.compra_confirmada('10', '20', fecha='2026-01-05')
        self.assertEqual(self.costo(self.mov_de(nc)), Decimal('10.00000000'))
        saldo = self.saldo()
        self.assertEqual(saldo.cantidad_total, Decimal('16.00000000'))
        self.assertEqual(saldo.valor_total_pen, Decimal('260.00000000'))  # 200 + 100 − 40
        self.assert_saldo_coherente()


class ResiduoTrasRecalculoTests(RecalculoBase, TestCase):
    """CON-005: residuos de redondeo cuando la cantidad vuelve a 0."""

    def _mov(self, codigo, cantidad, fecha, costo=None, valor_ajuste=None):
        return aplicar_movimiento(
            empresa_id=self.empresa.id, producto_id=self.producto.id, almacen_id=self.almacen.id,
            periodo=self.enero, tipo_operacion=self.op[codigo], fecha=fecha,
            cantidad=Decimal(cantidad), usuario_id=self.usuario.id,
            costo_unitario=Decimal(costo) if costo is not None else None,
            valor_ajuste=Decimal(valor_ajuste) if valor_ajuste is not None else None,
        )

    def _residuos(self):
        return Movimiento.objects.filter(
            empresa=self.empresa, producto=self.producto, tipo_operacion=self.op['RESIDUO_AUTOMATICO'],
        )

    def _assert_cantidad_cero_valor_cero(self):
        saldo = self.saldo()
        self.assertEqual(saldo.cantidad_total, Decimal('0E-8'))
        self.assertEqual(saldo.valor_total_pen, Decimal('0E-8'))
        self.assert_saldo_coherente()

    def _escenario_con_residuo(self):
        # 3 u. × 3.33333333 = 9.99999999 → CPP 3.333333 → vender 3 retira 9.999999 → queda 0.00000099
        self._mov('COMPRA', '3', date(2026, 1, 10), costo='3.33333333')
        self._mov('VENTA', '3', date(2026, 1, 20))
        residuo = self._residuos().get()
        self.assertEqual(self.valor(residuo), Decimal('-0.00000099'))
        self._assert_cantidad_cero_valor_cero()
        return residuo

    def test_residuo_que_cambia_de_importe_se_recalcula(self):
        residuo = self._escenario_con_residuo()
        importe_original = self.valor(residuo)

        # Descuento retroactivo de S/ 0.50 entre la compra y la venta: cambia el residuo.
        self._mov('NC_DESCUENTO_COMPRA', '0', date(2026, 1, 15), valor_ajuste='-0.50')

        self._assert_cantidad_cero_valor_cero()
        self.assertEqual(self._residuos().count(), 1)
        self.assertNotEqual(self.valor(residuo), importe_original)

    def test_residuo_que_desaparece_se_neutraliza(self):
        residuo = self._escenario_con_residuo()
        # Una compra retroactiva hace que la venta ya no agote el stock: el residuo ya no aplica.
        self._mov('COMPRA', '1', date(2026, 1, 5), costo='4')

        saldo = self.saldo()
        self.assertEqual(saldo.cantidad_total, Decimal('1.00000000'))
        self.assertEqual(self.valor(residuo), Decimal('0E-8'))
        # Valor exacto sin residuo viejo: 4.00 + 9.99999999 − 3 × CPP(3.500000) = 3.49999999
        self.assertEqual(saldo.valor_total_pen, Decimal('3.49999999'))
        self.assert_saldo_coherente()

    def test_residuo_nuevo_por_recalculo_se_ajusta(self):
        # 2 u. × 5.00 y venta de 2 el día 26: sale exacto, sin residuo.
        self._mov('COMPRA', '2', date(2026, 1, 25), costo='5')
        self._mov('VENTA', '2', date(2026, 1, 26))
        self.assertFalse(self._residuos().exists())
        # Ajuste retroactivo de +0.00000001 el día 25: ahora la venta deja un residuo que antes no existía.
        self._mov('ND_CARGO_COMPRA', '0', date(2026, 1, 25), valor_ajuste='0.00000001')
        residuo = self._residuos().get()
        self.assertEqual(residuo.fecha_movimiento, date(2026, 1, 26))
        self.assertTrue(residuo.generado_por_motor)
        self.assertEqual(self.valor(residuo), Decimal('-0.00000001'))
        self._assert_cantidad_cero_valor_cero()

    def test_residuo_que_supera_tolerancia_genera_incidencia_bloqueante(self):
        self._escenario_con_residuo()
        # Cargo de S/ 5.00 cuando ya no hay stock: residuo mayor a la tolerancia (0.05).
        self._mov('ND_CARGO_COMPRA', '0', date(2026, 1, 25), valor_ajuste='5.00')
        self.assertTrue(
            Incidencia.objects.filter(
                empresa=self.empresa, producto=self.producto, tipo='RESIDUO_VALORIZACION',
                estado='PENDIENTE', bloquea_cierre=True,
            ).exists()
        )
        # Recalcular de nuevo no debe borrar ni duplicar la incidencia, ni inventar ajuste.
        ejecutar_recalculo_producto(
            empresa_id=self.empresa.id, producto_id=self.producto.id,
            fecha_desde=date(2026, 1, 1), usuario_id=self.usuario.id,
        )
        self.assertEqual(
            Incidencia.objects.filter(empresa=self.empresa, producto=self.producto,
                                      tipo='RESIDUO_VALORIZACION', estado='PENDIENTE').count(), 1,
        )
        self.assertEqual(self.saldo().valor_total_pen, Decimal('5.00000000'))

    def test_recalculo_completo_reproducible(self):
        self._escenario_con_residuo()
        self._mov('NC_DESCUENTO_COMPRA', '0', date(2026, 1, 15), valor_ajuste='-0.50')
        antes = list(
            ValorizacionMovimiento.objects.filter(movimiento__empresa=self.empresa)
            .order_by('movimiento_id').values_list('movimiento_id', 'valor_movimiento_pen', 'saldo_valor_empresa')
        )
        ejecutar_recalculo_producto(
            empresa_id=self.empresa.id, producto_id=self.producto.id,
            fecha_desde=date(2026, 1, 1), usuario_id=self.usuario.id,
        )
        despues = list(
            ValorizacionMovimiento.objects.filter(movimiento__empresa=self.empresa)
            .order_by('movimiento_id').values_list('movimiento_id', 'valor_movimiento_pen', 'saldo_valor_empresa')
        )
        self.assertEqual(antes, despues)
        self._assert_cantidad_cero_valor_cero()
