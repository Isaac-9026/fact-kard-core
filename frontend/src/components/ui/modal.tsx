import * as React from 'react'
import { X } from 'lucide-react'
import { cn } from '../../lib/utils'

export interface ModalProps {
  isOpen: boolean
  onClose: () => void
  title?: React.ReactNode
  description?: React.ReactNode
  icon?: React.ReactNode
  children: React.ReactNode
  footer?: React.ReactNode
  maxWidth?: 'sm' | 'md' | 'lg' | 'xl' | '2xl' | '3xl' | '4xl' | '5xl' | '7xl'
  className?: string
}

const maxWidthMap = {
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-lg',
  xl: 'max-w-xl',
  '2xl': 'max-w-2xl',
  '3xl': 'max-w-3xl',
  '4xl': 'max-w-4xl',
  '5xl': 'max-w-5xl',
  // Bloque 10: formularios maestro-detalle anchos (comprobantes); en móvil sigue siendo w-full.
  '7xl': 'max-w-7xl',
}

export function Modal({
  isOpen,
  onClose,
  title,
  description,
  icon,
  children,
  footer,
  maxWidth = 'lg',
  className,
}: ModalProps) {
  React.useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    if (isOpen) {
      document.body.style.overflow = 'hidden'
      window.addEventListener('keydown', handleKeyDown)
    }
    return () => {
      document.body.style.overflow = 'unset'
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [isOpen, onClose])

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 overflow-y-auto">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-slate-900/60 backdrop-blur-xs transition-opacity animate-in fade-in"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Modal Dialog */}
      <div
        className={cn(
          'relative w-full rounded-xl bg-white border border-slate-200 shadow-xl z-10 overflow-hidden flex flex-col max-h-[90vh] animate-in zoom-in-95 duration-150',
          maxWidthMap[maxWidth] || 'max-w-lg',
          className
        )}
        role="dialog"
        aria-modal="true"
      >
        {/* Header */}
        {(title || icon) && (
          <div className="flex items-start justify-between p-5 border-b border-slate-100 bg-slate-50/50 shrink-0">
            <div className="flex items-center gap-3">
              {icon && (
                <div className="h-9 w-9 rounded-lg bg-indigo-50 border border-indigo-100 flex items-center justify-center text-indigo-600 shrink-0">
                  {icon}
                </div>
              )}
              <div>
                <h3 className="text-base font-semibold text-slate-900 leading-snug">{title}</h3>
                {description && <p className="text-xs text-slate-500 mt-0.5">{description}</p>}
              </div>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="text-slate-400 hover:text-slate-600 rounded-md p-1 hover:bg-slate-100 transition-colors cursor-pointer"
              aria-label="Cerrar modal"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        )}

        {/* Body */}
        <div className="p-4 sm:p-5 overflow-y-auto flex-1 min-w-0 text-sm text-slate-700">{children}</div>

        {/* Footer */}
        {footer && (
          <div className="flex items-center justify-end gap-2.5 p-4 border-t border-slate-100 bg-slate-50/50 shrink-0">
            {footer}
          </div>
        )}
      </div>
    </div>
  )
}

export const Dialog = Modal
