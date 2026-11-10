import { apiClient } from './http';

export interface AsignacionUsuarioEmpresa {
  id: number;
  empresa_id: number;
  empresa_ruc: string;
  empresa_razon_social: string;
  rol: 'ADMIN' | 'USUARIO';
  activo: boolean;
}

export interface UsuarioEstudio {
  id: number;
  username: string;
  email: string;
  first_name?: string;
  last_name?: string;
  activo: boolean;
  is_active: boolean;
  es_admin_global: boolean;
  is_staff: boolean;
  last_login?: string | null;
  asignaciones: AsignacionUsuarioEmpresa[];
}

export interface AsignacionEmpresaInput {
  empresa_id: number;
  rol: 'ADMIN' | 'USUARIO';
  activo: boolean;
}

export interface CrearUsuarioPayload {
  username: string;
  email: string;
  password_inicial: string;
  asignaciones?: AsignacionEmpresaInput[];
}

export interface ActualizarUsuarioPayload {
  email?: string;
  is_active?: boolean;
  activo?: boolean;
  asignaciones?: AsignacionEmpresaInput[];
}

export interface ResetPasswordPayload {
  password_nuevo: string;
}

export interface CambiarPasswordPayload {
  password_actual: string;
  password_nuevo: string;
}

/**
 * Obtiene la lista completa de usuarios del estudio con sus asignaciones multiempresa.
 */
export const obtenerUsuariosApi = async (): Promise<UsuarioEstudio[]> => {
  const response = await apiClient.get<UsuarioEstudio[]>('/usuarios/');
  return response.data;
};

/**
 * Crea un nuevo usuario en el sistema con asignaciones iniciales opcionales.
 */
export const crearUsuarioApi = async (payload: CrearUsuarioPayload): Promise<UsuarioEstudio> => {
  const response = await apiClient.post<UsuarioEstudio>('/usuarios/', payload);
  return response.data;
};

/**
 * Actualiza los datos o asignaciones de un usuario existente.
 */
export const actualizarUsuarioApi = async (
  id: number,
  payload: ActualizarUsuarioPayload
): Promise<UsuarioEstudio> => {
  const response = await apiClient.patch<UsuarioEstudio>(`/usuarios/${id}/`, payload);
  return response.data;
};

/**
 * Resetea la contraseña de un usuario (acción administrativa).
 */
export const resetearPasswordApi = async (
  id: number,
  payload: ResetPasswordPayload
): Promise<{ detail: string }> => {
  const response = await apiClient.post<{ detail: string }>(`/usuarios/${id}/reset-password/`, payload);
  return response.data;
};

/**
 * Cambia la contraseña del usuario en sesión actual.
 */
export const cambiarPasswordPropioApi = async (
  payload: CambiarPasswordPayload
): Promise<{ detail: string }> => {
  const response = await apiClient.post<{ detail: string }>('/auth/cambiar-password/', payload);
  return response.data;
};

