/**
 * Bloque 9 — credencial de sesión del frontend, en uno de dos modos:
 *
 * - Token (actual, por defecto): el backend devuelve `token` en el login; se guarda en
 *   localStorage y viaja en `Authorization: Bearer`.
 * - Cookie HttpOnly (AUTH_COOKIE_ENABLED=True en el backend): el login NO devuelve token;
 *   la sesión vive en la cookie `fk_sesion` (HttpOnly, inaccesible para JavaScript). En
 *   localStorage solo queda la marca `sesion_cookie=1` para saber, al recargar, que hay que
 *   validar la sesión con /me. La marca no es una credencial: sin la cookie no sirve.
 *
 * Nunca se guardan ambas cosas a la vez (no hay un segundo token como respaldo).
 */
export const SESION_COOKIE = 'cookie-httponly';
const CLAVE_TOKEN = 'token';
const CLAVE_MODO_COOKIE = 'sesion_cookie';

type Almacen = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

/** Credencial vigente: el token, la marca de cookie o null si no hay sesión. */
export function leerCredencial(almacen: Pick<Storage, 'getItem'>): string | null {
  const token = almacen.getItem(CLAVE_TOKEN);
  if (token) return token;
  return almacen.getItem(CLAVE_MODO_COOKIE) === '1' ? SESION_COOKIE : null;
}

/** Guarda la sesión recién iniciada. Sin token en la respuesta → modo cookie. */
export function guardarCredencial(almacen: Almacen, token: string | null | undefined): string {
  if (token) {
    almacen.removeItem(CLAVE_MODO_COOKIE);
    almacen.setItem(CLAVE_TOKEN, token);
    return token;
  }
  almacen.removeItem(CLAVE_TOKEN);
  almacen.setItem(CLAVE_MODO_COOKIE, '1');
  return SESION_COOKIE;
}

export function borrarCredencial(almacen: Almacen): void {
  almacen.removeItem(CLAVE_TOKEN);
  almacen.removeItem(CLAVE_MODO_COOKIE);
}

export function esSesionCookie(credencial: string | null): boolean {
  return credencial === SESION_COOKIE;
}

/** Valor de `Authorization` para la credencial (en modo cookie no se envía encabezado). */
export function encabezadoAutorizacion(credencial: string | null): string | null {
  if (!credencial || esSesionCookie(credencial)) return null;
  return `Bearer ${credencial}`;
}

/** Métodos que Django protege con CSRF cuando la sesión va en cookie. */
export function requiereCsrf(metodo: string | undefined): boolean {
  return !['GET', 'HEAD', 'OPTIONS', 'TRACE'].includes((metodo || 'GET').toUpperCase());
}

/** Lee una cookie no-HttpOnly (csrftoken) de document.cookie. */
export function leerCookie(cookies: string, nombre: string): string | null {
  for (const parte of cookies.split(';')) {
    const [clave, ...resto] = parte.trim().split('=');
    if (clave === nombre) return decodeURIComponent(resto.join('='));
  }
  return null;
}
