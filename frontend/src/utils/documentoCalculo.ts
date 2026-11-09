/**
 * Bloque 9 — cálculos del formulario de comprobantes, idénticos a los del backend
 * (apps/documentos/services.py y afectacion_igv.py), en decimal exacto con ROUND_HALF_UP.
 *
 * El backend sigue siendo la autoridad: valida el IGV, calcula costos en PEN con el tipo de
 * cambio y guarda los totales. Esto solo permite que la pantalla muestre, ANTES de guardar,
 * los mismos importes que el backend va a guardar.
 *
 *   base imponible  = precio × cantidad   (ajuste de valor sin cantidad: base = precio)
 *   IGV esperado    = (base × tasa%/100) redondeado a 0.01 (ROUND_HALF_UP)
 *   cantidad base   = cantidad × factor   redondeado a 0.000001 (ROUND_HALF_UP)
 *   subtotal        = Σ precio × cantidad redondeado a 0.00000001 (ROUND_HALF_UP)
 *   IGV documento   = Σ IGV de líneas     redondeado a 0.00000001
 *   total           = subtotal + IGV      redondeado a 0.00000001
 */
import { aDecimalesBd, decimalOCero, multiplicar, redondear, sumar, type ValorDecimal } from './decimal.ts';

export interface LineaParaTotales {
  cantidad: ValorDecimal;
  precio: ValorDecimal;
  igv: ValorDecimal;
}

export interface TotalesDocumento {
  subtotal: string;
  igv: string;
  total: string;
}

export function baseImponible(precio: ValorDecimal, cantidad: ValorDecimal, naturaleza?: string): string {
  if (naturaleza === 'AJUSTE_VALOR' && decimalOCero(cantidad).eq(0)) return aDecimalesBd(precio);
  return aDecimalesBd(multiplicar(precio, cantidad));
}

/** igv_esperado() del backend: base × tasa, a céntimos, en el formato de 8 decimales de la API. */
export function igvEsperado(base: ValorDecimal, tasaPct: ValorDecimal): string {
  const igv = multiplicar(base, decimalOCero(tasaPct).div(100));
  return aDecimalesBd(redondear(igv, 2));
}

export function importeLinea(cantidad: ValorDecimal, precio: ValorDecimal): string {
  return aDecimalesBd(multiplicar(precio, cantidad));
}

export function cantidadBase(cantidad: ValorDecimal, factor: ValorDecimal): string {
  return aDecimalesBd(redondear(multiplicar(cantidad, factor ?? '1'), 6));
}

export function totalesDocumento(lineas: LineaParaTotales[]): TotalesDocumento {
  const subtotal = sumar(...lineas.map((l) => multiplicar(l.precio, l.cantidad)));
  const igv = sumar(...lineas.map((l) => decimalOCero(l.igv)));
  const subtotalBd = aDecimalesBd(subtotal);
  const igvBd = aDecimalesBd(igv);
  // El backend suma los acumulados SIN redondear y redondea el total una sola vez.
  return { subtotal: subtotalBd, igv: igvBd, total: aDecimalesBd(subtotal.plus(igv)) };
}
