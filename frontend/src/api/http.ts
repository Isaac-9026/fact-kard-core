import axios, { type InternalAxiosRequestConfig } from 'axios';
import {
  crearControlCierreSesion,
  debeCerrarSesionPor401,
} from '../utils/sesion';
import {
  encabezadoAutorizacion, esSesionCookie, leerCookie, leerCredencial, requiereCsrf,
} from '../utils/credencialSesion';

const BASE_API = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

// Bloque 9: sesión por cookie HttpOnly. En producción (mismo dominio) el navegador envía la
// cookie solo; `VITE_AUTH_COOKIE=true` hace falta cuando el frontend y la API están en
// orígenes distintos (desarrollo 5173 → 8000) para enviar cookies entre orígenes.
const COOKIES_ENTRE_ORIGENES = import.meta.env.VITE_AUTH_COOKIE === 'true';

export const apiClient = axios.create({
  baseURL: BASE_API,
  withCredentials: COOKIES_ENTRE_ORIGENES,
  headers: {
    'Content-Type': 'application/json',
  },
});

/** Credencial con la que salió cada petición (para decidir si un 401 cierra la sesión vigente). */
type ConfigConSesion = InternalAxiosRequestConfig & { credencialSesion?: string | null };

/** En modo cookie, Django exige el token CSRF (cookie `csrftoken`) en las escrituras. */
export const asegurarCsrf = async (): Promise<string | null> => {
  const actual = leerCookie(document.cookie, 'csrftoken');
  if (actual) return actual;
  const { data } = await axios.get<{ csrfToken: string }>(`${BASE_API}/usuarios/csrf/`, { withCredentials: COOKIES_ENTRE_ORIGENES });
  return leerCookie(document.cookie, 'csrftoken') ?? data.csrfToken;
};

apiClient.interceptors.request.use(
  async (config: InternalAxiosRequestConfig) => {
    const credencial = leerCredencial(localStorage);
    (config as ConfigConSesion).credencialSesion = credencial;
    const autorizacion = encabezadoAutorizacion(credencial);
    if (autorizacion && !config.headers.has('Authorization')) {
      config.headers.set('Authorization', autorizacion);
    }
    if (esSesionCookie(credencial) && requiereCsrf(config.method)) {
      const csrf = await asegurarCsrf();
      if (csrf) config.headers.set('X-CSRFToken', csrf);
    }

    const empresaId = sessionStorage.getItem('empresa_id') || localStorage.getItem('empresa_id');
    if (empresaId) {
      config.headers.set('X-Empresa-Id', empresaId);
    }

    return config;
  },
  (error) => Promise.reject(error)
);

// FE-002: un 401 con el token vigente invalida la sesión una sola vez.
const controlCierreSesion = crearControlCierreSesion();
let manejadorSesionInvalida: (() => void) | null = null;

export const registrarManejadorSesionInvalida = (manejador: () => void) => {
  manejadorSesionInvalida = manejador;
  return () => {
    if (manejadorSesionInvalida === manejador) {
      manejadorSesionInvalida = null;
    }
  };
};

/** Se llama tras un login exitoso para volver a escuchar 401 de la nueva sesión. */
export const reiniciarControlSesion = () => controlCierreSesion.reiniciar();

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const config = error?.config as ConfigConSesion | undefined;
    const cerrar = debeCerrarSesionPor401({
      status: error?.response?.status,
      url: config?.url,
      tokenEnviado: config?.credencialSesion ?? null,
      tokenActual: leerCredencial(localStorage),
    });
    if (cerrar && manejadorSesionInvalida) {
      controlCierreSesion.intentar(manejadorSesionInvalida);
    }
    return Promise.reject(error);
  }
);

export default apiClient;
