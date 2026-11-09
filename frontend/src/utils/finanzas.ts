/**
 * Bloque 16 — utilidades puras del flujo comercial/financiero (sin React, probadas con
 * node --test). Todo importe con big.js; el backend vuelve a validar cada regla.
 */
import Big from 'big.js';
import { aDecimal, aDecimalesBd, comparar, decimalOCero, redondear, restar, sumar } from './decimal.ts';

// ---- Documento de identidad (Catálogo 06) -----------------------------------------------

export const TIPOS_DOCUMENTO_IDENTIDAD: readonly { codigo: string; etiqueta: string }[] = [
  { codigo: '6', etiqueta: 'RUC' },
  { codigo: '1', etiqueta: 'DNI' },
  { codigo: '4', etiqueta: 'Carnet de extranjería' },
  { codigo: '7', etiqueta: 'Pasaporte' },
  { codigo: 'A', etiqueta: 'Cédula diplomática' },
  { codigo: '0', etiqueta: 'Doc. trib. no domiciliado sin RUC' },
];

const PESOS_RUC = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2];
const PREFIJOS_RUC = ['10', '15', '16', '17', '20'];

export function esRucValido(numero: string): boolean {
  if (!/^\d{11}$/.test(numero) || !PREFIJOS_RUC.includes(numero.slice(0, 2))) return false;
  const suma = PESOS_RUC.reduce((acc, peso, i) => acc + Number(numero[i]) * peso, 0);
  const resto = 11 - (suma % 11);
  const digito = resto === 10 ? 0 : resto === 11 ? 1 : resto;
  return digito === Number(numero[10]);
}

/** Mensaje de error o null (la misma regla del backend; el backend decide). */
export function errorDocumentoIdentidad(tipo: string, numeroCrudo: string): string | null {
  const numero = (numeroCrudo || '').replace(/\s+/g, '').toUpperCase();
  if (!TIPOS_DOCUMENTO_IDENTIDAD.some((t) => t.codigo === tipo)) return 'Seleccione el tipo de documento.';
  if (!numero) return 'El número de documento es obligatorio.';
  if (tipo === '6') {
    if (!/^\d{11}$/.test(numero)) return 'El RUC debe tener exactamente 11 dígitos.';
    if (!PREFIJOS_RUC.includes(numero.slice(0, 2))) return 'El RUC debe empezar con 10, 15, 16, 17 o 20.';
    if (!esRucValido(numero)) return 'El RUC no es válido (dígito verificador incorrecto).';
  } else if (tipo === '1') {
    if (!/^\d{8}$/.test(numero)) return 'El DNI debe tener exactamente 8 dígitos.';
  } else if (['4', '7', 'A'].includes(tipo)) {
    if (!/^[A-Z0-9]{4,12}$/.test(numero)) return 'El documento debe tener entre 4 y 12 caracteres alfanuméricos.';
  } else if (!/^[A-Z0-9-]{1,15}$/.test(numero)) {
    return 'El documento debe tener hasta 15 caracteres alfanuméricos.';
  }
  return null;
}

// ---- Condición de pago y cuotas -----------------------------------------------------------

export interface CuotaForm { fecha_vencimiento: string; monto: string }

export interface CondicionPagoValor {
  condicion: 'CONTADO' | 'CREDITO';
  fechaVencimiento: string;
  cuotas: CuotaForm[];
}

export const CONDICION_INICIAL: CondicionPagoValor = { condicion: 'CONTADO', fechaVencimiento: '', cuotas: [] };

/**
 * Reparte el total en `n` cuotas de 2 decimales (ROUND_HALF_UP); la última absorbe la
 * diferencia para que la suma sea exactamente el total (8 decimales, como valida el backend).
 */
export function distribuirCuotas(total: string, fechas: string[]): CuotaForm[] {
  const n = fechas.length;
  if (n === 0) return [];
  const t = decimalOCero(total);
  const base = new Big(redondear(t.div(n), 2));
  const cuotas = fechas.map((fecha) => ({ fecha_vencimiento: fecha, monto: redondear(base, 2) }));
  const resto = restar(t, base.times(n - 1));
  const exacto = aDecimalesBd(resto);
  cuotas[n - 1].monto = new Big(exacto).eq(new Big(redondear(resto, 2))) ? redondear(resto, 2) : exacto;
  return cuotas;
}

/** Fechas mensuales a partir de la emisión (mismo día; fin de mes si no existe). */
export function fechasMensuales(emision: string, n: number): string[] {
  const [a, m, d] = emision.split('-').map(Number);
  if (!a || !m || !d) return [];
  return Array.from({ length: n }, (_, i) => {
    const ultimoDia = new Date(Date.UTC(a, m + i + 1, 0)).getUTCDate();
    const fecha = new Date(Date.UTC(a, m - 1 + i + 1, Math.min(d, ultimoDia)));
    return fecha.toISOString().slice(0, 10);
  });
}

export function sumaCuotas(cuotas: readonly CuotaForm[]): string {
  return aDecimalesBd(sumar(...cuotas.map((c) => c.monto)));
}

/** Errores de la condición de pago en el formulario (null si está bien). */
export function errorCondicionPago(p: {
  condicion: 'CONTADO' | 'CREDITO';
  fechaVencimiento: string;
  fechaEmision: string;
  cuotas: readonly CuotaForm[];
  total: string;
}): string | null {
  if (p.condicion === 'CONTADO') return null;
  if (!p.fechaVencimiento) return 'Ingrese la fecha de vencimiento del crédito.';
  if (p.fechaEmision && p.fechaVencimiento < p.fechaEmision) return 'El vencimiento no puede ser anterior a la emisión.';
  if (p.cuotas.length === 0) return null;
  for (let i = 0; i < p.cuotas.length; i++) {
    const c = p.cuotas[i];
    if (!c.fecha_vencimiento) return `Cuota ${i + 1}: falta la fecha.`;
    const monto = aDecimal(c.monto);
    if (!monto || monto.lte(0)) return `Cuota ${i + 1}: el monto debe ser mayor a 0.`;
    if (p.fechaEmision && c.fecha_vencimiento < p.fechaEmision) return `Cuota ${i + 1}: vence antes de la emisión.`;
    if (c.fecha_vencimiento > p.fechaVencimiento) return `Cuota ${i + 1}: vence después del vencimiento del comprobante.`;
    if (i > 0 && c.fecha_vencimiento < p.cuotas[i - 1].fecha_vencimiento) return 'Las cuotas deben estar en orden de vencimiento.';
  }
  if (p.cuotas[p.cuotas.length - 1].fecha_vencimiento !== p.fechaVencimiento) {
    return 'La última cuota debe vencer en la fecha de vencimiento del comprobante.';
  }
  if (comparar(sumaCuotas(p.cuotas), aDecimalesBd(p.total)) !== 0) {
    return `La suma de las cuotas (${sumaCuotas(p.cuotas)}) debe ser igual al total (${aDecimalesBd(p.total)}).`;
  }
  return null;
}

// ---- Estados financieros -------------------------------------------------------------------

export type EstadoFinancieroUI = 'PENDIENTE' | 'PARCIAL' | 'PAGADO' | 'VENCIDO';

export const ETIQUETA_ESTADO_FINANCIERO: Record<EstadoFinancieroUI, { texto: string; variante: 'neutral' | 'warning' | 'success' | 'destructive' }> = {
  PENDIENTE: { texto: 'Pendiente', variante: 'neutral' },
  PARCIAL: { texto: 'Parcial', variante: 'warning' },
  PAGADO: { texto: 'Pagado', variante: 'success' },
  VENCIDO: { texto: 'Vencido', variante: 'destructive' },
};

/** Error del monto de un pago frente al saldo (null si se puede enviar). */
export function errorMontoPago(monto: string, saldo: string): string | null {
  const m = aDecimal(monto);
  if (!m || m.lte(0)) return 'El monto debe ser mayor a 0.';
  if (m.gt(decimalOCero(saldo))) return `El monto supera el saldo pendiente (${aDecimalesBd(saldo)}).`;
  return null;
}

/**
 * Serie-número para mostrar: con serie automática el correlativo oficial de 8 dígitos
 * (F001-00000026); en los demás, el número normalizado de siempre.
 */
export const numeroComprobante = (d: { serie_normalizada: string; numero_normalizado: string; serie_comprobante?: number | null }) =>
  `${d.serie_normalizada}-${d.serie_comprobante ? d.numero_normalizado.padStart(8, '0') : d.numero_normalizado}`;

/** "F001-00000026" o "F001-26" según cómo se registró el número. */
export const comprobanteTexto = (serie: string | null | undefined, numero: string | null | undefined) =>
  `${serie || '—'}-${numero || '—'}`;
