/**
 * Bloque 16 — campos de condición de pago (CONTADO / CRÉDITO), vencimiento y cuotas.
 * Componente controlado: el padre guarda el estado y lo envía al backend, que vuelve a validar.
 */
import { Plus, Trash2, Wand2 } from 'lucide-react'
import type { CondicionPago } from '../../api/documentos'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { Label } from '../ui/label'
import { Select } from '../ui/select'
import { CONDICION_INICIAL, distribuirCuotas, fechasMensuales, sumaCuotas, type CondicionPagoValor, type CuotaForm } from '../../utils/finanzas'
import { formatearDecimal } from '../../utils/decimal'


interface Props {
  valor: CondicionPagoValor
  onChange: (valor: CondicionPagoValor) => void
  fechaEmision: string
  total: string
  simboloMoneda: string
  deshabilitado?: boolean
  /** Las notas siempre son al contado (ajustan el saldo de su comprobante de origen). */
  esNota?: boolean
}

export function CondicionPagoCampos({ valor, onChange, fechaEmision, total, simboloMoneda, deshabilitado, esNota }: Props) {
  const credito = valor.condicion === 'CREDITO'
  const set = (cambios: Partial<CondicionPagoValor>) => onChange({ ...valor, ...cambios })

  const generar = (n: number) => {
    const fechas = fechasMensuales(fechaEmision, n)
    if (fechas.length === 0) return
    set({ cuotas: distribuirCuotas(total, fechas), fechaVencimiento: fechas[fechas.length - 1] })
  }
  const editarCuota = (i: number, campo: keyof CuotaForm, v: string) => {
    const cuotas = valor.cuotas.map((c, j) => (j === i ? { ...c, [campo]: v } : c))
    const ultima = cuotas[cuotas.length - 1]
    set({ cuotas, ...(campo === 'fecha_vencimiento' && i === cuotas.length - 1 && ultima ? { fechaVencimiento: ultima.fecha_vencimiento } : {}) })
  }

  if (esNota) {
    return (
      <p className="text-xs text-slate-500" data-testid="condicion-nota">
        Condición de pago: <strong>Contado</strong>. La nota ajusta el saldo de su comprobante de origen.
      </p>
    )
  }

  return (
    <div className="space-y-3" data-testid="condicion-pago">
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3">
        <div className="space-y-1">
          <Label required htmlFor="condicion-pago-select">Condición de pago</Label>
          <Select
            id="condicion-pago-select"
            value={valor.condicion}
            disabled={deshabilitado}
            onChange={(e) => {
              const c = e.target.value as CondicionPago
              onChange(c === 'CONTADO' ? CONDICION_INICIAL : { ...valor, condicion: c })
            }}
          >
            <option value="CONTADO">Contado</option>
            <option value="CREDITO">Crédito</option>
          </Select>
        </div>
        {credito && (
          <div className="space-y-1">
            <Label required htmlFor="fecha-vencimiento-input">Fecha de vencimiento</Label>
            <Input
              id="fecha-vencimiento-input"
              type="date"
              min={fechaEmision || undefined}
              value={valor.fechaVencimiento}
              disabled={deshabilitado || valor.cuotas.length > 0}
              onChange={(e) => set({ fechaVencimiento: e.target.value })}
              className="font-mono tabular-nums"
            />
          </div>
        )}
        {credito && (
          <div className="space-y-1 sm:col-span-2">
            <Label>Cuotas (opcional)</Label>
            <div className="flex flex-wrap gap-2">
              {[2, 3, 6].map((n) => (
                <Button key={n} type="button" size="sm" variant="secondary" disabled={deshabilitado} onClick={() => generar(n)}>
                  <Wand2 className="h-3.5 w-3.5" /> {n} mensuales
                </Button>
              ))}
              <Button
                type="button" size="sm" variant="ghost" disabled={deshabilitado}
                onClick={() => set({ cuotas: [...valor.cuotas, { fecha_vencimiento: valor.fechaVencimiento, monto: '' }] })}
              >
                <Plus className="h-3.5 w-3.5" /> Agregar cuota
              </Button>
            </div>
          </div>
        )}
      </div>

      {credito && valor.cuotas.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-slate-200">
          <table className="w-full text-xs" data-testid="tabla-cuotas">
            <thead className="bg-slate-50 text-slate-500">
              <tr>
                <th className="p-2 text-left w-12">N°</th>
                <th className="p-2 text-left">Vence</th>
                <th className="p-2 text-right">Monto ({simboloMoneda})</th>
                <th className="p-2 w-10" />
              </tr>
            </thead>
            <tbody>
              {valor.cuotas.map((c, i) => (
                <tr key={i} className="border-t border-slate-100">
                  <td className="p-2 font-mono">{i + 1}</td>
                  <td className="p-2">
                    <Input
                      type="date" aria-label={`Vencimiento cuota ${i + 1}`} value={c.fecha_vencimiento}
                      disabled={deshabilitado} onChange={(e) => editarCuota(i, 'fecha_vencimiento', e.target.value)}
                      className="h-8 font-mono"
                    />
                  </td>
                  <td className="p-2">
                    <Input
                      type="number" inputMode="decimal" step="any" min="0" aria-label={`Monto cuota ${i + 1}`}
                      value={c.monto} disabled={deshabilitado} onChange={(e) => editarCuota(i, 'monto', e.target.value)}
                      className="h-8 text-right font-mono tabular-nums"
                    />
                  </td>
                  <td className="p-2 text-center">
                    <button
                      type="button" title="Quitar cuota" disabled={deshabilitado}
                      className="p-1 text-slate-400 hover:text-rose-600"
                      onClick={() => {
                        const cuotas = valor.cuotas.filter((_, j) => j !== i)
                        const ultima = cuotas[cuotas.length - 1]
                        set({ cuotas, ...(ultima ? { fechaVencimiento: ultima.fecha_vencimiento } : {}) })
                      }}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot className="bg-slate-50 font-mono tabular-nums">
              <tr className="border-t border-slate-200">
                <td className="p-2" colSpan={2}>Suma de cuotas / total</td>
                <td className="p-2 text-right font-semibold" data-testid="suma-cuotas">
                  {formatearDecimal(sumaCuotas(valor.cuotas))} / {formatearDecimal(total)}
                </td>
                <td />
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </div>
  )
}
