/**
 * Bloque 17C — botón "Consultar RUC" con vista previa. Reutilizable en Empresa, Datos fiscales
 * y Tercero: valida el RUC, consulta al backend, muestra lo encontrado (marcando lo que
 * reemplazaría) y solo cambia el formulario si el usuario pulsa "Aplicar datos". No guarda nada.
 *
 * Integridad (auditoría 17C, MEDIO-1): el resultado queda atado al RUC consultado. Si el RUC del
 * formulario cambia, la vista previa se descarta y hay que consultar de nuevo; además, al
 * aplicar se vuelve a comprobar que el resultado corresponde al RUC actual.
 */
import { useReducer, useState } from 'react'
import { AlertTriangle, Search } from 'lucide-react'
import { consultarRuc } from '../../api/consultaRuc'
import { Button } from '../ui/button'
import { Badge } from '../ui/badge'
import {
  ETIQUETA_FASE, aplicarCambios, cambiosPropuestos, codigoErrorConsulta, cuantosSobrescriben, descripcionFuente,
  errorRucLocal, etiquetasContribuyente, reducirConsulta, resultadoAplicable, rucNormalizado, type CampoMapeado, type EstadoConsulta,
} from '../../utils/consultaRuc'

interface Props<T extends Record<string, unknown>> {
  ruc: string
  formulario: T
  campos: readonly CampoMapeado[]
  onAplicar: (formulario: T) => void
  deshabilitado?: boolean
}

export function ConsultaRucBoton<T extends Record<string, unknown>>({ ruc, formulario, campos, onAplicar, deshabilitado }: Props<T>) {
  const [estado, despachar] = useReducer(reducirConsulta, { fase: 'inactivo' } as EstadoConsulta)
  const rucActual = rucNormalizado(ruc)

  // Si el RUC del formulario cambió, cualquier consulta en curso o resultado anterior deja de valer
  // (ajuste de estado durante el render, patrón recomendado por React en lugar de un efecto).
  const [rucVisto, setRucVisto] = useState(rucActual)
  if (rucVisto !== rucActual) {
    setRucVisto(rucActual)
    despachar({ tipo: 'RUC_CAMBIADO', ruc: rucActual })
  }

  const consultar = async () => {
    const consultado = rucActual
    const errorLocal = errorRucLocal(consultado)
    if (errorLocal) return despachar({ tipo: 'ERROR', codigo: 'RUC_INVALIDO', mensaje: `RUC inválido: ${errorLocal}` })
    despachar({ tipo: 'CONSULTAR', ruc: consultado })
    try {
      despachar({ tipo: 'EXITO', ruc: consultado, resultado: await consultarRuc(consultado) })
    } catch (e) {
      despachar({ tipo: 'ERROR', ruc: consultado, codigo: codigoErrorConsulta(e) })
    }
  }

  // Solo hay vista previa si el resultado corresponde al RUC que tiene AHORA el formulario.
  const resultado = resultadoAplicable(estado, rucActual)
  const cambios = resultado ? cambiosPropuestos(formulario, resultado.datos, campos) : []
  const reemplazos = cuantosSobrescriben(cambios)

  const aplicar = () => {
    // Defensa en profundidad: se vuelve a comprobar en el momento de aplicar.
    if (!resultadoAplicable(estado, ruc)) return despachar({ tipo: 'CANCELAR' })
    onAplicar(aplicarCambios(formulario, cambios))
    despachar({ tipo: 'APLICAR' })
  }

  return (
    <div className="space-y-2" data-testid="consulta-ruc">
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" size="sm" variant="secondary" onClick={consultar}
          disabled={deshabilitado || estado.fase === 'consultando'} isLoading={estado.fase === 'consultando'}>
          <Search className="h-3.5 w-3.5" /> Consultar RUC
        </Button>
        {estado.fase === 'consultando' && <span className="text-xs text-slate-500" role="status">{ETIQUETA_FASE.consultando}</span>}
        {estado.fase === 'error' && <span className="text-xs text-amber-700" role="alert" data-testid="consulta-ruc-error">{estado.mensaje}</span>}
      </div>

      {resultado && (
        <div className="space-y-2 rounded-lg border border-indigo-200 bg-indigo-50/50 p-3 text-xs" data-testid="consulta-ruc-vista-previa">
          <div className="flex flex-wrap items-center gap-2">
            <strong className="text-slate-800">{ETIQUETA_FASE.encontrado}</strong>
            <Badge size="sm" variant={resultado.oficial ? 'info' : 'warning'} data-testid="consulta-ruc-fuente">
              {descripcionFuente(resultado)}
            </Badge>
            {etiquetasContribuyente(resultado).map((e) => (
              <Badge key={e.etiqueta} size="sm" variant={e.ok ? 'success' : 'destructive'}>{e.etiqueta}: {e.valor}</Badge>
            ))}
          </div>
          <p className="text-slate-700" data-testid="consulta-ruc-consultado">
            RUC consultado: <span className="font-mono tabular-nums font-medium text-slate-900">{resultado.datos.ruc}</span>
          </p>
          {cambios.length === 0 ? (
            <p className="text-slate-600">El formulario ya tiene estos datos; no hay nada que aplicar.</p>
          ) : (
            <dl className="space-y-1">
              {cambios.map((c) => (
                <div key={c.campoFormulario} className="grid grid-cols-1 gap-0.5 sm:grid-cols-[9rem_1fr]">
                  <dt className="text-slate-500">{c.etiqueta}</dt>
                  <dd className="break-words">
                    <span className="font-medium text-slate-900">{c.nuevo}</span>
                    {c.sobrescribe && <span className="ml-1 text-amber-700" data-testid="consulta-ruc-reemplaza">(reemplaza: {c.actual})</span>}
                  </dd>
                </div>
              ))}
            </dl>
          )}
          {resultado.advertencias.map((a) => (
            <p key={a} className="flex gap-1 text-amber-700"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{a}</p>
          ))}
          <div className="flex flex-wrap gap-2 pt-1">
            {cambios.length > 0 && (
              <Button type="button" size="sm" variant="primary" onClick={aplicar}>
                {reemplazos > 0 ? `Aplicar datos (reemplaza ${reemplazos} campo${reemplazos > 1 ? 's' : ''})` : 'Aplicar datos'}
              </Button>
            )}
            <Button type="button" size="sm" variant="ghost" onClick={() => despachar({ tipo: 'CANCELAR' })}>Cancelar</Button>
          </div>
          <p className="text-[11px] text-slate-500">Revise y luego guarde el formulario normalmente; la consulta no guarda nada.</p>
        </div>
      )}
    </div>
  )
}
