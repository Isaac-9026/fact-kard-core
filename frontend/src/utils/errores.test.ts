import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mensajeDeError } from './errores.ts';

const err = (data: unknown) => ({ response: { data } });

test('usa el primer campo con contenido en el orden indicado', () => {
  assert.equal(mensajeDeError(err({ detail: 'D', archivo: 'A' }), ['archivo', 'detail'], 'x'), 'A');
  assert.equal(mensajeDeError(err({ detail: 'D' }), ['archivo', 'detail'], 'x'), 'D');
});

test('une las listas de errores de DRF', () => {
  assert.equal(mensajeDeError(err({ periodo: ['Periodo cerrado.', 'Otro.'] }), ['detail', 'periodo'], 'x'), 'Periodo cerrado. Otro.');
});

test('sin respuesta o sin campos conocidos usa el texto por defecto', () => {
  assert.equal(mensajeDeError(new Error('red'), ['detail'], 'Por defecto'), 'Por defecto');
  assert.equal(mensajeDeError(null, ['detail'], 'Por defecto'), 'Por defecto');
  assert.equal(mensajeDeError(err({ detail: '' }), ['detail'], 'Por defecto'), 'Por defecto');
  assert.equal(mensajeDeError(err('texto plano'), ['detail'], 'Por defecto'), 'Por defecto');
});

import { mensajesDeErrorApi } from './errores.ts';

test('mensajesDeErrorApi: el detail del backend va primero y sin prefijo', () => {
  assert.deepEqual(mensajesDeErrorApi(err({ detail: 'El período está cerrado.' }), 'x'), ['El período está cerrado.']);
  assert.deepEqual(
    mensajesDeErrorApi(err({ serie: ['Obligatorio.'], non_field_errors: ['Comprobante duplicado.'] }), 'x'),
    ['Comprobante duplicado.', 'Serie: Obligatorio.'],
  );
});

test('mensajesDeErrorApi: errores por línea del detalle con su número y todos los mensajes', () => {
  const data = { detalles: [{}, { igv: ['IGV fuera de tolerancia.'], cantidad_original: ['Debe ser mayor a 0.'] }] };
  assert.deepEqual(mensajesDeErrorApi(err(data), 'x'), ['Línea 2 · IGV: IGV fuera de tolerancia.', 'Línea 2 · Cantidad: Debe ser mayor a 0.']);
});

test('mensajesDeErrorApi: detalles como texto (ya nombra la línea) va sin prefijo', () => {
  assert.deepEqual(mensajesDeErrorApi(err({ detalles: 'Línea 1: el IGV 99.99 no corresponde.' }), 'x'), ['Línea 1: el IGV 99.99 no corresponde.']);
});

test('mensajesDeErrorApi: objetos simples del backend (stock) y campos desconocidos', () => {
  assert.deepEqual(mensajesDeErrorApi(err({ stock: 'Stock insuficiente para confirmar el movimiento.' }), 'x'), ['Stock: Stock insuficiente para confirmar el movimiento.']);
  assert.deepEqual(mensajesDeErrorApi(err({ campo_nuevo: ['A', 'A'] }), 'x'), ['campo_nuevo: A']);
});

test('mensajesDeErrorApi: sin respuesta usa el texto por defecto', () => {
  assert.deepEqual(mensajesDeErrorApi(new Error('red'), 'Error al guardar.'), ['Error al guardar.']);
  assert.deepEqual(mensajesDeErrorApi(err({}), 'Error al guardar.'), ['Error al guardar.']);
  assert.deepEqual(mensajesDeErrorApi(err('<html>500</html>'), 'Error al guardar.'), ['Error al guardar.']);
});
