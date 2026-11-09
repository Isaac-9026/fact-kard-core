/**
 * Bloque 9 — el formulario de comprobantes calcula EXACTAMENTE lo que el backend guarda.
 * Casos de oro: qa/precision/casos_documentos.json (Decimal + ROUND_HALF_UP en Python).
 * El backend verifica los mismos casos contra la API (apps/documentos/tests_b9_precision.py).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { igvSugerido, tasaVigente, type AfectacionIgv } from './afectacionIgv.ts';
import { cantidadBase, importeLinea, totalesDocumento } from './documentoCalculo.ts';
import { formatearDecimal, restar } from './decimal.ts';

interface LineaCaso { cantidad: string; precio: string; afectacion: AfectacionIgv; factor?: string; bonificacion?: boolean }
interface Caso {
  id: string; tasa_pct: string; fecha: string; tasa_historica?: { vigente_desde: string; tasa_pct: string };
  lineas: LineaCaso[];
  antes?: { igv_lineas: string[]; total: string; diferencia_total: string };
  esperado: { lineas: { igv: string; cantidad_base: string; importe: string }[]; subtotal: string; igv: string; total: string; total_2d: string };
}

const casos: Caso[] = JSON.parse(
  readFileSync(new URL('../../../qa/precision/casos_documentos.json', import.meta.url), 'utf8'),
);

/** Lo que hace el formulario: IGV sugerido por línea (o 0 en bonificación) y totales. */
const calcularComoElFormulario = (caso: Caso) => {
  const tasas = caso.tasa_historica ? [caso.tasa_historica] : [];
  const tasa = tasaVigente(tasas, caso.fecha, '18.00');
  const lineas = caso.lineas.map((l) => ({
    cantidad: l.cantidad,
    precio: l.precio,
    igv: l.bonificacion ? '0.00000000' : (igvSugerido(l.afectacion, l.cantidad, l.precio, tasa) ?? '0.00000000'),
    factor: l.factor ?? '1',
  }));
  return { tasa, lineas, totales: totalesDocumento(lineas) };
};

/** Algoritmo ANTERIOR (float + toFixed(8)), para documentar la diferencia corregida. */
const igvAnteriorFloat = (cantidad: string, precio: string, tasaPct: string) =>
  ((parseFloat(cantidad) || 0) * (parseFloat(precio) || 0) * ((parseFloat(tasaPct) || 0) / 100)).toFixed(8);

test('caso exacto de la auditoría: diferencia 0.00004875 antes, 0 ahora', () => {
  const caso = casos.find((c) => c.id === 'auditoria_0_00004875')!;
  const [l] = caso.lineas;
  assert.deepEqual([l.cantidad, l.precio, caso.tasa_pct], ['2.5', '0.066775', '18.00']);
  // Antes: float, sin redondear a céntimos.
  const igvAntes = igvAnteriorFloat(l.cantidad, l.precio, caso.tasa_pct);
  assert.equal(igvAntes, '0.03004875');
  assert.equal(restar(igvAntes, caso.esperado.lineas[0].igv).toFixed(8), '0.00004875');
  assert.equal(caso.antes?.diferencia_total, '0.00004875');
  // Ahora: Decimal + ROUND_HALF_UP = lo que espera y guarda el backend.
  const { lineas, totales } = calcularComoElFormulario(caso);
  assert.equal(lineas[0].igv, '0.03000000');
  assert.deepEqual(totales, { subtotal: '0.16693750', igv: '0.03000000', total: '0.19693750' });
  assert.equal(restar(totales.total, caso.esperado.total).toFixed(8), '0.00000000');
});

for (const caso of casos) {
  test(`documento "${caso.id}": IGV por línea, cantidad base, subtotal, IGV y total = backend`, () => {
    const { tasa, lineas, totales } = calcularComoElFormulario(caso);
    assert.equal(tasa, caso.tasa_pct, 'tasa vigente en la fecha del comprobante');
    lineas.forEach((l, i) => {
      assert.equal(l.igv, caso.esperado.lineas[i].igv, `IGV línea ${i + 1}`);
      assert.equal(cantidadBase(l.cantidad, l.factor), caso.esperado.lineas[i].cantidad_base, `cantidad base línea ${i + 1}`);
      assert.equal(importeLinea(l.cantidad, l.precio), caso.esperado.lineas[i].importe, `importe línea ${i + 1}`);
    });
    assert.deepEqual(totales, { subtotal: caso.esperado.subtotal, igv: caso.esperado.igv, total: caso.esperado.total });
    // Lo que se muestra con 2 decimales es el total guardado redondeado HALF_UP.
    assert.equal(formatearDecimal(totales.total).replace(/,/g, ''), caso.esperado.total_2d);
  });
}

test('IGV: 18 %, tasa configurada e histórica; exonerado, inafecto, exportación y gratuito', () => {
  assert.equal(igvSugerido('GRAVADO', '10', '10'), '18.00000000');
  assert.equal(igvSugerido('GRAVADO', '10', '10', '10.00'), '10.00000000');
  assert.equal(igvSugerido('GRAVADO', '1', '0.25', '18.00'), '0.05000000'); // empate → HALF_UP
  const tasas = [{ vigente_desde: '2026-01-15', tasa_pct: '16.00' }];
  assert.equal(igvSugerido('GRAVADO', '3', '33.33', tasaVigente(tasas, '2026-01-20', '18.00')), '16.00000000');
  assert.equal(igvSugerido('GRAVADO', '3', '33.33', tasaVigente(tasas, '2026-01-14', '18.00')), '18.00000000');
  for (const af of ['EXONERADO', 'INAFECTO', 'EXPORTACION'] as const) assert.equal(igvSugerido(af, '3', '33.33'), '0.00000000');
  assert.equal(igvSugerido('GRATUITO', '3', '33.33'), null); // no pisa el IGV referencial ingresado
});

test('ajuste de valor sin cantidad: la base es el precio (como el backend)', () => {
  assert.equal(igvSugerido('GRAVADO', '0', '10', '18.00', 'AJUSTE_VALOR'), '1.80000000');
  assert.equal(igvSugerido('GRAVADO', '0', '10', '18.00', 'SALIDA'), '0.00000000');
});

test('el algoritmo anterior difería del backend en varios casos de oro', () => {
  const diferencias = casos.filter((caso) => caso.lineas.some((l, i) => l.afectacion === 'GRAVADO'
    && igvAnteriorFloat(l.cantidad, l.precio, caso.tasa_pct) !== caso.esperado.lineas[i].igv));
  assert.ok(diferencias.length >= 5, `casos que antes diferían: ${diferencias.map((c) => c.id).join(', ')}`);
});
