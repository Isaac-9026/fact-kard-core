import { test } from 'node:test';
import assert from 'node:assert/strict';
import type { MesAnio, VistaPreviaAnio } from '../api/periodos.ts';
import {
  alternarMes, anioValido, elegidosSinIgv, seleccionDesde, seleccionInicial, textoResultado, textoResumen,
} from './abrirAnio.ts';

const NOMBRES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'];

const previa = (existentes: number[] = [], sinIgv: number[] = []): VistaPreviaAnio => {
  const meses: MesAnio[] = NOMBRES.map((nombre, i) => ({
    mes: i + 1, nombre, etiqueta: `2023-${String(i + 1).padStart(2, '0')}`, fecha_inicio: '', fecha_fin: '',
    existe: existentes.includes(i + 1), periodo_id: null, estado: existentes.includes(i + 1) ? 'CERRADO' : null,
    igv: { cubierto: !sinIgv.includes(i + 1), dias_sin_cobertura: sinIgv.includes(i + 1) ? 31 : 0, sin_cobertura_hasta: null },
  }));
  return { anio: 2023, meses, faltantes: meses.filter((m) => !m.existe).map((m) => m.mes), primera_vigencia_igv: null, advertencia_igv: null };
};

test('por defecto se marcan los meses que faltan; los existentes no se eligen', () => {
  const p = previa([1]);
  const sel = seleccionInicial(p);
  assert.deepEqual(sel, [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]);
  assert.deepEqual(alternarMes(p, sel, 1), sel);
  assert.deepEqual(alternarMes(p, sel, 5), [2, 3, 4, 6, 7, 8, 9, 10, 11, 12]);
  assert.deepEqual(alternarMes(p, [2], 5), [2, 5]);
  assert.equal(textoResumen(p, sel).startsWith('Se crearán 11 meses de 2023: febrero, marzo'), true);
  assert.equal(textoResumen(p, []), 'No hay meses seleccionados.');
  assert.equal(textoResumen(p, [3]), 'Se creará 1 mes de 2023: marzo.');
});

test('empresa que empezó en julio: solo julio–diciembre', () => {
  assert.deepEqual(seleccionDesde(previa(), 7), [7, 8, 9, 10, 11, 12]);
  assert.deepEqual(seleccionDesde(previa([8]), 7), [7, 9, 10, 11, 12]);
});

test('advertencia de IGV solo para los meses elegidos', () => {
  const p = previa([], [1, 2, 3]);
  assert.deepEqual(elegidosSinIgv(p, [2, 3, 4]).map((m) => m.mes), [2, 3]);
  assert.deepEqual(elegidosSinIgv(p, [4, 5]), []);
});

test('año válido y mensaje final', () => {
  const hoy = new Date(2026, 10, 24);
  assert.equal(anioValido(2000, hoy), true);
  assert.equal(anioValido(2027, hoy), true);
  assert.equal(anioValido(1999, hoy), false);
  assert.equal(anioValido(2028, hoy), false);
  assert.equal(anioValido(2023.5, hoy), false);
  assert.equal(textoResultado({ anio: 2023, creados: [], existentes: [1], total_creados: 11, total_existentes: 1, advertencia_igv: null }),
    'Año 2023: se crearon 11 meses; 1 ya existía.');
  assert.equal(textoResultado({ anio: 2023, creados: [], existentes: [], total_creados: 0, total_existentes: 12, advertencia_igv: null }),
    'Año 2023: se crearon 0 meses; 12 ya existían.');
});
