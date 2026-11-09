/**
 * QA-001 — líneas de una NC/ND que vienen de una línea del comprobante de origen.
 *
 * El backend exige `detalle_origen` en una devolución con movimiento físico (DEVOLUCION_COMPRA /
 * DEVOLUCION_VENTA) y no deja devolver más de lo que queda de esa línea. Antes la pantalla no
 * tenía cómo elegir la línea: la NC de devolución no se podía registrar.
 *
 * Todo en decimal exacto (big.js) y en cantidad base, igual que el backend.
 */
import { aDecimal, comparar, restar, sumar, aDecimalesBd, formatearDecimal } from './decimal.ts';
import { cantidadBase } from './documentoCalculo.ts';

export interface LineaOrigen {
  id: number;
  linea: number;
  producto: number;
  producto_codigo?: string;
  producto_descripcion?: string;
  producto_unidad: number | null;
  unidad_codigo?: string | null;
  almacen: number;
  tipo_operacion_naturaleza?: string | null;
  cantidad_original: string;
  factor_conversion: string;
  cantidad_base: string;
  precio_unitario: string;
  afectacion_igv?: string | null;
  /** B17A-QA-001: código del Catálogo 07 de la línea de origen (la nota lo hereda si es gratuita). */
  codigo_afectacion_igv?: string | null;
  cantidad_disponible_devolucion?: string | null;
}

export interface LineaNota {
  detalleOrigenId?: number | '';
  productoId: number | '' | string;
  cantidadOriginal: string;
  factorConversion: string;
  /** Naturaleza de la operación elegida en la línea (ENTRADA/SALIDA = devolución física). */
  naturaleza?: string | null;
  afectaKardex?: boolean;
}

export const esDevolucionFisica = (naturaleza?: string | null, afectaKardex = true): boolean =>
  afectaKardex && (naturaleza === 'ENTRADA' || naturaleza === 'SALIDA');

/** Cantidad base que todavía se puede devolver de la línea de origen. */
export const disponibleBase = (l: LineaOrigen): string =>
  aDecimalesBd(l.cantidad_disponible_devolucion ?? l.cantidad_base);

/** Lo disponible expresado en la unidad de la línea de origen (lo que se precarga en la nota). */
export const disponibleEnUnidad = (l: LineaOrigen): string => {
  const factor = aDecimal(l.factor_conversion);
  const base = aDecimal(disponibleBase(l));
  if (!factor || !base || factor.eq(0)) return aDecimalesBd(base ?? '0');
  return aDecimalesBd(base.div(factor).round(8, 0));
};

/** Líneas que se pueden elegir: con movimiento de inventario y con cantidad por devolver. */
export const lineasOrigenElegibles = (lineas: readonly LineaOrigen[]): LineaOrigen[] =>
  lineas.filter((l) => comparar(disponibleBase(l), '0') > 0);

export const etiquetaLineaOrigen = (l: LineaOrigen): string => {
  const disponible = formatearDecimal(disponibleEnUnidad(l), { min: 2, max: 6 });
  const original = formatearDecimal(l.cantidad_original, { min: 2, max: 6 });
  const und = l.unidad_codigo ? ` ${l.unidad_codigo}` : '';
  return `#${l.linea} ${l.producto_codigo ?? l.producto} · ${original}${und} · disponible ${disponible}${und}`;
};

/**
 * Error de las líneas de la nota o `null`. Revisa: devolución física sin línea de origen,
 * producto distinto al de la línea de origen y cantidad (sumando las líneas que apuntan a la
 * misma línea de origen) mayor que la disponible.
 */
export function errorLineasNota(lineas: readonly LineaNota[], origen: readonly LineaOrigen[]): string | null {
  const usado = new Map<number, string>();
  for (let i = 0; i < lineas.length; i++) {
    const l = lineas[i];
    const fisica = esDevolucionFisica(l.naturaleza, l.afectaKardex ?? true);
    if (!l.detalleOrigenId) {
      if (fisica) return `Línea ${i + 1}: seleccione la línea del comprobante de origen que se devuelve.`;
      continue;
    }
    const o = origen.find((x) => x.id === Number(l.detalleOrigenId));
    if (!o) return `Línea ${i + 1}: la línea de origen no pertenece al comprobante de origen elegido.`;
    if (String(o.producto) !== String(l.productoId)) {
      return `Línea ${i + 1}: el producto debe ser el de la línea de origen #${o.linea} (${o.producto_codigo ?? o.producto}).`;
    }
    if (!fisica) continue;
    const acumulado = sumar(usado.get(o.id) ?? '0', cantidadBase(l.cantidadOriginal, l.factorConversion));
    usado.set(o.id, aDecimalesBd(acumulado));
    if (comparar(aDecimalesBd(acumulado), disponibleBase(o)) > 0) {
      const exceso = formatearDecimal(aDecimalesBd(restar(acumulado, disponibleBase(o))), { min: 2, max: 6 });
      return `Línea ${i + 1}: se devuelve más de lo disponible en la línea de origen #${o.linea} `
        + `(disponible ${formatearDecimal(disponibleBase(o), { min: 2, max: 6 })} en unidad base; exceso ${exceso}).`;
    }
  }
  return null;
}
