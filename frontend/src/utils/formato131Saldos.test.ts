/// <reference types="node" />

import assert from 'node:assert/strict';
import test from 'node:test';
import { filaSaldoFinal, filaSaldoInicial, formatoContable } from './formato131Saldos.ts';

const reporte = {
  saldo_inicial: '1250.00000000',
  saldo_inicial_valorizado: { cantidad: '1250.00000000', costo_unitario: '10.68750000', costo_total: '13359.37500000' },
  saldo_final: { cantidad: '1300.00000000', costo_unitario: '10.70000000', costo_total: '13910.00000000' },
  movimientos: [{}],
};

test('1. saldo inicial valorizado visible', () => {
  const fila = filaSaldoInicial(reporte);
  assert.equal(fila.cantidad, '1,250.00000000');
  assert.notEqual(fila.costoTotal, '—');
});

test('2. CU inicial es el del backend, sin recalcular', () => {
  assert.equal(filaSaldoInicial(reporte).costoUnitario, '10.68750000');
});

test('3. CT inicial es el histórico del backend (no cantidad × CU)', () => {
  const historico = { ...reporte, saldo_inicial_valorizado: { ...reporte.saldo_inicial_valorizado, costo_total: '13359.37500001' } };
  assert.equal(filaSaldoInicial(historico).costoTotal, '13,359.37500001');
});

test('4. valores cero', () => {
  const cero = { saldo_inicial: '0E-8', saldo_inicial_valorizado: { cantidad: '0.00000000', costo_unitario: '0.00000000', costo_total: '0.00000000' }, saldo_final: { cantidad: '0.00000000', costo_unitario: '0.00000000', costo_total: '0.00000000' }, movimientos: [] };
  assert.deepEqual(filaSaldoInicial(cero), { cantidad: '0.00000000', costoUnitario: '0.00000000', costoTotal: '0.00000000' });
});

test('5. sin movimientos pero con saldo inicial', () => {
  const sinMovs = { ...reporte, movimientos: [], saldo_final: reporte.saldo_inicial_valorizado };
  assert.equal(filaSaldoInicial(sinMovs).costoTotal, '13,359.37500000');
  assert.deepEqual(filaSaldoFinal(sinMovs), filaSaldoInicial(sinMovs));
});

test('no pierde precisión ni redondea', () => {
  assert.equal(formatoContable('123456789012.12345678'), '123,456,789,012.12345678');
  assert.equal(formatoContable('-0.00000001'), '-0.00000001');
  assert.equal(formatoContable(null), '—');
});

test('respuesta sin bloque valorizado no inventa importes', () => {
  const antigua = { saldo_inicial: '5.00000000', saldo_final: null, movimientos: [] };
  assert.deepEqual(filaSaldoInicial(antigua), { cantidad: '5.00000000', costoUnitario: '—', costoTotal: '—' });
});
