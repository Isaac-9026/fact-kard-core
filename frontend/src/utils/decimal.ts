/**
 * Bloque 9 — aritmética decimal exacta para importes del frontend.
 *
 * El backend (Django, `decimal.Decimal`) es la fuente de verdad contable y redondea con
 * ROUND_HALF_UP. Aquí se replica lo mínimo para PREVISUALIZAR y MOSTRAR exactamente lo que
 * el backend va a guardar, sin pasar por `Number` (IEEE-754: 0.1 + 0.2 = 0.30000000000000004,
 * (1.005).toFixed(2) = "1.00").
 *
 * Reglas:
 * - Entradas como texto (como vienen de la API y de los <input>). Un `number` solo se
 *   acepta si es entero o viene de un endpoint que entrega números (se convierte con su
 *   representación más corta, sin operar en binario).
 * - Redondeo ROUND_HALF_UP (mitad lejos de cero), igual que Python.
 * - Nunca Decimal → float → Decimal.
 */
import Big from 'big.js';

/** Constructor aislado: no se modifica la configuración global de Big. */
const D = Big();
D.DP = 40; // decimales de las divisiones (no se usan para importes, solo por seguridad)
D.RM = Big.roundHalfUp;
D.strict = false;

export type ValorDecimal = string | number | null | undefined;

/** Decimales que usa el backend en los campos DecimalField(20, 8). */
export const DECIMALES_BD = 8;

/** Convierte a Big; texto vacío, inválido o no finito → null. */
export function aDecimal(valor: ValorDecimal): Big | null {
  if (valor === null || valor === undefined) return null;
  if (typeof valor === 'number' && !Number.isFinite(valor)) return null;
  const texto = String(valor).trim();
  if (texto === '') return null;
  try {
    return D(texto);
  } catch {
    return null;
  }
}

/** Como aDecimal, pero un valor vacío o inválido cuenta como 0 (igual que el formulario actual). */
export function decimalOCero(valor: ValorDecimal): Big {
  return aDecimal(valor) ?? D(0);
}

/** Redondea con ROUND_HALF_UP a `decimales` y devuelve texto con exactamente esos decimales. */
export function redondear(valor: Big | ValorDecimal, decimales: number): string {
  const numero = valor instanceof Big ? valor : decimalOCero(valor);
  return numero.round(decimales, Big.roundHalfUp).toFixed(decimales);
}

/** quantize(Decimal('0.00000001'), ROUND_HALF_UP) del backend. */
export function aDecimalesBd(valor: Big | ValorDecimal): string {
  return redondear(valor, DECIMALES_BD);
}

export function sumar(...valores: (Big | ValorDecimal)[]): Big {
  return valores.reduce<Big>((acc, v) => acc.plus(v instanceof Big ? v : decimalOCero(v)), D(0));
}

export function multiplicar(a: Big | ValorDecimal, b: Big | ValorDecimal): Big {
  return (a instanceof Big ? a : decimalOCero(a)).times(b instanceof Big ? b : decimalOCero(b));
}

export function restar(a: Big | ValorDecimal, b: Big | ValorDecimal): Big {
  return (a instanceof Big ? a : decimalOCero(a)).minus(b instanceof Big ? b : decimalOCero(b));
}

/** Comparación segura (sin float): -1, 0 o 1. Valores inválidos cuentan como 0. */
export function comparar(a: ValorDecimal, b: ValorDecimal): -1 | 0 | 1 {
  return decimalOCero(a).cmp(decimalOCero(b)) as -1 | 0 | 1;
}

export function esMayorQueCero(valor: ValorDecimal): boolean {
  const d = aDecimal(valor);
  return d !== null && d.gt(0);
}

const formateadores = new Map<string, Intl.NumberFormat>();

/**
 * Formato es-PE para mostrar (separador de miles, decimales mínimos/máximos).
 * Primero se redondea en decimal con ROUND_HALF_UP al máximo de decimales; recién entonces
 * se da formato. Así 1.005 se muestra "1.01" (como el backend), no "1.00" como toFixed.
 * Devuelve `vacio` si el valor no existe o no es numérico.
 */
export function formatearDecimal(
  valor: ValorDecimal,
  { min = 2, max = 2, vacio = '—' }: { min?: number; max?: number; vacio?: string } = {},
): string {
  const numero = aDecimal(valor);
  if (numero === null) return vacio;
  const redondeado = numero.round(max, Big.roundHalfUp);
  const clave = `${min}:${max}`;
  let fmt = formateadores.get(clave);
  if (!fmt) {
    fmt = new Intl.NumberFormat('es-PE', { minimumFractionDigits: min, maximumFractionDigits: max });
    formateadores.set(clave, fmt);
  }
  // El texto ya tiene como máximo `max` decimales: Intl solo agrega separadores y ceros, no
  // vuelve a redondear (el valor tiene ≤ 15 dígitos significativos en todo el sistema).
  return fmt.format(redondeado.toFixed(max) as unknown as number);
}
