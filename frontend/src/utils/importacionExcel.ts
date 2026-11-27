/**
 * Importación Excel de comprobantes: lógica de pantalla sin React (filtros, paginación,
 * proveedores elegidos para compras sin RUC, estado de polling y validaciones de confirmación).
 * Sin aritmética float de montos: los importes los calcula el backend.
 */
import type {
  ComprobanteImportado, EstadoComprobanteImportado, FiltroServidorPrevisualizacion, FiltrosDiferencias,
  NivelDiferencia, PrevisualizacionImportacion, ResultadoAnulacionLote, ResultadoImportacion, TrabajoImportacion,
} from '../api/importacion.ts';

export type FiltroImportacion = 'TODOS' | EstadoComprobanteImportado | 'OBSERVADOS' | 'SIN_PROVEEDOR';

export const FILTRO_A_SERVIDOR: Record<FiltroImportacion, FiltroServidorPrevisualizacion> = {
  TODOS: 'todos',
  NUEVO: 'nuevos',
  COMPLETAR: 'a_completar',
  YA_EXISTE: 'ya_existen',
  ERROR: 'errores',
  CONFLICTO: 'conflictos',
  SIN_PROVEEDOR: 'sin_proveedor',
  OBSERVADOS: 'observaciones',
};

export const ETIQUETA_ESTADO: Record<EstadoComprobanteImportado, string> = {
  NUEVO: 'Nuevo',
  COMPLETAR: 'Completar',
  YA_EXISTE: 'Ya existe',
  CONFLICTO: 'Conflicto',
  ERROR: 'Error',
};

export const ETIQUETA_OPERACION: Record<string, string> = {
  '01': 'Venta',
  '02': 'Compra',
  '05': 'Devolución recibida',
  '06': 'Devolución entregada',
};

export const ETIQUETA_TIPO: Record<string, string> = { '01': 'Factura', '03': 'Boleta', '07': 'N. crédito', '08': 'N. débito' };

export const ETIQUETA_FASE_TRABAJO: Record<string, string> = {
  EN_COLA: 'En cola',
  INICIANDO: 'Iniciando',
  LEYENDO_ARCHIVOS: 'Leyendo archivos',
  ANALIZANDO: 'Analizando Excel',
  GRABANDO_COMPROBANTES: 'Grabando comprobantes',
  RECALCULANDO_KARDEX: 'Recalculando Kardex',
  VALIDANDO_ANULACION: 'Validando anulación',
  ANULANDO_COMPROBANTES: 'Anulando comprobantes',
  COMPLETADO: 'Completado',
  ERROR: 'Error',
};

export const rucValido = (ruc: string): boolean => /^(10|15|16|17|20)\d{9}$/.test(ruc.trim());

/** Compras sin RUC que todavía no tienen proveedor elegido en pantalla. */
export const sinProveedor = (comprobantes: ComprobanteImportado[], proveedores: Record<string, string>) =>
  comprobantes.filter((c) => c.requiere_proveedor && c.clave_proveedor && !proveedores[c.clave_proveedor]);

export const filtrarComprobantes = (
  comprobantes: ComprobanteImportado[], filtro: FiltroImportacion, proveedores: Record<string, string>,
): ComprobanteImportado[] => {
  if (filtro === 'TODOS') return comprobantes;
  if (filtro === 'OBSERVADOS') return comprobantes.filter((c) => c.observaciones.length > 0);
  if (filtro === 'SIN_PROVEEDOR') return sinProveedor(comprobantes, proveedores);
  return comprobantes.filter((c) => c.estado === filtro);
};

export const contarPorFiltro = (comprobantes: ComprobanteImportado[], proveedores: Record<string, string>) => ({
  TODOS: comprobantes.length,
  NUEVO: comprobantes.filter((c) => c.estado === 'NUEVO').length,
  COMPLETAR: comprobantes.filter((c) => c.estado === 'COMPLETAR').length,
  YA_EXISTE: comprobantes.filter((c) => c.estado === 'YA_EXISTE').length,
  CONFLICTO: comprobantes.filter((c) => c.estado === 'CONFLICTO').length,
  ERROR: comprobantes.filter((c) => c.estado === 'ERROR').length,
  OBSERVADOS: comprobantes.filter((c) => c.observaciones.length > 0).length,
  SIN_PROVEEDOR: sinProveedor(comprobantes, proveedores).length,
});

/** Contadores globales de la previsualización paginada (usa totales del servidor cuando están presentes). */
export const contadoresDesdePrevia = (
  previa: PrevisualizacionImportacion | null,
  proveedores: Record<string, string>,
): Record<FiltroImportacion, number> => {
  if (!previa) {
    return { TODOS: 0, NUEVO: 0, COMPLETAR: 0, YA_EXISTE: 0, CONFLICTO: 0, ERROR: 0, OBSERVADOS: 0, SIN_PROVEEDOR: 0 };
  }
  if (previa.contadores) {
    return {
      TODOS: previa.contadores.todos,
      NUEVO: previa.contadores.nuevos,
      COMPLETAR: previa.contadores.a_completar,
      YA_EXISTE: previa.contadores.ya_existen,
      CONFLICTO: previa.contadores.conflictos,
      ERROR: previa.contadores.errores,
      OBSERVADOS: previa.contadores.observaciones,
      SIN_PROVEEDOR: previa.contadores.sin_proveedor,
    };
  }
  return contarPorFiltro(previa.comprobantes, proveedores);
};

/** Asigna (solo en memoria) un proveedor a todas las compras sin RUC visibles que aún no lo tienen. */
export const aplicarProveedorATodas = (
  comprobantes: ComprobanteImportado[], proveedores: Record<string, string>, ruc: string,
): Record<string, string> => {
  const nuevo = { ...proveedores };
  sinProveedor(comprobantes, proveedores).forEach((c) => {
    if (c.clave_proveedor) nuevo[c.clave_proveedor] = ruc;
  });
  return nuevo;
};

/** Asigna un proveedor a todas las claves pendientes devueltas por el servidor (soporta múltiples páginas). */
export const aplicarProveedorAClaves = (
  claves: string[], proveedores: Record<string, string>, ruc: string,
): Record<string, string> => {
  const nuevo = { ...proveedores };
  claves.forEach((clave) => {
    if (clave && !nuevo[clave]) nuevo[clave] = ruc;
  });
  return nuevo;
};

export const asignarProveedor = (
  proveedores: Record<string, string>, clave: string, ruc: string,
): Record<string, string> => {
  const nuevo = { ...proveedores };
  if (ruc) nuevo[clave] = ruc;
  else delete nuevo[clave];
  return nuevo;
};

export const hayErroresParaDescargar = (previa: PrevisualizacionImportacion | null): boolean => {
  if (!previa) return false;
  const r = previa.resumen;
  return Boolean(
    r.con_error > 0 || r.conflictos > 0 || (r.observaciones ?? r.filas_con_observacion) > 0,
  );
};

export const rangoPagina = (page: number, pageSize: number, total: number): { desde: number; hasta: number } => {
  if (total <= 0) return { desde: 0, hasta: 0 };
  const paginaSegura = Math.max(1, page);
  const desde = (paginaSegura - 1) * pageSize + 1;
  const hasta = Math.min(paginaSegura * pageSize, total);
  return { desde, hasta };
};

/** Texto corto de lo que se grabará: "56 nuevos y 2 por completar (2 líneas)". */
export const textoPorGrabar = (resumen: Pick<PrevisualizacionImportacion['resumen'], 'nuevos' | 'completar' | 'lineas_a_agregar'>): string => {
  const partes = [];
  if (resumen.nuevos) partes.push(`${resumen.nuevos} ${resumen.nuevos === 1 ? 'nuevo' : 'nuevos'}`);
  if (resumen.completar) {
    partes.push(`${resumen.completar} por completar (${resumen.lineas_a_agregar} ${resumen.lineas_a_agregar === 1 ? 'línea' : 'líneas'})`);
  }
  return partes.length ? partes.join(' y ') : 'nada';
};

/**
 * Solo se confirma con una previsualización vigente (hecha con los mismos archivos y proveedores),
 * sin errores ni conflictos, sin compras pendientes de proveedor y con un almacén elegido.
 */
export const motivoNoConfirmable = ({
  previa, desactualizada, almacenId, proveedores,
}: {
  previa: PrevisualizacionImportacion | null;
  desactualizada: boolean;
  almacenId: number | null;
  proveedores: Record<string, string>;
}): string | null => {
  if (!previa) return 'Primero previsualice los archivos.';
  if (desactualizada) return 'Cambió algo desde la última previsualización: vuelva a previsualizar.';
  const pendientesPagina = sinProveedor(previa.comprobantes, proveedores).length;
  const pendientesServidor = previa.resumen.requieren_proveedor ?? 0;
  const pendientes = Math.max(pendientesPagina, pendientesServidor);
  if (pendientes) return `Elija el proveedor de ${pendientes} compra(s) sin RUC.`;
  const { resumen } = previa;
  if (resumen.excede_limite) return `El lote supera ${resumen.limite_lote} comprobantes: divídalo por meses.`;
  if (resumen.con_error || resumen.conflictos) {
    return `Corrija ${resumen.con_error + resumen.conflictos} comprobante(s) con error o en conflicto.`;
  }
  if (!resumen.nuevos && !resumen.completar) return 'No hay comprobantes nuevos ni líneas por agregar.';
  if (!almacenId) return 'Elija el almacén.';
  return resumen.puede_confirmar ? null : 'La previsualización no permite confirmar.';
};

export const trabajoActivo = (trabajo: TrabajoImportacion | null | undefined): boolean =>
  Boolean(trabajo && (trabajo.estado === 'EN_COLA' || trabajo.estado === 'PROCESANDO'));

export const debeContinuarPolling = (trabajo: TrabajoImportacion | null | undefined): boolean =>
  trabajoActivo(trabajo);

export const etiquetaFaseTrabajo = (fase?: string | null): string =>
  (fase && ETIQUETA_FASE_TRABAJO[fase]) || fase || 'Procesando';

export const textoProgresoTrabajo = (trabajo: TrabajoImportacion): string => {
  const p = trabajo.progreso;
  const fase = etiquetaFaseTrabajo(p?.fase ?? trabajo.estado);
  if (!p || p.total <= 0) return p?.mensaje || `${fase}…`;
  return `${fase} · ${p.actual} / ${p.total} (${p.porcentaje}%)`;
};

export const resultadoDesdeTrabajo = (trabajo: TrabajoImportacion): ResultadoImportacion | null => {
  if (trabajo.estado !== 'COMPLETADO' || trabajo.tipo !== 'CONFIRMAR') return null;
  const r = trabajo.resumen as Partial<ResultadoImportacion>;
  return {
    lote: Number(r.lote ?? trabajo.lote_id ?? 0),
    comprobantes: Number(r.comprobantes ?? 0),
    completados: Number(r.completados ?? 0),
    lineas_agregadas: Number(r.lineas_agregadas ?? 0),
    omitidos: Number(r.omitidos ?? 0),
    segundos: Number(r.segundos ?? 0),
  };
};

export const resumenAnulacionDesdeTrabajo = (trabajo: TrabajoImportacion): ResultadoAnulacionLote | null => {
  if (trabajo.estado !== 'COMPLETADO' || trabajo.tipo !== 'ANULAR') return null;
  const r = trabajo.resumen as Partial<ResultadoAnulacionLote>;
  return {
    lote: Number(r.lote ?? trabajo.lote_id ?? 0),
    estado: 'ANULADO',
    comprobantes_anulados: Number(r.comprobantes_anulados ?? 0),
    lineas_revertidas: Number(r.lineas_revertidas ?? 0),
    comprobantes_revertidos: Array.isArray(r.comprobantes_revertidos) ? r.comprobantes_revertidos : [],
  };
};

export const fechaCorta = (iso: string | null): string => {
  if (!iso) return '—';
  const [a, m, d] = iso.slice(0, 10).split('-');
  return d && m && a ? `${d}/${m}/${a}` : iso;
};

export const archivosXlsx = (archivos: File[]): { validos: File[]; rechazados: string[] } => ({
  validos: archivos.filter((a) => a.name.toLowerCase().endsWith('.xlsx')),
  rechazados: archivos.filter((a) => !a.name.toLowerCase().endsWith('.xlsx')).map((a) => a.name),
});

// ── Diferencias costo Excel vs Kardex ──
export const ETIQUETA_NIVEL: Record<NivelDiferencia, string> = {
  VERDE: 'OK',
  AMBAR: 'Error A · menor',
  ROJO: 'Error B · crítica',
};

export const VARIANTE_NIVEL = { VERDE: 'success', AMBAR: 'warning', ROJO: 'destructive' } as const;

/** Signo de un monto que llega como texto del backend (sin convertirlo a número). */
export const signoMonto = (valor: string | null): -1 | 0 | 1 => {
  if (!valor) return 0;
  const limpio = valor.trim();
  if (/^-?0*(\.0*)?$/.test(limpio)) return 0;
  return limpio.startsWith('-') ? -1 : 1;
};

/** Texto de un monto con signo explícito: "+2.50", "-4.00", "0.00"; "—" si no hay dato. */
export const montoConSigno = (valor: string | null): string => {
  if (valor === null || valor === undefined || valor === '') return '—';
  return signoMonto(valor) === 1 && !valor.startsWith('+') ? `+${valor}` : valor;
};

export const nombreArchivoDiferencias = (loteId: number, filtros: FiltrosDiferencias, codigoProducto?: string): string =>
  ['diferencias_lote', String(loteId), filtros.producto && codigoProducto ? codigoProducto : '', filtros.nivel ? filtros.nivel.toLowerCase() : '']
    .filter(Boolean).join('_').replace(/[^A-Za-z0-9_-]/g, '') + '.xlsx';
