"""
Bloque 3 — NC (devolución de venta) del mismo día que la venta.

La devolución es ENTRADA (prioridad 2) y queda ordenada ANTES que su venta (SALIDA,
prioridad 4). En el recálculo retroactivo tomaba el costo precargado (viejo) de la
venta: devolución y venta quedaban con costos distintos y aparecía un residuo.
Ahora el recálculo resuelve la dependencia causal (devolución → venta) por pasadas
sucesivas sin alterar el orden oficial.
"""
from decimal import Decimal

from django.test import TestCase

from apps.documentos.models import Documento, DocumentoDetalle
from apps.kardex.models import Incidencia, Movimiento
from apps.kardex.tests_con003_005_recalculo import RecalculoBase

ORDEN = ('fecha_movimiento', 'prioridad_dia', 'secuencia', 'id')


class NcMismoDiaTests(RecalculoBase, TestCase):

    def venta(self, cantidad, fecha='2026-01-12'):
        return self.documento_confirmado('VENTA', [self.linea('VENTA', cantidad, '30')], fecha=fecha)

    def nc(self, venta_id, cantidad, fecha='2026-01-12'):
        detalle = DocumentoDetalle.objects.get(documento_id=venta_id)
        return self.documento_confirmado(
            'VENTA', [self.linea('DEVOLUCION_VENTA', cantidad, '30', detalle_origen=detalle.id)],
            tipo=self.nota_credito, origen=Documento.objects.get(pk=venta_id), fecha=fecha,
        )

    def assert_sin_residuos_ni_incidencias(self):
        self.assertFalse(self.movimientos().filter(tipo_operacion__codigo_interno='RESIDUO_AUTOMATICO').exists())
        self.assertFalse(Incidencia.objects.filter(
            empresa=self.empresa, tipo__in=('RESIDUO_VALORIZACION', 'RECALCULO_DEPENDENCIA_SIN_CONVERGER'),
        ).exists())

    def test_orden_oficial_se_conserva(self):
        self.compra_confirmada('10', '10', fecha='2026-01-10')
        venta = self.venta('6')
        nc = self.nc(venta, '2')
        orden = list(self.movimientos().order_by(*ORDEN).values_list('id', flat=True))
        self.assertLess(orden.index(self.mov_de(nc).id), orden.index(self.mov_de(venta).id))

    def test_compra_retroactiva_con_nc_del_mismo_dia(self):
        self.compra_confirmada('10', '10', fecha='2026-01-10')
        venta = self.venta('6')
        nc = self.nc(venta, '2')
        self.assertEqual(self.costo(self.mov_de(nc)), self.costo(self.mov_de(venta)))

        self.compra_confirmada('10', '20', fecha='2026-01-05')  # CPP de la venta → 15

        mov_venta, mov_nc = self.mov_de(venta), self.mov_de(nc)
        self.assertEqual(self.costo(mov_venta), Decimal('15.00000000'))
        self.assertEqual(self.costo(mov_nc), self.costo(mov_venta))
        self.assertEqual(self.valor(mov_nc), Decimal('30.00000000'))
        saldo = self.saldo()
        self.assertEqual(saldo.cantidad_total, Decimal('16.00000000'))
        self.assertEqual(saldo.valor_total_pen, Decimal('240.00000000'))  # 300 + 30 − 90
        self.assert_saldo_coherente()
        self.assert_sin_residuos_ni_incidencias()

    def test_dependencia_circular_converge_al_costo_exacto_de_la_venta(self):
        # El costo de la venta depende del valor de la NC (entra antes) y viceversa.
        self.compra_confirmada('10', '10', fecha='2026-01-10')
        self.compra_confirmada('4', '40', fecha='2026-01-12')
        venta = self.venta('6')
        nc = self.nc(venta, '2')
        self.compra_confirmada('6', '25', fecha='2026-01-05')  # retroactiva

        mov_venta, mov_nc = self.mov_de(venta), self.mov_de(nc)
        self.assertEqual(self.costo(mov_nc), self.costo(mov_venta))
        # c = (150 + 100 + 160 + 2c) / 22  →  c = 410 / 20 = 20.5
        self.assertEqual(self.costo(mov_venta), Decimal('20.50000000'))
        saldo = self.saldo()
        self.assertEqual(saldo.cantidad_total, Decimal('16.00000000'))
        self.assertEqual(saldo.valor_total_pen, Decimal('328.00000000'))  # 410 + 41 − 123
        self.assert_saldo_coherente()
        self.assert_sin_residuos_ni_incidencias()

    def test_varias_ventas_y_nc_el_mismo_dia(self):
        self.compra_confirmada('20', '10', fecha='2026-01-10')
        venta1 = self.venta('5')
        venta2 = self.venta('8')
        nc1 = self.nc(venta1, '2')
        nc2 = self.nc(venta2, '3')
        self.compra_confirmada('10', '25', fecha='2026-01-05')  # CPP → 15

        for venta, nc in ((venta1, nc1), (venta2, nc2)):
            self.assertEqual(self.costo(self.mov_de(venta)), Decimal('15.00000000'))
            self.assertEqual(self.costo(self.mov_de(nc)), self.costo(self.mov_de(venta)))
        saldo = self.saldo()
        self.assertEqual(saldo.cantidad_total, Decimal('22.00000000'))  # 30 + 5 − 13
        self.assertEqual(saldo.valor_total_pen, Decimal('330.00000000'))
        self.assert_saldo_coherente()
        self.assert_sin_residuos_ni_incidencias()

    def test_devolucion_total_del_mismo_dia_deja_saldo_sin_residuo(self):
        self.compra_confirmada('3', '10', fecha='2026-01-10')
        venta = self.venta('3')
        nc = self.nc(venta, '3')
        self.compra_confirmada('3', '11', fecha='2026-01-05')  # CPP → 10.5

        self.assertEqual(self.costo(self.mov_de(nc)), self.costo(self.mov_de(venta)))
        saldo = self.saldo()
        self.assertEqual(saldo.cantidad_total, Decimal('6.00000000'))
        self.assertEqual(saldo.valor_total_pen, Decimal('63.00000000'))
        self.assert_saldo_coherente()
        self.assert_sin_residuos_ni_incidencias()

    def test_nc_de_venta_de_otro_dia_no_cambia(self):
        self.compra_confirmada('10', '10', fecha='2026-01-10')
        venta = self.venta('6')
        nc = self.nc(venta, '2', fecha='2026-01-15')
        self.compra_confirmada('10', '20', fecha='2026-01-05')
        self.assertEqual(self.costo(self.mov_de(nc)), Decimal('15.00000000'))
        self.assertEqual(Movimiento.objects.filter(empresa=self.empresa).count(), 4)
        self.assert_saldo_coherente()
