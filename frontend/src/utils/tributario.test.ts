import { test } from 'node:test';
import assert from 'node:assert/strict';
import { errorUbigeo, catalogoMotivo } from './tributario.ts';

test('ubigeo INEI', () => {
  assert.equal(errorUbigeo('150101'), null);
  assert.equal(errorUbigeo('250101'), null);
  assert.match(errorUbigeo('1501') ?? '', /6 dígitos/);
  assert.match(errorUbigeo('260101') ?? '', /01 y 25/);
  assert.match(errorUbigeo('000101') ?? '', /01 y 25/);
  assert.match(errorUbigeo('150001') ?? '', /no pueden ser 00/);
  assert.match(errorUbigeo('150100') ?? '', /no pueden ser 00/);
});

test('catálogo de motivo según el tipo de nota', () => {
  assert.equal(catalogoMotivo('07'), '09');
  assert.equal(catalogoMotivo('08'), '10');
  assert.equal(catalogoMotivo('01'), null);
  assert.equal(catalogoMotivo(undefined), null);
});
