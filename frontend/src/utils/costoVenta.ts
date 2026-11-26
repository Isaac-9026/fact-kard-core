/**
 * Costo de venta — utilidades puras (sin React), probadas con `node --test`.
 *
 *   Saldo inicial + Compras − Saldo final = Costo de venta
 *
 * Los números los calcula el backend desde el Kardex; aquí solo se arman filtros y las filas
 * que se muestran con el formato del dueño (Unid. / P.U. / Total).
 */

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

export interface FiltrosCostoVentaAnual {
  anio: number | string;
  producto_id?: number | string;
}

export const paramsCostoVentaAnual = (f: FiltrosCostoVentaAnual): Record<string, number | string> => ({
  anio: f.anio,
  ...(f.producto_id ? { producto_id: f.producto_id } : {}),
});

/** Años con períodos registrados, del más reciente al más antiguo. */
export const aniosDePeriodos = (periodos: { anio: number }[]): number[] =>
  [...new Set(periodos.map((p) => p.anio))].sort((a, b) => b - a);

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

/** Salidas atribuibles a ventas (comprobación del costo de venta según el Kardex). */
export const ETIQUETAS_DESGLOSE: Record<string, string> = {
  ventas: 'Mercadería vendida',
  devoluciones_venta: 'Devoluciones de clientes',
};

/** Salidas del inventario que no son ventas: se concilian aparte del costo de venta. */
export const ETIQUETAS_CONCILIACION: Record<string, string> = {
  mermas_desmedros: 'Mermas y desmedros',
  consumo_retiros: 'Consumo interno y retiros',
  ajustes: 'Ajustes de inventario',
  transferencias: 'Transferencias entre almacenes',
  otros: 'Otros movimientos',
};

export interface BloqueCostoMin { cantidad: string | null; costo_unitario: string | null; valor: string }

export interface FilaFormula {
  clave: 'saldo_inicial' | 'compras' | 'subtotal' | 'saldo_final' | 'salidas' | 'no_atribuibles' | 'costo_venta';
  signo: '' | '+' | '−' | '=';
  etiqueta: string;
  cantidad: string | null;
  costoUnitario: string | null;
  valor: string;
}

export const esCero = (valor?: string | null): boolean => {
  if (valor === null || valor === undefined || valor === '') return true;
  return /^-?0*(\.0*)?$/.test(valor.trim());
};

/**
 * Filas del cálculo principal, con ambos saldos según el Kardex (promedio móvil):
 *   S.I. + Compras (subtotal) − S. final = Salidas del inventario − Salidas que no son ventas = Costo de venta
 * Las líneas de salidas y de conciliación solo aparecen si hubo salidas que no son ventas.
 */
export const filasFormula = (b: {
  saldo_inicial: BloqueCostoMin; compras: BloqueCostoMin; saldo_final: BloqueCostoMin; costo_venta: BloqueCostoMin;
  disponible?: BloqueCostoMin; salidas?: BloqueCostoMin; no_atribuibles?: BloqueCostoMin;
}): FilaFormula[] => {
  const subtotal: BloqueCostoMin = b.disponible
    ?? { cantidad: null, costo_unitario: null, valor: sumarTexto(b.saldo_inicial.valor, b.compras.valor) };
  const fila = (clave: FilaFormula['clave'], signo: FilaFormula['signo'], etiqueta: string, bloque: BloqueCostoMin): FilaFormula => ({
    clave, signo, etiqueta, cantidad: bloque.cantidad, costoUnitario: bloque.costo_unitario, valor: bloque.valor,
  });
  const conciliar = !!b.no_atribuibles && !esCero(b.no_atribuibles.valor);
  return [
    fila('saldo_inicial', '', 'Saldo inicial', b.saldo_inicial),
    fila('compras', '+', 'Compras', b.compras),
    fila('subtotal', '', 'Subtotal', subtotal),
    fila('saldo_final', '−', 'Saldo final (Kardex)', b.saldo_final),
    ...(conciliar && b.salidas ? [fila('salidas', '=', 'Salidas del inventario', b.salidas)] : []),
    ...(conciliar && b.no_atribuibles ? [fila('no_atribuibles', '−', 'Salidas que no son ventas', b.no_atribuibles)] : []),
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

/** El desglose explica todo el costo de venta (la diferencia del backend es 0); también sirve para ver si un importe es 0. */
export const cuadra = (diferencia?: string | null): boolean => esCero(diferencia);

/** Solo los conceptos con importe, para no llenar la pantalla de ceros. */
export const conceptosConImporte = (valores: Record<string, string | BloqueCostoMin>, etiquetas: Record<string, string>) =>
  Object.keys(etiquetas)
    .map((clave) => {
      const v = valores[clave];
      return { clave, etiqueta: etiquetas[clave], valor: typeof v === 'string' ? v : v?.valor ?? '0' };
    })
    .filter((c) => !esCero(c.valor));

/**
 * Comparación con el promedio ponderado: oculta por defecto (el resultado es el costo según Kardex).
 * Un solo mes o la vista «Por año» comparan con el promedio mensual; un rango de varios meses, con
 * un único promedio del rango.
 */
export const textosComparacion = (variosMeses: boolean) => {
  const base = variosMeses ? 'promedio del rango' : 'promedio mensual';
  return {
    ver: `Ver comparación con ${variosMeses ? 'el ' : ''}${base}`,
    ocultar: 'Ocultar comparación',
    titulo: variosMeses ? 'Comparación con el promedio del rango' : 'Comparación con el promedio mensual',
    columnaPromedio: variosMeses ? 'Promedio del rango' : 'Promedio mensual',
    columnaDiferencia: 'Diferencia (promedio − Kardex)',
  };
};

/** Signo explícito para una diferencia: "+29.21", "-39.48", "0.00". */
export const conSigno = (valor: string): string => {
  if (esCero(valor)) return valor.replace(/^[-+]/, '');
  return valor.startsWith('-') || valor.startsWith('+') ? valor : `+${valor}`;
};
