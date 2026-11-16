/**
 * Costo de venta — utilidades puras (sin React), probadas con `node --test`.
 *
 *   Saldo inicial + Compras − Saldo final = Costo de venta
 *
 * Los números los calcula el backend desde el Kardex; aquí solo se arman filtros, nombres de
 * archivo y las filas que se muestran con el formato del dueño (Unid. / P.U. / Total).
 */
import { nombreSeguro } from './descargaArchivo.ts';

export interface FiltrosCostoVenta {
  periodo_id: number | string;
  periodo_hasta_id?: number | string;
  producto_id?: number | string;
}

export const paramsCostoVenta = (f: FiltrosCostoVenta): Record<string, number | string> => ({
  periodo_id: f.periodo_id,
  ...(f.periodo_hasta_id && String(f.periodo_hasta_id) !== String(f.periodo_id) ? { periodo_hasta_id: f.periodo_hasta_id } : {}),
  ...(f.producto_id ? { producto_id: f.producto_id } : {}),
});

/** `Costo_de_venta_2026-01_20123456789.xlsx` o `Costo_de_venta_2026-01_a_2026-03_…` (igual que el backend). */
export const nombreArchivoCostoVenta = ({ desde, hasta, ruc }: { desde: string; hasta?: string | null; ruc?: string | null }): string => {
  const rango = hasta && hasta !== desde ? `${desde}_a_${hasta}` : desde;
  return `${nombreSeguro(['Costo_de_venta', rango, ruc].filter(Boolean).join('_'))}.xlsx`;
};

export interface PeriodoOrdenable { id: number; orden: number }

/** Mensaje de error si el período final es anterior al inicial; null si el rango es válido. */
export const validarRangoPeriodos = (
  periodos: PeriodoOrdenable[], desde: number | string | '', hasta: number | string | '',
): string | null => {
  if (!desde) return 'Seleccione el período.';
  if (!hasta) return null;
  const a = periodos.find((p) => String(p.id) === String(desde));
  const b = periodos.find((p) => String(p.id) === String(hasta));
  if (a && b && b.orden < a.orden) return 'El período final no puede ser anterior al inicial.';
  return null;
};

export const ETIQUETAS_COMPRA: Record<string, string> = {
  compras: 'Compras',
  bonificaciones: 'Bonificaciones recibidas',
  devoluciones: 'Devoluciones a proveedor',
  notas_credito_debito: 'Notas de crédito / débito de compra',
};

export const ETIQUETAS_DESGLOSE: Record<string, string> = {
  ventas: 'Mercadería vendida',
  devoluciones_venta: 'Devoluciones de clientes',
  mermas_desmedros: 'Mermas y desmedros',
  consumo_retiros: 'Consumo interno y retiros',
  ajustes: 'Ajustes de inventario',
  transferencias: 'Transferencias entre almacenes',
  otros: 'Otros',
};

export interface BloqueCostoMin { cantidad: string | null; costo_unitario: string | null; valor: string }

export interface FilaFormula {
  clave: 'saldo_inicial' | 'compras' | 'subtotal' | 'saldo_final' | 'costo_venta';
  signo: '' | '+' | '−' | '=';
  etiqueta: string;
  cantidad: string | null;
  costoUnitario: string | null;
  valor: string;
}

const esCero = (valor?: string | null): boolean => {
  if (valor === null || valor === undefined || valor === '') return true;
  return /^-?0*(\.0*)?$/.test(valor.trim());
};

/**
 * Filas en el orden de la hoja del dueño:
 *   S.I.  + Compras  (subtotal)  − S. final  = Costo de venta
 * El subtotal (S.I. + Compras) solo lleva total, como en su ejemplo (30 + 1 000 = 1 030).
 */
export const filasFormula = (b: {
  saldo_inicial: BloqueCostoMin; compras: BloqueCostoMin; saldo_final: BloqueCostoMin; costo_venta: BloqueCostoMin;
}): FilaFormula[] => {
  const subtotal = sumarTexto(b.saldo_inicial.valor, b.compras.valor);
  const fila = (clave: FilaFormula['clave'], signo: FilaFormula['signo'], etiqueta: string, bloque: BloqueCostoMin): FilaFormula => ({
    clave, signo, etiqueta, cantidad: bloque.cantidad, costoUnitario: bloque.costo_unitario, valor: bloque.valor,
  });
  return [
    fila('saldo_inicial', '', 'Saldo inicial', b.saldo_inicial),
    fila('compras', '+', 'Compras', b.compras),
    { clave: 'subtotal', signo: '', etiqueta: 'Subtotal', cantidad: null, costoUnitario: null, valor: subtotal },
    fila('saldo_final', '−', 'Saldo final', b.saldo_final),
    fila('costo_venta', '=', 'Costo de venta', b.costo_venta),
  ];
};

/** Suma exacta de dos decimales en texto (hasta 8 decimales), sin pasar por float. */
export const sumarTexto = (a: string, b: string): string => {
  const ESCALA = 8;
  const aEntero = (t: string): bigint => {
    const negativo = t.trim().startsWith('-');
    const [ent, dec = ''] = t.trim().replace('-', '').split('.');
    const valor = BigInt((ent || '0') + dec.padEnd(ESCALA, '0').slice(0, ESCALA));
    return negativo ? -valor : valor;
  };
  const total = aEntero(a || '0') + aEntero(b || '0');
  const negativo = total < 0n;
  const absoluto = (negativo ? -total : total).toString().padStart(ESCALA + 1, '0');
  return `${negativo ? '-' : ''}${absoluto.slice(0, -ESCALA)}.${absoluto.slice(-ESCALA)}`;
};

/** El desglose explica todo el costo de venta (la diferencia del backend es 0). */
export const cuadra = (diferencia?: string | null): boolean => esCero(diferencia);

/** Solo los conceptos con importe, para no llenar la pantalla de ceros. */
export const conceptosConImporte = (valores: Record<string, string | BloqueCostoMin>, etiquetas: Record<string, string>) =>
  Object.keys(etiquetas)
    .map((clave) => {
      const v = valores[clave];
      return { clave, etiqueta: etiquetas[clave], valor: typeof v === 'string' ? v : v?.valor ?? '0' };
    })
    .filter((c) => !esCero(c.valor));
