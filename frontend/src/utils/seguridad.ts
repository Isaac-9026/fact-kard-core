/**
 * Seguridad de la sesión — utilidades puras (sin React), probadas con `node --test`.
 *
 * - Confirmar con contraseña: el backend responde 403 con `code: 'confirmacion_password'` en las
 *   acciones críticas (anular comprobante, reabrir período, recalcular Kardex). El cliente HTTP pide
 *   la contraseña y reintenta la misma petición agregando `password_confirmacion`.
 * - Cierre por inactividad: tras 30 minutos sin uso se cierra la sesión.
 * - Rol CONSULTA: solo lectura.
 */

export const CODIGO_CONFIRMACION = 'confirmacion_password';
export const MAX_INTENTOS_CONFIRMACION = 3;
export const MINUTOS_INACTIVIDAD = 30;
export const CLAVE_AVISO_LOGIN = 'aviso_login';
export const AVISO_INACTIVIDAD = `Su sesión se cerró tras ${MINUTOS_INACTIVIDAD} minutos sin actividad. Vuelva a ingresar.`;

export type RolEmpresa = 'ADMIN' | 'USUARIO' | 'CONSULTA';

export const ETIQUETA_ROL: Record<RolEmpresa, string> = {
  ADMIN: 'Administrador',
  USUARIO: 'Operador',
  CONSULTA: 'Solo consulta',
};

export const esSoloConsulta = (rol?: string | null, esAdminGlobal = false): boolean =>
  !esAdminGlobal && rol === 'CONSULTA';

/** ¿La respuesta es el pedido de confirmar la contraseña? */
export const esPedidoDeConfirmacion = (status?: number, datos?: unknown): boolean =>
  status === 403 && typeof datos === 'object' && datos !== null
  && (datos as { code?: unknown }).code === CODIGO_CONFIRMACION;

/** Mensaje del backend (p. ej. "La contraseña de confirmación es incorrecta."). */
export const mensajeDeConfirmacion = (datos?: unknown): string => {
  const detalle = typeof datos === 'object' && datos !== null ? (datos as { detail?: unknown }).detail : null;
  return typeof detalle === 'string' && detalle ? detalle : 'Para esta acción debe confirmar su contraseña.';
};

/** Agrega `password_confirmacion` al cuerpo JSON de la petición original (texto u objeto). */
export const agregarPasswordAlCuerpo = (cuerpo: unknown, password: string): string => {
  let base: Record<string, unknown> = {};
  if (typeof cuerpo === 'string' && cuerpo.trim()) {
    try {
      const leido = JSON.parse(cuerpo);
      if (leido && typeof leido === 'object' && !Array.isArray(leido)) base = leido;
    } catch {
      base = {};
    }
  } else if (cuerpo && typeof cuerpo === 'object' && !Array.isArray(cuerpo)) {
    base = cuerpo as Record<string, unknown>;
  }
  return JSON.stringify({ ...base, password_confirmacion: password });
};

/** ¿Pasó el tiempo de inactividad desde el último uso? */
export const venciaPorInactividad = (
  ultimoUsoMs: number, ahoraMs: number, minutos: number = MINUTOS_INACTIVIDAD,
): boolean => ahoraMs - ultimoUsoMs >= minutos * 60 * 1000;
