import React, { startTransition, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { getMeApi, logoutApi } from '../api/auth';
import { registrarManejadorSesionInvalida, reiniciarControlSesion } from '../api/http';
import type { Usuario, EmpresaAsociada, EmpresaActiva, OpcionesSeleccionarEmpresa, AuthContextType } from '../types/auth';
import { reconciliarEstadoEmpresas } from './authState';
import { AuthContext } from './useAuth';
import { borrarCredencial, guardarCredencial, leerCredencial } from '../utils/credencialSesion';


export const AuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const refrescoEmpresasEnCurso = useRef<Promise<EmpresaAsociada[]> | null>(null);
  // Bloque 9: `token` es la credencial de sesión: el token (modo actual) o la marca de cookie
  // HttpOnly (el token real no es accesible para JavaScript). Ver utils/credencialSesion.ts.
  const [token, setToken] = useState<string | null>(() => leerCredencial(localStorage));
  // FE-002: con una sesión guardada, no se muestra contenido privado hasta que /me la valide.
  const [verificandoSesion, setVerificandoSesion] = useState<boolean>(() => Boolean(leerCredencial(localStorage)));
  const [usuario, setUsuario] = useState<Usuario | null>(() => {
    const saved = localStorage.getItem('usuario');
    if (!saved) return null;
    try {
      return JSON.parse(saved) as Usuario;
    } catch {
      return null;
    }
  });

  const [empresasDisponibles, setEmpresasDisponibles] = useState<EmpresaAsociada[]>(() => {
    const saved = localStorage.getItem('empresas_disponibles');
    if (!saved) return [];
    try {
      return JSON.parse(saved) as EmpresaAsociada[];
    } catch {
      return [];
    }
  });

  const [empresaActiva, setEmpresaActiva] = useState<EmpresaActiva | null>(() => {
    const saved = sessionStorage.getItem('empresa_activa') || localStorage.getItem('empresa_activa');
    if (!saved) return null;
    try {
      const activaGuardada = JSON.parse(saved) as EmpresaActiva;
      const empresasGuardadas = localStorage.getItem('empresas_disponibles');
      const empresas = empresasGuardadas
        ? JSON.parse(empresasGuardadas) as EmpresaAsociada[]
        : [];
      return reconciliarEstadoEmpresas(empresas, activaGuardada).empresaActiva;
    } catch {
      return null;
    }
  });

  // Estado de transición animada al cambiar de empresa accesible por cualquier vista
  const [empresaTransicion, setEmpresaTransicion] = useState<EmpresaAsociada | null>(null);
  const empresaTransicionRef = useRef<EmpresaAsociada | null>(null);

  const persistirEstadoEmpresas = useCallback((empresas: EmpresaAsociada[]) => {
    setEmpresasDisponibles(empresas);
    localStorage.setItem('empresas_disponibles', JSON.stringify(empresas));

    setEmpresaActiva((actual) => {
      const siguiente = reconciliarEstadoEmpresas(empresas, actual).empresaActiva;
      if (siguiente) {
        sessionStorage.setItem('empresa_id', String(siguiente.id));
        sessionStorage.setItem('empresa_activa', JSON.stringify(siguiente));
        localStorage.setItem('empresa_id', String(siguiente.id));
        localStorage.setItem('empresa_activa', JSON.stringify(siguiente));
      } else {
        sessionStorage.removeItem('empresa_id');
        sessionStorage.removeItem('empresa_activa');
        localStorage.removeItem('empresa_id');
        localStorage.removeItem('empresa_activa');
      }
      return siguiente;
    });
  }, []);

  const refrescarEmpresasDisponibles = useCallback(() => {
    if (refrescoEmpresasEnCurso.current) return refrescoEmpresasEnCurso.current;

    const refresco = getMeApi()
      .then((data) => {
        setUsuario(data.usuario);
        localStorage.setItem('usuario', JSON.stringify(data.usuario));
        persistirEstadoEmpresas(data.empresas);
        return data.empresas;
      })
      .catch((error: unknown) => {
        persistirEstadoEmpresas([]);
        throw error;
      })
      .finally(() => {
        refrescoEmpresasEnCurso.current = null;
      });

    refrescoEmpresasEnCurso.current = refresco;
    return refresco;
  }, [persistirEstadoEmpresas]);

  useEffect(() => {
    // Sin token no hay nada que verificar: el estado inicial ya es `false` y las rutas
    // privadas redirigen al login aunque `verificandoSesion` siguiera en true.
    if (!token) return;
    void refrescarEmpresasDisponibles()
      .catch(() => undefined)
      .finally(() => setVerificandoSesion(false));
  }, [refrescarEmpresasDisponibles, token]);

  const login = useCallback((newToken: string | null, newUsuario: Usuario, empresas: EmpresaAsociada[]) => {
    reiniciarControlSesion();
    setVerificandoSesion(false);
    // Sin token en la respuesta → sesión por cookie HttpOnly (no se guarda ningún token).
    setToken(guardarCredencial(localStorage, newToken));
    setUsuario(newUsuario);
    setEmpresasDisponibles(empresas);

    localStorage.setItem('usuario', JSON.stringify(newUsuario));
    localStorage.setItem('empresas_disponibles', JSON.stringify(empresas));

    const savedEmpresaId = localStorage.getItem('empresa_id');
    const matched = empresas.find((e) => String(e.id) === savedEmpresaId);
    const activa = matched || empresas[0] || null;

    if (activa) {
      const basicActiva: EmpresaActiva = {
        id: activa.id,
        ruc: activa.ruc,
        razon_social: activa.razon_social,
        nombre_comercial: activa.nombre_comercial,
        rol: activa.rol,
        logo: activa.logo ?? null,
        color_tema: activa.color_tema ?? null,
      };
      setEmpresaActiva(basicActiva);
      localStorage.setItem('empresa_id', String(basicActiva.id));
      localStorage.setItem('empresa_activa', JSON.stringify(basicActiva));
    } else {
      setEmpresaActiva(null);
      localStorage.removeItem('empresa_id');
      localStorage.removeItem('empresa_activa');
    }
  }, []);

  const logout = useCallback(() => {
    const credencial = leerCredencial(localStorage);
    if (credencial) void logoutApi(credencial);
    setVerificandoSesion(false);
    setToken(null);
    setUsuario(null);
    setEmpresaActiva(null);
    setEmpresasDisponibles([]);
    empresaTransicionRef.current = null;
    setEmpresaTransicion(null);

    sessionStorage.removeItem('empresa_id');
    sessionStorage.removeItem('empresa_activa');
    borrarCredencial(localStorage);
    localStorage.removeItem('empresa_id');
    localStorage.removeItem('usuario');
    localStorage.removeItem('empresas_disponibles');
    localStorage.removeItem('empresa_activa');
  }, []);

  // FE-002: un 401 de la sesión vigente limpia la sesión; RutaProtegida redirige a /login.
  useEffect(() => registrarManejadorSesionInvalida(logout), [logout]);

  // Si otra pestaña cerró la sesión (manual o por inactividad), esta también la cierra.
  useEffect(() => {
    const alCambiar = (e: StorageEvent) => {
      if (e.key !== null && e.key !== 'token' && e.key !== 'sesion_cookie') return
      if (!leerCredencial(localStorage)) logout()
    }
    window.addEventListener('storage', alCambiar)
    return () => window.removeEventListener('storage', alCambiar)
  }, [logout])

  const registrarEmpresaDisponible = useCallback((empresa: EmpresaAsociada) => {
    setEmpresasDisponibles((actuales) => {
      const existe = actuales.some((disponible) => disponible.id === empresa.id);
      const actualizadas = existe
        ? actuales.map((disponible) => disponible.id === empresa.id ? empresa : disponible)
        : [...actuales, empresa];

      localStorage.setItem('empresas_disponibles', JSON.stringify(actualizadas));
      return actualizadas;
    });
  }, []);

  const seleccionarEmpresa = useCallback((empresaId: number, opciones?: OpcionesSeleccionarEmpresa) => {
    if (!empresaId || empresaId === empresaActiva?.id || Boolean(empresaTransicionRef.current)) return;
    const encontrada = empresasDisponibles.find((e) => e.id === empresaId);
    if (!encontrada) return;

    // Modo silencioso: cambio inmediato sin overlay animado (ideal para onboarding o vistas fuera de MainLayout)
    if (opciones?.silencioso) {
      const basicActiva: EmpresaActiva = {
        id: encontrada.id,
        ruc: encontrada.ruc,
        razon_social: encontrada.razon_social,
        nombre_comercial: encontrada.nombre_comercial,
        rol: encontrada.rol,
        logo: encontrada.logo ?? null,
        color_tema: encontrada.color_tema ?? null,
      };
      sessionStorage.setItem('empresa_id', String(encontrada.id));
      sessionStorage.setItem('empresa_activa', JSON.stringify(basicActiva));
      localStorage.setItem('empresa_id', String(encontrada.id));
      localStorage.setItem('empresa_activa', JSON.stringify(basicActiva));
      startTransition(() => {
        setEmpresaActiva(basicActiva);
      });
      return;
    }

    empresaTransicionRef.current = encontrada;
    setEmpresaTransicion(encontrada);
  }, [empresasDisponibles, empresaActiva?.id]);

  const confirmarCambioEmpresa = useCallback(() => {
    const target = empresaTransicionRef.current;
    if (!target) return;
    const basicActiva: EmpresaActiva = {
      id: target.id,
      ruc: target.ruc,
      razon_social: target.razon_social,
      nombre_comercial: target.nombre_comercial,
      rol: target.rol,
      logo: target.logo ?? null,
      color_tema: target.color_tema ?? null,
    };

    // 1. Persistencia síncrona en storage ANTES de startTransition:
    // Garantiza que cuando los componentes se remonten y sus efectos o interceptores
    // de Axios se ejecuten, el header X-Empresa-Id ya tenga el nuevo ID.
    sessionStorage.setItem('empresa_id', String(target.id));
    sessionStorage.setItem('empresa_activa', JSON.stringify(basicActiva));
    localStorage.setItem('empresa_id', String(target.id));
    localStorage.setItem('empresa_activa', JSON.stringify(basicActiva));

    // 2. Transición reactiva de React 19 para remontar el subárbol
    startTransition(() => {
      setEmpresaActiva(basicActiva);
    });
  }, []);

  const terminarTransicionEmpresa = useCallback(() => {
    empresaTransicionRef.current = null;
    setEmpresaTransicion(null);
  }, []);

  // Salvaguarda: si por algún motivo la animación no llama a terminarTransicionEmpresa
  // (por ejemplo si se desmonta el layout a mitad de transición), se confirma y desbloquea tras 2s.
  useEffect(() => {
    if (!empresaTransicion) return;
    const timer = setTimeout(() => {
      if (empresaTransicionRef.current) {
        confirmarCambioEmpresa();
        terminarTransicionEmpresa();
      }
    }, 2000);
    return () => clearTimeout(timer);
  }, [empresaTransicion, confirmarCambioEmpresa, terminarTransicionEmpresa]);

  const actualizarIdentidadEmpresa = useCallback((empresaId: number, datos: { logo?: string | null; color_tema?: string | null }) => {
    setEmpresasDisponibles((actuales) => {
      const actualizadas = actuales.map((e) =>
        e.id === empresaId ? { ...e, ...datos } : e
      );
      localStorage.setItem('empresas_disponibles', JSON.stringify(actualizadas));
      return actualizadas;
    });

    setEmpresaActiva((actual) => {
      if (!actual || actual.id !== empresaId) return actual;
      const siguiente: EmpresaActiva = { ...actual, ...datos };
      sessionStorage.setItem('empresa_activa', JSON.stringify(siguiente));
      localStorage.setItem('empresa_activa', JSON.stringify(siguiente));
      return siguiente;
    });
  }, []);

  const contextValue = useMemo<AuthContextType>(() => ({
    usuario,
    empresaActiva,
    empresasDisponibles,
    token,
    isAuthenticated: !!token,
    verificandoSesion,
    empresaTransicion,
    confirmarCambioEmpresa,
    terminarTransicionEmpresa,
    login,
    logout,
    registrarEmpresaDisponible,
    refrescarEmpresasDisponibles,
    seleccionarEmpresa,
    actualizarIdentidadEmpresa,
  }), [
    usuario,
    empresaActiva,
    empresasDisponibles,
    token,
    verificandoSesion,
    empresaTransicion,
    confirmarCambioEmpresa,
    terminarTransicionEmpresa,
    login,
    logout,
    registrarEmpresaDisponible,
    refrescarEmpresasDisponibles,
    seleccionarEmpresa,
    actualizarIdentidadEmpresa,
  ]);

  return (
    <AuthContext.Provider value={contextValue}>
      {children}
    </AuthContext.Provider>
  );
};
