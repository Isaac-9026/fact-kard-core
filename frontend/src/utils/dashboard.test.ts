import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  SIN_DATO, contarPendientes, etiquetaPeriodo, pasosCierre, periodoActivo, resumenUltimoCierre, textoODato,
} from './dashboard.ts';

const periodos = [
  { id: 12, anio: 2026, mes: 3, estado: 'ABIERTO' },
  { id: 11, anio: 2026, mes: 2, estado: 'ABIERTO' },
  { id: 10, anio: 2026, mes: 1, estado: 'CERRADO' },
];

test('período activo: selección guardada válida o el abierto más reciente', () => {
  assert.equal(periodoActivo(periodos, null)?.id, 12);
  assert.equal(periodoActivo(periodos, '10')?.id, 10);
  assert.equal(periodoActivo(periodos, '999')?.id, 12);
  assert.equal(periodoActivo([], null), null);
  assert.equal(etiquetaPeriodo(periodos[0]), '2026-03');
  assert.equal(etiquetaPeriodo(null), SIN_DATO);
});

test('incidencias pendientes', () => {
  assert.equal(contarPendientes([{ estado: 'PENDIENTE' }, { estado: 'RESUELTA' }, { estado: 'PENDIENTE' }]), 2);
  assert.equal(contarPendientes([]), 0);
});

test('último cierre: el primero que devuelve el backend', () => {
  const r = resumenUltimoCierre([
    { periodo_info: { anio: 2026, mes: 1, estado: 'CERRADO' }, version_calculo: 2, vigente: true, cerrado_en: '2026-02-03T10:00:00Z', cerrado_por_username: 'ana' },
    { periodo_info: { anio: 2025, mes: 12, estado: 'CERRADO' }, version_calculo: 1, vigente: true, cerrado_en: '2026-01-05T10:00:00Z', cerrado_por_username: 'ana' },
  ]);
  assert.deepEqual(r, { titulo: '2026-01 · CERRADO', detalle: 'Versión 2 (vigente) · 2026-02-03 · ana' });
  assert.equal(resumenUltimoCierre([]), null);
});

test('un dato faltante se muestra como —, nunca como 0', () => {
  assert.equal(textoODato(null), SIN_DATO);
  assert.equal(textoODato(undefined), SIN_DATO);
  assert.equal(textoODato(''), SIN_DATO);
  assert.equal(textoODato(0), '0');
  assert.equal(textoODato('12.5', (v) => `S/ ${v}`), 'S/ 12.5');
});

test('pasos del cierre del mes', () => {
  const periodo = { id: 1, anio: 2026, mes: 11, estado: 'ABIERTO' };
  const base = { empresa: 'MAIZ DEL ABRA', periodo, valorTotal: '2003', pendientes: 0, bloqueantes: 0 };
  assert.deepEqual(pasosCierre(base).map((p) => p.listo), [true, true, true, false]);
  const bloqueado = pasosCierre({ ...base, pendientes: 2, bloqueantes: 1 });
  assert.equal(bloqueado[2].listo, false);
  assert.equal(bloqueado[2].detalle, '1 incidencia bloquea el cierre');
  assert.equal(pasosCierre({ ...base, periodo: { ...periodo, estado: 'CERRADO' } })[3].listo, true);
  const vacio = pasosCierre({ empresa: null, periodo: null, valorTotal: null, pendientes: null, bloqueantes: 0 });
  assert.deepEqual(vacio.map((p) => p.listo), [false, false, false, false]);
});
