import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  disponibleEnUnidad, errorLineasNota, esDevolucionFisica, etiquetaLineaOrigen, lineasOrigenElegibles, type LineaOrigen,
} from './devolucionNota.ts';

const origen: LineaOrigen[] = [
  { id: 11, linea: 1, producto: 5, producto_codigo: 'P-C-1', producto_unidad: 50, unidad_codigo: 'NIU', almacen: 6,
    cantidad_original: '10.00000000', factor_conversion: '1.00000000', cantidad_base: '10.00000000', precio_unitario: '12.50000000',
    cantidad_disponible_devolucion: '7.00000000' },
  { id: 12, linea: 2, producto: 39, producto_codigo: 'P-C-2', producto_unidad: 51, unidad_codigo: 'CJA', almacen: 6,
    cantidad_original: '2.00000000', factor_conversion: '12.00000000', cantidad_base: '24.00000000', precio_unitario: '40.00000000',
    cantidad_disponible_devolucion: '24.00000000' },
  { id: 13, linea: 3, producto: 5, producto_codigo: 'P-C-1', producto_unidad: 50, unidad_codigo: 'NIU', almacen: 6,
    cantidad_original: '1.00000000', factor_conversion: '1.00000000', cantidad_base: '1.00000000', precio_unitario: '12.50000000',
    cantidad_disponible_devolucion: '0.00000000' },
];

test('lista solo las líneas con cantidad por devolver y muestra lo disponible', () => {
  assert.deepEqual(lineasOrigenElegibles(origen).map((l) => l.id), [11, 12]);
  assert.equal(etiquetaLineaOrigen(origen[0]), '#1 P-C-1 · 10.00 NIU · disponible 7.00 NIU');
  assert.equal(disponibleEnUnidad(origen[1]), '2.00000000'); // 24 base / factor 12 = 2 cajas
});

test('devolución física sin línea de origen: error claro (antes el backend la rechazaba sin forma de elegirla)', () => {
  const linea = { productoId: 5, cantidadOriginal: '1', factorConversion: '1', naturaleza: 'SALIDA' };
  assert.match(errorLineasNota([linea], origen) ?? '', /Línea 1: seleccione la línea del comprobante de origen/);
  assert.equal(esDevolucionFisica('AJUSTE_VALOR'), false);
  assert.equal(esDevolucionFisica('ENTRADA', false), false);
});

test('no deja devolver más de lo disponible (sumando líneas que apuntan a la misma línea de origen)', () => {
  const l = (cantidad: string) => ({ detalleOrigenId: 11, productoId: 5, cantidadOriginal: cantidad, factorConversion: '1', naturaleza: 'SALIDA' });
  assert.equal(errorLineasNota([l('7')], origen), null);
  assert.match(errorLineasNota([l('7.000001')], origen) ?? '', /más de lo disponible en la línea de origen #1/);
  assert.match(errorLineasNota([l('4'), l('4')], origen) ?? '', /Línea 2: se devuelve más de lo disponible/);
  // En otra unidad: 2 cajas × 12 = 24 base = todo lo disponible.
  assert.equal(errorLineasNota([{ detalleOrigenId: 12, productoId: 39, cantidadOriginal: '2', factorConversion: '12', naturaleza: 'ENTRADA' }], origen), null);
});

test('producto distinto al de la línea de origen', () => {
  assert.match(errorLineasNota([{ detalleOrigenId: 11, productoId: 39, cantidadOriginal: '1', factorConversion: '1', naturaleza: 'SALIDA' }], origen) ?? '',
    /el producto debe ser el de la línea de origen #1 \(P-C-1\)/);
});

test('NC de descuento (ajuste de valor) sigue funcionando con o sin línea de origen', () => {
  assert.equal(errorLineasNota([{ productoId: 5, cantidadOriginal: '1', factorConversion: '1', naturaleza: 'AJUSTE_VALOR' }], origen), null);
  assert.equal(errorLineasNota([{ detalleOrigenId: 13, productoId: 5, cantidadOriginal: '1', factorConversion: '1', naturaleza: 'AJUSTE_VALOR' }], origen), null);
});
