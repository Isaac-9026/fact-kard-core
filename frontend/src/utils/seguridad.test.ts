import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  agregarPasswordAlCuerpo, esPedidoDeConfirmacion, esSoloConsulta, mensajeDeConfirmacion, ultimaActividad,
  venciaPorInactividad,
} from './seguridad.ts';

test('reconoce el pedido de confirmar contraseña', () => {
  assert.ok(esPedidoDeConfirmacion(403, { detail: 'x', code: 'confirmacion_password' }));
  assert.ok(!esPedidoDeConfirmacion(403, { detail: 'Sin permiso' }));
  assert.ok(!esPedidoDeConfirmacion(400, { code: 'confirmacion_password' }));
  assert.ok(!esPedidoDeConfirmacion(403, null));
});

test('mensaje de confirmación', () => {
  assert.equal(mensajeDeConfirmacion({ detail: 'La contraseña de confirmación es incorrecta.' }),
    'La contraseña de confirmación es incorrecta.');
  assert.equal(mensajeDeConfirmacion(undefined), 'Para esta acción debe confirmar su contraseña.');
});

test('agrega la contraseña sin perder el cuerpo original', () => {
  assert.deepEqual(JSON.parse(agregarPasswordAlCuerpo('{"motivo":"Error"}', 'clave')),
    { motivo: 'Error', password_confirmacion: 'clave' });
  assert.deepEqual(JSON.parse(agregarPasswordAlCuerpo({ producto: 3 }, 'clave')),
    { producto: 3, password_confirmacion: 'clave' });
  assert.deepEqual(JSON.parse(agregarPasswordAlCuerpo(undefined, 'clave')), { password_confirmacion: 'clave' });
  assert.deepEqual(JSON.parse(agregarPasswordAlCuerpo('no es json', 'clave')), { password_confirmacion: 'clave' });
});

test('cierre por inactividad a los 30 minutos', () => {
  const t0 = 1_000_000;
  assert.ok(!venciaPorInactividad(t0, t0 + 29 * 60 * 1000));
  assert.ok(venciaPorInactividad(t0, t0 + 30 * 60 * 1000));
});

test('rol CONSULTA es solo lectura (salvo el admin global)', () => {
  assert.ok(esSoloConsulta('CONSULTA'));
  assert.ok(!esSoloConsulta('CONSULTA', true));
  assert.ok(!esSoloConsulta('USUARIO'));
});

test('la actividad de otra pestaña cuenta para la inactividad', () => {
  assert.equal(ultimaActividad(1_000, 5_000), 5_000);
  assert.equal(ultimaActividad(7_000, 0), 7_000);
  assert.equal(ultimaActividad(0, NaN), 0);
});
