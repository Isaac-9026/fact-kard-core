"""
Bloque 6 — el recálculo ya no carga en memoria la historia anterior a fecha_desde (usa
agregación SQL para el stock y el último saldo). Equivalencia: recalcular desde el punto
mínimo afectado = recalcular toda la historia.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.documentos.models import Documento, DocumentoDetalle
from apps.empresas.models import Establecimiento, Periodo
from apps.inventario.models import Almacen
from apps.kardex.models import SaldoCppActual, StockAlmacen, ValorizacionMovimiento
from apps.kardex.services import ejecutar_recalculo_producto


class RecalculoEquivalenciaTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()
        Periodo.objects.filter(pk=self.diciembre.pk).update(estado='ABIERTO')
        suc = Establecimiento.objects.create(empresa=self.empresa, codigo_sunat='0001', nombre='S')
        self.almacen_b = Almacen.objects.create(empresa=self.empresa, establecimiento=suc, codigo='B', nombre='B')
        for d in range(1, 21):
            alm = self.almacen.id if d % 2 else self.almacen_b.id
            self.documento_confirmado('COMPRA', [self.linea('COMPRA', '3', str(d % 7 + 1), almacen=alm)],
                                      fecha=f'2025-12-{d:02d}', periodo=self.diciembre)
            self.documento_confirmado('VENTA', [self.linea('VENTA', '1', '30', almacen=alm)],
                                      fecha=f'2025-12-{d:02d}', periodo=self.diciembre)
        compra = self.compra_confirmada('4', '1.10', fecha='2026-01-05')
        venta = self.documento_confirmado('VENTA', [self.linea('VENTA', '3', '30')], fecha='2026-01-10')
        self.documento_confirmado('VENTA', [self.linea('DEVOLUCION_VENTA', '1', '30',
                                                       detalle_origen=DocumentoDetalle.objects.get(documento_id=venta).id)],
                                  tipo=self.nota_credito, origen=Documento.objects.get(pk=venta), fecha='2026-01-12')
        self.documento_confirmado('COMPRA', [self.linea('NC_DESCUENTO_COMPRA', '1', '0.37',
                                                        detalle_origen=DocumentoDetalle.objects.get(documento_id=compra).id)],
                                  tipo=self.nota_credito, origen=Documento.objects.get(pk=compra), fecha='2026-01-14')
        # Retroactivo: dispara el recálculo optimizado desde 2026-01-03.
        self.compra_confirmada('2', '0.5', fecha='2026-01-03')

    def foto(self):
        valores = list(ValorizacionMovimiento.objects.filter(movimiento__producto=self.producto).order_by(
            'movimiento__fecha_movimiento', 'movimiento__prioridad_dia', 'movimiento__secuencia', 'movimiento_id',
        ).values_list('movimiento_id', 'costo_unitario_pen', 'valor_movimiento_pen',
                      'saldo_cantidad_empresa', 'saldo_valor_empresa', 'cpp_empresa'))
        saldo = SaldoCppActual.objects.get(empresa=self.empresa, producto=self.producto)
        stocks = dict(StockAlmacen.objects.filter(empresa=self.empresa, producto=self.producto)
                      .values_list('almacen_id', 'cantidad_actual'))
        return valores, (saldo.cantidad_total, saldo.valor_total_pen, saldo.cpp_pen, saldo.ultimo_movimiento_id), stocks

    def test_recalculo_desde_el_punto_minimo_igual_al_completo(self):
        optimizado = self.foto()
        ejecutar_recalculo_producto(empresa_id=self.empresa.id, producto_id=self.producto.id,
                                    fecha_desde=date(2026, 1, 3), usuario_id=self.usuario.id)
        self.assertEqual(self.foto(), optimizado)  # idempotente
        ejecutar_recalculo_producto(empresa_id=self.empresa.id, producto_id=self.producto.id,
                                    fecha_desde=date(2000, 1, 1), usuario_id=self.usuario.id)
        self.assertEqual(self.foto(), optimizado)  # = recalcular toda la historia
        valores, saldo, stocks = optimizado
        self.assertEqual(sum(stocks.values()), saldo[0])
        self.assertEqual(valores[-1][4], saldo[1])

    def test_punto_de_partida_con_stock_en_varios_almacenes(self):
        ejecutar_recalculo_producto(empresa_id=self.empresa.id, producto_id=self.producto.id,
                                    fecha_desde=date(2026, 1, 20), usuario_id=self.usuario.id)  # sin movimientos después
        stocks = dict(StockAlmacen.objects.filter(empresa=self.empresa, producto=self.producto)
                      .values_list('almacen_id', 'cantidad_actual'))
        self.assertEqual(stocks[self.almacen_b.id], Decimal('20'))  # 10 días × (3 − 1)
        saldo = SaldoCppActual.objects.get(empresa=self.empresa, producto=self.producto)
        self.assertEqual(sum(stocks.values()), saldo.cantidad_total)
