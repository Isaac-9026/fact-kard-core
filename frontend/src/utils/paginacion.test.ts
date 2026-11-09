import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  PAGE_SIZE_DEFECTO, claveConsulta, irAPagina, leerPaginado, paginaVigente, paramsPaginacion, resumenPagina,
} from './paginacion.ts';

test('página 1 por defecto y parámetros enviados al backend', () => {
  const clave = claveConsulta(1, 'COMPRA');
  assert.equal(paginaVigente({ clave, page: 1 }, clave), 1);
  assert.deepEqual(paramsPaginacion(1), { page: 1, page_size: PAGE_SIZE_DEFECTO });
  assert.deepEqual(paramsPaginacion(0, 20), { page: 1, page_size: 20 });
  assert.deepEqual(paramsPaginacion(Number.NaN, 0), { page: 1, page_size: PAGE_SIZE_DEFECTO });
});

test('siguiente y anterior', () => {
  const clave = claveConsulta(1, '');
  let estado = irAPagina(clave, 1);
  const r1 = resumenPagina(paginaVigente(estado, clave), 50, 120);
  assert.deepEqual([r1.hayAnterior, r1.haySiguiente, r1.totalPaginas, r1.desde, r1.hasta], [false, true, 3, 1, 50]);
  estado = irAPagina(clave, r1.page + 1);
  const r2 = resumenPagina(paginaVigente(estado, clave), 50, 120);
  assert.deepEqual([r2.page, r2.hayAnterior, r2.haySiguiente, r2.desde, r2.hasta], [2, true, true, 51, 100]);
  estado = irAPagina(clave, r2.page + 1);
  const r3 = resumenPagina(paginaVigente(estado, clave), 50, 120, 20);
  assert.deepEqual([r3.page, r3.haySiguiente, r3.desde, r3.hasta], [3, false, 101, 120]);
  estado = irAPagina(clave, r3.page - 1);
  assert.equal(paginaVigente(estado, clave), 2);
});

test('cambiar un filtro reinicia a la página 1', () => {
  const antes = claveConsulta(1, 'COMPRA', '', '');
  const estado = irAPagina(antes, 4);
  assert.equal(paginaVigente(estado, antes), 4);
  assert.equal(paginaVigente(estado, claveConsulta(1, 'VENTA', '', '')), 1);
  assert.equal(paginaVigente(estado, claveConsulta(1, 'COMPRA', '', 'F001')), 1);
});

test('cambiar de empresa reinicia a la página 1', () => {
  const estado = irAPagina(claveConsulta(1, 'COMPRA'), 3);
  assert.equal(paginaVigente(estado, claveConsulta(2, 'COMPRA')), 1);
  // undefined/null y '' son la misma clave (sin filtro)
  assert.equal(claveConsulta(1, undefined), claveConsulta(1, ''));
});

test('total visible y lectura de la respuesta del backend', () => {
  const pag = leerPaginado({ count: 7, next: 'n', previous: null, results: [1, 2] });
  assert.deepEqual(pag, { count: 7, next: 'n', previous: null, results: [1, 2] });
  const r = resumenPagina(1, 2, pag.count, pag.results.length);
  assert.deepEqual([r.count, r.desde, r.hasta, r.totalPaginas], [7, 1, 2, 4]);
  // compatibilidad: servidor que devuelve la lista completa
  assert.deepEqual(leerPaginado([1, 2, 3]), { count: 3, next: null, previous: null, results: [1, 2, 3] });
  const vacio = resumenPagina(1, 50, 0, 0);
  assert.deepEqual([vacio.desde, vacio.hasta, vacio.totalPaginas, vacio.haySiguiente], [0, 0, 1, false]);
});

test('una página fuera de rango se muestra como la última', () => {
  const r = resumenPagina(9, 50, 60);
  assert.deepEqual([r.page, r.totalPaginas, r.haySiguiente], [2, 2, false]);
});
