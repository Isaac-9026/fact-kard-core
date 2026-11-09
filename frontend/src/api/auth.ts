import { apiClient, asegurarCsrf } from './http';
import type { Usuario, EmpresaAsociada } from '../types/auth';
import { encabezadoAutorizacion, esSesionCookie } from '../utils/credencialSesion';

export interface LoginCredentials {
  username: string;
  password: string;
}

export interface LoginResponse {
  /** Ausente cuando el backend usa la cookie HttpOnly (AUTH_COOKIE_ENABLED=True). */
  token?: string;
  usuario: Usuario;
  empresas: EmpresaAsociada[];
}

export interface MeResponse {
  usuario: Usuario;
  empresas: EmpresaAsociada[];
}

export interface UsuarioEmpresaItem {
  id: number;
  usuario_id: number;
  username: string;
  email: string;
  empresa_id: number;
  empresa_razon_social: string;
  rol: 'ADMIN' | 'USUARIO';
  activo: boolean;
}

export interface AsignarUsuarioPayload {
  usuario_id: number;
  rol: 'ADMIN' | 'USUARIO';
  activo?: boolean;
}

/**
 * Autentica usuario en FACT-KARD y devuelve token + empresas asignadas.
 */
export const loginApi = async (credentials: LoginCredentials): Promise<LoginResponse> => {
  const response = await apiClient.post<LoginResponse>('/usuarios/login/', credentials);
  return response.data;
};

/**
 * Obtiene el perfil del usuario autenticado y sus empresas activas.
 */
export const getMeApi = async (): Promise<MeResponse> => {
  const response = await apiClient.get<MeResponse>('/usuarios/me/');
  return response.data;
};

/**
 * Obtiene la lista de usuarios y roles asignados a la empresa activa (X-Empresa-Id).
 */
export const getAsignacionesApi = async (): Promise<UsuarioEmpresaItem[]> => {
  const response = await apiClient.get<UsuarioEmpresaItem[]>('/usuarios/asignaciones/');
  return response.data;
};

/**
 * Asigna o modifica el rol de un usuario en la empresa activa (X-Empresa-Id).
 */
export const asignarUsuarioApi = async (payload: AsignarUsuarioPayload): Promise<UsuarioEmpresaItem> => {
  const response = await apiClient.post<UsuarioEmpresaItem>('/usuarios/asignaciones/', payload);
  return response.data;
};

/**
 * Bloque 6: revoca el token en el servidor (logout efectivo). Es "best effort": si falla
 * (sin red o token ya inválido) la sesión local se limpia igual.
 */
export const logoutApi = async (credencial: string): Promise<void> => {
  try {
    // Los encabezados se fijan aquí porque la sesión local se limpia enseguida (el interceptor
    // ya no la vería). Modo token: Authorization. Modo cookie: la cookie HttpOnly + CSRF.
    const autorizacion = encabezadoAutorizacion(credencial);
    const headers: Record<string, string> = autorizacion ? { Authorization: autorizacion } : {};
    if (esSesionCookie(credencial)) {
      const csrf = await asegurarCsrf();
      if (csrf) headers['X-CSRFToken'] = csrf;
    }
    await apiClient.post('/usuarios/logout/', {}, { headers });
  } catch {
    // sin acción: el token igual se elimina del navegador
  }
};
