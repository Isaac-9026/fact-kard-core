import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  aNumeroGrafico, anchoMargen, destacados, esNegativo, filtrarProductos, tendenciaKpi, etiquetaMes, haySerie, nombreMes, ordenarProductos, participacionGrafico, recortar,
  serieMensualGrafico, tendencia, topInventarioGrafico, COLORES,
} from './graficosDashboard.ts';
import type { GraficosDashboardResponse, ProductoVenta } from '../api/dashboard.ts';

const periodo = (anio: number, mes: number) => ({ id: mes, anio, mes, estado: 'ABIERTO', etiqueta: `${anio}-${mes}` });
const mes = (m: number, ventas: string, costo: string, compras = '0') => ({
  periodo: periodo(2026, m), ventas, costo_venta: costo, margen: '0', margen_pct: null, compras, comprobantes: 0,
});

test('los importes de texto se dibujan como número y se muestran con el texto original', () => {
  const [enero] = serieMensualGrafico([mes(1, '795.12345678', '530', '1000')]);
  assert.equal(enero.mes, 'Ene 26');
  assert.equal(enero.ventas, 795.12345678);
  assert.equal(enero.ventasTexto, '795.12345678');
  assert.equal(enero.compras, 1000);
});

test('valores inválidos se dibujan en cero', () => {
  assert.equal(aNumeroGrafico('abc'), 0);
  assert.equal(aNumeroGrafico(null), 0);
  assert.equal(aNumeroGrafico('12.5'), 12.5);
});

test('etiquetas de mes y nombres largos', () => {
  assert.equal(etiquetaMes(2026, 9), 'Set 26');
  assert.equal(nombreMes(2026, 11), 'noviembre 2026');
  assert.equal(recortar('Arroz extra costeño bolsa de 50 kg', 12), 'Arroz extra…');
  assert.equal(recortar('Azúcar', 12), 'Azúcar');
});

test('tendencia y negativos sin pasar por float', () => {
  assert.equal(tendencia({ variacion_pct: '12.50' }), 'sube');
  assert.equal(tendencia({ variacion_pct: '-0.01' }), 'baja');
  assert.equal(tendencia({ variacion_pct: '0.00' }), 'igual');
  assert.equal(tendencia({ variacion_pct: null }), 'sin-dato');
  assert.equal(esNegativo('-0.01'), true);
  assert.equal(esNegativo('0'), false);
  assert.equal(esNegativo(null), false);
});

test('serie vacía o en cero no se dibuja', () => {
  assert.equal(haySerie([]), false);
  assert.equal(haySerie(serieMensualGrafico([mes(1, '0', '0')])), false);
  assert.equal(haySerie(serieMensualGrafico([mes(1, '0', '0', '5')])), true);
});

test('participación: Otros va en gris y el resto en orden fijo', () => {
  const sectores = participacionGrafico([
    { nombre: 'Maíz', ventas: '700', porcentaje: '70.00' },
    { nombre: 'Otros', ventas: '300', porcentaje: '30.00' },
  ]);
  assert.equal(sectores[0].color, '#2a78d6');
  assert.equal(sectores[1].color, COLORES.otros);
  assert.equal(sectores[0].ventasTexto, '700');
});

test('inventario: ancho relativo al de mayor valor y días de stock', () => {
  const prod = (id: number, valor: string, dias: string | null) => ({
    producto: { id, codigo: `P00${id}`, descripcion: `Prod ${id}` }, cantidad: '5', valor, dias_stock: dias,
  });
  const [a, b, c] = topInventarioGrafico([prod(1, '620', '35'), prod(2, '310', null), prod(3, '1', '2')]);
  assert.equal(a.detalle, 'P001 · Prod 1');
  assert.equal(a.ancho, 100);
  assert.equal(b.ancho, 50);
  assert.equal(c.ancho, 2);
  assert.equal(b.diasStock, null);
});

test('mini tendencia y barrita de margen', () => {
  assert.deepEqual(tendenciaKpi([mes(1, '10', '4'), mes(2, '20.5', '8')], 'ventas'), [{ i: 0, v: 10 }, { i: 1, v: 20.5 }]);
  assert.equal(anchoMargen('29.14'), 29);
  assert.equal(anchoMargen('-5.2'), 5);
  assert.equal(anchoMargen('0.4'), 3);
  assert.equal(anchoMargen('250'), 100);
  assert.equal(anchoMargen(null), 0);
});

const kpi = (actual: string) => ({ actual, anterior: null, variacion_pct: null });
const fila = (id: number, ventas: string, margen: string, pct: string | null): ProductoVenta => ({
  producto: { id, codigo: `P${id}`, descripcion: `Prod ${id}` }, unidad: 'NIU', unidades: '1', costo_unitario: '1',
  ventas, costo_venta: '0', margen, margen_pct: pct,
});
const datosBase = (): GraficosDashboardResponse => ({
  moneda: 'PEN', producto: null, periodo: periodo(2026, 11),
  kpis: { ventas: kpi('1000'), costo_venta: kpi('700'), margen: kpi('300'), compras: kpi('900'), margen_pct: '30.00', comprobantes: 3 },
  serie_mensual: [], mejor_mes: { periodo: periodo(2026, 11), ventas: '1000' },
  productos: [fila(1, '800', '280', '35.00'), fila(2, '200', '-10', '-5.00')],
  participacion: [{ nombre: 'Prod 1', ventas: '800', porcentaje: '80.00' }, { nombre: 'Prod 2', ventas: '200', porcentaje: '20.00' }],
  inventario: { valor_total: '500', productos_con_stock: 2, top_productos: [
    { producto: { id: 1, codigo: 'P1', descripcion: 'Prod 1' }, cantidad: '10', valor: '400', dias_stock: '12' },
    { producto: { id: 3, codigo: 'P3', descripcion: 'Prod 3' }, cantidad: '4', valor: '100', dias_stock: null },
  ] },
});

test('lo destacado del mes', () => {
  const frases = destacados(datosBase());
  assert.deepEqual(frases.map((f) => f.clave), ['mejor', 'top', 'margen', 'compras', 'stock', 'quietos']);
  assert.match(frases[0].texto, /noviembre 2026 con S\/ 1,000\.00/);
  assert.match(frases[1].texto, /Prod 1 \(80\.00 % de las ventas\)/);
  assert.equal(frases[2].tono, 'malo');
  assert.match(frases[2].texto, /Pierdes dinero con Prod 2: margen -5\.00 %/);
  assert.match(frases[3].texto, /S\/ 200\.00 más.*crece/);
  assert.match(frases[4].texto, /Prod 1: stock para unos 12 días/);
  assert.match(frases[5].texto, /Prod 3 tiene stock pero no se vendió/);
});

test('lo destacado con un producto filtrado y sin ventas', () => {
  const d = datosBase();
  d.producto = { id: 1, codigo: 'P1', descripcion: 'Prod 1' };
  d.productos = [fila(1, '800', '280', '35.00')];
  const frases = destacados(d);
  assert.ok(!frases.some((f) => f.clave === 'top'));
  assert.equal(frases.find((f) => f.clave === 'margen')?.texto, 'Margen del producto: 35.00 %.');
  const vacio = { ...datosBase(), kpis: null, mejor_mes: null, productos: [], participacion: [],
    inventario: { valor_total: '0', productos_con_stock: 0, top_productos: [] } };
  assert.deepEqual(destacados(vacio), []);
});

test('ordenar productos por columna decimal', () => {
  const fila = (id: number, margen: string, pct: string | null): ProductoVenta => ({
    producto: { id, codigo: `P${id}`, descripcion: `P${id}` }, unidad: 'NIU', unidades: '1', costo_unitario: '1',
    ventas: '10', costo_venta: '5', margen, margen_pct: pct,
  });
  const filas = [fila(1, '9.5', '10'), fila(2, '10', null), fila(3, '-2', '-5')];
  assert.deepEqual(ordenarProductos(filas, 'margen').map((f) => f.producto.id), [2, 1, 3]);
  assert.deepEqual(ordenarProductos(filas, 'margen', false).map((f) => f.producto.id), [3, 1, 2]);
  assert.deepEqual(ordenarProductos(filas, 'margen_pct').map((f) => f.producto.id), [1, 3, 2]);
});

test('buscar producto por código o nombre sin importar tildes ni mayúsculas', () => {
  const lista = [
    { id: 1, codigo_interno: 'P-007', descripcion: 'MAÍZ AMARILLO DURO 50 KG' },
    { id: 2, codigo_interno: 'P-003', descripcion: 'AZÚCAR RUBIA 50 KG' },
  ];
  assert.deepEqual(filtrarProductos(lista, 'maiz').map((p) => p.id), [1]);
  assert.deepEqual(filtrarProductos(lista, 'p-003').map((p) => p.id), [2]);
  assert.deepEqual(filtrarProductos(lista, '50 kg').map((p) => p.id), [1, 2]);
  assert.deepEqual(filtrarProductos(lista, 'azucar duro'), []);
  assert.equal(filtrarProductos(lista, '', 1).length, 1);
});

test('el resto de productos va en gris', () => {
  const [, resto] = participacionGrafico([
    { nombre: 'Maíz', ventas: '795', porcentaje: '79.50' },
    { nombre: 'Resto de productos', ventas: '205', porcentaje: '20.50' },
  ]);
  assert.equal(resto.color, COLORES.otros);
});
