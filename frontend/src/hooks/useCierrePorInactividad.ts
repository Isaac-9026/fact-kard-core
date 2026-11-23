import { useEffect, useRef } from 'react'
import {
  AVISO_INACTIVIDAD, CLAVE_AVISO_LOGIN, CLAVE_ULTIMA_ACTIVIDAD, MINUTOS_INACTIVIDAD, ultimaActividad,
  venciaPorInactividad,
} from '../utils/seguridad'

const EVENTOS = ['mousemove', 'mousedown', 'keydown', 'scroll', 'touchstart', 'wheel'] as const

const leerCompartida = (): number => {
  try {
    return Number(localStorage.getItem(CLAVE_ULTIMA_ACTIVIDAD)) || 0
  } catch {
    return 0
  }
}

export function useCierrePorInactividad(cerrarSesion: () => void, activo: boolean, minutos = MINUTOS_INACTIVIDAD) {
  const ultimoUso = useRef(0)

  useEffect(() => {
    if (!activo) return
    const guardar = (ahora: number) => {
      ultimoUso.current = ahora
      try {
        localStorage.setItem(CLAVE_ULTIMA_ACTIVIDAD, String(ahora))
      } catch {
        /* sin almacenamiento */
      }
    }
    guardar(Date.now())
    const marcar = () => {
      const ahora = Date.now()
      if (ahora - ultimoUso.current > 10_000) guardar(ahora)
      else ultimoUso.current = ahora
    }
    EVENTOS.forEach((evento) => window.addEventListener(evento, marcar, { passive: true }))
    const revisar = window.setInterval(() => {
      const ultimo = ultimaActividad(ultimoUso.current, leerCompartida())
      if (!venciaPorInactividad(ultimo, Date.now(), minutos)) return
      try {
        sessionStorage.setItem(CLAVE_AVISO_LOGIN, AVISO_INACTIVIDAD)
      } catch {
        /* sin almacenamiento */
      }
      cerrarSesion()
    }, 30_000)
    return () => {
      EVENTOS.forEach((evento) => window.removeEventListener(evento, marcar))
      window.clearInterval(revisar)
    }
  }, [activo, cerrarSesion, minutos])
}
