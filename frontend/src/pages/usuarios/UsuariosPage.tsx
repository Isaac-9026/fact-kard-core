import React, { useState, useEffect, useMemo } from 'react';
import {
  Users,
  UserPlus,
  Search,
  KeyRound,
  Pencil,
  ShieldAlert,
  CheckCircle2,
  AlertCircle,
  Building2,
  Lock,
  UserCheck,
  UserX,
  RefreshCw,
} from 'lucide-react';
import {
  obtenerUsuariosApi,
  crearUsuarioApi,
  actualizarUsuarioApi,
  resetearPasswordApi,
  type UsuarioEstudio,
  type AsignacionEmpresaInput,
} from '../../api/usuarios';
import { obtenerEmpresas, type Empresa } from '../../api/empresas';
import { useAuth } from '../../context/useAuth';
import { Badge } from '../../components/ui/badge';
import { Modal } from '../../components/ui/modal';

export const UsuariosPage: React.FC = () => {
  const { usuario: usuarioSesion } = useAuth();

  const [usuarios, setUsuarios] = useState<UsuarioEstudio[]>([]);
  const [empresas, setEmpresas] = useState<Empresa[]>([]);
  const [cargando, setCargando] = useState<boolean>(true);
  const [errorGlobal, setErrorGlobal] = useState<string | null>(null);
  const [mensajeExito, setMensajeExito] = useState<string | null>(null);

  // Filtros
  const [busqueda, setBusqueda] = useState<string>('');
  const [filtroEstado, setFiltroEstado] = useState<'TODOS' | 'ACTIVOS' | 'INACTIVOS'>('TODOS');

  // Modales
  const [modalUsuarioAbierto, setModalUsuarioAbierto] = useState<boolean>(false);
  const [usuarioEditando, setUsuarioEditando] = useState<UsuarioEstudio | null>(null);

  const [modalResetAbierto, setModalResetAbierto] = useState<boolean>(false);
  const [usuarioParaReset, setUsuarioParaReset] = useState<UsuarioEstudio | null>(null);
  const [nuevoPasswordReset, setNuevoPasswordReset] = useState<string>('');
  const [resetError, setResetError] = useState<string | null>(null);
  const [resetGuardando, setResetGuardando] = useState<boolean>(false);

  // Formulario Usuario (Crear / Editar)
  const [formUsername, setFormUsername] = useState<string>('');
  const [formEmail, setFormEmail] = useState<string>('');
  const [formPasswordInicial, setFormPasswordInicial] = useState<string>('');
  const [formActivo, setFormActivo] = useState<boolean>(true);
  // Matriz de asignaciones: Record<empresa_id, { activo: boolean; rol: 'ADMIN' | 'USUARIO' }>
  const [matrizAsignaciones, setMatrizAsignaciones] = useState<
    Record<number, { asignado: boolean; rol: 'ADMIN' | 'USUARIO' }>
  >({});
  const [formError, setFormError] = useState<string | null>(null);
  const [formGuardando, setFormGuardando] = useState<boolean>(false);

  const cargarDatos = async () => {
    try {
      setCargando(true);
      setErrorGlobal(null);
      const [dataUsuarios, dataEmpresas] = await Promise.all([
        obtenerUsuariosApi(),
        obtenerEmpresas().catch(() => []),
      ]);
      setUsuarios(dataUsuarios);
      setEmpresas(dataEmpresas);
    } catch (err: unknown) {
      const errorMsg =
        err && typeof err === 'object' && 'response' in err
          ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
          : null;
      setErrorGlobal(errorMsg || 'No se pudieron cargar los datos de usuarios.');
    } finally {
      setCargando(false);
    }
  };

  useEffect(() => {
    cargarDatos();
  }, []);

  const usuariosFiltrados = useMemo(() => {
    return usuarios.filter((u) => {
      // Filtro de estado
      if (filtroEstado === 'ACTIVOS' && !u.activo) return false;
      if (filtroEstado === 'INACTIVOS' && u.activo) return false;

      // Filtro de texto
      if (!busqueda.trim()) return true;
      const q = busqueda.toLowerCase().trim();
      const matchUsername = u.username.toLowerCase().includes(q);
      const matchEmail = u.email.toLowerCase().includes(q);
      const matchEmpresa = u.asignaciones.some(
        (a) =>
          a.empresa_razon_social.toLowerCase().includes(q) ||
          a.empresa_ruc.includes(q)
      );
      return matchUsername || matchEmail || matchEmpresa;
    });
  }, [usuarios, filtroEstado, busqueda]);

  const abrirModalCrear = () => {
    setUsuarioEditando(null);
    setFormUsername('');
    setFormEmail('');
    setFormPasswordInicial('');
    setFormActivo(true);
    setFormError(null);

    // Inicializar matriz de empresas desmarcadas
    const inicial: Record<number, { asignado: boolean; rol: 'ADMIN' | 'USUARIO' }> = {};
    empresas.forEach((emp) => {
      inicial[emp.id] = { asignado: false, rol: 'USUARIO' };
    });
    setMatrizAsignaciones(inicial);
    setModalUsuarioAbierto(true);
  };

  const abrirModalEditar = (u: UsuarioEstudio) => {
    setUsuarioEditando(u);
    setFormUsername(u.username);
    setFormEmail(u.email);
    setFormPasswordInicial('');
    setFormActivo(u.activo);
    setFormError(null);

    // Mapear asignaciones existentes
    const inicial: Record<number, { asignado: boolean; rol: 'ADMIN' | 'USUARIO' }> = {};
    empresas.forEach((emp) => {
      const asig = u.asignaciones.find((a) => a.empresa_id === emp.id);
      if (asig && asig.activo) {
        inicial[emp.id] = { asignado: true, rol: asig.rol };
      } else {
        inicial[emp.id] = { asignado: false, rol: asig ? asig.rol : 'USUARIO' };
      }
    });
    setMatrizAsignaciones(inicial);
    setModalUsuarioAbierto(true);
  };

  const guardarUsuario = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);

    if (!usuarioEditando && !formUsername.trim()) {
      setFormError('El nombre de usuario es obligatorio.');
      return;
    }
    if (!formEmail.trim() || !formEmail.includes('@')) {
      setFormError('Ingrese un correo electrónico válido.');
      return;
    }
    if (!usuarioEditando && formPasswordInicial.length < 8) {
      setFormError('La contraseña inicial debe tener al menos 8 caracteres.');
      return;
    }

    // Candado en sesión propia
    if (usuarioEditando && usuarioEditando.id === usuarioSesion?.id && !formActivo) {
      setFormError('No puedes desactivar tu propia cuenta en sesión.');
      return;
    }

    // Construir lista de asignaciones para enviar
    const asignacionesPayload: AsignacionEmpresaInput[] = Object.entries(matrizAsignaciones).map(
      ([empIdStr, val]) => ({
        empresa_id: Number(empIdStr),
        rol: val.rol,
        activo: val.asignado,
      })
    );

    try {
      setFormGuardando(true);
      if (usuarioEditando) {
        await actualizarUsuarioApi(usuarioEditando.id, {
          email: formEmail.trim(),
          activo: formActivo,
          asignaciones: asignacionesPayload,
        });
        setMensajeExito(`Usuario '${usuarioEditando.username}' actualizado exitosamente.`);
      } else {
        await crearUsuarioApi({
          username: formUsername.trim(),
          email: formEmail.trim(),
          password_inicial: formPasswordInicial,
          asignaciones: asignacionesPayload.filter((a) => a.activo),
        });
        setMensajeExito(`Usuario '${formUsername.trim()}' creado exitosamente.`);
      }
      setModalUsuarioAbierto(false);
      await cargarDatos();
      setTimeout(() => setMensajeExito(null), 4000);
    } catch (err: unknown) {
      const respData = (err as { response?: { data?: Record<string, unknown> } })?.response?.data;
      if (respData) {
        if (typeof respData.detail === 'string') {
          setFormError(respData.detail);
        } else if (respData.username) {
          setFormError(`Usuario: ${respData.username}`);
        } else if (respData.email) {
          setFormError(`Correo: ${respData.email}`);
        } else if (respData.password_inicial) {
          setFormError(`Contraseña: ${respData.password_inicial}`);
        } else {
          setFormError('Error al guardar la información del usuario.');
        }
      } else {
        setFormError('Error de red o comunicación con el servidor.');
      }
    } finally {
      setFormGuardando(false);
    }
  };

  const toggleEstadoUsuario = async (u: UsuarioEstudio) => {
    if (u.id === usuarioSesion?.id) {
      return;
    }
    const nuevoEstado = !u.activo;
    try {
      await actualizarUsuarioApi(u.id, { activo: nuevoEstado });
      setMensajeExito(`Usuario '${u.username}' ${nuevoEstado ? 'activado' : 'desactivado'}.`);
      await cargarDatos();
      setTimeout(() => setMensajeExito(null), 3000);
    } catch (err: unknown) {
      const errorMsg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'Error al cambiar el estado del usuario.';
      setErrorGlobal(errorMsg);
      setTimeout(() => setErrorGlobal(null), 4000);
    }
  };

  const abrirModalReset = (u: UsuarioEstudio) => {
    setUsuarioParaReset(u);
    setNuevoPasswordReset('');
    setResetError(null);
    setModalResetAbierto(true);
  };

  const ejecutarResetPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!usuarioParaReset) return;
    if (nuevoPasswordReset.length < 8) {
      setResetError('La nueva contraseña debe tener al menos 8 caracteres.');
      return;
    }

    try {
      setResetGuardando(true);
      setResetError(null);
      await resetearPasswordApi(usuarioParaReset.id, {
        password_nuevo: nuevoPasswordReset,
      });
      setMensajeExito(`Contraseña de '${usuarioParaReset.username}' actualizada exitosamente.`);
      setModalResetAbierto(false);
      setTimeout(() => setMensajeExito(null), 4000);
    } catch (err: unknown) {
      const errorMsg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        'No se pudo resetear la contraseña.';
      setResetError(errorMsg);
    } finally {
      setResetGuardando(false);
    }
  };

  const esAdminGlobal = Boolean(usuarioSesion?.es_admin_global);

  if (!esAdminGlobal) {
    return (
      <div className="flex flex-col items-center justify-center p-12 text-center bg-white rounded-xl border border-slate-200 shadow-2xs">
        <div className="p-3 bg-amber-50 text-amber-700 rounded-full mb-3">
          <ShieldAlert className="h-6 w-6" strokeWidth={1.75} />
        </div>
        <h2 className="text-base font-bold text-slate-800">Acceso Restringido a Administradores Globales</h2>
        <p className="text-xs text-slate-500 max-w-md mt-1">
          La administración de usuarios y la asignación multiempresa están reservadas exclusivamente para los administradores globales del estudio contable.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* 1. CABECERA */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-slate-200 pb-5">
        <div>
          <div className="flex items-center gap-2.5">
            <div className="p-2 bg-indigo-50 text-indigo-700 rounded-lg">
              <Users className="h-5 w-5" strokeWidth={1.75} />
            </div>
            <div>
              <h1 className="text-xl font-bold tracking-tight text-slate-900">
                Gestión de Usuarios y Accesos
              </h1>
              <p className="text-xs text-slate-500 mt-0.5">
                Administración centralizada de usuarios del estudio y asignación de roles multiempresa.
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={cargarDatos}
            disabled={cargando}
            className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-medium text-slate-700 bg-white border border-slate-300 rounded-lg hover:bg-slate-50 transition-colors shadow-2xs"
            title="Refrescar lista"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${cargando ? 'animate-spin' : ''}`} />
            <span>Refrescar</span>
          </button>
          <button
            type="button"
            onClick={abrirModalCrear}
            className="inline-flex items-center gap-1.5 px-3.5 py-2 text-xs font-semibold text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 active:scale-[0.98] transition-all shadow-sm"
          >
            <UserPlus className="h-4 w-4" />
            <span>Nuevo Usuario</span>
          </button>
        </div>
      </div>

      {/* MENSAJES FEEDBACK */}
      {mensajeExito && (
        <div className="flex items-center gap-2 p-3 bg-emerald-50 border border-emerald-200 text-emerald-800 rounded-lg text-xs font-medium">
          <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" />
          <span>{mensajeExito}</span>
        </div>
      )}
      {errorGlobal && (
        <div className="flex items-center gap-2 p-3 bg-rose-50 border border-rose-200 text-rose-800 rounded-lg text-xs font-medium">
          <AlertCircle className="h-4 w-4 shrink-0 text-rose-600" />
          <span>{errorGlobal}</span>
        </div>
      )}

      {/* 2. BARRA DE HERRAMIENTAS Y FILTROS */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 bg-white p-3 rounded-xl border border-slate-200 shadow-2xs">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
          <input
            type="text"
            placeholder="Buscar por usuario, correo o RUC de empresa..."
            value={busqueda}
            onChange={(e) => setBusqueda(e.target.value)}
            className="w-full pl-9 pr-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500"
          />
        </div>

        <div className="flex items-center gap-1.5 bg-slate-100 p-1 rounded-lg">
          {(['TODOS', 'ACTIVOS', 'INACTIVOS'] as const).map((estado) => (
            <button
              key={estado}
              type="button"
              onClick={() => setFiltroEstado(estado)}
              className={`px-3 py-1 text-xs font-semibold rounded-md transition-all ${
                filtroEstado === estado
                  ? 'bg-white text-slate-900 shadow-2xs'
                  : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              {estado === 'TODOS' ? 'Todos' : estado === 'ACTIVOS' ? 'Activos' : 'Inactivos'}
            </button>
          ))}
        </div>
      </div>

      {/* 3. TABLA DE USUARIOS */}
      <div className="bg-white border border-slate-200 rounded-xl shadow-2xs overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50/75 text-[11px] font-semibold text-slate-600 uppercase tracking-wider">
                <th className="py-3 px-4">Usuario / Identidad</th>
                <th className="py-3 px-4">Estado</th>
                <th className="py-3 px-4">Empresas Asignadas</th>
                <th className="py-3 px-4 text-right">Acciones</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-xs text-slate-700">
              {cargando ? (
                <tr>
                  <td colSpan={4} className="py-12 text-center text-slate-500">
                    <RefreshCw className="h-5 w-5 animate-spin mx-auto text-indigo-500 mb-2" />
                    Cargando usuarios del estudio...
                  </td>
                </tr>
              ) : usuariosFiltrados.length === 0 ? (
                <tr>
                  <td colSpan={4} className="py-12 text-center text-slate-500">
                    <Users className="h-8 w-8 mx-auto text-slate-300 mb-2" />
                    No se encontraron usuarios con los filtros aplicados.
                  </td>
                </tr>
              ) : (
                usuariosFiltrados.map((u) => {
                  const esPropio = u.id === usuarioSesion?.id;
                  return (
                    <tr key={u.id} className="hover:bg-slate-50/70 transition-colors">
                      {/* Usuario / Email */}
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-3">
                          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-100 text-slate-700 font-bold text-xs border border-slate-200">
                            {u.username.charAt(0).toUpperCase()}
                          </div>
                          <div>
                            <div className="font-semibold text-slate-900 flex items-center gap-1.5">
                              <span>{u.username}</span>
                              {esPropio && (
                                <span className="inline-flex items-center px-1.5 py-0.2 rounded text-[10px] font-medium bg-indigo-50 text-indigo-700 border border-indigo-200">
                                  Tú
                                </span>
                              )}
                              {u.es_admin_global && (
                                <span className="inline-flex items-center px-1.5 py-0.2 rounded text-[10px] font-medium bg-amber-50 text-amber-700 border border-amber-200">
                                  Admin Global
                                </span>
                              )}
                            </div>
                            <div className="text-[11px] text-slate-500">{u.email}</div>
                          </div>
                        </div>
                      </td>

                      {/* Estado */}
                      <td className="py-3 px-4">
                        <Badge variant={u.activo ? 'success' : 'neutral'} dot>
                          {u.activo ? 'Activo' : 'Inactivo'}
                        </Badge>
                      </td>

                      {/* Empresas Asignadas */}
                      <td className="py-3 px-4 max-w-md">
                        {u.asignaciones && u.asignaciones.length > 0 ? (
                          <div className="flex flex-wrap gap-1.5">
                            {u.asignaciones.map((asig) => (
                              <span
                                key={asig.id || asig.empresa_id}
                                className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] border ${
                                  asig.activo
                                    ? asig.rol === 'ADMIN'
                                      ? 'bg-amber-50/60 border-amber-200/80 text-amber-900'
                                      : 'bg-slate-50 border-slate-200 text-slate-700'
                                    : 'bg-slate-100 border-slate-200 text-slate-400 line-through'
                                }`}
                                title={`${asig.empresa_razon_social} (RUC: ${asig.empresa_ruc}) - Rol: ${asig.rol}`}
                              >
                                <span className="font-medium truncate max-w-[140px]">
                                  {asig.empresa_razon_social}
                                </span>
                                <span className="font-mono text-[10px] text-slate-500">
                                  {asig.empresa_ruc}
                                </span>
                                <span
                                  className={`text-[9px] font-semibold px-1 rounded ${
                                    asig.rol === 'ADMIN'
                                      ? 'bg-amber-200 text-amber-900'
                                      : 'bg-slate-200 text-slate-700'
                                  }`}
                                >
                                  {asig.rol}
                                </span>
                              </span>
                            ))}
                          </div>
                        ) : (
                          <span className="text-slate-400 text-xs italic">
                            Sin empresas asignadas
                          </span>
                        )}
                      </td>

                      {/* Acciones */}
                      <td className="py-3 px-4 text-right">
                        <div className="inline-flex items-center gap-1">
                          <button
                            type="button"
                            onClick={() => abrirModalEditar(u)}
                            className="p-1.5 text-slate-500 hover:text-indigo-600 hover:bg-indigo-50 rounded-lg transition-colors"
                            title="Editar usuario y asignaciones de empresa"
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </button>
                          <button
                            type="button"
                            onClick={() => abrirModalReset(u)}
                            className="p-1.5 text-slate-500 hover:text-amber-600 hover:bg-amber-50 rounded-lg transition-colors"
                            title="Resetear contraseña temporal"
                          >
                            <KeyRound className="h-3.5 w-3.5" />
                          </button>
                          <button
                            type="button"
                            disabled={esPropio}
                            onClick={() => toggleEstadoUsuario(u)}
                            className={`p-1.5 rounded-lg transition-colors ${
                              esPropio
                                ? 'text-slate-300 cursor-not-allowed'
                                : u.activo
                                ? 'text-slate-500 hover:text-rose-600 hover:bg-rose-50'
                                : 'text-slate-500 hover:text-emerald-600 hover:bg-emerald-50'
                            }`}
                            title={
                              esPropio
                                ? 'No puedes desactivar tu propia cuenta en sesión'
                                : u.activo
                                ? 'Desactivar usuario'
                                : 'Activar usuario'
                            }
                          >
                            {u.activo ? (
                              <UserX className="h-3.5 w-3.5" />
                            ) : (
                              <UserCheck className="h-3.5 w-3.5" />
                            )}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* 4. MODAL CREAR / EDITAR USUARIO + MATRIZ DE ASIGNACIONES */}
      <Modal
        isOpen={modalUsuarioAbierto}
        onClose={() => !formGuardando && setModalUsuarioAbierto(false)}
        title={usuarioEditando ? `Editar Usuario: ${usuarioEditando.username}` : 'Nuevo Usuario del Estudio'}
        description="Configure los datos de acceso y asigne las empresas con sus roles correspondientes."
        maxWidth="2xl"
      >
        <form onSubmit={guardarUsuario} className="space-y-5">
          {formError && (
            <div className="p-3 bg-rose-50 border border-rose-200 text-rose-800 rounded-lg text-xs font-medium flex items-center gap-2">
              <AlertCircle className="h-4 w-4 shrink-0 text-rose-600" />
              <span>{formError}</span>
            </div>
          )}

          {/* DATOS BÁSICOS */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 bg-slate-50/70 p-3.5 rounded-xl border border-slate-200">
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                Nombre de usuario <span className="text-rose-500">*</span>
              </label>
              <input
                type="text"
                required
                disabled={!!usuarioEditando}
                value={formUsername}
                onChange={(e) => setFormUsername(e.target.value)}
                placeholder="ej. jperezo"
                className="w-full px-3 py-1.5 text-xs bg-white border border-slate-300 rounded-lg focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 disabled:bg-slate-100 disabled:text-slate-500"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">
                Correo electrónico <span className="text-rose-500">*</span>
              </label>
              <input
                type="email"
                required
                value={formEmail}
                onChange={(e) => setFormEmail(e.target.value)}
                placeholder="jperez@estudio.pe"
                className="w-full px-3 py-1.5 text-xs bg-white border border-slate-300 rounded-lg focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500"
              />
            </div>

            {!usuarioEditando && (
              <div className="sm:col-span-2">
                <label className="block text-xs font-semibold text-slate-700 mb-1">
                  Contraseña inicial <span className="text-rose-500">* (mínimo 8 caracteres)</span>
                </label>
                <input
                  type="password"
                  required
                  value={formPasswordInicial}
                  onChange={(e) => setFormPasswordInicial(e.target.value)}
                  placeholder="••••••••"
                  className="w-full px-3 py-1.5 text-xs bg-white border border-slate-300 rounded-lg focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500"
                />
              </div>
            )}

            {usuarioEditando && (
              <div className="sm:col-span-2 flex items-center gap-2 pt-1">
                <input
                  type="checkbox"
                  id="usuario-activo"
                  checked={formActivo}
                  disabled={usuarioEditando.id === usuarioSesion?.id}
                  onChange={(e) => setFormActivo(e.target.checked)}
                  className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
                />
                <label
                  htmlFor="usuario-activo"
                  className={`text-xs font-medium cursor-pointer ${
                    usuarioEditando.id === usuarioSesion?.id ? 'text-slate-400' : 'text-slate-700'
                  }`}
                >
                  Cuenta activa para acceder al sistema
                  {usuarioEditando.id === usuarioSesion?.id && ' (no puedes desactivarte a ti mismo)'}
                </label>
              </div>
            )}
          </div>

          {/* MATRIZ MULTIEMPRESA */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label className="text-xs font-bold text-slate-800 flex items-center gap-1.5">
                <Building2 className="h-4 w-4 text-indigo-600" />
                <span>Asignación de Empresas y Roles en el Estudio</span>
              </label>
              <span className="text-[11px] text-slate-500">
                Seleccione las empresas a las que tendrá acceso
              </span>
            </div>

            <div className="border border-slate-200 rounded-xl overflow-hidden max-h-60 overflow-y-auto">
              <table className="w-full text-left border-collapse">
                <thead className="bg-slate-50 text-[11px] font-semibold text-slate-600 sticky top-0 border-b border-slate-200">
                  <tr>
                    <th className="py-2 px-3 w-10 text-center">Acceso</th>
                    <th className="py-2 px-3">Empresa</th>
                    <th className="py-2 px-3 w-36">Rol asignado</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 text-xs">
                  {empresas.length === 0 ? (
                    <tr>
                      <td colSpan={3} className="py-4 text-center text-slate-400">
                        No hay empresas registradas en el estudio.
                      </td>
                    </tr>
                  ) : (
                    empresas.map((emp) => {
                      const asig = matrizAsignaciones[emp.id] || {
                        asignado: false,
                        rol: 'USUARIO',
                      };
                      return (
                        <tr
                          key={emp.id}
                          className={`transition-colors ${
                            asig.asignado ? 'bg-indigo-50/30' : 'hover:bg-slate-50'
                          }`}
                        >
                          <td className="py-2 px-3 text-center">
                            <input
                              type="checkbox"
                              checked={asig.asignado}
                              onChange={(e) =>
                                setMatrizAsignaciones({
                                  ...matrizAsignaciones,
                                  [emp.id]: { ...asig, asignado: e.target.checked },
                                })
                              }
                              className="h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
                            />
                          </td>
                          <td className="py-2 px-3">
                            <div className="font-medium text-slate-900">{emp.razon_social}</div>
                            <div className="text-[10px] font-mono text-slate-500">
                              RUC: {emp.ruc}
                            </div>
                          </td>
                          <td className="py-2 px-3">
                            <select
                              value={asig.rol}
                              disabled={!asig.asignado}
                              onChange={(e) =>
                                setMatrizAsignaciones({
                                  ...matrizAsignaciones,
                                  [emp.id]: {
                                    ...asig,
                                    rol: e.target.value as 'ADMIN' | 'USUARIO',
                                  },
                                })
                              }
                              className="w-full px-2 py-1 text-xs bg-white border border-slate-300 rounded focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500 disabled:bg-slate-100 disabled:text-slate-400 cursor-pointer font-medium"
                            >
                              <option value="USUARIO">USUARIO (Operador)</option>
                              <option value="ADMIN">ADMIN (Administrador)</option>
                            </select>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className="flex justify-end gap-2 pt-3 border-t border-slate-200">
            <button
              type="button"
              disabled={formGuardando}
              onClick={() => setModalUsuarioAbierto(false)}
              className="px-4 py-2 text-xs font-semibold text-slate-700 bg-white border border-slate-300 rounded-lg hover:bg-slate-50 transition-colors"
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={formGuardando}
              className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 active:scale-[0.98] transition-all disabled:opacity-50"
            >
              {formGuardando && <RefreshCw className="h-3.5 w-3.5 animate-spin" />}
              <span>{usuarioEditando ? 'Actualizar Usuario' : 'Crear Usuario'}</span>
            </button>
          </div>
        </form>
      </Modal>

      {/* 5. MODAL RESETEAR CONTRASEÑA */}
      <Modal
        isOpen={modalResetAbierto}
        onClose={() => !resetGuardando && setModalResetAbierto(false)}
        title="Resetear Contraseña"
        description={
          usuarioParaReset
            ? `Asigne una nueva contraseña temporal para el usuario '${usuarioParaReset.username}'.`
            : 'Asigne una nueva contraseña temporal.'
        }
        maxWidth="md"
      >
        <form onSubmit={ejecutarResetPassword} className="space-y-4">
          {resetError && (
            <div className="p-3 bg-rose-50 border border-rose-200 text-rose-800 rounded-lg text-xs font-medium flex items-center gap-2">
              <AlertCircle className="h-4 w-4 shrink-0 text-rose-600" />
              <span>{resetError}</span>
            </div>
          )}

          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1">
              Nueva contraseña temporal <span className="text-rose-500">* (mínimo 8 caracteres)</span>
            </label>
            <div className="relative">
              <Lock className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
              <input
                type="password"
                required
                autoFocus
                value={nuevoPasswordReset}
                onChange={(e) => setNuevoPasswordReset(e.target.value)}
                placeholder="••••••••"
                className="w-full pl-9 pr-3 py-1.5 text-xs bg-white border border-slate-300 rounded-lg focus:ring-2 focus:ring-amber-500/20 focus:border-amber-500"
              />
            </div>
            <p className="text-[11px] text-slate-500 mt-1">
              Comunique esta clave de manera segura al usuario para su próximo inicio de sesión.
            </p>
          </div>

          <div className="flex justify-end gap-2 pt-3 border-t border-slate-200">
            <button
              type="button"
              disabled={resetGuardando}
              onClick={() => setModalResetAbierto(false)}
              className="px-4 py-2 text-xs font-semibold text-slate-700 bg-white border border-slate-300 rounded-lg hover:bg-slate-50 transition-colors"
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={resetGuardando}
              className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold text-white bg-amber-600 rounded-lg hover:bg-amber-700 active:scale-[0.98] transition-all disabled:opacity-50"
            >
              {resetGuardando && <RefreshCw className="h-3.5 w-3.5 animate-spin" />}
              <span>Establecer Contraseña</span>
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
};

export default UsuariosPage;
