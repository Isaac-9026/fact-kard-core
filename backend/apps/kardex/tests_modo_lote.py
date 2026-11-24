"""
Modo lote del Kardex (importación Excel): los recálculos de movimientos retroactivos se difieren y
se ejecutan una sola vez por producto al final. El resultado debe ser idéntico al flujo uno a uno.
"""
from decimal import Decimal

from django.db import transaction
from django.test import TestCase
from rest_framework.exceptions import ValidationError

from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.kardex.models import Movimiento, Recalculo, SaldoCppActual
from apps.kardex.services import _pendientes_lote, modo_lote_kardex


class _Rollback(Exception):
    pass


class ModoLoteKardexTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()
        # Historia posterior: todo lo que se registre antes del 20/01 es retroactivo.
        self.compra_confirmada('10', '10', fecha='2026-01-20')
        self.documento_confirmado('VENTA', [self.linea('VENTA', '5', '15')], fecha='2026-01-25')

    def retroactivos(self):
        self.compra_confirmada('4', '20', fecha='2026-01-05')
        self.documento_confirmado('VENTA', [self.linea('VENTA', '2', '30')], fecha='2026-01-06')
        self.compra_confirmada('3', '15', fecha='2026-01-08')
        venta = self.documento_confirmado('VENTA', [self.linea('VENTA', '1', '30')], fecha='2026-01-09')
        self.anular(venta)

    def foto(self):
        saldo = SaldoCppActual.objects.get(empresa=self.empresa, producto=self.producto)
        movimientos = [
            (m.fecha_movimiento, m.naturaleza, m.cantidad_base, m.es_extorno, m.valorizacion.costo_unitario_pen,
             m.valorizacion.valor_movimiento_pen, m.valorizacion.saldo_cantidad_empresa, m.valorizacion.saldo_valor_empresa)
            for m in Movimiento.objects.filter(empresa=self.empresa, producto=self.producto, generado_por_motor=False)
            .select_related('valorizacion').order_by('fecha_movimiento', 'prioridad_dia', 'secuencia', 'id')
        ]
        return (saldo.cantidad_total, saldo.valor_total_pen, saldo.cpp_pen, self.stock(), movimientos)

    def test_mismo_resultado_que_uno_a_uno_con_un_solo_recalculo(self):
        antes = Recalculo.objects.count()
        try:
            with transaction.atomic():
                self.retroactivos()
                uno_a_uno = self.foto()
                recalculos_uno_a_uno = Recalculo.objects.count() - antes
                raise _Rollback
        except _Rollback:
            pass
        with transaction.atomic(), modo_lote_kardex(empresa_id=self.empresa.id, usuario_id=self.usuario.id):
            self.retroactivos()
            self.assertEqual(Recalculo.objects.count(), antes)
        self.assertEqual(self.foto(), uno_a_uno)
        self.assertEqual(Recalculo.objects.count() - antes, 1)
        self.assertGreater(recalculos_uno_a_uno, 1)
        self.assertEqual(self.foto()[0], Decimal('10'))

    def test_el_estado_se_limpia_aunque_falle(self):
        with self.assertRaises(ValueError):
            with transaction.atomic(), modo_lote_kardex(empresa_id=self.empresa.id):
                self.assertEqual(_pendientes_lote(), {})
                raise ValueError('falla')
        self.assertIsNone(_pendientes_lote())
        self.compra_confirmada('1', '10', fecha='2026-01-03')
        self.assertTrue(Recalculo.objects.exists())

    def test_no_admite_anidar(self):
        with transaction.atomic(), modo_lote_kardex(empresa_id=self.empresa.id):
            with self.assertRaises(RuntimeError):
                with modo_lote_kardex(empresa_id=self.empresa.id):
                    pass
        self.assertIsNone(_pendientes_lote())

    def test_stock_negativo_posterior_revierte_todo(self):
        movimientos = Movimiento.objects.count()
        with self.assertRaisesMessage(ValidationError, 'deja stock negativo'):
            with transaction.atomic(), modo_lote_kardex(empresa_id=self.empresa.id):
                # Venta del 10/01 con stock actual suficiente (5), pero antes de la compra del 20/01:
                # en su fecha el stock queda en −5.
                self.documento_confirmado('VENTA', [self.linea('VENTA', '5', '30')], fecha='2026-01-10')
        self.assertEqual(Movimiento.objects.count(), movimientos)
        self.assertIsNone(_pendientes_lote())
