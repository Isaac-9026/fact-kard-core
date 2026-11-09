// Bloque 3: saldo inicial / final valorizado del Formato 13.1.
// Se muestran EXACTAMENTE los importes históricos que entrega el backend (texto con
// 8 decimales); aquí no se recalcula nada ni se pasa por number (sin pérdida de precisión).

export interface BloqueSaldo { cantidad: string; costo_unitario: string; costo_total: string }

export interface ReporteConSaldos {
  saldo_inicial?: string | null;
  saldo_inicial_valorizado?: BloqueSaldo | null;
  saldo_final?: BloqueSaldo | null;
  movimientos: unknown[];
}

export interface FilaSaldo { cantidad: string; costoUnitario: string; costoTotal: string }

const SIN_DATO = '—';

/** Agrupa miles sobre el texto decimal, conservando todos los decimales recibidos. */
export function formatoContable(valor?: string | null): string {
  if (valor === null || valor === undefined || valor.trim() === '') return SIN_DATO;
  const texto = valor.trim();
  if (!/^-?\d+(\.\d+)?$/.test(texto)) return texto;
  const negativo = texto.startsWith('-');
  const [entero, decimales] = (negativo ? texto.slice(1) : texto).split('.');
  const agrupado = entero.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return `${negativo ? '-' : ''}${agrupado}${decimales !== undefined ? `.${decimales}` : ''}`;
}

function fila(bloque?: BloqueSaldo | null): FilaSaldo {
  return {
    cantidad: formatoContable(bloque?.cantidad),
    costoUnitario: formatoContable(bloque?.costo_unitario),
    costoTotal: formatoContable(bloque?.costo_total),
  };
}

/** Saldo inicial valorizado tal como lo entrega el backend (CU y CT nunca se derivan aquí). */
export function filaSaldoInicial(reporte: ReporteConSaldos): FilaSaldo {
  if (reporte.saldo_inicial_valorizado) return fila(reporte.saldo_inicial_valorizado);
  // Respuesta antigua sin bloque valorizado: solo la cantidad, sin inventar importes.
  return { cantidad: formatoContable(reporte.saldo_inicial), costoUnitario: SIN_DATO, costoTotal: SIN_DATO };
}

export function filaSaldoFinal(reporte: ReporteConSaldos): FilaSaldo {
  return fila(reporte.saldo_final);
}
