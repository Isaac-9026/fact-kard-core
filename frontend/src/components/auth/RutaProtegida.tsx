import React from 'react'
import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { useAuth } from '../../context/useAuth'
import { resolverAccesoRuta } from '../../utils/sesion'

/**
 * FE-002: envuelve las rutas privadas. Sin sesión redirige a /login; mientras
 * se valida un token guardado no renderiza ningún módulo privado.
 */
export const RutaProtegida: React.FC = () => {
  const { token, verificandoSesion } = useAuth()
  const location = useLocation()
  const acceso = resolverAccesoRuta({ token, verificandoSesion })

  if (acceso === 'redirigir_login') {
    return <Navigate to="/login" replace state={{ desde: location.pathname }} />
  }

  if (acceso === 'verificando') {
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex min-h-screen items-center justify-center gap-2 bg-slate-50 text-sm text-slate-500"
      >
        <Loader2 className="h-4 w-4 animate-spin" />
        Verificando sesión…
      </div>
    )
  }

  return <Outlet />
}

export default RutaProtegida
