"""
Bloque 5 — conciliación final. Escenario integral (saldo inicial, compra, venta,
devolución, transferencia entre establecimientos, ajuste de valor, anulación), cambio de
tasa de IGV posterior, cierre y operación futura. Para el período cerrado:
Kardex (API y Excel) = Formato 13.1 (resumen y última fila por establecimiento)
= Resumen de Saldos (Excel) = CierrePeriodoDetalle, en cantidad y valor; inmutable.
"""
import io
from decimal import Decimal

import openpyxl
from django.urls import reverse

from apps.empresas.services import cerrar_periodo
from apps.reportes.formato131_service import generar_formato_131
from apps.reportes import tests_b4_conciliacion_integral as b4  # módulo: evita duplicar su test

D = Decimal


class ConciliacionFinalTests(b4.ConciliacionIntegralTests):

    def fuentes(self, cierre):
        fuentes = super().fuentes(cierre)
        # Excel del Kardex: fila de totales (saldo final) del período.
        resp = self.client.get(reverse('kardex-excel-export'),
                               {'periodo_id': self.enero.id, 'producto_id': self.producto.id}, **self.headers)
        ws = openpyxl.load_workbook(io.BytesIO(resp.content))['Kardex Valorizado']
        totales = next(r for r in ws.iter_rows(min_row=8) if r[0].value == 'TOTALES DEL REPORTE')
        fuentes['Excel Kardex'] = (D(repr(totales[11].value)), D(repr(totales[13].value)), None)
        # 13.1: el valor de cada establecimiento tras el último movimiento del período.
        reportes = [r for r in generar_formato_131(empresa_id=self.empresa.id, periodo_id=self.enero.id)['reportes']
                    if r['cabecera']['producto_id'] == self.producto.id]
        fuentes['13.1 (filas)'] = (sum(D(r['movimientos'][-1]['saldo_final']['cantidad']) for r in reportes),
                                   sum(D(r['saldo_final']['costo_total']) for r in reportes), None)
        return fuentes

    def test_kardex_13_1_excel_y_cierre_concilian_y_son_inmutables(self):
        self.escenario_enero()
        # Cambio de tasa del IGV con vigencia en febrero: no altera enero.
        resp = self.client.patch(reverse('empresa-config'),
                                 {'tasa_igv_pct': '10.00', 'tasa_igv_vigente_desde': '2026-02-01'},
                                 format='json', **self.headers)
        self.assertEqual(resp.status_code, 200, resp.data)
        cierre, _ = cerrar_periodo(empresa_id=self.empresa.id, periodo_id=self.enero.id, usuario=self.usuario)
        antes = self.fuentes(cierre)
        cantidad, valor, _ = antes['Cierre']
        self.assertEqual((cantidad, valor), (D('7'), D('6.19250000')))
        for fuente, (c, v, _) in antes.items():
            with self.subTest(fuente=fuente):
                self.assertEqual((c, v), (cantidad, valor))

        # Operación futura (con la nueva tasa) en febrero.
        self.documento_confirmado('COMPRA', [self.linea('COMPRA', '7', '13', igv='9.10')],
                                  fecha='2026-02-03', periodo=self.febrero)
        self.assertEqual(self.fuentes(cierre), antes)
