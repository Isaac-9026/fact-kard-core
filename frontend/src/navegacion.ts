/**
 * Navegación por flujo del sistema: configuración → maestros → inventario inicial →
 * operaciones → Kardex → cierre y reportes → seguridad.
 *
 * Archivo sin JSX ni dependencias de React para poder probarlo con `node --test`.
 * El menú (MainLayout) y las rutas (App) se construyen a partir de estas constantes.
 */

export const RUTA_INICIAL = '/dashboard';
export const RUTA_LOGIN = '/login';

/** Clave del icono; MainLayout la traduce a un icono de lucide-react. */
export type IconoNav =
  | 'dashboard' | 'empresas' | 'periodos' | 'catalogos'
  | 'productos' | 'almacenes' | 'terceros'
  | 'saldoInicial' | 'inventario'
  | 'compras' | 'ventas' | 'comprobantes' | 'notas' | 'transferencias' | 'captura'
  | 'cuentasCobrar' | 'cuentasPagar'
  | 'kardex' | 'incidencias'
  | 'cierres' | 'formato131' | 'registroComercial'
  | 'auditoria';

export interface ItemNav {
  path: string;
  label: string;
  icono: IconoNav;
}

export interface SeccionNav {
  title: string;
  items: ItemNav[];
}

export const NAV_SECCIONES: SeccionNav[] = [
  {
    title: 'INICIO',
    items: [{ path: '/dashboard', label: 'Dashboard', icono: 'dashboard' }],
  },
  {
    title: 'CONFIGURACIÓN',
    items: [
      { path: '/empresas', label: 'Empresas y Anexos', icono: 'empresas' },
      { path: '/periodos', label: 'Períodos e IGV', icono: 'periodos' },
      { path: '/catalogos', label: 'Catálogos y TC SBS', icono: 'catalogos' },
    ],
  },
  {
    title: 'MAESTROS',
    items: [
      { path: '/productos', label: 'Productos y Unidades', icono: 'productos' },
      { path: '/almacenes', label: 'Almacenes', icono: 'almacenes' },
      { path: '/terceros', label: 'Terceros', icono: 'terceros' },
    ],
  },
  {
    title: 'INVENTARIO INICIAL',
    items: [
      { path: '/saldo-inicial', label: 'Saldo Inicial', icono: 'saldoInicial' },
      { path: '/inventario', label: 'Inventario', icono: 'inventario' },
    ],
  },
  {
    title: 'OPERACIONES',
    items: [
      // Bloque 13: Compras y Ventas son pestañas de Comprobantes (ya no opciones del menú).
      { path: '/comprobantes', label: 'Comprobantes', icono: 'comprobantes' },
      { path: '/notas', label: 'Notas de Crédito / Débito', icono: 'notas' },
      { path: '/transferencias', label: 'Transferencias', icono: 'transferencias' },
      { path: '/captura-homologacion', label: 'Captura XML / OCR', icono: 'captura' },
    ],
  },
  {
    // Bloque 16: flujo financiero (saldos calculados desde comprobantes y pagos).
    title: 'FINANZAS',
    items: [
      { path: '/cuentas-por-cobrar', label: 'Cuentas por cobrar', icono: 'cuentasCobrar' },
      { path: '/cuentas-por-pagar', label: 'Cuentas por pagar', icono: 'cuentasPagar' },
    ],
  },
  {
    title: 'KARDEX',
    items: [
      { path: '/kardex', label: 'Kardex Valorizado', icono: 'kardex' },
      { path: '/incidencias', label: 'Incidencias y Recálculo', icono: 'incidencias' },
    ],
  },
  {
    title: 'CIERRE Y REPORTES',
    items: [
      { path: '/cierres', label: 'Cierres y Snapshots', icono: 'cierres' },
      { path: '/formato-13-1', label: 'Formato 13.1 SUNAT', icono: 'formato131' },
      { path: '/registro-ventas-compras', label: 'Registro de ventas y compras', icono: 'registroComercial' },
    ],
  },
  {
    title: 'SEGURIDAD',
    items: [{ path: '/auditoria', label: 'Auditoría Inmutable', icono: 'auditoria' }],
  },
];

/**
 * Rutas antiguas que siguen funcionando (marcadores, enlaces guardados) y redirigen a su
 * nueva ubicación en el menú.
 */
export const RUTAS_ANTERIORES: Record<string, string> = {
  '/operaciones-internas': '/saldo-inicial',
  // Bloque 13: Compras, Ventas y Comprobantes (/documentos) son una sola pantalla.
  '/compras': '/comprobantes?clase=COMPRA',
  '/ventas': '/comprobantes?clase=VENTA',
  '/documentos': '/comprobantes',
};

/**
 * URL final de una redirección: la ruta nueva con sus parámetros, conservando los que traía
 * el enlace antiguo (p. ej. `/compras?nuevo=1` → `/comprobantes?clase=COMPRA&nuevo=1`). Si
 * ambos traen el mismo parámetro manda el del destino.
 */
export const destinoRedireccion = (hacia: string, searchActual: string): string => {
  const [ruta, queryDestino = ''] = hacia.split('?');
  const params = new URLSearchParams(searchActual);
  new URLSearchParams(queryDestino).forEach((valor, clave) => params.set(clave, valor));
  const query = params.toString();
  return query ? `${ruta}?${query}` : ruta;
};

export interface AccesoRapido {
  label: string;
  to: string;
}

/** `?nuevo=1` abre el formulario de nuevo comprobante con la clase ya elegida. */
export const ACCESOS_RAPIDOS: AccesoRapido[] = [
  { label: 'Nueva compra', to: '/comprobantes?clase=COMPRA&nuevo=1' },
  { label: 'Nueva venta', to: '/comprobantes?clase=VENTA&nuevo=1' },
  { label: 'Ver Kardex', to: '/kardex' },
  { label: 'Ver incidencias', to: '/incidencias' },
];

export const todasLasRutasDelMenu = (): string[] => NAV_SECCIONES.flatMap((s) => s.items.map((i) => i.path));

/** Sección y opción del menú que corresponden a una URL (para el encabezado y el resaltado). */
export const itemActivo = (pathname: string): { seccion: SeccionNav; item: ItemNav } | null => {
  for (const seccion of NAV_SECCIONES) {
    for (const item of seccion.items) {
      if (pathname === item.path || pathname.startsWith(`${item.path}/`)) return { seccion, item };
    }
  }
  return null;
};

/** A dónde va quien abre la raíz `/` o una ruta desconocida. */
export const destinoInicial = ({ token }: { token: string | null }): string =>
  token ? RUTA_INICIAL : RUTA_LOGIN;
