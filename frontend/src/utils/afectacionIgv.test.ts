/// <reference types="node" />

import assert from 'node:assert/strict';
import test from 'node:test';
import {
  AFECTACIONES_IGV, codigoAfectacionParaEnviar, codigosGratuitos, errorCodigoGratuito, igvEditable, igvSugerido,
  reconciliarCodigoAfectacion, tasaVigente, type EntradaCatalogo07,
} from './afectacionIgv.ts';

test('tasa vigente según la fecha del comprobante', () => {
  const tasas = [{ vigente_desde: '1900-01-01', tasa_pct: '18.00' }, { vigente_desde: '2026-01-15', tasa_pct: '10.00' }];
  assert.equal(tasaVigente(tasas, '2026-01-14', '10.00'), '18.00');
  assert.equal(tasaVigente(tasas, '2026-01-15', '10.00'), '10.00');
  assert.equal(tasaVigente([], '2026-01-14', '18.00'), '18.00');
  assert.equal(tasaVigente(undefined, '2026-01-14', '18.00'), '18.00');
});

test('gravado sugiere 18 % por defecto', () => {
  assert.equal(igvSugerido('GRAVADO', '10', '10'), '18.00000000');
});

test('gravado usa la tasa configurada de la empresa', () => {
  assert.equal(igvSugerido('GRAVADO', '10', '10', '10.00'), '10.00000000');
  assert.equal(igvSugerido('EXONERADO', '10', '10', '10.00'), '0.00000000');
  assert.equal(igvSugerido('GRATUITO', '10', '10', '10.00'), null);
});

for (const afectacion of ['EXONERADO', 'INAFECTO', 'EXPORTACION'] as const) {
  test(`${afectacion} lleva IGV 0 y no es editable`, () => {
    assert.equal(igvSugerido(afectacion, '10', '10'), '0.00000000');
    assert.equal(igvEditable(afectacion), false);
  });
}

test('gratuito no sobrescribe el IGV ingresado', () => {
  assert.equal(igvSugerido('GRATUITO', '10', '10'), null);
  assert.equal(igvEditable('GRATUITO'), true);
});

test('las opciones coinciden con las del backend', () => {
  assert.deepEqual(AFECTACIONES_IGV.map((a) => a.valor), ['GRAVADO', 'EXONERADO', 'INAFECTO', 'EXPORTACION', 'GRATUITO']);
});

// ---- B17A-QA-001 ------------------------------------------------------------------------------
// Muestra del catálogo tal como lo entrega la API (la fuente canónica es el backend).
const CATALOGO: EntradaCatalogo07[] = [
  { codigo: '10', descripcion: 'Gravado - Operación Onerosa', afectacion: 'GRAVADO', soportado: true },
  { codigo: '15', descripcion: 'Gravado – Bonificaciones', afectacion: 'GRATUITO', soportado: true },
  { codigo: '17', descripcion: 'Gravado – IVAP', afectacion: null, soportado: false },
  { codigo: '21', descripcion: 'Exonerado – Transferencia Gratuita', afectacion: 'GRATUITO', soportado: true },
  { codigo: '31', descripcion: 'Inafecto – Retiro por Bonificación', afectacion: 'GRATUITO', soportado: true },
];

test('selector: solo códigos gratuitos soportados, con su descripción', () => {
  assert.deepEqual(codigosGratuitos(CATALOGO).map((c) => `${c.codigo} — ${c.descripcion}`),
    ['15 — Gravado – Bonificaciones', '21 — Exonerado – Transferencia Gratuita', '31 — Inafecto – Retiro por Bonificación']);
});

test('GRATUITO -> GRAVADO limpia el código; gratuito compatible se conserva', () => {
  assert.equal(reconciliarCodigoAfectacion('GRAVADO', '15', CATALOGO), '');
  assert.equal(reconciliarCodigoAfectacion('EXONERADO', '21', CATALOGO), '');
  assert.equal(reconciliarCodigoAfectacion('GRATUITO', '15', CATALOGO), '15');
  assert.equal(reconciliarCodigoAfectacion('GRATUITO', '10', CATALOGO), '');  // incompatible
  assert.equal(reconciliarCodigoAfectacion('GRATUITO', '17', CATALOGO), '');  // no soportado
});

test('al enviar: código solo en líneas gratuitas', () => {
  assert.equal(codigoAfectacionParaEnviar('GRATUITO', '31'), '31');
  assert.equal(codigoAfectacionParaEnviar('GRAVADO', '31'), null);
  assert.equal(codigoAfectacionParaEnviar('GRATUITO', ''), null);
});

test('venta con línea gratuita sin código: error claro; compra o línea normal: sin error', () => {
  assert.match(errorCodigoGratuito([{ afectacion: 'GRAVADO', codigo: '' }, { afectacion: 'GRATUITO', codigo: '' }], 'VENTA') ?? '',
    /^Línea 2: seleccione el código del Catálogo 07/);
  assert.equal(errorCodigoGratuito([{ afectacion: 'GRATUITO', codigo: '15' }], 'VENTA'), null);
  assert.equal(errorCodigoGratuito([{ afectacion: 'GRATUITO', codigo: '' }], 'COMPRA'), null);
  assert.equal(errorCodigoGratuito([{ afectacion: 'GRAVADO', codigo: '' }], 'VENTA'), null);
});
