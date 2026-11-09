import { ChevronLeft, ChevronRight } from 'lucide-react'
import { Button } from './button'
import { resumenPagina } from '../../utils/paginacion'

export interface PaginacionProps {
  page: number
  pageSize: number
  count: number
  /** Filas recibidas en la página actual (para el rango "desde–hasta"). */
  enPagina?: number
  cargando?: boolean
  onCambiarPagina: (page: number) => void
  etiqueta?: string
}

/** Bloque 7 — barra de paginación con total de registros y anterior/siguiente. */
export function Paginacion({ page, pageSize, count, enPagina, cargando, onCambiarPagina, etiqueta = 'registros' }: PaginacionProps) {
  const r = resumenPagina(page, pageSize, count, enPagina)
  return (
    <div
      className="flex flex-col sm:flex-row items-center justify-between gap-2 px-4 py-2.5 border-t border-slate-100 bg-slate-50/50 text-xs text-slate-600"
      data-testid="paginacion"
    >
      <span>
        {r.count === 0 ? (
          <>Sin {etiqueta}</>
        ) : (
          <>
            Mostrando <strong className="font-mono text-slate-900">{r.desde}–{r.hasta}</strong> de{' '}
            <strong className="font-mono text-slate-900">{r.count}</strong> {etiqueta}
          </>
        )}
      </span>
      <div className="flex items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="xs"
          disabled={!r.hayAnterior || cargando}
          onClick={() => onCambiarPagina(r.page - 1)}
          aria-label="Página anterior"
        >
          <ChevronLeft className="h-3.5 w-3.5" /> Anterior
        </Button>
        <span className="font-mono">
          Página {r.page} de {r.totalPaginas}
        </span>
        <Button
          type="button"
          variant="outline"
          size="xs"
          disabled={!r.haySiguiente || cargando}
          onClick={() => onCambiarPagina(r.page + 1)}
          aria-label="Página siguiente"
        >
          Siguiente <ChevronRight className="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  )
}
