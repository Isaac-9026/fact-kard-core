from decimal import Decimal
import datetime
from django.db import DatabaseError, IntegrityError, transaction
from django.test import TestCase

from apps.catalogos.models import Moneda, TipoExistencia, UnidadMedida, TipoOperacion
from apps.empresas.models import Empresa, Establecimiento, Periodo
from apps.inventario.models import Almacen, Producto, Transferencia, TransferenciaDetalle
from apps.kardex.models import (
    Movimiento, StockAlmacen, SaldoCppActual, Incidencia,
    Recalculo, ValorizacionMovimiento
)
from apps.usuarios.models import Usuario


class KardexModelAndTriggerTest(TestCase):
    def setUp(self):
        self.moneda = Moneda.objects.create(codigo='PEN', nombre='Soles')
        self.empresa = Empresa.objects.create(
            ruc='20100070970',
            razon_social='EMPRESA MODELO S.A.C.',
            moneda_base_codigo=self.moneda
        )
        self.establecimiento = Establecimiento.objects.create(
            empresa=self.empresa,
            codigo_sunat='0000',
            nombre='PRINCIPAL'
        )
        self.almacen_origen = Almacen.objects.create(
            empresa=self.empresa,
            establecimiento=self.establecimiento,
            codigo='ALM01',
            nombre='ALMACEN CENTRAL'
        )
        self.almacen_destino = Almacen.objects.create(
            empresa=self.empresa,
            establecimiento=self.establecimiento,
            codigo='ALM02',
            nombre='ALMACEN SECUNDARIO'
        )
        self.tipo_existencia = TipoExistencia.objects.create(
            codigo='01',
            descripcion='MERCADERIAS'
        )
        self.und = UnidadMedida.objects.create(codigo='NIU', descripcion='UNIDADES')
        self.producto = Producto.objects.create(
            empresa=self.empresa,
            tipo_existencia_codigo=self.tipo_existencia,
            codigo_interno='PROD001',
            descripcion='PRODUCTO DE PRUEBA'
        )
        self.periodo = Periodo.objects.create(
            empresa=self.empresa,
            anio=2026,
            mes=1,
            orden=202601,
            fecha_inicio=datetime.date(2026, 1, 1),
            fecha_fin=datetime.date(2026, 1, 31),
            estado='ABIERTO'
        )
        self.tipo_op_compra = TipoOperacion.objects.create(
            codigo_interno='COMPRA_NACIONAL',
            codigo_sunat='02',
            descripcion='COMPRA NACIONAL',
            naturaleza='ENTRADA',
            origen_requerido='DOCUMENTO'
        )

    def test_transferencia_mismo_almacen_rechazado(self):
        """Verifica que almacen_origen == almacen_destino lance IntegrityError por CheckConstraint."""
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                Transferencia.objects.create(
                    empresa=self.empresa,
                    almacen_origen=self.almacen_origen,
                    almacen_destino=self.almacen_origen,
                    fecha=datetime.date(2026, 1, 15)
                )

    def test_transferencia_valida_y_detalle(self):
        """Verifica creación válida de transferencia y su detalle."""
        transf = Transferencia.objects.create(
            empresa=self.empresa,
            almacen_origen=self.almacen_origen,
            almacen_destino=self.almacen_destino,
            fecha=datetime.date(2026, 1, 15),
            estado='BORRADOR'
        )
        self.assertIsNotNone(transf.id)
        self.assertEqual(transf.estado, 'BORRADOR')

        detalle = TransferenciaDetalle.objects.create(
            transferencia=transf,
            producto=self.producto,
            cantidad_base=Decimal('10.50000000')
        )
        self.assertIsNotNone(detalle.id)

        # Detalle con cantidad_base <= 0 debe fallar
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                TransferenciaDetalle.objects.create(
                    transferencia=transf,
                    producto=self.producto,
                    cantidad_base=Decimal('0.00000000')
                )

    def test_movimiento_insercion_exitosa(self):
        """Verifica creación válida de un registro en movimiento."""
        mov = Movimiento.objects.create(
            empresa=self.empresa,
            producto=self.producto,
            almacen=self.almacen_origen,
            periodo=self.periodo,
            tipo_operacion=self.tipo_op_compra,
            fecha_movimiento=datetime.date(2026, 1, 15),
            prioridad_dia=1,
            secuencia=1,
            naturaleza='ENTRADA',
            cantidad_base=Decimal('100.00000000')
        )
        self.assertIsNotNone(mov.id)
        self.assertEqual(mov.naturaleza, 'ENTRADA')
        self.assertEqual(mov.cantidad_base, Decimal('100.00000000'))

    def test_movimiento_inmutable_trigger_no_update(self):
        """Verifica que el trigger PostgreSQL bloquee UPDATE sobre movimiento."""
        mov = Movimiento.objects.create(
            empresa=self.empresa,
            producto=self.producto,
            almacen=self.almacen_origen,
            periodo=self.periodo,
            tipo_operacion=self.tipo_op_compra,
            fecha_movimiento=datetime.date(2026, 1, 15),
            prioridad_dia=1,
            secuencia=1,
            naturaleza='ENTRADA',
            cantidad_base=Decimal('100.00000000')
        )

        with transaction.atomic():
            with self.assertRaises(DatabaseError) as ctx:
                mov.naturaleza = 'SALIDA'
                mov.save()
            self.assertIn('MOVIMIENTO es inmutable', str(ctx.exception))

        with transaction.atomic():
            with self.assertRaises(DatabaseError) as ctx:
                Movimiento.objects.filter(id=mov.id).update(cantidad_base=Decimal('50.00000000'))
            self.assertIn('MOVIMIENTO es inmutable', str(ctx.exception))

    def test_movimiento_inmutable_trigger_no_delete(self):
        """Verifica que el trigger PostgreSQL bloquee DELETE sobre movimiento."""
        mov = Movimiento.objects.create(
            empresa=self.empresa,
            producto=self.producto,
            almacen=self.almacen_origen,
            periodo=self.periodo,
            tipo_operacion=self.tipo_op_compra,
            fecha_movimiento=datetime.date(2026, 1, 15),
            prioridad_dia=1,
            secuencia=1,
            naturaleza='ENTRADA',
            cantidad_base=Decimal('100.00000000')
        )

        with transaction.atomic():
            with self.assertRaises(DatabaseError) as ctx:
                mov.delete()
            self.assertIn('MOVIMIENTO es inmutable', str(ctx.exception))

        with transaction.atomic():
            with self.assertRaises(DatabaseError) as ctx:
                Movimiento.objects.filter(id=mov.id).delete()
            self.assertIn('MOVIMIENTO es inmutable', str(ctx.exception))

    def test_stock_almacen_unique_constraint(self):
        """Verifica la unicidad por (empresa, almacen, producto)."""
        StockAlmacen.objects.create(
            empresa=self.empresa,
            almacen=self.almacen_origen,
            producto=self.producto,
            cantidad_actual=Decimal('50.00000000')
        )
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                StockAlmacen.objects.create(
                    empresa=self.empresa,
                    almacen=self.almacen_origen,
                    producto=self.producto,
                    cantidad_actual=Decimal('20.00000000')
                )

    def test_saldo_cpp_actual_unique_constraint(self):
        """Verifica la unicidad por (empresa, producto)."""
        SaldoCppActual.objects.create(
            empresa=self.empresa,
            producto=self.producto,
            cantidad_total=Decimal('50.00000000'),
            valor_total_pen=Decimal('500.00000000'),
            cpp_pen=Decimal('10.00000000')
        )
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                SaldoCppActual.objects.create(
                    empresa=self.empresa,
                    producto=self.producto,
                    cantidad_total=Decimal('20.00000000'),
                    valor_total_pen=Decimal('200.00000000'),
                    cpp_pen=Decimal('10.00000000')
                )
