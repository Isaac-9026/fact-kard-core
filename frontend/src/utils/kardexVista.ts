// Bloque 4: reglas de presentación del Kardex (sin recalcular importes del backend).

export interface SaldoInicialProducto { producto_id: number; cantidad: string; cpp: string | null; valor: string }
export interface ResumenSaldoInicial { saldo_inicial_cantidad?: string; saldo_inicial_valor?: string }
export interface PeriodoBasico { id: number; estado: string }

export const SIN_DATO = '—';

/**
 * Fila SALDO INICIAL: visible siempre que el filtro arranque con saldo, haya o no
 * movimientos. El CPP solo tiene sentido con un único producto.
 */
export function filaSaldoInicialKardex(
  resumen: ResumenSaldoInicial | null | undefined,
  saldosIniciales: SaldoInicialProducto[] | null | undefined,
): { mostrar: boolean; cantidad: string; cpp: string | null; valor: string } {
  const cantidad = resumen?.saldo_inicial_cantidad ?? '0';
  const valor = resumen?.saldo_inicial_valor ?? '0';
  const mostrar = Number(cantidad) !== 0 || Number(valor) !== 0;
  const cpp = saldosIniciales && saldosIniciales.length === 1 ? saldosIniciales[0].cpp : null;
  return { mostrar, cantidad, cpp, valor };
}

/** El CPP de cierre no aplica a varios productos: el backend envía null y no se muestra 0. */
export function textoCppFinal(cppFinal: string | null | undefined, formatear: (v: string) => string): string {
  return cppFinal === null || cppFinal === undefined || cppFinal === '' ? 'No aplica' : `S/ ${formatear(cppFinal)}`;
}

const clave = (empresaId: number | string) => `kardex_periodo_${empresaId}`;

/** Período inicial: la última selección válida de esta pestaña; si no, el último abierto. */
export function periodoInicialKardex(periodos: PeriodoBasico[], guardado: string | null): string {
  if (guardado !== null && (guardado === '' || periodos.some((p) => String(p.id) === guardado))) return guardado;
  const abierto = periodos.find((p) => p.estado === 'ABIERTO');
  return abierto ? String(abierto.id) : '';
}

export function leerPeriodoGuardado(empresaId: number | string | undefined, almacen?: Storage): string | null {
  if (empresaId === undefined) return null;
  try {
    return (almacen ?? sessionStorage).getItem(clave(empresaId));
  } catch {
    return null;
  }
}

export function guardarPeriodo(empresaId: number | string | undefined, periodoId: string, almacen?: Storage): void {
  if (empresaId === undefined) return;
  try {
    (almacen ?? sessionStorage).setItem(clave(empresaId), periodoId);
  } catch {
    // almacenamiento no disponible: la selección simplemente no se recuerda
  }
}
