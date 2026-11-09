import { apiClient } from './http';
import { leerPaginado, type Paginado, type ParamsPaginacion } from '../utils/paginacion';

export interface AuditoriaItem {
  id: number;
  empresa_id: number | null;
  empresa_razon_social?: string | null;
  usuario_id: number | null;
  usuario_username?: string | null;
  accion: string;
  entidad: string;
  registro_id: number | null;
  valor_anterior: Record<string, unknown> | null;
  valor_nuevo: Record<string, unknown> | null;
  motivo: string | null;
  fecha: string;
}

export interface AuditoriaFiltros {
  entidad?: string;
  accion?: string;
}

/**
 * Consulta el registro de auditoría de la empresa activa (vía header X-Empresa-Id).
 * Permite filtrar por tipo de acción y nombre de entidad.
 */
const paramsAuditoria = (filtros?: AuditoriaFiltros): Record<string, string> => {
  const params: Record<string, string> = {};
  if (filtros?.entidad && filtros.entidad.trim() !== '') {
    params.entidad = filtros.entidad.trim();
  }
  if (filtros?.accion && filtros.accion.trim() !== '') {
    params.accion = filtros.accion.trim();
  }

  return params;
};

export const getAuditoriaApi = async (filtros?: AuditoriaFiltros): Promise<AuditoriaItem[]> => {
  const response = await apiClient.get<AuditoriaItem[]>('/auditoria/', { params: paramsAuditoria(filtros) });
  return response.data;
};

/** Bloque 7 — una página del registro de auditoría (`?page=&page_size=`). */
export const getAuditoriaPaginadaApi = async (
  filtros: AuditoriaFiltros | undefined,
  paginacion: ParamsPaginacion,
): Promise<Paginado<AuditoriaItem>> => {
  const response = await apiClient.get<Paginado<AuditoriaItem> | AuditoriaItem[]>('/auditoria/', {
    params: { ...paramsAuditoria(filtros), ...paginacion },
  });
  return leerPaginado(response.data);
};
