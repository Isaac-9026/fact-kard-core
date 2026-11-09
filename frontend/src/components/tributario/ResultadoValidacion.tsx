/**
 * Bloque 17A — muestra el resultado de una validación previa a la emisión electrónica
 * (errores bloqueantes y advertencias). Solo presenta lo que calcula el backend.
 */
import { AlertTriangle, CheckCircle2, XCircle } from 'lucide-react'
import { Badge } from '../ui/badge'

interface Props {
  listo: boolean
  errores: string[]
  advertencias: string[]
  etiquetaListo?: string
  etiquetaNoListo?: string
}

export function ResultadoValidacion({ listo, errores, advertencias, etiquetaListo = 'Listo para emisión', etiquetaNoListo = 'No preparado' }: Props) {
  return (
    <div className="space-y-2" data-testid="resultado-validacion">
      <Badge variant={listo ? 'success' : 'destructive'} data-testid="estado-preparacion">
        {listo ? <CheckCircle2 className="mr-1 h-3.5 w-3.5" /> : <XCircle className="mr-1 h-3.5 w-3.5" />}
        {listo ? etiquetaListo : etiquetaNoListo}
      </Badge>
      {errores.length > 0 && (
        <ul className="space-y-1 text-xs text-rose-700" data-testid="errores-validacion">
          {errores.map((e) => (
            <li key={e} className="flex gap-1.5"><XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{e}</li>
          ))}
        </ul>
      )}
      {advertencias.length > 0 && (
        <ul className="space-y-1 text-xs text-amber-700" data-testid="advertencias-validacion">
          {advertencias.map((a) => (
            <li key={a} className="flex gap-1.5"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{a}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
