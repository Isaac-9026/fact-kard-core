/**
 * Bloque 16 — series y correlativos, condición de pago, pagos/cobros, cuentas por cobrar y
 * pagar, historial de terceros y registro de ventas/compras.
 */
import apiClient from './http';
import type { CondicionPago, Documento, EstadoFinanciero, Pago } from './documentos';

export interface SerieComprobante {
  id: number;
  establecimiento: number;
  establecimiento_codigo: string;
  establecimiento_nombre: string;
  tipo_comprobante: number;
  tipo_comprobante_codigo: string;
  tipo_comprobante_descripcion: string;
  serie: string;
  ultimo_correlativo: number;
  siguiente_numero: string;
  activo: boolean;
  en_uso: boolean;
}

export interface SeriePayload {
  establecimiento?: number;
  tipo_comprobante?: number;
  serie?: string;
  ultimo_correlativo?: number;
  activo?: boolean;
}

export interface MetodoPago { codigo: string; descripcion: string; activo: boolean }

export interface FilaCuenta {
  id: number;
  clase: 'COMPRA' | 'VENTA';
  tercero: number | null;
  tercero_razon_social: string | null;
  tercero_numero_documento: string | null;
  tipo_comprobante_codigo: string;
  serie: string;
  numero: string | null;
  numero_normalizado: string;
  fecha_emision: string;
  fecha_vencimiento: string | null;
  condicion_pago: CondicionPago;
  moneda_codigo: string;
  periodo: number;
  total: string;
  total_notas_credito: string;
  total_notas_debito: string;
  total_ajustado: string;
  pagado: string;
  saldo_pendiente: string;
  monto_vencido: string;
  estado_financiero: EstadoFinanciero;
}

export interface TotalesCuenta { total_ajustado: string; pagado: string; saldo_pendiente: string; monto_vencido: string }

export interface RespuestaCuentas {
  clase: 'COMPRA' | 'VENTA';
  fecha_corte: string;
  cantidad: number;
  resultados: FilaCuenta[];
  totales: Record<string, TotalesCuenta>;
}

export interface FiltrosCuentas {
  tercero?: number | string;
  periodo?: number | string;
  estado?: EstadoFinanciero | 'ABIERTOS' | '';
  condicion?: CondicionPago | 'TODAS';
}

export interface FilaHistorial {
  id: number;
  clase: 'COMPRA' | 'VENTA';
  fecha_emision: string;
  tipo_comprobante_codigo: string;
  es_nota: boolean;
  serie: string;
  numero: string | null;
  moneda_codigo: string;
  /** Importe del propio comprobante (en una nota, el importe de la nota). */
  total_original: string;
  /** B16-QA-001: importes conciliados por el backend (null en notas, borradores y anulados). */
  total_notas_credito: string | null;
  total_notas_debito: string | null;
  total_ajustado: string | null;
  pagado: string | null;
  saldo_pendiente: string | null;
  condicion_pago: CondicionPago;
  fecha_vencimiento: string | null;
  estado: string;
  estado_financiero: EstadoFinanciero | null;
}

export interface ResumenHistorial {
  clase: string;
  moneda_codigo: string;
  comprobantes: number;
  total_original: string;
  total_notas_credito: string;
  total_notas_debito: string;
  total_ajustado: string;
  pagado: string;
  saldo_pendiente: string;
}

export interface HistorialTercero {
  tercero: { id: number; tipo_documento: string; numero_documento: string; razon_social: string; es_cliente: boolean; es_proveedor: boolean };
  clases: ('COMPRA' | 'VENTA')[];
  comprobantes: FilaHistorial[];
  resumen: ResumenHistorial[];
}

export interface FilaRegistro {
  id: number;
  fecha_emision: string;
  tipo_comprobante_codigo: string;
  tipo_comprobante_descripcion: string;
  serie: string;
  numero: string;
  tercero_tipo_documento: string | null;
  tercero_numero_documento: string | null;
  tercero_razon_social: string | null;
  moneda_codigo: string;
  monto_tc: string | null;
  base: string;
  igv: string;
  total: string;
  condicion_pago: CondicionPago;
  estado: string;
}

export interface RegistroComercial {
  clase: 'COMPRA' | 'VENTA';
  periodo: { id: number; anio: number; mes: number };
  empresa: { ruc: string; razon_social: string };
  filas: FilaRegistro[];
  totales: Record<string, { base: string; igv: string; total: string; comprobantes: number }>;
}

const limpiar = (params: object) =>
  Object.fromEntries(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ''));

// Series
export const obtenerSeries = async (params?: { tipo_comprobante?: number; activo?: boolean }): Promise<SerieComprobante[]> =>
  (await apiClient.get<SerieComprobante[]>('/documentos/series/', { params: limpiar({ ...params, activo: params?.activo ? 1 : undefined }) })).data;
export const crearSerie = async (payload: SeriePayload): Promise<SerieComprobante> =>
  (await apiClient.post<SerieComprobante>('/documentos/series/', payload)).data;
export const actualizarSerie = async (id: number, payload: SeriePayload): Promise<SerieComprobante> =>
  (await apiClient.patch<SerieComprobante>(`/documentos/series/${id}/`, payload)).data;
export const eliminarSerie = async (id: number): Promise<void> => {
  await apiClient.delete(`/documentos/series/${id}/`);
};

// Pagos
export const obtenerMetodosPago = async (): Promise<MetodoPago[]> =>
  (await apiClient.get<MetodoPago[]>('/catalogos/metodos-pago/')).data;
export const registrarPago = async (payload: { documento: number; fecha: string; monto: string; metodo_pago: string; referencia?: string }): Promise<Pago> =>
  (await apiClient.post<Pago>('/documentos/pagos/', payload)).data;
export const anularPago = async (id: number, motivo: string): Promise<Pago> =>
  (await apiClient.post<Pago>(`/documentos/pagos/${id}/anular/`, { motivo })).data;
export const cambiarCondicionPago = async (
  id: number,
  payload: { condicion_pago: CondicionPago; fecha_vencimiento?: string | null; cuotas?: { fecha_vencimiento: string; monto: string }[]; motivo?: string },
): Promise<Documento> => (await apiClient.put<Documento>(`/documentos/${id}/condicion-pago/`, payload)).data;

// Cuentas
export const obtenerCuentas = async (tipo: 'cobrar' | 'pagar', filtros: FiltrosCuentas): Promise<RespuestaCuentas> =>
  (await apiClient.get<RespuestaCuentas>(`/documentos/cuentas-por-${tipo}/`, { params: limpiar(filtros) })).data;

// Historial
export const obtenerHistorialTercero = async (id: number, clase?: 'COMPRA' | 'VENTA'): Promise<HistorialTercero> =>
  (await apiClient.get<HistorialTercero>(`/inventario/terceros/${id}/historial/`, { params: limpiar({ clase }) })).data;

// Registro de ventas / compras
export const rutaRegistro = (clase: 'COMPRA' | 'VENTA') => (clase === 'VENTA' ? '/reportes/registro-ventas/' : '/reportes/registro-compras/');
export const obtenerRegistro = async (clase: 'COMPRA' | 'VENTA', periodo_id: number | string, estado?: string): Promise<RegistroComercial> =>
  (await apiClient.get<RegistroComercial>(rutaRegistro(clase), { params: limpiar({ periodo_id, estado }) })).data;
export const descargarRegistroExcel = async (clase: 'COMPRA' | 'VENTA', periodo_id: number | string, estado?: string): Promise<Blob> =>
  (await apiClient.get<Blob>(`${rutaRegistro(clase)}excel/`, { params: limpiar({ periodo_id, estado }), responseType: 'blob' })).data;
