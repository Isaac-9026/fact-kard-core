import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  aniosDePeriodos, conceptosConImporte, cuadra, esCero, ETIQUETAS_CONCILIACION, ETIQUETAS_DESGLOSE, filasFormula, paramsCostoVenta,
  paramsCostoVentaAnual, sumarTexto, validarRangoPeriodos, textosComparacion, conSigno,
} from './costoVenta.ts';

test('parámetros: el período final igual al inicial no se envía; producto opcional', () => {
  assert.deepEqual(paramsCostoVenta({ periodo_id: 3 }), { periodo_id: 3 });
  assert.deepEqual(paramsCostoVenta({ periodo_id: 3, periodo_hasta_id: 3 }), { periodo_id: 3 });
  assert.deepEqual(paramsCostoVenta({ periodo_id: 3, periodo_hasta_id: 5, producto_id: 9 }),
    { periodo_id: 3, periodo_hasta_id: 5, producto_id: 9 });
  assert.deepEqual(paramsCostoVenta({ periodo_id: 3, periodo_hasta_id: '', producto_id: '' }), { periodo_id: 3 });
});

test('rango de períodos', () => {
  const periodos = [{ id: 1, orden: 202601 }, { id: 2, orden: 202602 }];
  assert.equal(validarRangoPeriodos(periodos, '', ''), 'Seleccione el período.');
  assert.equal(validarRangoPeriodos(periodos, 1, ''), null);
  assert.equal(validarRangoPeriodos(periodos, 1, 2), null);
  assert.equal(validarRangoPeriodos(periodos, 2, 1), 'El período final no puede ser anterior al inicial.');
});

test('ejemplo del dueño: 30 + 1 000 = 1 030; − 500 = 530', () => {
  const b = (cantidad: string, pu: string, valor: string) => ({ cantidad, costo_unitario: pu, valor });
  const filas = filasFormula({
    saldo_inicial: b('3.00000000', '10.00000000', '30.00000000'),
    compras: b('100.00000000', '10.00000000', '1000.00000000'),
    saldo_final: b('50.00000000', '10.00000000', '500.00000000'),
    costo_venta: b('53.00000000', '10.00000000', '530.00000000'),
  });
  assert.deepEqual(filas.map((f) => [f.signo, f.etiqueta, f.valor]), [
    ['', 'Saldo inicial', '30.00000000'],
    ['+', 'Compras', '1000.00000000'],
    ['', 'Subtotal', '1030.00000000'],
    ['−', 'Saldo final (Kardex)', '500.00000000'],
    ['=', 'Costo de venta', '530.00000000'],
  ]);
  assert.equal(filas[2].cantidad, null);
});

test('principal según Kardex: el subtotal lleva unidades y su costo medio', () => {
  const b = (cantidad: string, pu: string, valor: string) => ({ cantidad, costo_unitario: pu, valor });
  const filas = filasFormula({
    saldo_inicial: b('100.00000000', '20.00000000', '2000.00000000'),
    compras: b('100.00000000', '22.50000000', '2250.00000000'),
    disponible: b('200.00000000', '21.25000000', '4250.00000000'),
    saldo_final: b('150.00000000', '21.66666667', '3250.00000000'),
    salidas: b('50.00000000', '20.00000000', '1000.00000000'),
    no_atribuibles: b('0.00000000', '', '0.00000000'),
    costo_venta: b('50.00000000', '20.00000000', '1000.00000000'),
  });
  assert.deepEqual(filas.map((f) => [f.etiqueta, f.cantidad, f.costoUnitario, f.valor]), [
    ['Saldo inicial', '100.00000000', '20.00000000', '2000.00000000'],
    ['Compras', '100.00000000', '22.50000000', '2250.00000000'],
    ['Subtotal', '200.00000000', '21.25000000', '4250.00000000'],
    ['Saldo final (Kardex)', '150.00000000', '21.66666667', '3250.00000000'],
    ['Costo de venta', '50.00000000', '20.00000000', '1000.00000000'],
  ]);
});

test('suma decimal exacta, sin float', () => {
  assert.equal(sumarTexto('0.1', '0.2'), '0.30000000');
  assert.equal(sumarTexto('2.00000000', '-0.37000000'), '1.63000000');
  assert.equal(sumarTexto('-5', '2'), '-3.00000000');
  assert.equal(sumarTexto('', '7.5'), '7.50000000');
});

test('cuadra y conceptos con importe', () => {
  assert.ok(cuadra('0.00000000'));
  assert.ok(cuadra('-0.00000000'));
  assert.ok(!cuadra('0.00000001'));
  const conceptos = conceptosConImporte({ ventas: '530.00000000', devoluciones_venta: '0.00000000' }, ETIQUETAS_DESGLOSE);
  assert.deepEqual(conceptos.map((c) => c.clave), ['ventas']);
  const conciliacion = conceptosConImporte({ mermas_desmedros: '30', ajustes: '0', otros: '-1.5' }, ETIQUETAS_CONCILIACION);
  assert.deepEqual(conciliacion.map((c) => c.clave), ['mermas_desmedros', 'otros']);
});

test('salidas que no son ventas: se concilian solo si hubo', () => {
  const b = (cantidad: string, pu: string, valor: string) => ({ cantidad, costo_unitario: pu, valor });
  const base = {
    saldo_inicial: b('100.00000000', '20.00000000', '2000.00000000'),
    compras: b('100.00000000', '22.50000000', '2250.00000000'),
    saldo_final: b('148.00000000', '21.66666667', '3206.66666600'),
    salidas: b('52.00000000', '', '1043.33333400'),
    costo_venta: b('50.00000000', '20.00000000', '1000.00000000'),
  };
  assert.ok(esCero('0.00000000'));
  assert.ok(!filasFormula({ ...base, no_atribuibles: b('0.00000000', '', '0.00000000') }).some((f) => f.clave === 'salidas'));
  const conMerma = filasFormula({ ...base, no_atribuibles: b('2.00000000', '', '43.33333400') });
  assert.deepEqual(conMerma.map((f) => [f.signo, f.etiqueta, f.valor]).slice(3), [
    ['−', 'Saldo final (Kardex)', '3206.66666600'],
    ['=', 'Salidas del inventario', '1043.33333400'],
    ['−', 'Salidas que no son ventas', '43.33333400'],
    ['=', 'Costo de venta', '1000.00000000'],
  ]);
});

test('vista por año: años disponibles y parámetros', () => {
  assert.deepEqual(aniosDePeriodos([{ anio: 2023 }, { anio: 2026 }, { anio: 2023 }, { anio: 2024 }]), [2026, 2024, 2023]);
  assert.deepEqual(aniosDePeriodos([]), []);
  assert.deepEqual(paramsCostoVentaAnual({ anio: 2023 }), { anio: 2023 });
  assert.deepEqual(paramsCostoVentaAnual({ anio: 2023, producto_id: 7 }), { anio: 2023, producto_id: 7 });
  assert.deepEqual(paramsCostoVentaAnual({ anio: 2023, producto_id: '' }), { anio: 2023 });
});

test('comparación con el promedio: textos por mes, año y rango; diferencia con signo', () => {
  assert.equal(textosComparacion(false).ver, 'Ver comparación con promedio mensual');
  assert.equal(textosComparacion(false).columnaPromedio, 'Promedio mensual');
  assert.equal(textosComparacion(true).titulo, 'Comparación con el promedio del rango');
  assert.equal(textosComparacion(true).ver, 'Ver comparación con el promedio del rango');
  assert.equal(textosComparacion(true).columnaDiferencia, 'Diferencia (promedio − Kardex)');
  assert.equal(conSigno('29.21'), '+29.21');
  assert.equal(conSigno('-39.48'), '-39.48');
  assert.equal(conSigno('0.00'), '0.00');
  assert.equal(conSigno('-0.00'), '0.00');
});
