"""
Bloque 4 — regresión integral. Escenario completo en enero con dos establecimientos y
CPP con decimales; tras el cierre:
Kardex = Formato 13.1 = Resumen de Saldos (Excel) = CierrePeriodoDetalle
en cantidad y valor (CPP donde aplica), y el resultado no cambia tras una operación
posterior en febrero.
"""
import io
from datetime import date
from decimal import Decimal

import openpyxl
from django.test import TestCase
from django.urls import reverse

from apps.catalogos.models import TipoOperacion
from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.documentos.models import Documento, DocumentoDetalle
from apps.empresas.models import CierrePeriodoDetalle, Establecimiento, Periodo
from apps.empresas.services import cerrar_periodo
from apps.inventario.models import Almacen, SaldoInicial, Transferencia, TransferenciaDetalle
from apps.inventario.services import confirmar_saldo_inicial, confirmar_transferencia
from apps.reportes.formato131_service import generar_formato_131
from apps.reportes.services import consultar_kardex_valorizado

D = Decimal


class ConciliacionIntegralTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()
        for codigo, sunat, naturaleza in (('TRANSFERENCIA_SALIDA', '11', 'SALIDA'), ('TRANSFERENCIA_ENTRADA', '21', 'ENTRADA')):
            TipoOperacion.objects.create(codigo_interno=codigo, codigo_sunat=sunat, descripcion=codigo,
                                         naturaleza=naturaleza, origen_requerido='TRANSFERENCIA', es_interna=True)
        self.sucursal = Establecimiento.objects.create(empresa=self.empresa, codigo_sunat='0001', nombre='SUCURSAL')
        self.almacen_b = Almacen.objects.create(empresa=self.empresa, establecimiento=self.sucursal, codigo='ALMB', nombre='SUCURSAL')
        self.febrero = Periodo.objects.create(empresa=self.empresa, anio=2026, mes=2, orden=202602,
                                              fecha_inicio=date(2026, 2, 1), fecha_fin=date(2026, 2, 28), estado='ABIERTO')

    def escenario_enero(self):
        # 1. Saldo inicial: 3 u. por S/ 2.00 (CPP 0.666667)
        saldo = SaldoInicial.objects.create(empresa=self.empresa, periodo=self.enero, almacen=self.almacen,
                                            producto=self.producto, cantidad=D('3'), valor_pen=D('2.00'),
                                            cpp_inicial=D('0.666667'), creado_por=self.usuario)
        confirmar_saldo_inicial(saldo_id=saldo.id, empresa_id=self.empresa.id, usuario=self.usuario)
        # 2. Compra
        compra = self.compra_confirmada('5', '1.10', fecha='2026-01-05')
        # 3. Venta
        venta = self.documento_confirmado('VENTA', [self.linea('VENTA', '2', '30')], fecha='2026-01-10')
        # 4. Devolución de venta
        self.documento_confirmado(
            'VENTA', [self.linea('DEVOLUCION_VENTA', '1', '30',
                                 detalle_origen=DocumentoDetalle.objects.get(documento_id=venta).id)],
            tipo=self.nota_credito, origen=Documento.objects.get(pk=venta), fecha='2026-01-12',
        )
        # 5. Transferencia al otro establecimiento
        transferencia = Transferencia.objects.create(empresa=self.empresa, almacen_origen=self.almacen,
                                                     almacen_destino=self.almacen_b, fecha=date(2026, 1, 14),
                                                     creado_por=self.usuario)
        TransferenciaDetalle.objects.create(transferencia=transferencia, producto=self.producto, cantidad_base=D('2'))
        confirmar_transferencia(transferencia_id=transferencia.id, empresa_id=self.empresa.id, usuario=self.usuario)
        # 6. Ajuste de valor (descuento de compra)
        self.documento_confirmado(
            'COMPRA', [self.linea('NC_DESCUENTO_COMPRA', '1', '0.37',
                                  detalle_origen=DocumentoDetalle.objects.get(documento_id=compra).id)],
            tipo=self.nota_credito, origen=Documento.objects.get(pk=compra), fecha='2026-01-15',
        )
        # 7. Anulación (extorno)
        self.anular(self.documento_confirmado('VENTA', [self.linea('VENTA', '1', '30')], fecha='2026-01-16'))

    def fuentes(self, cierre):
        kardex = consultar_kardex_valorizado(empresa_id=self.empresa.id, producto_id=self.producto.id,
                                             periodo_id=self.enero.id)['resumen']
        f131 = [r for r in generar_formato_131(empresa_id=self.empresa.id, periodo_id=self.enero.id)['reportes']
                if r['cabecera']['producto_id'] == self.producto.id]
        resp = self.client.get(reverse('kardex-excel-export'), {'periodo_id': self.enero.id}, **self.headers)
        hoja = openpyxl.load_workbook(io.BytesIO(resp.content))['Resumen de Saldos']
        filas = [f for f in hoja.iter_rows(min_row=4, values_only=True) if f[0] == self.producto.codigo_interno]
        detalles = CierrePeriodoDetalle.objects.filter(cierre_periodo=cierre, producto=self.producto)
        return {
            'Kardex': (kardex['saldo_final_cantidad'], kardex['saldo_final_valor'], kardex['cpp_final']),
            'Formato 13.1': (sum(D(r['saldo_final']['cantidad']) for r in f131),
                             sum(D(r['saldo_final']['costo_total']) for r in f131),
                             {D(r['saldo_final']['costo_unitario']) for r in f131}),
            'Excel (empresa)': (D(str(filas[0][7])), D(str(filas[0][8])), {D(str(f[5])) for f in filas}),
            'Excel (Σ almacenes)': (sum(D(str(f[4])) for f in filas), sum(D(str(f[6])) for f in filas), None),
            'Cierre': (sum(d.saldo_cantidad for d in detalles), sum(d.saldo_valor_pen for d in detalles),
                       {d.cpp_pen for d in detalles}),
        }

    def test_kardex_13_1_excel_y_cierre_concilian_y_son_inmutables(self):
        self.escenario_enero()
        cierre, _ = cerrar_periodo(empresa_id=self.empresa.id, periodo_id=self.enero.id, usuario=self.usuario)
        antes = self.fuentes(cierre)

        cantidad, valor, cpp = antes['Kardex']
        # 3 + 5 − 2 + 1 = 7 u.; transferencia y extorno no cambian el saldo empresa.
        self.assertEqual(cantidad, D('7'))
        for fuente, (c, v, cpps) in antes.items():
            with self.subTest(fuente=fuente):
                self.assertEqual(c, cantidad)
                self.assertEqual(v, valor)
                if cpps is not None and fuente != 'Kardex':
                    self.assertEqual(cpps, {cpp})

        # Operación posterior en otro período: el histórico no cambia.
        self.documento_confirmado('COMPRA', [self.linea('COMPRA', '7', '13')], fecha='2026-02-03', periodo=self.febrero)
        self.assertEqual(self.fuentes(cierre), antes)
        self.assertEqual(self.saldo().cantidad_total, D('14'))
