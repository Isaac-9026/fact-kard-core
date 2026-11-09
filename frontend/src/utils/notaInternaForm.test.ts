/// <reference types="node" />

import assert from 'node:assert/strict';
import test from 'node:test';
import {
  campoFechaNotaInterna,
  formularioNotaTrasRespuesta,
} from './notaInternaForm.ts';

test('construye el campo fecha del payload sin transformar la fecha calendario', () => {
  assert.deepEqual(campoFechaNotaInterna('2026-10-21'), {
    fecha: '2026-10-21',
  });
});

test('una respuesta 400 conserva el formulario y su fecha', () => {
  const formulario = { fecha: '2026-10-21', motivo: 'MERMA QA' };

  assert.strictEqual(formularioNotaTrasRespuesta(formulario, false), formulario);
  assert.equal(formularioNotaTrasRespuesta(formulario, false)?.fecha, '2026-10-21');
});

test('un guardado exitoso permite cerrar y resetear el formulario', () => {
  assert.equal(formularioNotaTrasRespuesta({ fecha: '2026-10-21' }, true), null);
});
