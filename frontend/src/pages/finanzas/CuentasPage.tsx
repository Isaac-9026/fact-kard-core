/**
 * Bloque 16 — Cuentas por cobrar (ventas) y Cuentas por pagar (compras).
 * Saldos calculados por el backend (total ± notas − pagos vigentes); nunca se guardan.
 */
import { useCallback, useEffect, useState } from 'react'
import { HandCoins, Search, Wallet, Eye } from 'lucide-react'
import { obtenerDocumento, type Documento } from '../../api/documentos'
import { obtenerCuentas, type FiltrosCuentas, type RespuestaCuentas } from '../../api/finanzas'
import { getTerceros, type Tercero } from '../../api/inventario'
import { obtenerPeriodos, type Periodo } from '../../api/periodos'
import { useAuth } from '../../context/useAuth'
import { PageHeader } from '../../components/ui/page-header'
import { Card, CardContent } from '../../components/ui/card'
import { Button } from '../../components/ui/button'
import { Label } from '../../components/ui/label'
import { Select } from '../../components/ui/select'
import { Modal } from '../../components/ui/modal'
import { AlertaFormulario } from '../../components/ui/alerta-formulario'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../components/ui/table'
import { EstadoFinancieroBadge, PagosDocumento } from '../../components/finanzas/PagosDocumento'
import { formatearDecimal } from '../../utils/decimal'
import { mensajesDeErrorApi } from '../../utils/errores'
import { diferirCarga } from '../../utils/efectos'
import { comprobanteTexto, numeroComprobante } from '../../utils/finanzas'

interface Props { tipo: 'cobrar' | 'pagar' }

export function CuentasPage({ tipo }: Props) {
  const { empresaActiva, usuario } = useAuth()
  const esAdmin = Boolean(usuario?.es_admin_global || empresaActiva?.rol === 'ADMIN')
  const cobrar = tipo === 'cobrar'
  const rol = cobrar ? 'Cliente' : 'Proveedor'

  const [filtros, setFiltros] = useState<FiltrosCuentas>({ estado: 'ABIERTOS', condicion: 'CREDITO' })
  const [datos, setDatos] = useState<RespuestaCuentas | null>(null)
  const [terceros, setTerceros] = useState<Tercero[]>([])
  const [periodos, setPeriodos] = useState<Periodo[]>([])
  const [cargando, setCargando] = useState(false)
  const [error, setError] = useState<string[] | null>(null)
  const [detalle, setDetalle] = useState<Documento | null>(null)

  const cargar = useCallback(async () => {
    if (!empresaActiva?.id) return
    setCargando(true)
    setError(null)
    try {
      setDatos(await obtenerCuentas(tipo, filtros))
    } catch (e) {
      setError(mensajesDeErrorApi(e, 'No se pudieron cargar las cuentas.'))
    } finally {
      setCargando(false)
    }
  }, [empresaActiva?.id, tipo, filtros])

  useEffect(() => { diferirCarga(cargar) }, [cargar])

  useEffect(() => {
    if (!empresaActiva?.id) return
    getTerceros({ tipo: cobrar ? 'cliente' : 'proveedor' }).then(setTerceros).catch(() => setTerceros([]))
    obtenerPeriodos().then(setPeriodos).catch(() => setPeriodos([]))
  }, [empresaActiva?.id, cobrar])

  const set = (cambios: Partial<FiltrosCuentas>) => setFiltros((f) => ({ ...f, ...cambios }))
  const abrir = async (id: number) => {
    try {
      setDetalle(await obtenerDocumento(id))
    } catch (e) {
      setError(mensajesDeErrorApi(e, 'No se pudo abrir el comprobante.'))
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title={cobrar ? 'Cuentas por cobrar' : 'Cuentas por pagar'}
        description={cobrar
          ? 'Ventas confirmadas con saldo: total, notas, cobros vigentes y vencimientos.'
          : 'Compras confirmadas con saldo: total, notas, pagos vigentes y vencimientos.'}
        icon={cobrar ? <HandCoins className="h-5 w-5" /> : <Wallet className="h-5 w-5" />}
      />

      <Card>
        <CardContent className="grid grid-cols-1 gap-3 pt-4 sm:grid-cols-2 lg:grid-cols-5">
          <div className="space-y-1">
            <Label htmlFor="f-tercero">{rol}</Label>
            <Select id="f-tercero" value={filtros.tercero ?? ''} onChange={(e) => set({ tercero: e.target.value || undefined })}>
              <option value="">Todos</option>
              {terceros.map((t) => <option key={t.id} value={t.id}>{t.numero_documento} — {t.razon_social}</option>)}
            </Select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="f-periodo">Período</Label>
            <Select id="f-periodo" value={filtros.periodo ?? ''} onChange={(e) => set({ periodo: e.target.value || undefined })}>
              <option value="">Todos</option>
              {periodos.map((p) => <option key={p.id} value={p.id}>{p.anio}-{String(p.mes).padStart(2, '0')}</option>)}
            </Select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="f-estado">Estado</Label>
            <Select id="f-estado" value={filtros.estado ?? ''} onChange={(e) => set({ estado: e.target.value as FiltrosCuentas['estado'] })}>
              <option value="ABIERTOS">Con saldo (pendientes, parciales, vencidos)</option>
              <option value="PENDIENTE">Pendientes</option>
              <option value="PARCIAL">Parciales</option>
              <option value="VENCIDO">Vencidos</option>
              <option value="PAGADO">Pagados</option>
              <option value="">Todos</option>
            </Select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="f-condicion">Condición</Label>
            <Select id="f-condicion" value={filtros.condicion ?? 'CREDITO'} onChange={(e) => set({ condicion: e.target.value as FiltrosCuentas['condicion'] })}>
              <option value="CREDITO">Crédito</option>
              <option value="CONTADO">Contado</option>
              <option value="TODAS">Todas</option>
            </Select>
          </div>
          <div className="flex items-end">
            <Button variant="secondary" className="w-full" onClick={cargar} isLoading={cargando}>
              <Search className="h-4 w-4" /> Actualizar
            </Button>
          </div>
        </CardContent>
      </Card>

      {error && <AlertaFormulario titulo="No se pudo completar la operación" mensajes={error} />}

      {datos && Object.keys(datos.totales).length > 0 && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2" data-testid="totales-cuentas">
          {Object.entries(datos.totales).map(([moneda, t]) => (
            <Card key={moneda}>
              <CardContent className="grid grid-cols-2 gap-2 pt-4 text-xs font-mono tabular-nums sm:grid-cols-4">
                <div><span className="block font-sans text-slate-400">Total {moneda}</span>{formatearDecimal(t.total_ajustado)}</div>
                <div><span className="block font-sans text-slate-400">{cobrar ? 'Cobrado' : 'Pagado'}</span>{formatearDecimal(t.pagado)}</div>
                <div><span className="block font-sans text-slate-400">Saldo</span><strong className="text-slate-900">{formatearDecimal(t.saldo_pendiente)}</strong></div>
                <div><span className="block font-sans text-slate-400">Vencido</span><span className="text-rose-700">{formatearDecimal(t.monto_vencido)}</span></div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <Card>
        <CardContent className="pt-4">
          <p className="mb-2 text-xs text-slate-500">
            {datos ? `${datos.cantidad} comprobante(s) · corte al ${datos.fecha_corte}` : cargando ? 'Cargando…' : ''}
          </p>
          <div className="overflow-x-auto">
            <Table data-testid="tabla-cuentas">
              <TableHeader>
                <TableRow>
                  <TableHead>Comprobante</TableHead>
                  <TableHead>{rol}</TableHead>
                  <TableHead>Emisión</TableHead>
                  <TableHead>Vence</TableHead>
                  <TableHead numeric>Total</TableHead>
                  <TableHead numeric>{cobrar ? 'Cobrado' : 'Pagado'}</TableHead>
                  <TableHead numeric>Saldo</TableHead>
                  <TableHead>Estado</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {datos?.resultados.length === 0 && (
                  <TableRow><TableCell colSpan={9} className="py-8 text-center text-slate-500">Sin comprobantes para los filtros elegidos.</TableCell></TableRow>
                )}
                {datos?.resultados.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell className="font-mono whitespace-nowrap">{r.tipo_comprobante_codigo} {comprobanteTexto(r.serie, r.numero || r.numero_normalizado)}</TableCell>
                    <TableCell className="min-w-[180px]">
                      <span className="block font-semibold text-slate-800">{r.tercero_razon_social || (cobrar ? 'Clientes varios' : '—')}</span>
                      <span className="font-mono text-[11px] text-slate-500">{r.tercero_numero_documento}</span>
                    </TableCell>
                    <TableCell className="font-mono whitespace-nowrap">{r.fecha_emision}</TableCell>
                    <TableCell className="font-mono whitespace-nowrap">{r.fecha_vencimiento || '—'}</TableCell>
                    <TableCell numeric className="whitespace-nowrap">{r.moneda_codigo} {formatearDecimal(r.total_ajustado)}</TableCell>
                    <TableCell numeric>{formatearDecimal(r.pagado)}</TableCell>
                    <TableCell numeric className="font-bold">{formatearDecimal(r.saldo_pendiente)}</TableCell>
                    <TableCell><EstadoFinancieroBadge estado={r.estado_financiero} /></TableCell>
                    <TableCell>
                      <Button size="xs" variant="ghost" onClick={() => abrir(r.id)} title="Ver pagos">
                        <Eye className="h-3.5 w-3.5" /> {esAdmin ? (cobrar ? 'Cobrar' : 'Pagar') : 'Ver'}
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      {detalle && (
        <Modal
          isOpen
          onClose={() => setDetalle(null)}
          maxWidth="4xl"
          icon={cobrar ? <HandCoins className="h-5 w-5" /> : <Wallet className="h-5 w-5" />}
          title={`${numeroComprobante(detalle)}`}
          description={`${detalle.tercero_razon_social ?? ''} · Emisión ${detalle.fecha_emision}`}
          footer={<Button variant="secondary" onClick={() => setDetalle(null)}>Cerrar</Button>}
        >
          <PagosDocumento
            documento={detalle}
            esAdmin={esAdmin}
            onActualizado={async () => {
              setDetalle(await obtenerDocumento(detalle.id))
              await cargar()
            }}
          />
        </Modal>
      )}
    </div>
  )
}
