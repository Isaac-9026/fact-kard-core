import apiClient from './http';

export interface Moneda {
  codigo: string;
  nombre: string;
}

export interface TipoComprobante {
  id: number;
  codigo_sunat: string;
  descripcion: string;
  es_nota: boolean;
  efecto_nota: 'CREDITO' | 'DEBITO' | 'NINGUNO';
  activo: boolean;
}

export interface TipoOperacion {
  id: number;
  codigo_interno: string;
  codigo_sunat: string | null;
  descripcion: string;
  naturaleza: 'ENTRADA' | 'SALIDA' | 'AJUSTE_VALOR';
  es_interna: boolean;
  afecta_kardex: boolean;
  origen_requerido: string;
  activo: boolean;
}

export interface TipoExistencia {
  codigo: string;
  descripcion: string;
}

export interface UnidadMedida {
  codigo: string;
  descripcion: string;
}

export interface TipoCambio {
  id: number;
  moneda_codigo: string;
  fecha_publicacion: string;
  venta: string | null;
  compra: string | null;
  fuente: string;
}

export interface CrearTipoCambioPayload {
  moneda_codigo: string;
  fecha_publicacion: string;
  venta: string;
  compra: string;
  fuente?: string;
}

export interface TipoCambioResolverResult {
  id: number;
  moneda_codigo: string;
  fecha_publicacion: string;
  fecha_consultada: string;
  es_fecha_exacta: boolean;
  venta: string;
  compra: string;
  fuente: string;
}

export const obtenerMonedas = async (): Promise<Moneda[]> => {
  const { data } = await apiClient.get<Moneda[]>('/catalogos/monedas/');
  return data;
};

export const obtenerTiposComprobante = async (): Promise<TipoComprobante[]> => {
  const { data } = await apiClient.get<TipoComprobante[]>('/catalogos/tipos-comprobante/');
  return data;
};

export const obtenerTiposOperacion = async (): Promise<TipoOperacion[]> => {
  const { data } = await apiClient.get<TipoOperacion[]>('/catalogos/tipos-operacion/');
  return data;
};

export const obtenerTiposExistencia = async (): Promise<TipoExistencia[]> => {
  const { data } = await apiClient.get<TipoExistencia[]>('/catalogos/tipos-existencia/');
  return data;
};

export const obtenerUnidadesMedida = async (): Promise<UnidadMedida[]> => {
  const { data } = await apiClient.get<UnidadMedida[]>('/catalogos/unidades-medida/');
  return data;
};

export const obtenerTiposCambio = async (params?: { moneda?: string; fecha?: string }): Promise<TipoCambio[]> => {
  const { data } = await apiClient.get<TipoCambio[]>('/catalogos/tipos-cambio/', { params });
  return data;
};

export const crearTipoCambio = async (payload: CrearTipoCambioPayload): Promise<TipoCambio> => {
  const { data } = await apiClient.post<TipoCambio>('/catalogos/tipos-cambio/', payload);
  return data;
};

export const resolverTipoCambio = async (moneda: string, fecha: string): Promise<TipoCambioResolverResult> => {
  const { data } = await apiClient.get<TipoCambioResolverResult>('/catalogos/tipo-cambio/resolver/', {
    params: { moneda, fecha },
  });
  return data;
};

/** Bloque 17A: motivo tributario de NC (catálogo 09) o ND (catálogo 10). */
export interface MotivoNota { id: number; catalogo: '09' | '10'; codigo: string; descripcion: string; activo: boolean }

export const obtenerMotivosNota = async (catalogo: '09' | '10'): Promise<MotivoNota[]> =>
  (await apiClient.get<MotivoNota[]>('/catalogos/motivos-nota/', { params: { catalogo } })).data;

/** B17A-QA-001: Catálogo 07 desde su fuente canónica (backend), con descripción oficial. */
export interface CodigoAfectacionIgv {
  codigo: string;
  descripcion: string;
  afectacion: 'GRAVADO' | 'EXONERADO' | 'INAFECTO' | 'EXPORTACION' | 'GRATUITO' | null;
  soportado: boolean;
}

export const obtenerCatalogo07 = async (): Promise<CodigoAfectacionIgv[]> =>
  (await apiClient.get<CodigoAfectacionIgv[]>('/catalogos/afectaciones-igv/')).data;
