// Bloque 3: afectación del IGV por línea. Solo sugiere el IGV en pantalla;
// el backend es quien valida (GRAVADO 18 %, EXONERADO/INAFECTO/EXPORTACION 0).
import { baseImponible, igvEsperado } from './documentoCalculo.ts';

export type AfectacionIgv = 'GRAVADO' | 'EXONERADO' | 'INAFECTO' | 'EXPORTACION' | 'GRATUITO';

export const AFECTACIONES_IGV: { valor: AfectacionIgv; etiqueta: string }[] = [
  { valor: 'GRAVADO', etiqueta: 'Gravado' },
  { valor: 'EXONERADO', etiqueta: 'Exonerado' },
  { valor: 'INAFECTO', etiqueta: 'Inafecto' },
  { valor: 'EXPORTACION', etiqueta: 'Exportación' },
  { valor: 'GRATUITO', etiqueta: 'Gratuito' },
];

// Bloque 4: la tasa real la entrega el backend (ConfigEmpresa.tasa_igv_pct). Este valor
// solo se usa mientras no se haya leído la configuración.
export const TASA_IGV_POR_DEFECTO_PCT = '18.00';

/**
 * IGV sugerido para la línea, o null si la afectación no tiene tasa que sugerir (GRATUITO).
 * Bloque 9: es exactamente el IGV que espera el backend (base × tasa a céntimos, ROUND_HALF_UP,
 * en decimal exacto). Antes se calculaba con float y 8 decimales sin redondear a céntimos
 * (p. ej. 2.5 × 0.066775 al 18 % → 0.03004875 en vez de 0.03).
 */
export function igvSugerido(
  afectacion: AfectacionIgv, cantidad: string, precio: string, tasaPct: string = TASA_IGV_POR_DEFECTO_PCT,
  naturaleza?: string,
): string | null {
  if (afectacion === 'GRATUITO') return null;
  if (afectacion !== 'GRAVADO') return '0.00000000';
  return igvEsperado(baseImponible(precio, cantidad, naturaleza), tasaPct);
}

export interface TasaIgvVigencia { vigente_desde: string; tasa_pct: string }

/** Bloque 5: tasa vigente en la fecha del comprobante (ISO yyyy-mm-dd); si no hay historial, la actual. */
export function tasaVigente(tasas: TasaIgvVigencia[] | undefined, fecha: string, actual: string): string {
  const aplicables = (tasas ?? []).filter((t) => t.vigente_desde <= fecha);
  if (aplicables.length === 0) return actual;
  return aplicables.reduce((a, b) => (b.vigente_desde > a.vigente_desde ? b : a)).tasa_pct;
}

/** El IGV solo es editable en líneas gravadas o gratuitas; en las demás es 0. */
export function igvEditable(afectacion: AfectacionIgv): boolean {
  return afectacion === 'GRAVADO' || afectacion === 'GRATUITO';
}

// ---- B17A-QA-001: código del Catálogo 07 en líneas gratuitas --------------------------------
// El catálogo (código, descripción oficial, afectación) llega del backend; aquí no se copia.

export interface EntradaCatalogo07 { codigo: string; descripcion: string; afectacion: AfectacionIgv | null; soportado: boolean }

/** Códigos de transferencia gratuita soportados (11-16, 21, 31-36), en el orden del catálogo. */
export function codigosGratuitos(catalogo: readonly EntradaCatalogo07[]): EntradaCatalogo07[] {
  return catalogo.filter((c) => c.afectacion === 'GRATUITO' && c.soportado);
}

/**
 * Código que debe conservar la línea al cambiar su afectación: solo una línea GRATUITA guarda
 * código y solo uno gratuito del catálogo; cualquier otro caso queda vacío (no se arrastra un
 * dato incompatible).
 */
export function reconciliarCodigoAfectacion(
  afectacion: AfectacionIgv, codigo: string, catalogo: readonly EntradaCatalogo07[],
): string {
  if (afectacion !== 'GRATUITO' || !codigo) return '';
  return codigosGratuitos(catalogo).some((c) => c.codigo === codigo) ? codigo : '';
}

/** Valor que se envía a la API: el código solo en líneas gratuitas. */
export function codigoAfectacionParaEnviar(afectacion: AfectacionIgv, codigo: string): string | null {
  return afectacion === 'GRATUITO' && codigo ? codigo : null;
}

/**
 * En ventas (lo que se emitirá electrónicamente) una línea gratuita exige su código del
 * Catálogo 07. Devuelve el primer error o null.
 */
export function errorCodigoGratuito(
  lineas: readonly { afectacion: AfectacionIgv; codigo: string }[], clase: 'COMPRA' | 'VENTA',
): string | null {
  if (clase !== 'VENTA') return null;
  const i = lineas.findIndex((l) => l.afectacion === 'GRATUITO' && !l.codigo);
  return i < 0 ? null : `Línea ${i + 1}: seleccione el código del Catálogo 07 de la operación gratuita (11-16, 21 o 31-36).`;
}
