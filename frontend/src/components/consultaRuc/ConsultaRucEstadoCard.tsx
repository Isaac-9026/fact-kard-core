/**
 * Bloque 17D — recuadro "Consulta RUC" (solo ADMIN): de dónde salen los datos del botón
 * "Consultar RUC" y, si es el padrón SUNAT, su fecha y cantidad de registros. Solo metadatos;
 * el padrón se importa en el servidor con `manage.py importar_padron_ruc` (no hay subida aquí).
 */
import { useEffect, useState } from 'react'
import { CheckCircle2, CircleDashed, Search } from 'lucide-react'
import { obtenerEstadoConsultaRuc, type EstadoConsultaRuc } from '../../api/consultaRuc'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../ui/card'
import { AlertaFormulario } from '../ui/alerta-formulario'
import { mensajesDeErrorApi } from '../../utils/errores'
import { filasEstadoConsultaRuc } from '../../utils/consultaRuc'

export function ConsultaRucEstadoCard() {
  const [estado, setEstado] = useState<EstadoConsultaRuc | null>(null)
  const [error, setError] = useState<string[] | null>(null)

  useEffect(() => {
    let vigente = true
    obtenerEstadoConsultaRuc()
      .then((e) => { if (vigente) setEstado(e) })
      .catch((e) => { if (vigente) setError(mensajesDeErrorApi(e, 'No se pudo consultar el estado de la consulta RUC.')) })
    return () => { vigente = false }
  }, [])

  return (
    <Card data-testid="consulta-ruc-estado">
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Search className="h-4 w-4" /> Consulta RUC</CardTitle>
        <CardDescription>Fuente de los datos que completa el botón "Consultar RUC".</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {error && <AlertaFormulario titulo="No disponible" mensajes={error} />}
        {estado && (
          <dl className="space-y-1.5 text-xs">
            {filasEstadoConsultaRuc(estado).map((f) => (
              <div key={f.etiqueta} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-0.5">
                <dt className="text-slate-500">{f.etiqueta}</dt>
                <dd className={`flex items-center gap-1 font-medium ${f.ok ? 'text-emerald-700' : 'text-slate-700'}`}>
                  {f.ok ? <CheckCircle2 className="h-3.5 w-3.5 shrink-0" /> : <CircleDashed className="h-3.5 w-3.5 shrink-0" />}
                  {f.valor}
                </dd>
              </div>
            ))}
          </dl>
        )}
        {estado?.oficial && !estado.disponible && (
          <p className="text-[11px] text-slate-500">
            Descargue el padrón reducido desde el portal de SUNAT e impórtelo en el servidor con{' '}
            <code className="break-all rounded bg-slate-100 px-1">importar_padron_ruc</code>.
          </p>
        )}
      </CardContent>
    </Card>
  )
}
