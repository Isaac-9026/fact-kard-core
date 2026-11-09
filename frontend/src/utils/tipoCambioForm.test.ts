/// <reference types="node" />

import assert from 'node:assert/strict';
import test from 'node:test';
import {
  FechaTipoCambioInvalidaError,
  nuevoTipoCambioInicial,
  payloadTipoCambio,
} from './tipoCambioForm.ts';

// FE-001: QA ingresó 2026-10-01 y se almacenó otra fecha.
for (const fecha of ['2026-10-01', '2026-10-22', '2026-10-31']) {
  test(`envía literalmente la fecha elegida ${fecha}`, () => {
    const form = { ...nuevoTipoCambioInicial(new Date(2026, 9, 25, 21, 0, 0)), fecha_publicacion: fecha };
    const payload = payloadTipoCambio({ ...form, compra: '3.70000000', venta: '3.71000000' });

    assert.equal(form.fecha_publicacion, fecha); // valor mostrado
    assert.equal(payload.fecha_publicacion, fecha); // payload enviado
    assert.deepEqual(payload, {
      moneda_codigo: 'USD',
      fecha_publicacion: fecha,
      compra: '3.70000000',
      venta: '3.71000000',
      fuente: 'SBS',
    });
  });
}

test('la fecha por defecto es el día calendario local, no el día UTC', () => {
  const nocheLima = new Date(2026, 9, 24, 21, 30, 0);
  assert.equal(nuevoTipoCambioInicial(nocheLima).fecha_publicacion, '2026-10-24');
});

test('rechaza fechas vacías o con hora en lugar de enviarlas', () => {
  const base = nuevoTipoCambioInicial(new Date(2026, 9, 1, 10, 0, 0));
  assert.throws(() => payloadTipoCambio({ ...base, fecha_publicacion: '' }), FechaTipoCambioInvalidaError);
  assert.throws(
    () => payloadTipoCambio({ ...base, fecha_publicacion: '2026-10-01T00:00:00Z' }),
    FechaTipoCambioInvalidaError,
  );
});

test('usa SBS cuando la fuente queda vacía', () => {
  const base = nuevoTipoCambioInicial(new Date(2026, 9, 1, 10, 0, 0));
  assert.equal(payloadTipoCambio({ ...base, fuente: '   ' }).fuente, 'SBS');
});
