import { test } from 'node:test';
import assert from 'node:assert/strict';
import { construirFilasStock } from './stockActual.ts';

const productos = [
  { id: 1, codigo_interno: 'P-002', descripcion: 'Tornillo', unidad_base: { codigo: 'NIU' } },
  { id: 2, codigo_interno: 'P-001', descripcion: 'Cemento', unidad_base: { codigo: 'BG' } },
];
const almacenes = [{ id: 5, codigo: 'A1', nombre: 'Central' }, { id: 6, codigo: 'A2', nombre: 'Sur' }];
const saldos = [
  { producto_id: 1, cantidad_total: 0, valor_total_pen: 0, cpp_pen: 0 },
  { producto_id: 2, cantidad_total: '10.00000000', valor_total_pen: 140, cpp_pen: '14.00000000' },
];
const stocks = [
  { producto_id: 2, almacen_id: 6, cantidad_actual: 4 },
  { producto_id: 2, almacen_id: 5, cantidad_actual: '6' },
  { producto_id: 1, almacen_id: 5, cantidad_actual: 0 },
];

test('une saldos del motor con nombres, sin recalcular', () => {
  const filas = construirFilasStock(saldos, stocks, productos, almacenes);
  assert.equal(filas.length, 1); // sin stock se oculta por defecto
  assert.deepEqual(filas[0], {
    productoId: 2, codigo: 'P-001', descripcion: 'Cemento', unidad: 'BG', cantidad: 10, cpp: 14, valor: 140,
    almacenes: [{ almacenId: 5, almacen: 'A1 · Central', cantidad: 6 }, { almacenId: 6, almacen: 'A2 · Sur', cantidad: 4 }],
  });
});

test('opción para incluir productos sin stock, ordenados por código', () => {
  const filas = construirFilasStock(saldos, stocks, productos, almacenes, { incluirSinStock: true });
  assert.deepEqual(filas.map((f) => f.codigo), ['P-001', 'P-002']);
  assert.deepEqual(filas[1].almacenes, []); // almacenes en cero nunca se listan
});

test('producto o almacén no encontrado no rompe la vista', () => {
  const filas = construirFilasStock([{ producto_id: 9, cantidad_total: 1, valor_total_pen: 2, cpp_pen: null }],
    [{ producto_id: 9, almacen_id: 77, cantidad_actual: 1 }], [], []);
  assert.equal(filas[0].codigo, '#9');
  assert.equal(filas[0].cpp, null);
  assert.equal(filas[0].almacenes[0].almacen, '#77');
});
