/// <reference types="node" />

import assert from 'node:assert/strict';
import test from 'node:test';
import {
  abrirReapertura,
  cancelarReapertura,
  etiquetaEstadoCierre,
  ejecutarReapertura,
} from './reaperturaPeriodo.ts';

const periodo = { id: 2, anio: 2026, mes: 10 };

test('abre el modal para el periodo seleccionado', () => {
  const estado = abrirReapertura(periodo);
  assert.equal(estado.abierto, true);
  assert.deepEqual(estado.periodo, periodo);
});

test('cancelar cierra el modal sin ejecutar la API', () => {
  let llamadas = 0;
  const enviar = async () => { llamadas += 1; };
  const estado = cancelarReapertura();

  assert.equal(estado.abierto, false);
  assert.equal(llamadas, 0);
  void enviar;
});

test('confirmar ejecuta la API con el motivo normalizado', async () => {
  let llamada: unknown;
  const estado = { ...abrirReapertura(periodo), motivo: '  Corrección QA  ', enviando: true };
  const resultado = await ejecutarReapertura(estado, async (id, payload) => {
    llamada = { id, payload };
    return { mensaje: 'ok' };
  });

  assert.deepEqual(llamada, {
    id: 2,
    payload: { motivo_reapertura: 'Corrección QA' },
  });
  assert.equal(resultado.estado.abierto, false);
  assert.deepEqual(resultado.respuesta, { mensaje: 'ok' });
});

test('un error conserva abierto el modal y el texto escrito', async () => {
  const estado = { ...abrirReapertura(periodo), motivo: 'Corrección QA', enviando: true };
  const resultado = await ejecutarReapertura(estado, async () => {
    throw { response: { data: { detail: 'Error controlado' } } };
  });

  assert.equal(resultado.estado.abierto, true);
  assert.equal(resultado.estado.motivo, 'Corrección QA');
  assert.equal(resultado.estado.error, 'Error controlado');
});

test('un motivo inválido no ejecuta la API ni cierra el modal', async () => {
  let llamadas = 0;
  const estado = { ...abrirReapertura(periodo), motivo: '  x ', enviando: true };
  const resultado = await ejecutarReapertura(estado, async () => { llamadas += 1; });

  assert.equal(llamadas, 0);
  assert.equal(resultado.estado.abierto, true);
  assert.equal(resultado.estado.error, 'Ingrese un motivo de al menos 3 caracteres.');
});

test('el snapshot vigente se presenta como historico mientras el periodo esta reabierto', () => {
  assert.equal(etiquetaEstadoCierre(true, 'CERRADO'), 'Vigente');
  assert.equal(etiquetaEstadoCierre(true, 'ABIERTO'), 'Histórico');
});
