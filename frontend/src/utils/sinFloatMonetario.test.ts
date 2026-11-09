/**
 * Bloque 9 — guardián: evita que vuelva la aritmética IEEE-754 sobre importes en el frontend.
 * Los cálculos y formatos de dinero/cantidades usan utils/decimal.ts (big.js, ROUND_HALF_UP).
 *
 * Prohibido en src/ (fuera de la lista blanca justificada):
 *   parseFloat(...), .toFixed(...), Number(...).toLocaleString(...),
 *   Number(...) seguido de * / + -  (operar en float valores que vienen como texto decimal).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const SRC = fileURLToPath(new URL('..', import.meta.url));

// Usos permitidos: no son importes ni cantidades contables.
const LISTA_BLANCA: { archivo: string; contiene: string; motivo: string }[] = [
  { archivo: 'pages/captura/CapturaHomologacionPage.tsx', contiene: 'num.toFixed(1)', motivo: 'porcentaje de confianza del OCR' },
  { archivo: 'pages/captura/CapturaHomologacionPage.tsx', contiene: '(uploadFile.size / 1024).toFixed(1)', motivo: 'tamaño del archivo en KB' },
  { archivo: 'pages/captura/CapturaHomologacionPage.tsx', contiene: 'Number(a) - Number(b)', motivo: 'orden de números de línea' },
  { archivo: 'pages/transferencias/TransferenciasPage.tsx', contiene: 'parseFloat(l.cantidad_base) > 0', motivo: 'solo verifica el signo; el backend valida la cantidad' },
  { archivo: 'utils/decimal.ts', contiene: 'toFixed(', motivo: 'toFixed de big.js (decimal exacto), no de Number' },
  { archivo: 'utils/decimal.ts', contiene: '(1.005).toFixed(2)', motivo: 'comentario que documenta el error' },
];

const PATRONES = [
  /parseFloat\(/,
  /\.toFixed\(/,
  /Number\([^()]*\)\.toLocaleString\(/,
  /Number\([^()]*\)\s*[*/+-]\s*(Number|parseFloat|\d)/,
];

const archivos = (dir: string): string[] => readdirSync(dir).flatMap((n) => {
  const ruta = join(dir, n);
  if (statSync(ruta).isDirectory()) return archivos(ruta);
  return /\.(ts|tsx)$/.test(n) && !/\.test\.ts$/.test(n) ? [ruta] : [];
});

test('no hay aritmética float sobre importes fuera de la lista blanca', () => {
  const hallazgos: string[] = [];
  for (const ruta of archivos(SRC)) {
    const rel = relative(SRC, ruta).replace(/\\/g, '/');
    readFileSync(ruta, 'utf8').split('\n').forEach((linea, i) => {
      if (!PATRONES.some((p) => p.test(linea))) return;
      if (LISTA_BLANCA.some((b) => b.archivo === rel && linea.includes(b.contiene))) return;
      hallazgos.push(`${rel}:${i + 1}: ${linea.trim()}`);
    });
  }
  assert.deepEqual(hallazgos, [], `Use utils/decimal.ts (formatearDecimal, sumar, multiplicar…):\n${hallazgos.join('\n')}`);
});
