/**
 * Bloque 16 — historial comercial de un cliente/proveedor (lee `documento`, sin tabla propia):
 * comprobantes, condición, pagado, saldo y estado; con resumen por clase y moneda.
 */
import { useEffect, useState } from 'react'
import { History } from 'lucide-react'
import { obtenerHistorialTercero, type HistorialTercero } from '../../api/finanzas'
import type { Tercero } from '../../api/inventario'
import { Modal } from '../ui/modal'
import { Button } from '../ui/button'
import { Badge } from '../ui/badge'
import { Tabs, TabsList, TabsTrigger } from '../ui/tabs'
import { AlertaFormulario } from '../ui/alerta-formulario'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../ui/table'
import { EstadoFinancieroBadge } from './PagosDocumento'
import { formatearDecimal } from '../../utils/decimal'
import { mensajesDeErrorApi } from '../../utils/errores'
import { comprobanteTexto } from '../../utils/finanzas'

type Filtro = 'TODOS' | 'VENTA' | 'COMPRA'

/** Importe ya conciliado por el backend; '—' cuando no aplica (notas, borradores, anulados). */
const importe = (valor: string | null, signo = '') => (valor === null ? '—' : `${signo && valor !== '0.00000000' ? signo : ''}${formatearDecimal(valor)}`)

export function HistorialTerceroModal({ tercero, onClose }: { tercero: Tercero; onClose: () => void }) {
  const [filtro, setFiltro] = useState<Filtro>('TODOS')
  const [datos, setDatos] = useState<HistorialTercero | null>(null)
  const [error, setError] = useState<string[] | null>(null)

  useEffect(() => {
    let vigente = true
    obtenerHistorialTercero(tercero.id, filtro === 'TODOS' ? undefined : filtro)
      .then((d) => { if (vigente) { setDatos(d); setError(null) } })
      .catch((e) => { if (vigente) setError(mensajesDeErrorApi(e, 'No se pudo cargar el historial.')) })
    return () => { vigente = false }
  }, [tercero.id, filtro])

  return (
    <Modal
      isOpen
      onClose={onClose}
      maxWidth="5xl"
      icon={<History className="h-5 w-5" />}
      title={`Historial: ${tercero.razon_social}`}
      description={`Documento ${tercero.numero_documento} · Total ajustado = original − NC + ND (notas confirmadas); saldo = ajustado − pagado`}
      footer={<Button variant="secondary" onClick={onClose}>Cerrar</Button>}
    >
      <div className="space-y-4" data-testid="historial-tercero">
        {tercero.es_cliente && tercero.es_proveedor && (
          <Tabs value={filtro} onValueChange={(v) => setFiltro(v as Filtro)}>
            <TabsList>
              <TabsTrigger value="TODOS">Todos</TabsTrigger>
              <TabsTrigger value="VENTA">Ventas</TabsTrigger>
              <TabsTrigger value="COMPRA">Compras</TabsTrigger>
            </TabsList>
          </Tabs>
        )}
        {error && <AlertaFormulario titulo="No se pudo cargar el historial" mensajes={error} />}
        {datos && datos.resumen.length > 0 && (
          <div className="flex flex-wrap gap-2 text-xs">
            {datos.resumen.map((r) => (
              <div key={`${r.clase}-${r.moneda_codigo}`} className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 font-mono tabular-nums">
                <span className="font-sans font-semibold">{r.clase === 'VENTA' ? 'Ventas' : 'Compras'} {r.moneda_codigo}</span>
                {' '}· {r.comprobantes} comp. · Original {formatearDecimal(r.total_original)}
                {' '}· NC −{formatearDecimal(r.total_notas_credito)} · ND +{formatearDecimal(r.total_notas_debito)}
                {' '}· Ajustado {formatearDecimal(r.total_ajustado)} · Pagado {formatearDecimal(r.pagado)}
                {' '}· <strong>Saldo {formatearDecimal(r.saldo_pendiente)}</strong>
              </div>
            ))}
          </div>
        )}
        <div className="overflow-x-auto">
          <Table data-testid="tabla-historial">
            <TableHeader>
              <TableRow>
                <TableHead>Fecha</TableHead><TableHead>Clase</TableHead><TableHead>Comprobante</TableHead>
                <TableHead numeric>Total original</TableHead><TableHead numeric>NC</TableHead><TableHead numeric>ND</TableHead>
                <TableHead numeric>Total ajustado</TableHead><TableHead numeric>Pagado</TableHead><TableHead numeric>Saldo</TableHead>
                <TableHead>Condición</TableHead><TableHead>Estado</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {datos?.comprobantes.length === 0 && (
                <TableRow><TableCell colSpan={11} className="py-6 text-center text-slate-500">Sin comprobantes registrados.</TableCell></TableRow>
              )}
              {datos?.comprobantes.map((c) => (
                <TableRow key={c.id}>
                  <TableCell className="font-mono whitespace-nowrap">{c.fecha_emision}</TableCell>
                  <TableCell>{c.clase === 'VENTA' ? 'Venta' : 'Compra'}</TableCell>
                  <TableCell className="font-mono whitespace-nowrap">{c.tipo_comprobante_codigo} {comprobanteTexto(c.serie, c.numero)}</TableCell>
                  <TableCell numeric className="whitespace-nowrap">{c.moneda_codigo} {formatearDecimal(c.total_original)}</TableCell>
                  <TableCell numeric data-col="nc">{importe(c.total_notas_credito, '−')}</TableCell>
                  <TableCell numeric data-col="nd">{importe(c.total_notas_debito, '+')}</TableCell>
                  <TableCell numeric data-col="ajustado" className="font-semibold">{importe(c.total_ajustado)}</TableCell>
                  <TableCell numeric data-col="pagado">{importe(c.pagado)}</TableCell>
                  <TableCell numeric data-col="saldo" className="font-bold">{importe(c.saldo_pendiente)}</TableCell>
                  <TableCell>{c.es_nota ? (c.tipo_comprobante_codigo === '07' ? 'Nota de crédito' : 'Nota de débito') : c.condicion_pago === 'CREDITO' ? `Crédito (${c.fecha_vencimiento})` : 'Contado'}</TableCell>
                  <TableCell>
                    {c.estado === 'CONFIRMADO' && c.estado_financiero
                      ? <EstadoFinancieroBadge estado={c.estado_financiero} />
                      : <Badge size="sm" variant={c.estado === 'ANULADO' ? 'destructive' : 'neutral'}>{c.estado}</Badge>}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </div>
    </Modal>
  )
}
