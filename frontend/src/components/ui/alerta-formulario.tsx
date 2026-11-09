import * as React from 'react'
import { AlertTriangle } from 'lucide-react'
import { cn } from '../../lib/utils'

export interface AlertaFormularioProps {
  titulo: string
  mensajes: string[]
  className?: string
}

/**
 * Bloque 10 — error de un formulario mostrado DENTRO del modal activo (no en la página de
 * atrás). Admite varios mensajes (p. ej. uno por línea del detalle) y textos largos en móvil.
 */
export const AlertaFormulario = React.forwardRef<HTMLDivElement, AlertaFormularioProps>(
  ({ titulo, mensajes, className }, ref) => (
    <div
      ref={ref}
      role="alert"
      aria-live="assertive"
      className={cn(
        'flex items-start gap-2.5 rounded-lg border border-rose-300 bg-rose-50 p-3.5 text-xs text-rose-800 animate-in fade-in',
        className,
      )}
    >
      <AlertTriangle className="h-4 w-4 shrink-0 text-rose-600 mt-0.5" aria-hidden="true" />
      <div className="min-w-0 flex-1 space-y-1">
        <p className="font-semibold text-rose-900">{titulo}</p>
        {mensajes.length === 1 ? (
          <p className="leading-relaxed break-words whitespace-pre-line">{mensajes[0]}</p>
        ) : (
          <ul className="list-disc space-y-0.5 pl-4 leading-relaxed break-words">
            {mensajes.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        )}
      </div>
    </div>
  ),
)
AlertaFormulario.displayName = 'AlertaFormulario'
