import React, { useEffect, useRef, useState } from 'react'
import {
  obtenerInicialesEmpresa,
  resolverUrlMedia,
  obtenerFiltroLogo,
} from '../utils/identidadEmpresa'
import { ETIQUETA_ROL, type RolEmpresa } from '../utils/seguridad'

export interface DatosEmpresaTransicion {
  id?: number
  razon_social: string
  nombre_comercial?: string | null
  ruc?: string | null
  logo?: string | null
  color_tema?: string | null
  rol?: string | null
}

export interface TransicionCambioEmpresaProps {
  empresa: DatosEmpresaTransicion | null
  onCubierto: () => void
  onTerminar: () => void
  duracionMs?: number
}

const DURACION_ENTRADA_MS = 160
const DURACION_SALIDA_MS = 200

const EASE_ENTRADA = 'cubic-bezier(0.22, 1, 0.36, 1)'
const EASE_SALIDA = 'cubic-bezier(0.4, 0, 1, 1)'

export const TransicionCambioEmpresa: React.FC<TransicionCambioEmpresaProps> = ({
  empresa,
  onCubierto,
  onTerminar,
  duracionMs = 750,
}) => {
  const [fase, setFase] = useState<'entrando' | 'visible' | 'saliendo' | 'oculto'>('oculto')
  const [logoFallido, setLogoFallido] = useState(false)

  const onCubiertoRef = useRef(onCubierto)
  const onTerminarRef = useRef(onTerminar)
  onCubiertoRef.current = onCubierto
  onTerminarRef.current = onTerminar

  const empresaClave = empresa
    ? `${empresa.id ?? ''}-${empresa.ruc ?? ''}-${empresa.razon_social}`
    : null

  useEffect(() => {
    if (!empresaClave) {
      setFase('oculto')
      setLogoFallido(false)
      return
    }

    const reduceMotion =
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches

    if (reduceMotion) {
      onCubiertoRef.current()
      onTerminarRef.current()
      return
    }

    setLogoFallido(false)
    setFase('entrando')

    let frame2 = 0
    const frame1 = requestAnimationFrame(() => {
      frame2 = requestAnimationFrame(() => {
        setFase('visible')
      })
    })

    const timerCubierto = setTimeout(() => {
      onCubiertoRef.current()
    }, DURACION_ENTRADA_MS)

    const tiempoSalida = Math.max(duracionMs - DURACION_SALIDA_MS, DURACION_ENTRADA_MS + 100)
    const timerSalida = setTimeout(() => {
      setFase('saliendo')
    }, tiempoSalida)

    const timerFin = setTimeout(() => {
      setFase('oculto')
      onTerminarRef.current()
    }, duracionMs)

    return () => {
      cancelAnimationFrame(frame1)
      cancelAnimationFrame(frame2)
      clearTimeout(timerCubierto)
      clearTimeout(timerSalida)
      clearTimeout(timerFin)
    }
  }, [empresaClave, duracionMs])

  if (!empresa || fase === 'oculto') return null

  const logoUrl = resolverUrlMedia(empresa.logo)
  const colorTema = empresa.color_tema?.trim() || '#4F46E5'
  const rolEtiqueta = empresa.rol
    ? ETIQUETA_ROL[empresa.rol as RolEmpresa] || empresa.rol
    : null

  const esVisible = fase === 'visible'
  const esSaliendo = fase === 'saliendo'

  const estiloMotion = (delayMs: number, escalaInicial = 0.96): React.CSSProperties => ({
    opacity: esVisible ? 1 : 0,
    transform: esVisible
      ? 'translate3d(0, 0, 0) scale(1)'
      : esSaliendo
        ? 'translate3d(0, -4px, 0) scale(1.025)'
        : `translate3d(0, 12px, 0) scale(${escalaInicial})`,
    transitionProperty: 'opacity, transform',
    transitionDuration: esSaliendo ? `${DURACION_SALIDA_MS}ms` : '340ms',
    transitionTimingFunction: esSaliendo ? EASE_SALIDA : EASE_ENTRADA,
    transitionDelay: esVisible ? `${delayMs}ms` : '0ms',
  })

  return (
    <aside
      role="presentation"
      className="fixed inset-0 z-50 flex flex-col items-center justify-center p-8 bg-white/97 backdrop-blur-md pointer-events-auto cursor-wait select-none overflow-hidden"
      style={{
        opacity: esVisible ? 1 : 0,
        transitionProperty: 'opacity',
        transitionDuration: esSaliendo ? `${DURACION_SALIDA_MS}ms` : `${DURACION_ENTRADA_MS}ms`,
        transitionTimingFunction: esSaliendo ? EASE_SALIDA : 'ease-out',
      }}
    >
      <style>{`
        @keyframes factkard-dot-wave {
          0%, 100% { transform: scale(0.75); opacity: 0.25; }
          50% { transform: scale(1.15); opacity: 1; }
        }
      `}</style>

      {/* Luz cenital atmosférica */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 h-[60vh] origin-top will-change-transform"
        style={{
          background: `radial-gradient(ellipse 75% 60% at 50% -10%, ${colorTema}24 0%, ${colorTema}0A 45%, transparent 78%)`,
          opacity: esVisible ? 1 : 0,
          transform: esVisible ? 'scale(1)' : 'scale(0.92)',
          transition: `opacity 300ms ${EASE_ENTRADA}, transform 450ms ${EASE_ENTRADA}`,
        }}
      />

      {/* Monolito central */}
      <div className="relative flex flex-col items-center text-center max-w-xl w-full">
        {/* 1. Logo amplio (soporta cuadrado y horizontal) o Monograma grande */}
        <div
          className="relative mb-7 will-change-transform"
          style={estiloMotion(0, 0.93)}
        >
          {logoUrl && !logoFallido ? (
            <div
              className="p-2 rounded-[28px] bg-white/80 border border-slate-200/75"
              style={{
                boxShadow: `0 24px 50px -14px ${colorTema}30, 0 4px 14px -2px rgba(15, 23, 42, 0.06), inset 0 1px 0 rgba(255, 255, 255, 0.95)`,
              }}
            >
              <div className="h-28 sm:h-32 min-w-[112px] sm:min-w-[128px] max-w-[260px] sm:max-w-[300px] px-4 py-3 rounded-[22px] bg-white border border-slate-100 flex items-center justify-center overflow-hidden">
                <img
                  src={logoUrl}
                  alt={empresa.razon_social}
                  onError={() => setLogoFallido(true)}
                  className="max-h-full max-w-full object-contain"
                  style={{ filter: obtenerFiltroLogo(false) }}
                />
              </div>
            </div>
          ) : (
            <div
              className="p-2 rounded-[28px] bg-white/80 border border-slate-200/75"
              style={{
                boxShadow: `0 24px 50px -14px ${colorTema}30, 0 4px 14px -2px rgba(15, 23, 42, 0.06), inset 0 1px 0 rgba(255, 255, 255, 0.95)`,
              }}
            >
              <div
                className="relative h-28 w-28 sm:h-32 sm:w-32 rounded-[22px] flex items-center justify-center overflow-hidden"
                style={{
                  background: `linear-gradient(145deg, color-mix(in srgb, ${colorTema} 11%, white) 0%, color-mix(in srgb, ${colorTema} 4%, white) 100%)`,
                  border: `1px solid color-mix(in srgb, ${colorTema} 20%, transparent)`,
                  boxShadow: 'inset 0 1px 0 rgba(255, 255, 255, 0.85)',
                }}
              >
                <span
                  className="text-3xl sm:text-4xl font-bold tracking-tight"
                  style={{ color: colorTema }}
                >
                  {obtenerInicialesEmpresa(empresa.razon_social)}
                </span>
              </div>
            </div>
          )}
        </div>

        {/* 2. Tipografía Principal */}
        <div className="relative px-4 will-change-transform" style={estiloMotion(35)}>
          <h2 className="text-2xl sm:text-3xl font-semibold text-slate-900 tracking-[-0.03em] leading-tight line-clamp-2">
            {empresa.razon_social}
          </h2>

          {empresa.nombre_comercial &&
            empresa.nombre_comercial.trim() !== empresa.razon_social.trim() && (
              <p className="text-sm sm:text-base font-medium text-slate-500 tracking-[-0.01em] mt-1.5 line-clamp-1">
                {empresa.nombre_comercial}
              </p>
            )}
        </div>

        {/* 3. Metadatos Fiscales */}
        {(empresa.ruc || rolEtiqueta) && (
          <div
            className="relative mt-4 flex items-center justify-center gap-3.5 text-xs sm:text-sm text-slate-500 will-change-transform"
            style={estiloMotion(65)}
          >
            {empresa.ruc && (
              <span className="font-mono tabular-nums tracking-tight text-slate-600">
                RUC {empresa.ruc}
              </span>
            )}
            {empresa.ruc && rolEtiqueta && (
              <span aria-hidden="true" className="h-3.5 w-px bg-slate-200" />
            )}
            {rolEtiqueta && (
              <span className="inline-flex items-center gap-2 font-medium text-slate-700 bg-slate-50 px-3 py-1 rounded-full border border-slate-200/80">
                <span
                  aria-hidden="true"
                  className="h-2 w-2 rounded-full"
                  style={{ backgroundColor: colorTema }}
                />
                {rolEtiqueta}
              </span>
            )}
          </div>
        )}

        {/* 4. Onda de 3 Nodos */}
        <div
          className="relative mt-9 flex items-center gap-2.5 will-change-transform"
          style={estiloMotion(95)}
        >
          {[0, 110, 220].map((delay) => (
            <span
              key={delay}
              className="h-1.5 w-1.5 rounded-full"
              style={{
                backgroundColor: colorTema,
                animation: `factkard-dot-wave 600ms ease-in-out ${delay}ms infinite`,
              }}
            />
          ))}
        </div>
      </div>
    </aside>
  )
}