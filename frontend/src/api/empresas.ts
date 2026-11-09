import apiClient from './http';

export type RolEmpresa = 'ADMIN' | 'USUARIO';
export interface Moneda { codigo: string; nombre: string }
export interface Empresa { id: number; ruc: string; razon_social: string; nombre_comercial: string | null; direccion: string | null; moneda_base_codigo: string; estado: 'ACTIVA' | 'INACTIVA'; creado_en: string; rol: RolEmpresa; logo?: string | null; color_tema?: string | null }
export interface CrearEmpresaPayload { ruc: string; razon_social: string; nombre_comercial?: string; direccion?: string; moneda_base_codigo: string }
export interface Establecimiento { id: number; codigo_sunat: string; nombre: string; activo: boolean; direccion?: string | null; ubigeo?: string | null; es_principal?: boolean }
export type EstablecimientoPayload = Omit<Establecimiento, 'id' | 'es_principal'>;

/** Bloque 17A: resultado de una validación previa a la emisión electrónica (solo lectura). */
export interface ValidacionTributaria { listo: boolean; errores: string[]; advertencias: string[] }
/** Bloque 17A: datos del emisor electrónico de la empresa activa (el RUC no se edita aquí). */
export interface DatosFiscales {
  id: number; ruc: string; razon_social: string; nombre_comercial: string | null; direccion: string | null;
  ubigeo: string | null; departamento: string | null; provincia: string | null; distrito: string | null; codigo_pais: string;
  validacion: ValidacionTributaria;
}
export type DatosFiscalesPayload = Partial<Omit<DatosFiscales, 'id' | 'ruc' | 'validacion'>>;
export interface ConfigEmpresa { id: number; empresa: number; tolerancia_residuo_pen: string; decimales_calculo: number; regla_redondeo: 'ROUND_HALF_UP'; metodo_valuacion: 'CPP'; establecimiento_principal: number | null; tasa_igv_pct?: string; tasas_igv?: { vigente_desde: string; tasa_pct: string }[] }
export interface ActualizarConfigPayload { tolerancia_residuo_pen?: string; decimales_calculo?: number; establecimiento_principal?: number | null; tasa_igv_pct?: string; tasa_igv_vigente_desde?: string }

export const obtenerMonedas = async (): Promise<Moneda[]> => (await apiClient.get<Moneda[]>('/catalogos/monedas/')).data;
export const obtenerEmpresas = async (): Promise<Empresa[]> => (await apiClient.get<Empresa[]>('/empresas/')).data;
export const crearEmpresa = async (payload: CrearEmpresaPayload): Promise<Empresa> => (await apiClient.post<Empresa>('/empresas/', payload)).data;
export const obtenerConfigEmpresa = async (): Promise<ConfigEmpresa> => (await apiClient.get<ConfigEmpresa>('/empresas/config/')).data;
export const actualizarConfigEmpresa = async (payload: ActualizarConfigPayload): Promise<ConfigEmpresa> => (await apiClient.patch<ConfigEmpresa>('/empresas/config/', payload)).data;
export const obtenerDatosFiscales = async (): Promise<DatosFiscales> => (await apiClient.get<DatosFiscales>('/empresas/datos-fiscales/')).data;
export const actualizarDatosFiscales = async (payload: DatosFiscalesPayload): Promise<DatosFiscales> => (await apiClient.patch<DatosFiscales>('/empresas/datos-fiscales/', payload)).data;
export const obtenerEstablecimientos = async (): Promise<Establecimiento[]> => (await apiClient.get<Establecimiento[]>('/empresas/establecimientos/')).data;
export const crearEstablecimiento = async (payload: EstablecimientoPayload): Promise<Establecimiento> => (await apiClient.post<Establecimiento>('/empresas/establecimientos/', payload)).data;

export interface ActualizarIdentidadPayload {
  logo?: File | null;
  color_tema?: string | null;
  quitar_logo?: boolean;
}

export const actualizarIdentidadEmpresaApi = async (
  empresaId: number,
  payload: ActualizarIdentidadPayload | FormData
): Promise<Empresa> => {
  let body: FormData | Record<string, unknown>;
  if (payload instanceof FormData) {
    body = payload;
  } else {
    const formData = new FormData();
    if (payload.logo) {
      formData.append('logo', payload.logo);
    }
    if (payload.quitar_logo) {
      formData.append('quitar_logo', 'true');
    }
    if (payload.color_tema !== undefined) {
      formData.append('color_tema', payload.color_tema ?? '');
    }
    body = formData;
  }
  const response = await apiClient.patch<Empresa>(`/empresas/${empresaId}/`, body, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });
  return response.data;
};
export const actualizarEstablecimiento = async (id: number, payload: Partial<EstablecimientoPayload>): Promise<Establecimiento> => (await apiClient.patch<Establecimiento>(`/empresas/establecimientos/${id}/`, payload)).data;
