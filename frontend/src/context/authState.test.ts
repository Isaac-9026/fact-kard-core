/// <reference types="node" />

import assert from 'node:assert/strict';
import test from 'node:test';
import type { EmpresaActiva, EmpresaAsociada } from '../types/auth.ts';
import { reconciliarEstadoEmpresas } from './authState.ts';

const demo: EmpresaAsociada = {
  id: 1,
  ruc: '94613584951',
  razon_social: 'EMPRESA DEMO FACT-KARD',
  rol: 'USUARIO',
  activo: true,
};
const otra: EmpresaAsociada = {
  id: 2,
  ruc: '20123456789',
  razon_social: 'OTRA EMPRESA',
  rol: 'ADMIN',
  activo: true,
};

test('usuario con empresa asignada conserva la lista accesible', () => {
  assert.deepEqual(reconciliarEstadoEmpresas([demo], null).empresas, [demo]);
});

test('empresa activa valida se conserva', () => {
  const activa: EmpresaActiva = { ...demo };
  assert.equal(reconciliarEstadoEmpresas([otra, demo], activa).empresaActiva?.id, demo.id);
});

test('empresa activa obsoleta se sustituye por una accesible', () => {
  const obsoleta: EmpresaActiva = { ...demo, id: 99 };
  assert.equal(reconciliarEstadoEmpresas([otra], obsoleta).empresaActiva?.id, otra.id);
});

test('respuesta vacia limpia la empresa activa', () => {
  assert.equal(reconciliarEstadoEmpresas([], { ...demo }).empresaActiva, null);
});

test('recarga reconcilia una empresa persistida con la lista persistida', () => {
  const restaurado = reconciliarEstadoEmpresas([demo, otra], { ...demo });
  assert.equal(restaurado.empresaActiva?.id, demo.id);
  assert.equal(restaurado.empresas.length, 2);
});

test('error de API representado por lista no validada no deja estado contradictorio', () => {
  const estadoSeguro = reconciliarEstadoEmpresas([], { ...demo });
  assert.equal(estadoSeguro.empresas.length, 0);
  assert.equal(estadoSeguro.empresaActiva, null);
});
