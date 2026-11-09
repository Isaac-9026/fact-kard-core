/**
 * Comprobantes y Notas de Crédito/Débito son la MISMA pantalla (DocumentosPage) con un modo
 * distinto. Aquí está toda la diferencia entre modos, como funciones puras: qué filtros fijos
 * se envían a la API, qué tipos de comprobante ofrece el formulario y con qué clase se abre.
 *
 * Bloque 13: Compras y Ventas dejaron de ser pantallas propias. Son las pestañas
 * `Todos | Compras | Ventas` de Comprobantes, guardadas en la URL (`/comprobantes?clase=COMPRA`);
 * las rutas antiguas `/compras` y `/ventas` redirigen ahí (navegacion.ts, RUTAS_ANTERIORES).
 */
export type ClaseVista = 'COMPRA' | 'VENTA';
export type VistaDocumentos = 'COMPROBANTES' | 'NOTAS';

export interface FiltrosUsuarioDocumentos {
  clase?: ClaseVista;
  periodo?: number;
  estado?: string;
  estado_revision?: string;
  search?: string;
}

export interface FiltrosApiDocumentos extends FiltrosUsuarioDocumentos {
  es_nota?: boolean;
}

export interface ConfigVistaDocumentos {
  titulo: string;
  descripcion: string;
  /** true = solo notas; false = sin notas. */
  esNota: boolean;
  botonNuevo: string;
}

export const CONFIG_VISTAS: Record<VistaDocumentos, ConfigVistaDocumentos> = {
  COMPROBANTES: {
    titulo: 'Comprobantes',
    descripcion: 'Gestión de comprobantes comerciales de compra y venta.',
    esNota: false,
    botonNuevo: 'Nuevo Comprobante',
  },
  NOTAS: {
    titulo: 'Notas de Crédito / Débito',
    descripcion: 'Notas de crédito y débito de compras y ventas, vinculadas a su comprobante de origen.',
    esNota: true,
    botonNuevo: 'Nueva Nota',
  },
};

/** Filtros que se envían a la API: los del usuario (incluida la clase de la pestaña) más los fijos de la vista. */
export const filtrosApiDocumentos = <F extends FiltrosUsuarioDocumentos>(
  vista: VistaDocumentos,
  usuario: F,
): F & { es_nota?: boolean } => ({ ...usuario, es_nota: CONFIG_VISTAS[vista].esNota });

/** Tipos de comprobante que ofrece el formulario según la vista (notas o no notas). */
export const tiposComprobanteDeVista = <T extends { es_nota?: boolean }>(vista: VistaDocumentos, tipos: T[]): T[] =>
  tipos.filter((t) => Boolean(t.es_nota) === CONFIG_VISTAS[vista].esNota);

// ---- Pestañas de Comprobantes -------------------------------------------------------------

export type TabComprobantes = 'TODOS' | ClaseVista;

export const TABS_COMPROBANTES: { valor: TabComprobantes; etiqueta: string }[] = [
  { valor: 'TODOS', etiqueta: 'Todos' },
  { valor: 'COMPRA', etiqueta: 'Compras' },
  { valor: 'VENTA', etiqueta: 'Ventas' },
];

/** `?clase=COMPRA` → Compras, `?clase=VENTA` → Ventas; sin parámetro (o inválido) → Todos. */
export const tabDesdeQuery = (clase: string | null | undefined): TabComprobantes => {
  const valor = (clase ?? '').trim().toUpperCase();
  return valor === 'COMPRA' || valor === 'VENTA' ? valor : 'TODOS';
};

/** Clase que se filtra en la API para la pestaña (Todos = sin filtro de clase). */
export const claseDeTab = (tab: TabComprobantes): ClaseVista | undefined => (tab === 'TODOS' ? undefined : tab);

/** Query de la URL al cambiar de pestaña: conserva los demás parámetros y solo cambia `clase`. */
export const queryConTab = (actual: string | URLSearchParams, tab: TabComprobantes): URLSearchParams => {
  const params = new URLSearchParams(actual);
  if (tab === 'TODOS') params.delete('clase');
  else params.set('clase', tab);
  return params;
};

/**
 * Clase con la que se abre "Nuevo Comprobante": la de la pestaña activa (Compras/Ventas) o la
 * última usada si se está en Todos. En el modal la clase se puede cambiar igual.
 */
export const claseInicialNuevo = (tab: TabComprobantes, actual: ClaseVista): ClaseVista => claseDeTab(tab) ?? actual;
