import React, { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { getMeApi, logoutApi } from '../api/auth';
import { registrarManejadorSesionInvalida, reiniciarControlSesion } from '../api/http';
import type { Usuario, EmpresaAsociada, EmpresaActiva } from '../types/auth';
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

  const login = (newToken: string | null, newUsuario: Usuario, empresas: EmpresaAsociada[]) => {
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
  };

  const logout = useCallback(() => {
    const credencial = leerCredencial(localStorage);
    if (credencial) void logoutApi(credencial);
    setVerificandoSesion(false);
    setToken(null);
    setUsuario(null);
    setEmpresaActiva(null);
    setEmpresasDisponibles([]);

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

  const registrarEmpresaDisponible = (empresa: EmpresaAsociada) => {
    setEmpresasDisponibles((actuales) => {
      const existe = actuales.some((disponible) => disponible.id === empresa.id);
      const actualizadas = existe
        ? actuales.map((disponible) => disponible.id === empresa.id ? empresa : disponible)
        : [...actuales, empresa];

      localStorage.setItem('empresas_disponibles', JSON.stringify(actualizadas));
      return actualizadas;
    });
  };

  const seleccionarEmpresa = (empresaId: number) => {
    const encontrada = empresasDisponibles.find((e) => e.id === empresaId);
    if (encontrada) {
      const basicActiva: EmpresaActiva = {
        id: encontrada.id,
        ruc: encontrada.ruc,
        razon_social: encontrada.razon_social,
        nombre_comercial: encontrada.nombre_comercial,
        rol: encontrada.rol,
        logo: encontrada.logo ?? null,
        color_tema: encontrada.color_tema ?? null,
      };
      setEmpresaActiva(basicActiva);
      sessionStorage.setItem('empresa_id', String(empresaId));
      sessionStorage.setItem('empresa_activa', JSON.stringify(basicActiva));
      localStorage.setItem('empresa_id', String(empresaId));
      localStorage.setItem('empresa_activa', JSON.stringify(basicActiva));
    }
  };

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

  return (
    <AuthContext.Provider
      value={{
        usuario,
        empresaActiva,
        empresasDisponibles,
        token,
        isAuthenticated: !!token,
        verificandoSesion,
        login,
        logout,
        registrarEmpresaDisponible,
        refrescarEmpresasDisponibles,
        seleccionarEmpresa,
        actualizarIdentidadEmpresa,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};
