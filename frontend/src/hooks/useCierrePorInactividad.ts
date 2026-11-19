/**
 * Cierra la sesión tras 30 minutos sin uso (mouse, teclado, scroll o toque). El aviso se muestra
 * en la pantalla de ingreso. La sesión además vence a las 8 horas en el backend.
 */
import { useEffect, useRef } from 'react'
import { AVISO_INACTIVIDAD, CLAVE_AVISO_LOGIN, MINUTOS_INACTIVIDAD, venciaPorInactividad } from '../utils/seguridad'

const EVENTOS = ['mousemove', 'mousedown', 'keydown', 'scroll', 'touchstart', 'wheel'] as const

export function useCierrePorInactividad(cerrarSesion: () => void, activo: boolean, minutos = MINUTOS_INACTIVIDAD) {
  const ultimoUso = useRef(0)

  useEffect(() => {
    if (!activo) return
    ultimoUso.current = Date.now()
    const marcar = () => { ultimoUso.current = Date.now() }
    EVENTOS.forEach((evento) => window.addEventListener(evento, marcar, { passive: true }))
    const revisar = window.setInterval(() => {
      if (!venciaPorInactividad(ultimoUso.current, Date.now(), minutos)) return
      try {
        sessionStorage.setItem(CLAVE_AVISO_LOGIN, AVISO_INACTIVIDAD)
      } catch {
        // sin almacenamiento: igual se cierra la sesión
      }
      cerrarSesion()
    }, 30_000)
    return () => {
      EVENTOS.forEach((evento) => window.removeEventListener(evento, marcar))
      window.clearInterval(revisar)
    }
  }, [activo, cerrarSesion, minutos])
}
