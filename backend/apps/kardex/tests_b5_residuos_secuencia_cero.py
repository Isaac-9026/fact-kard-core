"""
Bloque 5 — diagnóstico de residuos antiguos con secuencia 0: lista los casos, los
clasifica y no modifica ningún dato (los movimientos son inmutables).
"""
from io import StringIO

from django.core.management import call_command
from django.db import connection
from django.test import TestCase

from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.documentos.models import Documento, DocumentoDetalle
from apps.empresas.models import Periodo
from apps.kardex.management.commands.residuos_secuencia_cero import diagnosticar
from apps.kardex.models import Movimiento, ValorizacionMovimiento


class ResiduosSecuenciaCeroTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()
        self.compra = self.compra_confirmada('1', '1', fecha='2026-01-08')
        self.compra_confirmada('2', '0.5', fecha='2026-01-09')
        self.documento_confirmado('VENTA', [self.linea('VENTA', '3', '30')], fecha='2026-01-12')
        self.residuo = Movimiento.objects.get(tipo_operacion__codigo_interno='RESIDUO_AUTOMATICO')
        # Simula un residuo creado antes del Bloque 4 (secuencia 0): solo para la prueba
        # se desactiva el trigger de inmutabilidad dentro de la transacción del test.
        with connection.cursor() as cursor:
            cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
            cursor.execute('ALTER TABLE movimiento DISABLE TRIGGER trg_movimiento_no_update')
            cursor.execute('UPDATE movimiento SET secuencia = 0 WHERE id = %s', [self.residuo.id])
            cursor.execute('ALTER TABLE movimiento ENABLE TRIGGER trg_movimiento_no_update')
            cursor.execute('SET CONSTRAINTS ALL DEFERRED')

    def foto(self):
        return (list(Movimiento.objects.order_by('id').values_list('id', 'secuencia', 'cantidad_base', 'valor_ajuste_pen')),
                list(ValorizacionMovimiento.objects.order_by('id').values_list(
                    'movimiento_id', 'valor_movimiento_pen', 'saldo_cantidad_empresa', 'saldo_valor_empresa')))

    def ejecutar(self, *args):
        salida = StringIO()
        call_command('residuos_secuencia_cero', *args, stdout=salida)
        return salida.getvalue()

    def test_lista_sin_modificar_datos(self):
        antes = self.foto()
        texto = self.ejecutar()
        self.assertIn(f'SIN_EFECTO        mov={self.residuo.id}', texto)
        self.assertIn('Total: 1 | SIN_EFECTO: 1', texto)
        self.assertIn('no se modificó ningún dato', texto)
        self.assertEqual(self.foto(), antes)
        self.assertEqual(self.ejecutar(), texto)  # idempotente

    def test_clasifica_orden_anticipado_y_periodo_cerrado(self):
        detalle = DocumentoDetalle.objects.get(documento_id=self.compra)
        self.documento_confirmado(  # otro ajuste (prioridad 3) el mismo día del residuo
            'COMPRA', [self.linea('NC_DESCUENTO_COMPRA', '1', '0.10', detalle_origen=detalle.id)],
            tipo=self.nota_credito, origen=Documento.objects.get(pk=self.compra), fecha='2026-01-12',
        )
        self.assertEqual([c['estado'] for c in diagnosticar(self.empresa.id)], ['ORDEN_ANTICIPADO'])
        Periodo.objects.filter(pk=self.enero.pk).update(estado='CERRADO')
        self.assertEqual([c['estado'] for c in diagnosticar(self.empresa.id)], ['PERIODO_CERRADO'])
        self.assertEqual(diagnosticar(self.otra_empresa.id), [])

    def test_sin_casos_en_otra_empresa(self):
        self.assertEqual(diagnosticar(self.otra_empresa.id), [])
        self.assertIn('No hay residuos', self.ejecutar('--empresa', str(self.otra_empresa.id)))

    def test_el_movimiento_sigue_siendo_inmutable(self):
        from django.db import DatabaseError, transaction
        with self.assertRaises(DatabaseError), transaction.atomic():
            Movimiento.objects.filter(pk=self.residuo.pk).update(secuencia=1)
        self.assertEqual(Movimiento.objects.get(pk=self.residuo.pk).secuencia, 0)
