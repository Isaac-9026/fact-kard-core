/**
 * Importación Excel de comprobantes: lógica de pantalla sin React (filtros, proveedores elegidos
 * para compras sin RUC y cuándo se puede confirmar). Sin aritmética de montos: los importes
 * los calcula el backend.
 */
import type {
  ComprobanteImportado, EstadoComprobanteImportado, FiltrosDiferencias, NivelDiferencia, PrevisualizacionImportacion,
} from '../api/importacion.ts';

export type FiltroImportacion = 'TODOS' | EstadoComprobanteImportado | 'OBSERVADOS' | 'SIN_PROVEEDOR';

export const ETIQUETA_ESTADO: Record<EstadoComprobanteImportado, string> = {
  NUEVO: 'Nuevo',
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
  YA_EXISTE: comprobantes.filter((c) => c.estado === 'YA_EXISTE').length,
  CONFLICTO: comprobantes.filter((c) => c.estado === 'CONFLICTO').length,
  ERROR: comprobantes.filter((c) => c.estado === 'ERROR').length,
  OBSERVADOS: comprobantes.filter((c) => c.observaciones.length > 0).length,
  SIN_PROVEEDOR: sinProveedor(comprobantes, proveedores).length,
});

/** Asigna (solo en memoria) un proveedor a todas las compras sin RUC que aún no lo tienen. */
export const aplicarProveedorATodas = (
  comprobantes: ComprobanteImportado[], proveedores: Record<string, string>, ruc: string,
): Record<string, string> => {
  const nuevo = { ...proveedores };
  sinProveedor(comprobantes, proveedores).forEach((c) => {
    if (c.clave_proveedor) nuevo[c.clave_proveedor] = ruc;
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
  const pendientes = sinProveedor(previa.comprobantes, proveedores).length;
  if (pendientes) return `Elija el proveedor de ${pendientes} compra(s) sin RUC.`;
  const { resumen } = previa;
  if (resumen.excede_limite) return `El lote supera ${resumen.limite_lote} comprobantes: divídalo por meses.`;
  if (resumen.con_error || resumen.conflictos) {
    return `Corrija ${resumen.con_error + resumen.conflictos} comprobante(s) con error o en conflicto.`;
  }
  if (!resumen.nuevos) return 'No hay comprobantes nuevos para grabar.';
  if (!almacenId) return 'Elija el almacén.';
  return resumen.puede_confirmar ? null : 'La previsualización no permite confirmar.';
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

// ── Paso 4: diferencias costo Excel vs Kardex ──
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
