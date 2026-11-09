import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  aDecimal, aDecimalesBd, comparar, esMayorQueCero, formatearDecimal, multiplicar, redondear, restar, sumar,
} from './decimal.ts';

test('0.1 + 0.2 es exactamente 0.3 (en float sería 0.30000000000000004)', () => {
  assert.notEqual(0.1 + 0.2, 0.3);
  assert.equal(sumar('0.1', '0.2').toString(), '0.3');
  assert.equal(aDecimalesBd(sumar('0.1', '0.2')), '0.30000000');
});

test('ROUND_HALF_UP como Python (mitad lejos de cero), no como toFixed', () => {
  assert.equal((1.005).toFixed(2), '1.00'); // el error que se corrige
  assert.equal(redondear('1.005', 2), '1.01');
  assert.equal(redondear('0.045', 2), '0.05'); // HALF_EVEN daría 0.04
  assert.equal(redondear('2.5', 0), '3');
  assert.equal(redondear('-2.5', 0), '-3');
  assert.equal(redondear('-0.045', 2), '-0.05');
  assert.equal(aDecimalesBd('1.267345665'), '1.26734567');
});

test('productos de 8 × 8 decimales sin pérdida', () => {
  assert.equal(multiplicar('12.34567891', '0.00000001').toString(), '1.234567891e-7');
  assert.equal(aDecimalesBd(multiplicar('3.333', '12.345678')), '41.14814477');
  assert.equal(restar('0.3', '0.1').toString(), '0.2');
});

test('valores vacíos o inválidos', () => {
  assert.equal(aDecimal(''), null);
  assert.equal(aDecimal('abc'), null);
  assert.equal(aDecimal(Number.NaN), null);
  assert.equal(aDecimalesBd(''), '0.00000000');
  assert.equal(esMayorQueCero('0.00000001'), true);
  assert.equal(esMayorQueCero('0'), false);
  assert.equal(esMayorQueCero('x'), false);
  assert.equal(comparar('1.10', '1.1'), 0);
});

test('formato es-PE con redondeo decimal previo', () => {
  assert.equal(formatearDecimal('1.005'), '1.01');
  assert.equal(formatearDecimal('1234567.125'), '1,234,567.13');
  assert.equal(formatearDecimal('8.345'), '8.35');
  assert.equal(formatearDecimal('14.00000000', { min: 4, max: 6 }), '14.0000');
  assert.equal(formatearDecimal('0.1234565', { min: 2, max: 6 }), '0.123457');
  assert.equal(formatearDecimal(null), '—');
  assert.equal(formatearDecimal('', { vacio: '-' }), '-');
  assert.equal(formatearDecimal(140, { min: 2, max: 2 }), '140.00');
});
