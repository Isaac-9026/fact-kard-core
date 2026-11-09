/// <reference types="node" />

import assert from 'node:assert/strict';
import test from 'node:test';
import { fechaCalendarioFormulario, fechaCalendarioLocal } from './date.ts';

test('conserva el dia calendario local aunque UTC pueda estar en el dia siguiente', () => {
  const nocheLocal = new Date(2026, 9, 21, 23, 30, 0);

  assert.equal(fechaCalendarioLocal(nocheLocal), '2026-10-21');
  assert.equal(nocheLocal.toISOString().slice(0, 10), '2026-10-22');
});

test('conserva exactamente la fecha calendario usada en el payload', () => {
  assert.equal(fechaCalendarioFormulario('2026-10-21'), '2026-10-21');
  assert.equal(fechaCalendarioFormulario('2026-10-21T00:00:00Z'), '');
});
