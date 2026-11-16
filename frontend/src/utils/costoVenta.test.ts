import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  conceptosConImporte, cuadra, ETIQUETAS_DESGLOSE, filasFormula, nombreArchivoCostoVenta, paramsCostoVenta,
  sumarTexto, validarRangoPeriodos,
} from './costoVenta.ts';

test('parámetros: el período final igual al inicial no se envía; producto opcional', () => {
  assert.deepEqual(paramsCostoVenta({ periodo_id: 3 }), { periodo_id: 3 });
  assert.deepEqual(paramsCostoVenta({ periodo_id: 3, periodo_hasta_id: 3 }), { periodo_id: 3 });
  assert.deepEqual(paramsCostoVenta({ periodo_id: 3, periodo_hasta_id: 5, producto_id: 9 }),
    { periodo_id: 3, periodo_hasta_id: 5, producto_id: 9 });
  assert.deepEqual(paramsCostoVenta({ periodo_id: 3, periodo_hasta_id: '', producto_id: '' }), { periodo_id: 3 });
});

test('nombre del Excel igual al del backend', () => {
  assert.equal(nombreArchivoCostoVenta({ desde: '2026-01', ruc: '20123456789' }), 'Costo_de_venta_2026-01_20123456789.xlsx');
  assert.equal(nombreArchivoCostoVenta({ desde: '2026-01', hasta: '2026-01', ruc: '20123456789' }), 'Costo_de_venta_2026-01_20123456789.xlsx');
  assert.equal(nombreArchivoCostoVenta({ desde: '2026-01', hasta: '2026-03', ruc: '20123456789' }),
    'Costo_de_venta_2026-01_a_2026-03_20123456789.xlsx');
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
    ['−', 'Saldo final', '500.00000000'],
    ['=', 'Costo de venta', '530.00000000'],
  ]);
  assert.equal(filas[2].cantidad, null);
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
  const conceptos = conceptosConImporte({ ventas: '530.00000000', mermas_desmedros: '0.00000000', otros: '-1.5' }, ETIQUETAS_DESGLOSE);
  assert.deepEqual(conceptos.map((c) => c.clave), ['ventas', 'otros']);
});
