/// <reference types="node" />

import assert from 'node:assert/strict';
import test from 'node:test';
import { filaSaldoInicialKardex, guardarPeriodo, leerPeriodoGuardado, periodoInicialKardex, textoCppFinal } from './kardexVista.ts';

const fmt = (v: string) => Number(v).toFixed(6);

test('1. saldo inicial visible aunque no haya movimientos', () => {
  const fila = filaSaldoInicialKardex(
    { saldo_inicial_cantidad: '3.00000000', saldo_inicial_valor: '1.90000000' },
    [{ producto_id: 6, cantidad: '3.00000000', cpp: '0.63333300', valor: '1.90000000' }],
  );
  assert.deepEqual(fila, { mostrar: true, cantidad: '3.00000000', cpp: '0.63333300', valor: '1.90000000' });
});

test('saldo inicial cero no se muestra; varios productos sin CPP común', () => {
  assert.equal(filaSaldoInicialKardex({ saldo_inicial_cantidad: '0', saldo_inicial_valor: '0' }, []).mostrar, false);
  const varios = filaSaldoInicialKardex({ saldo_inicial_cantidad: '5', saldo_inicial_valor: '10' }, [
    { producto_id: 1, cantidad: '2', cpp: '1', valor: '2' }, { producto_id: 2, cantidad: '3', cpp: '2.666667', valor: '8' },
  ]);
  assert.equal(varios.cpp, null);
});

test('2. cpp_final null no se muestra como S/ 0.000000', () => {
  assert.equal(textoCppFinal(null, fmt), 'No aplica');
  assert.equal(textoCppFinal(undefined, fmt), 'No aplica');
  assert.equal(textoCppFinal('0.666667', fmt), 'S/ 0.666667');
  assert.equal(textoCppFinal('0.00000000', fmt), 'S/ 0.000000');
});

test('3. período inicial: selección guardada válida, si no el último abierto', () => {
  const periodos = [{ id: 4, estado: 'ABIERTO' }, { id: 3, estado: 'ABIERTO' }, { id: 2, estado: 'CERRADO' }];
  assert.equal(periodoInicialKardex(periodos, null), '4');
  assert.equal(periodoInicialKardex(periodos, '2'), '2');
  assert.equal(periodoInicialKardex(periodos, ''), '');      // "Todos los períodos" también se recuerda
  assert.equal(periodoInicialKardex(periodos, '99'), '4');   // guardado inválido (otra empresa o borrado)
  assert.equal(periodoInicialKardex([], null), '');
});

test('la selección se guarda por empresa y tolera almacenamiento no disponible', () => {
  const datos = new Map<string, string>();
  const almacen = { getItem: (k: string) => datos.get(k) ?? null, setItem: (k: string, v: string) => { datos.set(k, v); } } as Storage;
  guardarPeriodo(1, '2', almacen);
  assert.equal(leerPeriodoGuardado(1, almacen), '2');
  assert.equal(leerPeriodoGuardado(2, almacen), null);
  const roto = { getItem: () => { throw new Error('bloqueado'); }, setItem: () => { throw new Error('bloqueado'); } } as unknown as Storage;
  assert.equal(leerPeriodoGuardado(1, roto), null);
  assert.doesNotThrow(() => guardarPeriodo(1, '2', roto));
});
