/**
 * Dashboard: funciones puras para presentar datos que ya entregan las APIs existentes.
 * No hay cálculos contables aquí: si un dato no está disponible se muestra SIN_DATO.
 */
import { periodoInicialKardex } from './kardexVista.ts';

export const SIN_DATO = '—';

export interface PeriodoDashboard { id: number; anio: number; mes: number; estado: string }
export interface CierreDashboard {
  periodo_info: { anio: number; mes: number; estado: string };
  version_calculo: number;
  vigente: boolean;
  cerrado_en: string;
  cerrado_por_username: string;
}
export interface IncidenciaDashboard { estado: string }

export const etiquetaPeriodo = (p: { anio: number; mes: number } | null | undefined): string =>
  p ? `${p.anio}-${String(p.mes).padStart(2, '0')}` : SIN_DATO;

/**
 * Período activo: el mismo criterio del Kardex (la última selección de la pestaña si
 * sigue existiendo; si no, el período ABIERTO más reciente; el backend los ordena del más
 * reciente al más antiguo).
 */
export const periodoActivo = <P extends PeriodoDashboard>(periodos: P[], guardado: string | null): P | null => {
  const id = periodoInicialKardex(periodos, guardado);
  return periodos.find((p) => String(p.id) === id) ?? null;
};

export const contarPendientes = (incidencias: IncidenciaDashboard[]): number =>
  incidencias.filter((i) => i.estado === 'PENDIENTE').length;

export interface ResumenCierre { titulo: string; detalle: string }

/** El backend devuelve los cierres del período más reciente primero (y su última versión). */
export const resumenUltimoCierre = (cierres: CierreDashboard[]): ResumenCierre | null => {
  const ultimo = cierres[0];
  if (!ultimo) return null;
  const fecha = (ultimo.cerrado_en || '').slice(0, 10);
  return {
    titulo: `${etiquetaPeriodo(ultimo.periodo_info)} · ${ultimo.periodo_info.estado}`,
    detalle: `Versión ${ultimo.version_calculo}${ultimo.vigente ? ' (vigente)' : ''}${fecha ? ` · ${fecha}` : ''}${
      ultimo.cerrado_por_username ? ` · ${ultimo.cerrado_por_username}` : ''
    }`,
  };
};

/** Texto de un dato que puede faltar: nunca se inventa un valor. */
export const textoODato = (valor: string | number | null | undefined, formato?: (v: string | number) => string): string => {
  if (valor === null || valor === undefined || valor === '') return SIN_DATO;
  return formato ? formato(valor) : String(valor);
};
