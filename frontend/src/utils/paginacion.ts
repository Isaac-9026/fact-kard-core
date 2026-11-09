/**
 * Bloque 7 — paginación real contra el backend (`?page=&page_size=`, Bloque 6).
 *
 * Funciones puras para que las páginas compartan la misma lógica y se puedan probar:
 * - parámetros que se envían a la API,
 * - lectura de la respuesta `{count, next, previous, results}` (o `paginacion` del Kardex),
 * - página vigente: vuelve a 1 cuando cambia la "clave" (empresa + filtros), sin efectos.
 */

export const PAGE_SIZE_DEFECTO = 50;

/** Respuesta paginada de DRF. */
export interface Paginado<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

/** Metadatos de paginación que devuelve `/api/reportes/kardex/`. */
export interface MetaPaginacion {
  count: number;
  page: number;
  page_size: number;
  num_pages: number;
  next: string | null;
  previous: string | null;
}

export interface ParamsPaginacion {
  page: number;
  page_size: number;
}

export const paramsPaginacion = (page: number, pageSize: number = PAGE_SIZE_DEFECTO): ParamsPaginacion => ({
  page: Math.max(1, Math.trunc(page) || 1),
  page_size: Math.max(1, Math.trunc(pageSize) || PAGE_SIZE_DEFECTO),
});

/**
 * Acepta la respuesta paginada o, por compatibilidad, una lista completa (servidor sin
 * paginar): en ese caso todo cabe en una página.
 */
export const leerPaginado = <T>(data: Paginado<T> | T[]): Paginado<T> => {
  if (Array.isArray(data)) return { count: data.length, next: null, previous: null, results: data };
  return {
    count: Number(data.count) || 0,
    next: data.next ?? null,
    previous: data.previous ?? null,
    results: Array.isArray(data.results) ? data.results : [],
  };
};

export interface ResumenPagina {
  page: number;
  totalPaginas: number;
  /** Número (1-based) del primer registro mostrado; 0 si no hay registros. */
  desde: number;
  hasta: number;
  count: number;
  hayAnterior: boolean;
  haySiguiente: boolean;
}

export const resumenPagina = (page: number, pageSize: number, count: number, enPagina?: number): ResumenPagina => {
  const totalPaginas = Math.max(1, Math.ceil(count / Math.max(1, pageSize)));
  const actual = Math.min(Math.max(1, page), totalPaginas);
  const desde = count === 0 ? 0 : (actual - 1) * pageSize + 1;
  const hasta = count === 0 ? 0 : Math.min(count, desde - 1 + (enPagina ?? pageSize));
  return {
    page: actual,
    totalPaginas,
    desde,
    hasta,
    count,
    hayAnterior: actual > 1,
    haySiguiente: actual < totalPaginas,
  };
};

/** Clave estable de los criterios de consulta (empresa + filtros). */
export const claveConsulta = (...partes: Array<string | number | null | undefined>): string =>
  JSON.stringify(partes.map((p) => (p === undefined || p === null ? '' : String(p))));

export interface EstadoPagina {
  clave: string;
  page: number;
}

/**
 * Página que corresponde mostrar: si la clave (empresa o filtros) cambió desde que se
 * eligió la página, se reinicia a 1.
 */
export const paginaVigente = (estado: EstadoPagina, claveActual: string): number =>
  estado.clave === claveActual ? Math.max(1, estado.page) : 1;

export const irAPagina = (claveActual: string, page: number): EstadoPagina => ({
  clave: claveActual,
  page: Math.max(1, Math.trunc(page) || 1),
});
