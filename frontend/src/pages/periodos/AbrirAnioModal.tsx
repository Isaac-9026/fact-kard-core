/**
 * «Abrir año»: crea en una sola operación los meses que faltan de un año (para importar un
 * Excel histórico). Cada mes sigue siendo un período normal; los existentes no se tocan.
 */
import React, { useEffect, useState } from 'react'
import { AlertTriangle, CalendarPlus, CheckCircle2, Lock } from 'lucide-react'
import {
  abrirAnio, obtenerVistaPreviaAnio, type ResultadoAbrirAnio, type VistaPreviaAnio,
} from '../../api/periodos'
import { Modal } from '../../components/ui/modal'
import { Button } from '../../components/ui/button'
import { Input } from '../../components/ui/input'
import { Label } from '../../components/ui/label'
import { Select } from '../../components/ui/select'
import { Badge } from '../../components/ui/badge'
import { diferirCarga } from '../../utils/efectos'
import { mensajesDeErrorApi } from '../../utils/errores'
import {
  ANIO_MINIMO, alternarMes, anioMaximo, anioValido, elegidosSinIgv, seleccionDesde, seleccionInicial, textoResumen,
} from '../../utils/abrirAnio'

const VARIANTE_ESTADO = { ABIERTO: 'success', CERRADO: 'neutral', DESACTUALIZADO: 'warning' } as const

export const AbrirAnioModal: React.FC<{
  onClose: () => void
  onAbierto: (resultado: ResultadoAbrirAnio) => void
}> = ({ onClose, onAbierto }) => {
  const [anio, setAnio] = useState<number>(() => new Date().getFullYear())
  const [previa, setPrevia] = useState<VistaPreviaAnio | null>(null)
  const [seleccion, setSeleccion] = useState<number[]>([])
  const [cargando, setCargando] = useState(false)
  const [guardando, setGuardando] = useState(false)
  const [errores, setErrores] = useState<string[]>([])

  const consultar = async () => {
    if (!anioValido(anio)) {
      setErrores([`El año debe estar entre ${ANIO_MINIMO} y ${anioMaximo()}.`])
      return
    }
    setCargando(true)
    setErrores([])
    try {
      const datos = await obtenerVistaPreviaAnio(anio)
      setPrevia(datos)
      setSeleccion(seleccionInicial(datos))
    } catch (err) {
      setPrevia(null)
      setErrores(mensajesDeErrorApi(err, 'No se pudieron consultar los meses del año.'))
    } finally {
      setCargando(false)
    }
  }

  // Al abrir, muestra de una vez los meses del año actual.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { diferirCarga(consultar) }, [])

  const confirmar = async () => {
    if (!previa || !seleccion.length || guardando) return
    setGuardando(true)
    setErrores([])
    try {
      onAbierto(await abrirAnio(previa.anio, seleccion))
    } catch (err) {
      setErrores(mensajesDeErrorApi(err, 'No se pudo abrir el año. No se creó ningún mes.'))
    } finally {
      setGuardando(false)
    }
  }

  const sinIgv = previa ? elegidosSinIgv(previa, seleccion) : []

  return (
    <Modal
      isOpen
      onClose={() => { if (!guardando) onClose() }}
      title="Abrir año"
      description="Crea de una vez los meses que faltan, por ejemplo para importar un Excel histórico. El Kardex, el IGV y los cierres siguen siendo mensuales."
      icon={<CalendarPlus className="h-5 w-5" />}
      maxWidth="3xl"
      footer={(
        <div className="flex gap-2">
          <Button variant="secondary" onClick={onClose} disabled={guardando}>Cancelar</Button>
          <Button variant="primary" onClick={confirmar} isLoading={guardando} disabled={!previa || !seleccion.length}
                  data-testid="abrir-anio-confirmar">
            {seleccion.length ? `Crear ${seleccion.length} ${seleccion.length === 1 ? 'mes' : 'meses'}` : 'Crear meses'}
          </Button>
        </div>
      )}
    >
      <div className="space-y-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="space-y-1.5">
            <Label required htmlFor="abrir-anio">Año</Label>
            <Input
              id="abrir-anio" type="number" min={ANIO_MINIMO} max={anioMaximo()} value={anio}
              onChange={(e) => { setAnio(Number(e.target.value)); setPrevia(null) }}
              onKeyDown={(e) => { if (e.key === 'Enter') consultar() }}
              className="w-32 font-mono tabular-nums"
            />
          </div>
          <Button variant="outline" onClick={consultar} isLoading={cargando}>Ver meses</Button>
          {previa && previa.faltantes.length > 0 && (
            <div className="ml-auto flex items-end gap-2 text-xs">
              <div className="space-y-1.5">
                <Label htmlFor="abrir-desde">Abrir desde</Label>
                <Select
                  id="abrir-desde" className="h-9 text-xs" value=""
                  onChange={(e) => { if (e.target.value) setSeleccion(seleccionDesde(previa, Number(e.target.value))) }}
                >
                  <option value="">Elegir mes…</option>
                  {previa.meses.filter((m) => !m.existe).map((m) => <option key={m.mes} value={m.mes}>{m.nombre} a diciembre</option>)}
                </Select>
              </div>
              <Button size="sm" variant="ghost" onClick={() => setSeleccion(seleccionInicial(previa))}>Todos</Button>
              <Button size="sm" variant="ghost" onClick={() => setSeleccion([])}>Ninguno</Button>
            </div>
          )}
        </div>

        {previa && (
          <>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4" role="group" aria-label={`Meses de ${previa.anio}`}>
              {previa.meses.map((m) => {
                const marcado = seleccion.includes(m.mes)
                return (
                  <label
                    key={m.mes}
                    className={`flex cursor-pointer flex-col gap-1 rounded-lg border p-2.5 text-xs transition-colors ${
                      m.existe ? 'cursor-not-allowed border-slate-200 bg-slate-50 text-slate-500'
                        : marcado ? 'border-indigo-300 bg-indigo-50' : 'border-slate-200 bg-white hover:bg-slate-50'}`}
                  >
                    <span className="flex items-center gap-2">
                      <input
                        type="checkbox" className="h-4 w-4 rounded border-slate-300 text-indigo-600"
                        checked={marcado} disabled={m.existe} onChange={() => setSeleccion(alternarMes(previa, seleccion, m.mes))}
                        aria-label={m.nombre}
                      />
                      <span className="font-semibold text-slate-800">{m.nombre}</span>
                    </span>
                    {m.existe && m.estado ? (
                      <span className="flex items-center gap-1">
                        {m.estado === 'CERRADO' && <Lock className="h-3 w-3" />}
                        <Badge size="xs" variant={VARIANTE_ESTADO[m.estado]}>Ya existe · {m.estado}</Badge>
                      </span>
                    ) : (
                      <span className="text-slate-500">Nuevo · al {m.fecha_fin.slice(8, 10)}/{m.fecha_fin.slice(5, 7)}</span>
                    )}
                    {!m.existe && !m.igv.cubierto && (
                      <span className="flex items-center gap-1 text-amber-700" title="Días sin vigencia de IGV">
                        <AlertTriangle className="h-3 w-3" /> {m.igv.dias_sin_cobertura} día(s) sin IGV
                      </span>
                    )}
                  </label>
                )
              })}
            </div>

            <div className="rounded-lg border border-indigo-100 bg-indigo-50/60 p-3 text-xs text-indigo-900" data-testid="abrir-anio-resumen">
              <p className="flex items-start gap-1.5 font-medium">
                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {textoResumen(previa, seleccion)}
              </p>
              {previa.faltantes.length === 0 && <p className="mt-1">Todos los meses de {previa.anio} ya existen: no hay nada que crear.</p>}
            </div>

            {sinIgv.length > 0 && (
              <div role="alert" className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800" data-testid="abrir-anio-igv">
                <p className="flex items-start gap-1.5 font-semibold">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  {sinIgv.map((m) => m.nombre).join(', ')}: días sin vigencia de IGV.
                </p>
                <p className="mt-1">
                  {previa.primera_vigencia_igv
                    ? `La primera vigencia de IGV registrada rige desde ${previa.primera_vigencia_igv.split('-').reverse().join('/')}. `
                    : 'La empresa no tiene vigencias de IGV registradas. '}
                  Configure la vigencia en Configuración → Empresa antes de importar o registrar comprobantes de esas fechas que la requieran.
                  Puede abrir los meses igual.
                </p>
              </div>
            )}
          </>
        )}

        {errores.length > 0 && (
          <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs font-medium text-rose-700">
            {errores.map((e) => <p key={e}>{e}</p>)}
          </div>
        )}
      </div>
    </Modal>
  )
}
