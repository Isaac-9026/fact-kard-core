import type { UsuarioEstudio, AsignacionEmpresaInput } from '../api/usuarios';

export interface FormUsuarioInput {
  username: string;
  email: string;
  passwordInicial?: string;
  activo?: boolean;
  esEdicion: boolean;
  usuarioSesionId?: number;
  editandoUsuarioId?: number;
}

export interface ValidacionResultado {
  valido: boolean;
  error?: string;
}

export interface CambioClaveInput {
  claveActual: string;
  claveNueva: string;
  claveConfirmar: string;
}

/**
 * Valida reglas de negocio del formulario de creación y edición de usuarios.
 */
export const validarFormularioUsuario = (input: FormUsuarioInput): ValidacionResultado => {
  if (!input.esEdicion && (!input.username || !input.username.trim())) {
    return { valido: false, error: 'El nombre de usuario es obligatorio.' };
  }

  if (!input.email || !input.email.trim() || !input.email.includes('@')) {
    return { valido: false, error: 'Ingrese un correo electrónico válido.' };
  }

  if (!input.esEdicion && (!input.passwordInicial || input.passwordInicial.length < 8)) {
    return { valido: false, error: 'La contraseña inicial debe tener al menos 8 caracteres.' };
  }

  // Candado de seguridad: Prohibido desactivar la propia cuenta en sesión
  if (
    input.esEdicion &&
    input.usuarioSesionId !== undefined &&
    input.editandoUsuarioId !== undefined &&
    input.usuarioSesionId === input.editandoUsuarioId &&
    input.activo === false
  ) {
    return { valido: false, error: 'No puedes desactivar tu propia cuenta en sesión.' };
  }

  return { valido: true };
};

/**
 * Valida los campos del modal de cambio de contraseña propio.
 */
export const validarCambioClave = (input: CambioClaveInput): ValidacionResultado => {
  if (!input.claveActual) {
    return { valido: false, error: 'Debe ingresar la contraseña actual.' };
  }

  if (!input.claveNueva || input.claveNueva.length < 8) {
    return { valido: false, error: 'La nueva contraseña debe tener al menos 8 caracteres.' };
  }

  if (input.claveNueva !== input.claveConfirmar) {
    return { valido: false, error: 'Las nuevas contraseñas no coinciden.' };
  }

  if (input.claveNueva === input.claveActual) {
    return { valido: false, error: 'La nueva contraseña debe ser diferente de la actual.' };
  }

  return { valido: true };
};

/**
 * Valida el reseteo administrativo de contraseña.
 */
export const validarReseteoClave = (passwordNuevo: string): ValidacionResultado => {
  if (!passwordNuevo || passwordNuevo.length < 8) {
    return { valido: false, error: 'La nueva contraseña debe tener al menos 8 caracteres.' };
  }
  return { valido: true };
};

/**
 * Filtra la lista de usuarios por texto y estado.
 */
export const filtrarUsuarios = (
  usuarios: UsuarioEstudio[],
  busqueda: string,
  filtroEstado: 'TODOS' | 'ACTIVOS' | 'INACTIVOS'
): UsuarioEstudio[] => {
  const q = busqueda.trim().toLowerCase();

  return usuarios.filter((u) => {
    if (filtroEstado === 'ACTIVOS' && !u.activo) return false;
    if (filtroEstado === 'INACTIVOS' && u.activo) return false;

    if (!q) return true;

    const matchUsername = u.username.toLowerCase().includes(q);
    const matchEmail = u.email.toLowerCase().includes(q);
    const matchEmpresa = u.asignaciones.some(
      (a) =>
        a.empresa_razon_social.toLowerCase().includes(q) ||
        a.empresa_ruc.includes(q)
    );

    return matchUsername || matchEmail || matchEmpresa;
  });
};

/**
 * Construye el array de asignaciones a enviar al backend a partir de la matriz de la interfaz.
 */
export const construirPayloadAsignaciones = (
  matriz: Record<number, { asignado: boolean; rol: 'ADMIN' | 'USUARIO' }>
): AsignacionEmpresaInput[] => {
  return Object.entries(matriz).map(([empIdStr, val]) => ({
    empresa_id: Number(empIdStr),
    rol: val.rol,
    activo: val.asignado,
  }));
};

