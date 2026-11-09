"""
Bloque 4 — el RESIDUO_AUTOMATICO creado al confirmar se guardaba con secuencia 0 y
quedaba antes de los ajustes (prioridad 3) ya registrados ese día. Ahora toma la
siguiente secuencia de prioridad 3, igual que el residuo creado por un recálculo.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.documentos.models import Documento, DocumentoDetalle
from apps.kardex.models import Movimiento, ValorizacionMovimiento
from apps.kardex.services import ejecutar_recalculo_producto

ORDEN = ('fecha_movimiento', 'prioridad_dia', 'secuencia', 'id')
D = Decimal


class ResiduoSecuenciaTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()
        # 1 × 1.00 + 2 × 0.50 = 2.00 / 3 u. → CPP 0.666667: vender 3 deja −0.000001.
        self.compra = self.compra_confirmada('1', '1', fecha='2026-01-08')
        self.compra_confirmada('2', '0.5', fecha='2026-01-09')

    def residuos(self):
        return self.movimientos().filter(tipo_operacion__codigo_interno='RESIDUO_AUTOMATICO')

    def orden(self):
        return list(self.movimientos().order_by(*ORDEN).values_list('id', 'prioridad_dia', 'secuencia'))

    def foto(self):
        return [
            (v.movimiento_id, v.costo_unitario_pen, v.valor_movimiento_pen, v.saldo_cantidad_empresa, v.saldo_valor_empresa)
            for v in ValorizacionMovimiento.objects.filter(movimiento__producto=self.producto)
            .order_by(*(f'movimiento__{c}' for c in ORDEN))
        ]

    def ajuste_mismo_dia(self):
        detalle = DocumentoDetalle.objects.get(documento_id=self.compra)
        return self.documento_confirmado(
            'COMPRA', [self.linea('NC_DESCUENTO_COMPRA', '1', '0.30', detalle_origen=detalle.id)],
            tipo=self.nota_credito, origen=Documento.objects.get(pk=self.compra), fecha='2026-01-12',
        )

    def test_residuo_con_secuencia_valida_y_posicion_determinista(self):
        nc = self.ajuste_mismo_dia()  # prioridad 3, mismo día que la venta
        venta = self.documento_confirmado('VENTA', [self.linea('VENTA', '3', '30')], fecha='2026-01-12')
        residuo = self.residuos().get()
        ajuste = Movimiento.objects.get(documento_detalle__documento_id=nc)
        salida = Movimiento.objects.get(documento_detalle__documento_id=venta)
        self.assertEqual(residuo.prioridad_dia, 3)
        self.assertGreater(residuo.secuencia, ajuste.secuencia)  # antes: 0, delante del ajuste
        ids = [m[0] for m in self.orden()]
        self.assertLess(ids.index(ajuste.id), ids.index(residuo.id))
        self.assertLess(ids.index(residuo.id), ids.index(salida.id))  # CON-005: antes de la salida que lo origina
        # Secuencias únicas por (fecha, prioridad).
        claves = list(self.movimientos().values_list('fecha_movimiento', 'prioridad_dia', 'secuencia'))
        self.assertEqual(len(claves), len(set(claves)))

    def test_residuo_queda_despues_del_ajuste_que_lo_provoca(self):
        self.documento_confirmado('VENTA', [self.linea('VENTA', '3', '30')], fecha='2026-01-11')
        detalle = DocumentoDetalle.objects.get(documento_id=self.compra)
        nc = self.documento_confirmado(  # con cantidad 0, un ajuste de −0.01 deja un residuo
            'COMPRA', [self.linea('NC_DESCUENTO_COMPRA', '1', '0.01', detalle_origen=detalle.id)],
            tipo=self.nota_credito, origen=Documento.objects.get(pk=self.compra), fecha='2026-01-12',
        )
        ajuste = Movimiento.objects.get(documento_detalle__documento_id=nc)
        residuo = self.residuos().get(fecha_movimiento=date(2026, 1, 12))
        self.assertEqual((residuo.prioridad_dia, residuo.secuencia), (3, ajuste.secuencia + 1))
        ids = [m[0] for m in self.orden()]
        self.assertLess(ids.index(ajuste.id), ids.index(residuo.id))
        self.assertEqual(self.saldo().valor_total_pen, D('0'))

    def test_recalculo_reproduce_orden_y_saldos(self):
        self.ajuste_mismo_dia()
        self.documento_confirmado('VENTA', [self.linea('VENTA', '3', '30')], fecha='2026-01-12')
        self.compra_confirmada('5', '2', fecha='2026-01-12')  # más movimientos el mismo día (retroactivo → recálculo)
        self.documento_confirmado('VENTA', [self.linea('VENTA', '1', '30')], fecha='2026-01-13')
        orden, foto = self.orden(), self.foto()
        saldo = (self.saldo().cantidad_total, self.saldo().valor_total_pen)

        ejecutar_recalculo_producto(empresa_id=self.empresa.id, producto_id=self.producto.id,
                                    fecha_desde=date(2026, 1, 1), usuario_id=self.usuario.id)

        self.assertEqual(self.orden(), orden)
        self.assertEqual(self.foto(), foto)
        self.assertEqual((self.saldo().cantidad_total, self.saldo().valor_total_pen), saldo)
        self.assertTrue(all(sec >= 1 for _, prio, sec in self.orden() if prio == 3))
