import apiClient from './http';

export type EstadoPeriodo = 'ABIERTO' | 'CERRADO' | 'DESACTUALIZADO';
export type MetodoIgv = 'TOTAL' | 'NULO' | 'PRORRATA';

export interface ConfigIgvInfo {
  id: number;
  metodo: MetodoIgv;
  porcentaje_recuperable: string;
  creado_en?: string | null;
}

export interface Periodo {
  id: number;
  empresa: number;
  anio: number;
  mes: number;
  orden: number;
  fecha_inicio: string;
  fecha_fin: string;
  estado: EstadoPeriodo;
  motivo_desactualizado: string | null;
  cerrado_por: number | null;
  cerrado_en: string | null;
  reabierto_por: number | null;
  reabierto_en: string | null;
  motivo_reapertura: string | null;
  config_igv: ConfigIgvInfo | null;
}

export interface CrearPeriodoPayload {
  anio: number;
  mes: number;
  fecha_inicio: string;
  fecha_fin: string;
}

export interface ReabrirPeriodoPayload {
  motivo_reapertura: string;
}

export interface ConfigurarIgvPayload {
  metodo: MetodoIgv;
  porcentaje_recuperable?: string;
}

export interface ReaperturaResponse {
  mensaje: string;
  periodos_desactualizados: number;
  periodo: Periodo;
}

export const obtenerPeriodos = async (): Promise<Periodo[]> => {
  const { data } = await apiClient.get<Periodo[]>('/empresas/periodos/');
  return data;
};

export const crearPeriodo = async (payload: CrearPeriodoPayload): Promise<Periodo> => {
  const { data } = await apiClient.post<Periodo>('/empresas/periodos/', payload);
  return data;
};

export const cerrarPeriodo = async (id: number): Promise<{ mensaje: string; periodo: Periodo }> => {
  const { data } = await apiClient.post<{ mensaje: string; periodo: Periodo }>(`/empresas/periodos/${id}/cerrar/`);
  return data;
};

export const reabrirPeriodo = async (id: number, payload: ReabrirPeriodoPayload): Promise<ReaperturaResponse> => {
  const { data } = await apiClient.post<ReaperturaResponse>(`/empresas/periodos/${id}/reabrir/`, payload);
  return data;
};

export const obtenerConfigIgvPeriodo = async (periodoId: number): Promise<ConfigIgvInfo> => {
  const { data } = await apiClient.get<ConfigIgvInfo>(`/empresas/periodos/${periodoId}/igv/`);
  return data;
};

export const configurarIgvPeriodo = async (
  periodoId: number,
  payload: ConfigurarIgvPayload
): Promise<ConfigIgvInfo> => {
  const { data } = await apiClient.post<ConfigIgvInfo>(`/empresas/periodos/${periodoId}/igv/`, payload);
  return data;
};

/** Configuración → Períodos e IGV → «Abrir año». */
export interface CoberturaIgvMes { cubierto: boolean; dias_sin_cobertura: number; sin_cobertura_hasta: string | null }

export interface MesAnio {
  mes: number;
  nombre: string;
  etiqueta: string;
  fecha_inicio: string;
  fecha_fin: string;
  existe: boolean;
  periodo_id: number | null;
  estado: EstadoPeriodo | null;
  igv: CoberturaIgvMes;
}

export interface VistaPreviaAnio {
  anio: number;
  meses: MesAnio[];
  faltantes: number[];
  primera_vigencia_igv: string | null;
  advertencia_igv: string | null;
}

export interface ResultadoAbrirAnio {
  anio: number;
  creados: { id: number; mes: number; etiqueta: string }[];
  existentes: number[];
  total_creados: number;
  total_existentes: number;
  advertencia_igv: string | null;
}

export const obtenerVistaPreviaAnio = async (anio: number): Promise<VistaPreviaAnio> => {
  const { data } = await apiClient.get<VistaPreviaAnio>('/empresas/periodos/abrir-anio/', { params: { anio } });
  return data;
};

export const abrirAnio = async (anio: number, meses: number[]): Promise<ResultadoAbrirAnio> => {
  const { data } = await apiClient.post<ResultadoAbrirAnio>('/empresas/periodos/abrir-anio/', { anio, meses });
  return data;
};
