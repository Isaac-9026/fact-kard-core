/**
 * Bloque 16 — sección "Pagos" del detalle del comprobante: total, pagado, saldo, estado
 * financiero, cuotas, pagos registrados (con anulación) y registro de un pago/cobro.
 * Todo se calcula en el backend; aquí solo se muestra y se valida antes de enviar.
 */
import { useEffect, useState } from 'react'
import { Ban, Banknote } from 'lucide-react'
import type { Documento } from '../../api/documentos'
import { anularPago, obtenerMetodosPago, registrarPago, type MetodoPago } from '../../api/finanzas'
import { Badge } from '../ui/badge'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { Label } from '../ui/label'
import { Select } from '../ui/select'
import { AlertaFormulario } from '../ui/alerta-formulario'
import { esMayorQueCero, formatearDecimal } from '../../utils/decimal'
import { fechaCalendarioLocal } from '../../utils/date'
import { mensajesDeErrorApi } from '../../utils/errores'
import { ETIQUETA_ESTADO_FINANCIERO, errorMontoPago } from '../../utils/finanzas'

interface Props {
  documento: Documento
  esAdmin: boolean
  /** Recarga el documento tras registrar o anular un pago. */
  onActualizado: () => Promise<void> | void
}

export function EstadoFinancieroBadge({ estado }: { estado: string | null | undefined }) {
  if (!estado) return <span className="text-slate-400">—</span>
  const e = ETIQUETA_ESTADO_FINANCIERO[estado as keyof typeof ETIQUETA_ESTADO_FINANCIERO]
  return <Badge variant={e?.variante ?? 'neutral'} size="sm">{e?.texto ?? estado}</Badge>
}

export function PagosDocumento({ documento, esAdmin, onActualizado }: Props) {
  const f = documento.finanzas
  const moneda = documento.moneda_codigo
  const [metodos, setMetodos] = useState<MetodoPago[]>([])
  const [fecha, setFecha] = useState(fechaCalendarioLocal)
  const [monto, setMonto] = useState(f?.saldo_pendiente ?? '')
  const [metodo, setMetodo] = useState('')
  const [referencia, setReferencia] = useState('')
  const [errores, setErrores] = useState<string[] | null>(null)
  const [enviando, setEnviando] = useState(false)
  const [anulandoId, setAnulandoId] = useState<number | null>(null)
  const [motivo, setMotivo] = useState('')

  const puedeRegistrar = esAdmin && documento.estado === 'CONFIRMADO' && Boolean(f) && esMayorQueCero(f?.saldo_pendiente)

  useEffect(() => {
    if (!esAdmin) return
    obtenerMetodosPago()
      .then((m) => { setMetodos(m); setMetodo((actual) => actual || m[0]?.codigo || '') })
      .catch(() => setMetodos([]))
  }, [esAdmin])

  // Al cambiar de documento o de saldo, el monto propuesto es el saldo pendiente.
  const claveSaldo = `${documento.id}:${f?.saldo_pendiente ?? ''}`
  const [claveAnterior, setClaveAnterior] = useState(claveSaldo)
  if (claveAnterior !== claveSaldo) {
    setClaveAnterior(claveSaldo)
    setMonto(f?.saldo_pendiente ?? '')
  }

  const registrar = async () => {
    setErrores(null)
    const err = errorMontoPago(String(monto), f?.saldo_pendiente ?? '0')
    if (err) return setErrores([err])
    if (!metodo) return setErrores(['Seleccione el método de pago.'])
    if (!fecha) return setErrores(['Ingrese la fecha del pago.'])
    setEnviando(true)
    try {
      await registrarPago({ documento: documento.id, fecha, monto: String(monto), metodo_pago: metodo, referencia: referencia.trim() || undefined })
      setReferencia('')
      await onActualizado()
    } catch (e) {
      setErrores(mensajesDeErrorApi(e, 'No se pudo registrar el pago.'))
    } finally {
      setEnviando(false)
    }
  }

  const anular = async (id: number) => {
    setErrores(null)
    if (!motivo.trim()) return setErrores(['Indique el motivo de la anulación del pago.'])
    setEnviando(true)
    try {
      await anularPago(id, motivo.trim())
      setAnulandoId(null)
      setMotivo('')
      await onActualizado()
    } catch (e) {
      setErrores(mensajesDeErrorApi(e, 'No se pudo anular el pago.'))
    } finally {
      setEnviando(false)
    }
  }

  const etiquetaAccion = documento.clase === 'VENTA' ? 'cobro' : 'pago'

  return (
    <section className="space-y-3" data-testid="seccion-pagos">
      <h4 className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-slate-700">
        <Banknote className="h-4 w-4" /> Pagos
        <span className="font-normal normal-case text-slate-500">
          ({documento.condicion_pago === 'CREDITO' ? `Crédito, vence ${documento.fecha_vencimiento}` : 'Contado'})
        </span>
      </h4>

      {!f || documento.estado !== 'CONFIRMADO' ? (
        <p className="text-xs text-slate-500" data-testid="pagos-no-aplica">
          {!f
            ? 'Las notas no reciben pagos: ajustan el saldo de su comprobante de origen.'
            : documento.estado === 'BORRADOR'
              ? 'El comprobante está en borrador: los pagos se registran después de confirmarlo.'
              : 'El comprobante está anulado: no tiene saldo por cobrar ni por pagar.'}
        </p>
      ) : (
        <dl className="grid grid-cols-2 sm:grid-cols-5 gap-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs font-mono tabular-nums">
          <div><dt className="text-slate-400">Total</dt><dd className="font-semibold">{moneda} {formatearDecimal(f.total_ajustado)}</dd></div>
          <div><dt className="text-slate-400">Pagado</dt><dd className="font-semibold" data-testid="finanzas-pagado">{moneda} {formatearDecimal(f.pagado)}</dd></div>
          <div><dt className="text-slate-400">Saldo</dt><dd className="font-bold text-slate-900" data-testid="finanzas-saldo">{moneda} {formatearDecimal(f.saldo_pendiente)}</dd></div>
          <div><dt className="text-slate-400">Vencido</dt><dd className="font-semibold">{moneda} {formatearDecimal(f.monto_vencido)}</dd></div>
          <div><dt className="text-slate-400 font-sans">Estado</dt><dd data-testid="finanzas-estado"><EstadoFinancieroBadge estado={f.estado_financiero} /></dd></div>
          {(esMayorQueCero(f.total_notas_credito) || esMayorQueCero(f.total_notas_debito)) && (
            <div className="col-span-2 sm:col-span-5 font-sans text-slate-500">
              Total original {formatearDecimal(f.total)} · Notas de crédito −{formatearDecimal(f.total_notas_credito)} · Notas de débito +{formatearDecimal(f.total_notas_debito)}
            </div>
          )}
        </dl>
      )}

      {documento.cuotas && documento.cuotas.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-slate-500"><tr><th className="p-1.5 text-left">Cuota</th><th className="p-1.5 text-left">Vence</th><th className="p-1.5 text-right">Monto</th></tr></thead>
            <tbody>
              {documento.cuotas.map((c) => (
                <tr key={c.id ?? c.numero} className="border-t border-slate-100 font-mono tabular-nums">
                  <td className="p-1.5">{c.numero}</td><td className="p-1.5">{c.fecha_vencimiento}</td>
                  <td className="p-1.5 text-right">{formatearDecimal(c.monto)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {errores && <AlertaFormulario titulo={`No se pudo completar la operación`} mensajes={errores} />}

      {documento.pagos && documento.pagos.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full text-xs" data-testid="tabla-pagos">
            <thead className="text-slate-500">
              <tr>
                <th className="p-1.5 text-left">Fecha</th><th className="p-1.5 text-left">Método</th><th className="p-1.5 text-left">Referencia</th>
                <th className="p-1.5 text-right">Monto</th><th className="p-1.5 text-left">Estado</th><th className="p-1.5" />
              </tr>
            </thead>
            <tbody>
              {documento.pagos.map((p) => (
                <tr key={p.id} className={`border-t border-slate-100 ${p.estado === 'ANULADO' ? 'text-slate-400 line-through' : ''}`}>
                  <td className="p-1.5 font-mono">{p.fecha}</td>
                  <td className="p-1.5">{p.metodo_pago_descripcion || p.metodo_pago}</td>
                  <td className="p-1.5">{p.referencia || '—'}</td>
                  <td className="p-1.5 text-right font-mono tabular-nums">{p.moneda_codigo} {formatearDecimal(p.monto)}</td>
                  <td className="p-1.5 no-underline" title={p.motivo_anulacion || undefined}>
                    <Badge size="sm" variant={p.estado === 'VIGENTE' ? 'success' : 'neutral'}>{p.estado}</Badge>
                  </td>
                  <td className="p-1.5 text-right">
                    {esAdmin && p.estado === 'VIGENTE' && anulandoId !== p.id && (
                      <Button type="button" size="xs" variant="ghost" onClick={() => { setAnulandoId(p.id); setMotivo('') }}>
                        <Ban className="h-3.5 w-3.5" /> Anular
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : f && documento.estado === 'CONFIRMADO' ? (
        <p className="text-xs text-slate-500">Sin pagos registrados.</p>
      ) : null}

      {anulandoId !== null && (
        <div className="flex flex-col gap-2 rounded-lg border border-rose-200 bg-rose-50/50 p-3 sm:flex-row sm:items-end">
          <div className="flex-1 space-y-1">
            <Label required htmlFor="motivo-anular-pago">Motivo de la anulación del pago</Label>
            <Input id="motivo-anular-pago" value={motivo} onChange={(e) => setMotivo(e.target.value)} maxLength={500} />
          </div>
          <div className="flex gap-2">
            <Button type="button" size="sm" variant="secondary" onClick={() => setAnulandoId(null)}>Cancelar</Button>
            <Button type="button" size="sm" variant="destructive" isLoading={enviando} onClick={() => anular(anulandoId)}>Anular pago</Button>
          </div>
        </div>
      )}

      {puedeRegistrar && (
        <div className="grid grid-cols-1 gap-3 rounded-lg border border-indigo-100 bg-indigo-50/40 p-3 sm:grid-cols-2 lg:grid-cols-5" data-testid="form-pago">
          <div className="space-y-1">
            <Label required htmlFor="pago-fecha">Fecha</Label>
            <Input id="pago-fecha" type="date" value={fecha} min={documento.fecha_emision} max={fechaCalendarioLocal()} onChange={(e) => setFecha(e.target.value)} className="font-mono" />
          </div>
          <div className="space-y-1">
            <Label required htmlFor="pago-monto">Monto ({moneda})</Label>
            <Input id="pago-monto" type="number" inputMode="decimal" step="any" min="0" value={monto} onChange={(e) => setMonto(e.target.value)} className="text-right font-mono tabular-nums" />
          </div>
          <div className="space-y-1">
            <Label required htmlFor="pago-metodo">Método</Label>
            <Select id="pago-metodo" value={metodo} onChange={(e) => setMetodo(e.target.value)}>
              {metodos.map((m) => <option key={m.codigo} value={m.codigo}>{m.descripcion}</option>)}
            </Select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="pago-referencia">Referencia</Label>
            <Input id="pago-referencia" value={referencia} maxLength={100} placeholder="N° operación" onChange={(e) => setReferencia(e.target.value)} />
          </div>
          <div className="flex items-end">
            <Button type="button" variant="primary" className="w-full" isLoading={enviando} onClick={registrar}>
              Registrar {etiquetaAccion}
            </Button>
          </div>
        </div>
      )}
    </section>
  )
}
