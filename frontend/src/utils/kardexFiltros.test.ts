/// <reference types="node" />

import assert from 'node:assert/strict';
import test from 'node:test';
import { filtrosKardexDesdeFormulario, parametrosKardex } from './kardexFiltros.ts';

const formularioConRango = () => {
  const datos = new FormData();
  datos.set('producto_id', '2');
  datos.set('periodo_id', '2');
  datos.set('fecha_desde', '2026-10-21');
  datos.set('fecha_hasta', '2026-10-21');
  return datos;
};

test('construye ambos parametros de fecha con los valores visibles del formulario', () => {
  const filtros = filtrosKardexDesdeFormulario(formularioConRango());

  assert.deepEqual(parametrosKardex(filtros), {
    producto_id: 2,
    periodo_id: 2,
    fecha_desde: '2026-10-21',
    fecha_hasta: '2026-10-21',
  });
});

test('construir la consulta no modifica ni limpia las fechas del formulario', () => {
  const datos = formularioConRango();
  filtrosKardexDesdeFormulario(datos);
  parametrosKardex(filtrosKardexDesdeFormulario(datos));

  assert.equal(datos.get('fecha_desde'), '2026-10-21');
  assert.equal(datos.get('fecha_hasta'), '2026-10-21');
});
