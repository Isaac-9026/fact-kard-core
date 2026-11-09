/**
 * FE-002: lógica pura de sesión y protección de rutas. El backend sigue siendo
 * la autoridad real; esto solo evita renderizar módulos privados sin sesión.
 */

export type AccesoRuta = 'verificando' | 'permitido' | 'redirigir_login';

export const resolverAccesoRuta = ({
  token,
  verificandoSesion,
}: {
  token: string | null;
  verificandoSesion: boolean;
}): AccesoRuta => {
  if (!token) return 'redirigir_login';
  if (verificandoSesion) return 'verificando';
  return 'permitido';
};

const RUTA_LOGIN_API = '/usuarios/login/';

export const esSolicitudDeLogin = (url?: string | null): boolean => {
  if (!url) return false;
  const sinQuery = url.split('?')[0];
  const normalizada = sinQuery.endsWith('/') ? sinQuery : `${sinQuery}/`;
  return normalizada.endsWith(RUTA_LOGIN_API);
};

export const tokenDesdeAuthorization = (valor: unknown): string | null => {
  if (typeof valor !== 'string') return null;
  const [esquema, token] = valor.trim().split(/\s+/);
  if (!token || !['bearer', 'token'].includes(esquema.toLowerCase())) return null;
  return token;
};

/**
 * Solo un 401 de una petición autenticada con el token VIGENTE invalida la sesión.
 * - El login con credenciales erradas también responde 401 y no debe cerrar nada.
 * - Una respuesta tardía de un token anterior no debe cerrar la sesión nueva.
 */
export const debeCerrarSesionPor401 = ({
  status,
  url,
  tokenEnviado,
  tokenActual,
}: {
  status?: number;
  url?: string | null;
  tokenEnviado: string | null;
  tokenActual: string | null;
}): boolean => (
  status === 401
  && !esSolicitudDeLogin(url)
  && Boolean(tokenEnviado)
  && tokenEnviado === tokenActual
);

/** Ejecuta el cierre de sesión una sola vez hasta que se reinicie (nuevo login). */
export const crearControlCierreSesion = () => {
  let enCurso = false;
  return {
    intentar(accion: () => void): boolean {
      if (enCurso) return false;
      enCurso = true;
      accion();
      return true;
    },
    reiniciar() {
      enCurso = false;
    },
    get enCurso() {
      return enCurso;
    },
  };
};
