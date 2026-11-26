"""
Bloque 3 — revisión cruzada: para un producto y un período CERRADO,
saldo final Kardex = saldo final Formato 13.1 = CierrePeriodoDetalle
en cantidad, costo unitario y valor total.

Cada escenario incluye compras de 1 × 1.00 y 2 × 0.50 (CPP 0.666667 a 6 decimales) para
que cantidad × CPP difiera del valor contable real y la comparación no sea trivial.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from openpyxl import load_workbook

from apps.documentos.fixtures_bloque2 import Bloque2Fixture
from apps.documentos.models import Documento, DocumentoDetalle
from apps.empresas.models import CierrePeriodoDetalle, Periodo
from apps.empresas.services import cerrar_periodo
from apps.reportes.excel_exporter import generar_bytes_excel_kardex
from apps.reportes.formato131_service import generar_formato_131
from apps.reportes.services import consultar_kardex_valorizado

D = Decimal


def continuidad_excel(libro):
    """
    Por hoja de movimientos: (referencia, cantidad esperada, cantidad mostrada, valor esperado,
    valor mostrado) de cada fila, acumulando desde el saldo inicial (o desde la primera fila).
    """
    resultado = {}
    ws = libro['Kardex Valorizado']
    filas, cantidad, valor, en_datos = [], None, None, False
    for r in ws.iter_rows(values_only=True):
        if r[0] == 'Fecha':
            en_datos, cantidad, valor = True, 0.0, 0.0
            continue
        if not en_datos or r[0] is None and r[11] is None:
            continue
        if r[0] == 'SALDO INICIAL':
            cantidad, valor = float(r[11] or 0), float(r[13] or 0)
            continue
        if str(r[0]).startswith('TOTALES'):
            break
        cantidad += float(r[5] or 0) - float(r[8] or 0)
        valor += float(r[7] or 0) - float(r[10] or 0)
        filas.append((r[1], cantidad, float(r[11]), valor, float(r[13])))
    resultado['Kardex Valorizado'] = filas
    ws = libro['Movimientos']
    filas, cantidad, valor = [], None, None
    for r in ws.iter_rows(min_row=4, values_only=True):
        if not isinstance(r[0], int):
            continue
        signo = {'ENTRADA': 1, 'SALIDA': -1}.get(r[8], 0)
        if cantidad is None:
            cantidad, valor = float(r[15]) - signo * float(r[12] or 0), float(r[17]) - (signo or 1) * float(r[14] or 0)
        cantidad += signo * float(r[12] or 0)
        valor += (signo or 1) * float(r[14] or 0)
        filas.append((r[11], cantidad, float(r[15]), valor, float(r[17])))
    resultado['Movimientos'] = filas
    return resultado


class ConciliacionCruzadaTests(Bloque2Fixture, TestCase):
    def setUp(self):
        self.crear_base()
        self.febrero = Periodo.objects.create(
            empresa=self.empresa, anio=2026, mes=2, orden=202602,
            fecha_inicio=date(2026, 2, 1), fecha_fin=date(2026, 2, 28), estado='ABIERTO',
        )

    # ---- helpers -------------------------------------------------------------

    def base_con_redondeo(self):
        self.compra_confirmada('1', '1', fecha='2026-01-08')
        return self.compra_confirmada('2', '0.5', fecha='2026-01-09')

    def venta(self, cantidad, fecha='2026-01-20'):
        return self.documento_confirmado('VENTA', [self.linea('VENTA', cantidad, '30')], fecha=fecha)

    def nota(self, clase, operacion, origen_id, cantidad, precio, fecha='2026-01-22'):
        detalle = DocumentoDetalle.objects.get(documento_id=origen_id)
        return self.documento_confirmado(
            clase, [self.linea(operacion, cantidad, precio, detalle_origen=detalle.id)],
            tipo=self.nota_credito, origen=Documento.objects.get(pk=origen_id), fecha=fecha,
        )

    def conciliar(self, esperado_cantidad, esperado_valor):
        cierre, _ = cerrar_periodo(empresa_id=self.empresa.id, periodo_id=self.enero.id, usuario=self.usuario)
        # Operaciones posteriores al cierre no deben alterar ninguna de las tres fuentes.
        self.documento_confirmado('COMPRA', [self.linea('COMPRA', '7', '13')], fecha='2026-02-03', periodo=self.febrero)

        detalle = CierrePeriodoDetalle.objects.get(cierre_periodo=cierre, producto=self.producto)
        kardex = consultar_kardex_valorizado(
            empresa_id=self.empresa.id, producto_id=self.producto.id, periodo_id=self.enero.id,
        )['resumen']
        f131 = next(
            r for r in generar_formato_131(empresa_id=self.empresa.id, periodo_id=self.enero.id)['reportes']
            if r['cabecera']['producto_id'] == self.producto.id
        )['saldo_final']

        filas = {
            'cierre': (detalle.saldo_cantidad, detalle.cpp_pen, detalle.saldo_valor_pen),
            'kardex': (kardex['saldo_final_cantidad'], kardex['cpp_final'], kardex['saldo_final_valor']),
            '13.1': (D(f131['cantidad']), D(f131['costo_unitario']), D(f131['costo_total'])),
        }
        for fuente, (cantidad, cu, valor) in filas.items():
            with self.subTest(fuente=fuente):
                self.assertEqual(cantidad, D(esperado_cantidad))
                self.assertEqual(valor, D(esperado_valor))
                self.assertEqual(cu, filas['cierre'][1])
        return filas

    # ---- escenarios ----------------------------------------------------------

    def test_1_compra_y_venta(self):
        self.base_con_redondeo()
        self.venta('2')
        # 2.00 − 2 × 0.666667 = 0.666666 (cantidad × CPP daría 0.666667)
        self.conciliar('1', '0.66666600')

    def test_2_devoluciones(self):
        compra = self.base_con_redondeo()
        venta = self.venta('2')
        self.nota('VENTA', 'DEVOLUCION_VENTA', venta, '1', '30')       # vuelve 1 × 0.666667
        self.nota('COMPRA', 'DEVOLUCION_COMPRA', compra, '1', '0.5')   # sale 1 × 0.50
        self.conciliar('1', '0.83333300')  # 0.666666 + 0.666667 − 0.50

    def test_3_ajuste_de_valor(self):
        compra = self.base_con_redondeo()
        self.nota('COMPRA', 'NC_DESCUENTO_COMPRA', compra, '1', '0.10')  # −0.10 de valor
        self.conciliar('3', '1.90000000')

    def test_4_anulacion_extorno(self):
        self.base_con_redondeo()
        venta = self.venta('2')
        self.venta('1', fecha='2026-01-21')
        self.anular(venta)
        self.conciliar('2', '1.33333300')  # 2.00 − 0.666667

    def test_5_movimiento_retroactivo_antes_del_cierre(self):
        self.compra_confirmada('1', '1', fecha='2026-01-08')
        self.venta('1', fecha='2026-01-20')
        self.compra_confirmada('2', '0.5', fecha='2026-01-05')  # retroactiva: la venta pasa a CPP 0.666667
        self.conciliar('2', '1.33333300')

    def test_ocultar_revertidos_conserva_saldos_y_coincide_con_el_excel(self):
        self.base_con_redondeo()
        anulada = self.venta('2')
        self.venta('1', fecha='2026-01-21')
        self.anular(anulada)
        filtros = dict(empresa_id=self.empresa.id, producto_id=self.producto.id, periodo_id=self.enero.id)

        completo = consultar_kardex_valorizado(**filtros)
        filtrado = consultar_kardex_valorizado(**filtros, ocultar_revertidos=True)
        extorno = next(fila for fila in completo['movimientos'] if fila['es_extorno'])
        ocultos = {extorno['id'], extorno['movimiento_extornado_id']}
        self.assertEqual(
            filtrado['movimientos'],
            [fila for fila in completo['movimientos'] if fila['id'] not in ocultos],
        )
        for campo in ('saldo_final_cantidad', 'saldo_final_valor', 'cpp_final'):
            self.assertEqual(filtrado['resumen'][campo], completo['resumen'][campo])

        excel_completo = load_workbook(generar_bytes_excel_kardex(**filtros))
        excel_filtrado = load_workbook(generar_bytes_excel_kardex(**filtros, ocultar_revertidos=True))
        self.assertIn('Movimientos revertidos ocultos', excel_filtrado['Kardex Valorizado']['A3'].value)
        for hoja in ('Kardex Valorizado', 'Movimientos'):
            self.assertEqual(excel_filtrado[hoja].max_row, excel_completo[hoja].max_row - 2)

    def test_ocultar_revertidos_cada_saldo_cuadra_con_la_fila_visible_anterior(self):
        # Mismo día: la compra anulada (entrada, prioridad 2) va antes que la venta vigente y su
        # extorno (salida, prioridad 4) después. La venta vigente queda ENTRE la compra y su extorno
        # y no debe mostrar el stock de la compra anulada.
        self.compra_confirmada('1', '1', fecha='2026-01-08')
        anulada = self.compra_confirmada('5', '2', fecha='2026-01-15')
        self.venta('1', fecha='2026-01-15')
        self.anular(anulada)
        filtros = dict(empresa_id=self.empresa.id, producto_id=self.producto.id, periodo_id=self.enero.id)
        completo = consultar_kardex_valorizado(**filtros)
        filtrado = consultar_kardex_valorizado(**filtros, ocultar_revertidos=True)

        # La venta vigente está entre la compra anulada y su extorno en el orden del motor.
        orden = [f['documento_referencia'] for f in completo['movimientos']]
        venta_ref = next(f['documento_referencia'] for f in completo['movimientos'] if f['naturaleza'] == 'SALIDA' and not f['es_extorno'])
        compra_ref = next(f['documento_referencia'] for f in completo['movimientos'] if f['id'] == next(
            x['movimiento_extornado_id'] for x in completo['movimientos'] if x['es_extorno']))
        self.assertLess(orden.index(compra_ref), orden.index(venta_ref))
        self.assertLess(orden.index(venta_ref), max(i for i, f in enumerate(completo['movimientos']) if f['es_extorno']))

        self.assertEqual(len(filtrado['movimientos']), len(completo['movimientos']) - 2)
        cantidad, valor = D('0'), D('0')
        for fila in filtrado['movimientos']:
            cantidad += (fila['entrada_cantidad'] or 0) - (fila['salida_cantidad'] or 0)
            valor += (fila['entrada_valor'] or 0) - (fila['salida_valor'] or 0)
            self.assertEqual(fila['saldo_cantidad'], cantidad, fila['documento_referencia'])
            self.assertEqual(fila['saldo_valor'], valor, fila['documento_referencia'])
        venta = next(f for f in filtrado['movimientos'] if f['documento_referencia'] == venta_ref)
        self.assertEqual((venta['saldo_cantidad'], venta['cpp']), (D('0'), D('0')))
        # El costo unitario de cada movimiento es el registrado; solo el saldo se ajusta.
        registrados = {f['id']: (f['entrada_costo_unitario'], f['salida_costo_unitario'], f['entrada_valor'], f['salida_valor'])
                       for f in completo['movimientos']}
        for fila in filtrado['movimientos']:
            self.assertEqual(registrados[fila['id']],
                             (fila['entrada_costo_unitario'], fila['salida_costo_unitario'], fila['entrada_valor'], fila['salida_valor']))
        for campo in ('saldo_final_cantidad', 'saldo_final_valor', 'cpp_final'):
            self.assertEqual(filtrado['resumen'][campo], completo['resumen'][campo])

        # Excel: las dos hojas de movimientos, fila por fila.
        libro = load_workbook(generar_bytes_excel_kardex(**filtros, ocultar_revertidos=True))
        for hoja, filas in continuidad_excel(libro).items():
            self.assertEqual(len(filas), len(filtrado['movimientos']), hoja)
            for referencia, esperado_c, mostrado_c, esperado_v, mostrado_v in filas:
                self.assertAlmostEqual(mostrado_c, esperado_c, places=6, msg=f'{hoja} {referencia}')
                self.assertAlmostEqual(mostrado_v, esperado_v, places=6, msg=f'{hoja} {referencia}')

    def test_par_que_no_se_compensa_no_se_oculta(self):
        from apps.reportes.services import _par_se_compensa
        self.assertTrue(_par_se_compensa('SALIDA', D('5'), D('10'), 'ENTRADA', D('5'), D('10')))
        self.assertFalse(_par_se_compensa('SALIDA', D('5'), D('10.01'), 'ENTRADA', D('5'), D('10')))
        self.assertFalse(_par_se_compensa('SALIDA', D('4'), D('10'), 'ENTRADA', D('5'), D('10')))
        self.assertFalse(_par_se_compensa('SALIDA', D('5'), None, 'ENTRADA', D('5'), D('10')))
        self.assertTrue(_par_se_compensa('AJUSTE_VALOR', D('0'), D('0.10'), 'AJUSTE_VALOR', D('0'), D('-0.10')))

    def test_periodo_siguiente_sin_movimientos_arranca_y_termina_en_el_cierre(self):
        compra = self.base_con_redondeo()
        self.nota('COMPRA', 'NC_DESCUENTO_COMPRA', compra, '1', '0.10')
        cerrar_periodo(empresa_id=self.empresa.id, periodo_id=self.enero.id, usuario=self.usuario)
        r = next(r for r in generar_formato_131(empresa_id=self.empresa.id, periodo_id=self.febrero.id)['reportes']
                 if r['cabecera']['producto_id'] == self.producto.id)
        esperado = {'cantidad': '3.00000000', 'costo_unitario': '0.63333300', 'costo_total': '1.90000000'}
        self.assertEqual(r['movimientos'], [])
        self.assertEqual(r['saldo_inicial_valorizado'], esperado)
        self.assertEqual(r['saldo_final'], esperado)  # antes: 3 × 0.633333 = 1.89999900
        kardex = consultar_kardex_valorizado(empresa_id=self.empresa.id, producto_id=self.producto.id,
                                             periodo_id=self.febrero.id)['resumen']
        self.assertEqual((kardex['saldo_inicial_valor'], kardex['saldo_final_valor']), (D('1.9'), D('1.9')))
