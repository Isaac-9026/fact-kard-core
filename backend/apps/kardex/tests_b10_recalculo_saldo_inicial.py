"""
Bloque 10 — B10-04: un recálculo que incluye el movimiento de SALDO_INICIAL fallaba con
AttributeError ('SaldoInicial' no tiene 'valor_total_pen'; el campo es 'valor_pen').
Pasaba al recalcular desde el primer día del período o al confirmar un documento con la
fecha del saldo inicial cuando ya existían movimientos posteriores.
"""
import datetime
from decimal import Decimal

from django.test import TestCase

from apps.catalogos.models import TipoOperacion
from apps.empresas.models import Periodo
from apps.inventario.models import Producto, SaldoInicial
from apps.inventario.services import confirmar_saldo_inicial
from apps.kardex.models import Movimiento, SaldoCppActual
from apps.kardex.services import aplicar_movimiento, ejecutar_recalculo_producto
from apps.kardex import tests_motor_m1_m6


class RecalculoIncluyeSaldoInicialTest(TestCase):
    setUp = tests_motor_m1_m6.MotorM1M6Test.setUp  # misma base de datos de prueba del motor, sin repetir sus tests

    def _preparar(self):
        self.octubre = Periodo.objects.create(
            empresa=self.empresa, anio=2026, mes=10, orden=202610,
            fecha_inicio=datetime.date(2026, 10, 1), fecha_fin=datetime.date(2026, 10, 31), estado='ABIERTO',
        )
        self.prod = Producto.objects.create(
            empresa=self.empresa, codigo_interno='B10-SI', descripcion='Recálculo con saldo inicial',
            tipo_existencia_codigo=self.producto.tipo_existencia_codigo,
        )
        si = SaldoInicial.objects.create(
            empresa=self.empresa, periodo=self.octubre, almacen=self.origen, producto=self.prod,
            cantidad=Decimal('100.00000000'), valor_pen=Decimal('1000.00000000'),
            cpp_inicial=Decimal('10.00000000'), creado_por=self.usuario,
        )
        confirmar_saldo_inicial(saldo_id=si.id, empresa_id=self.empresa.id, usuario=self.usuario)
        self.mov_si = Movimiento.objects.get(saldo_inicial=si)
        self.compra_op = TipoOperacion.objects.get(codigo_interno='COMPRA')

    def _compra(self, dia, cantidad, costo):
        return aplicar_movimiento(
            empresa_id=self.empresa.id, producto_id=self.prod.id, almacen_id=self.origen.id,
            periodo=self.octubre, tipo_operacion=self.compra_op, fecha=datetime.date(2026, 10, dia),
            cantidad=Decimal(cantidad), costo_unitario=Decimal(costo), usuario_id=self.usuario.id,
        )

    def test_recalculo_desde_el_saldo_inicial_conserva_su_valor(self):
        self._preparar()
        self._compra(21, '10', '11')
        ejecutar_recalculo_producto(
            empresa_id=self.empresa.id, producto_id=self.prod.id,
            fecha_desde=datetime.date(2026, 10, 1), usuario_id=self.usuario.id,
        )
        self.mov_si.valorizacion.refresh_from_db()
        self.assertEqual(self.mov_si.valorizacion.valor_movimiento_pen, Decimal('1000.00000000'))
        self.assertEqual(self.mov_si.valorizacion.costo_unitario_pen, Decimal('10.00000000'))
        saldo = SaldoCppActual.objects.get(empresa=self.empresa, producto=self.prod)
        self.assertEqual((saldo.cantidad_total, saldo.valor_total_pen), (Decimal('110.00000000'), Decimal('1110.00000000')))

    def test_documento_con_fecha_del_saldo_inicial_y_posteriores(self):
        self._preparar()
        self._compra(21, '10', '11')
        self._compra(1, '10', '12')   # mismo día que el saldo inicial → recálculo que lo incluye
        saldo = SaldoCppActual.objects.get(empresa=self.empresa, producto=self.prod)
        self.assertEqual((saldo.cantidad_total, saldo.valor_total_pen), (Decimal('120.00000000'), Decimal('1230.00000000')))
