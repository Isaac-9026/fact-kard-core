import React, { useCallback, useEffect, useState, useMemo } from 'react'
import { diferirCarga } from '../../utils/efectos'
import {
  CalendarRange,
  Plus,
  RotateCcw,
  Lock,
  Unlock,
  Percent,
  AlertOctagon,
  CheckCircle2,
  AlertCircle,
  Calendar,
  Layers,
} from 'lucide-react'
import { useAuth } from '../../context/useAuth'
import {
  obtenerPeriodos,
  crearPeriodo,
  cerrarPeriodo,
  reabrirPeriodo,
  configurarIgvPeriodo,
  type Periodo,
  type MetodoIgv,
} from '../../api/periodos'
import { PageHeader } from '../../components/ui/page-header'
import { Button } from '../../components/ui/button'
import { Card, CardContent, KpiCard } from '../../components/ui/card'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '../../components/ui/table'
import { Badge } from '../../components/ui/badge'
import { Input } from '../../components/ui/input'
import { Select } from '../../components/ui/select'
import { Label } from '../../components/ui/label'
import { Modal } from '../../components/ui/modal'

/** Primer y último día del mes (AAAA-MM-DD); null si año o mes no son válidos. */
const rangoDelMes = (year: number, month: number) => {
  if (!year || !month) return null
  const mm = String(month).padStart(2, '0')
  const lastDate = new Date(year, month, 0).getDate()
  return { inicio: `${year}-${mm}-01`, fin: `${year}-${mm}-${String(lastDate).padStart(2, '0')}` }
}

export const PeriodosPage: React.FC = () => {
  const { empresaActiva, usuario } = useAuth()
  const esAdmin = Boolean(usuario?.es_admin_global || empresaActiva?.rol === 'ADMIN')

  const [periodos, setPeriodos] = useState<Periodo[]>([]);
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)

  // Modal: Crear Período
  const [modalCrearOpen, setModalCrearOpen] = useState(false)
  const [anio, setAnio] = useState(() => new Date().getFullYear())
  const [mes, setMes] = useState(() => new Date().getMonth() + 1)
  const [fechaInicio, setFechaInicio] = useState(() => rangoDelMes(anio, mes)?.inicio ?? '')
  const [fechaFin, setFechaFin] = useState(() => rangoDelMes(anio, mes)?.fin ?? '')
  const [guardandoPeriodo, setGuardandoPeriodo] = useState(false)

  // Modal: Configurar IGV
  const [modalIgvOpen, setModalIgvOpen] = useState(false)
  const [periodoIgv, setPeriodoIgv] = useState<Periodo | null>(null)
  const [metodoIgv, setMetodoIgv] = useState<MetodoIgv>('TOTAL')
  const [porcentajeProrrata, setPorcentajeProrrata] = useState('100.0000')
  const [guardandoIgv, setGuardandoIgv] = useState(false)

  // Modal: Reabrir Período
  const [modalReabrirOpen, setModalReabrirOpen] = useState(false)
  const [periodoReabrir, setPeriodoReabrir] = useState<Periodo | null>(null)
  const [motivoReapertura, setMotivoReapertura] = useState('')
  const [reabriendo, setReabriendo] = useState(false)

  // Fechas por defecto del modal de creación: se recalculan al cambiar año o mes
  // (antes en un efecto; ahora en el mismo evento, sin render adicional).
  const actualizarAnioMes = (nuevoAnio: number, nuevoMes: number) => {
    setAnio(nuevoAnio)
    setMes(nuevoMes)
    const rango = rangoDelMes(nuevoAnio, nuevoMes)
    if (rango) {
      setFechaInicio(rango.inicio)
      setFechaFin(rango.fin)
    }
  }

  const empresaId = empresaActiva?.id
  const cargarPeriodos = useCallback(async () => {
    if (!empresaId) return
    setLoading(true)
    setError(null)
    try {
      const data = await obtenerPeriodos()
      setPeriodos(data)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg || 'Error al obtener los períodos contables.')
    } finally {
      setLoading(false)
    }
  }, [empresaId])

  useEffect(() => {
    diferirCarga(cargarPeriodos)
  }, [cargarPeriodos, empresaActiva])

  // Handlers
  const handleCrearPeriodo = async (e: React.FormEvent) => {
    e.preventDefault()
    if (fechaFin < fechaInicio) {
      alert('La fecha de fin debe ser posterior o igual a la fecha de inicio.')
      return
    }
    setGuardandoPeriodo(true)
    setError(null)
    try {
      const nuevo = await crearPeriodo({
        anio: Number(anio),
        mes: Number(mes),
        fecha_inicio: fechaInicio,
        fecha_fin: fechaFin,
      })
      setPeriodos((prev) => [nuevo, ...prev])
      setModalCrearOpen(false)
      setSuccessMsg(`Período ${nuevo.anio}-${String(nuevo.mes).padStart(2, '0')} aperturado exitosamente.`)
      setTimeout(() => setSuccessMsg(null), 4000)
    } catch (err: unknown) {
      const respData = (err as { response?: { data?: Record<string, string[] | string> } })?.response?.data
      let msg = 'Error al crear el período contable.'
      if (respData) {
        msg = Object.entries(respData)
          .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(' ') : v}`)
          .join(' | ')
      }
      alert(msg)
    } finally {
      setGuardandoPeriodo(false)
    }
  }

  const abrirModalIgv = (p: Periodo) => {
    setPeriodoIgv(p)
    const existing = p.config_igv
    if (existing) {
      setMetodoIgv(existing.metodo)
      setPorcentajeProrrata(existing.porcentaje_recuperable)
    } else {
      setMetodoIgv('TOTAL')
      setPorcentajeProrrata('100.0000')
    }
    setModalIgvOpen(true)
  }

  const handleGuardarIgv = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!periodoIgv) return
    setGuardandoIgv(true)
    try {
      const payload = {
        metodo: metodoIgv,
        porcentaje_recuperable:
          metodoIgv === 'PRORRATA'
            ? porcentajeProrrata
            : metodoIgv === 'TOTAL'
            ? '100.0000'
            : '0.0000',
      }
      const res = await configurarIgvPeriodo(periodoIgv.id, payload)
      setPeriodos((prev) =>
        prev.map((item) => (item.id === periodoIgv.id ? { ...item, config_igv: res } : item))
      )
      setModalIgvOpen(false)
      setSuccessMsg(`Criterio de IGV configurado en ${res.metodo} (${res.porcentaje_recuperable}%).`)
      setTimeout(() => setSuccessMsg(null), 4000)
    } catch (err: unknown) {
      const respData = (err as { response?: { data?: Record<string, string[] | string> } })?.response?.data
      alert(respData?.detail || 'Error al guardar la configuración de IGV.')
    } finally {
      setGuardandoIgv(false)
    }
  }

  const abrirModalReapertura = (p: Periodo) => {
    setPeriodoReabrir(p)
    setMotivoReapertura('')
    setModalReabrirOpen(true)
  }

  const handleReabrir = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!periodoReabrir) return
    if (motivoReapertura.trim().length < 5) {
      alert('Debe ingresar un motivo detallado de reapertura (mínimo 5 caracteres).')
      return
    }
    setReabriendo(true)
    try {
      const res = await reabrirPeriodo(periodoReabrir.id, {
        motivo_reapertura: motivoReapertura.trim(),
      })
      await cargarPeriodos()
      setModalReabrirOpen(false)
      setSuccessMsg(
        `Período ${periodoReabrir.anio}-${String(periodoReabrir.mes).padStart(2, '0')} reabierto. ${res.periodos_desactualizados} período(s) posterior(es) marcado(s) como DESACTUALIZADO.`
      )
      setTimeout(() => setSuccessMsg(null), 6000)
    } catch (err: unknown) {
      const respData = (err as { response?: { data?: Record<string, string[] | string> } })?.response?.data
      alert(respData?.detail || 'Error al reabrir el período.')
    } finally {
      setReabriendo(false)
    }
  }

  const [cerrandoId, setCerrandoId] = useState<number | null>(null)

  const handleCerrarPeriodo = async (p: Periodo) => {
    if (!window.confirm(`¿Confirma el cierre del período fiscal ${p.anio}-${String(p.mes).padStart(2, '0')}?`)) {
      return
    }
    setCerrandoId(p.id)
    try {
      await cerrarPeriodo(p.id)
      await cargarPeriodos()
      setSuccessMsg(`Período ${p.anio}-${String(p.mes).padStart(2, '0')} cerrado exitosamente.`)
      setTimeout(() => setSuccessMsg(null), 4000)
    } catch (err: unknown) {
      const respData = (err as { response?: { data?: Record<string, string[] | string> } })?.response?.data
      alert(respData?.detail || 'Error al cerrar el período.')
    } finally {
      setCerrandoId(null)
    }
  }

  // Metrics
  const metricas = useMemo(() => {
    const abiertos = periodos.filter((p) => p.estado === 'ABIERTO').length
    const cerrados = periodos.filter((p) => p.estado === 'CERRADO').length
    const desactualizados = periodos.filter((p) => p.estado === 'DESACTUALIZADO').length
    return { total: periodos.length, abiertos, cerrados, desactualizados }
  }, [periodos])

  return (
    <div className="space-y-6">
      <PageHeader
        title="Períodos Contables y Configuración de IGV"
        description="Apertura mensual estricta, control de vigencia, asignación de crédito fiscal IGV y reapertura autorizada con invalidación en cascada."
        icon={<CalendarRange className="h-5 w-5" />}
        actions={
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={cargarPeriodos} isLoading={loading}>
              <RotateCcw className="h-4 w-4 mr-1.5" /> Actualizar
            </Button>
            <Button variant="primary" size="sm" onClick={() => setModalCrearOpen(true)}>
              <Plus className="h-4 w-4 mr-1.5" /> Nuevo Período
            </Button>
          </div>
        }
      />

      {/* KPI Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <KpiCard
          title="Total Períodos"
          value={metricas.total}
          subtitle="Registrados en el ejercicio"
          icon={<Layers className="h-4 w-4 text-slate-500" />}
        />
        <KpiCard
          title="Períodos Abiertos"
          value={metricas.abiertos}
          subtitle="Admiten comprobantes"
          icon={<Calendar className="h-4 w-4 text-emerald-600" />}
          badge={<Badge variant="success" dot size="sm">Operando</Badge>}
        />
        <KpiCard
          title="Períodos Cerrados"
          value={metricas.cerrados}
          subtitle="Bloqueados para edición"
          icon={<Lock className="h-4 w-4 text-slate-500" />}
          badge={<Badge variant="neutral" size="sm">Auditados</Badge>}
        />
        <KpiCard
          title="Desactualizados"
          value={metricas.desactualizados}
          subtitle="Exigen recálculo posterior"
          icon={<AlertOctagon className="h-4 w-4 text-rose-600" />}
          badge={metricas.desactualizados > 0 ? <Badge variant="destructive" size="sm">Atención</Badge> : undefined}
        />
      </div>

      {/* Alertas */}
      {error && (
        <div
          role="alert"
          className="flex items-start gap-2.5 rounded-lg border border-rose-200 bg-rose-50/90 p-3.5 text-xs text-rose-700 animate-in fade-in"
        >
          <AlertCircle className="h-4 w-4 shrink-0 text-rose-600 mt-0.5" />
          <span className="font-medium leading-relaxed">{error}</span>
        </div>
      )}

      {successMsg && (
        <div
          role="status"
          className="flex items-start gap-2.5 rounded-lg border border-emerald-200 bg-emerald-50/90 p-3.5 text-xs text-emerald-700 animate-in fade-in"
        >
          <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600 mt-0.5" />
          <span className="font-medium leading-relaxed">{successMsg}</span>
        </div>
      )}

      {/* Tabla de Períodos */}
      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-32">Período Fiscal</TableHead>
                <TableHead className="w-32">Fecha Inicio</TableHead>
                <TableHead className="w-32">Fecha Fin</TableHead>
                <TableHead className="w-40">Estado Contable</TableHead>
                <TableHead className="w-48">Criterio IGV</TableHead>
                <TableHead className="text-right">Acciones</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {periodos.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-center py-8 text-slate-400">
                    No hay períodos contables aperturados para esta empresa.
                  </TableCell>
                </TableRow>
              ) : (
                periodos.map((p) => {
                  const estadoBadge =
                    p.estado === 'ABIERTO' ? (
                      <Badge variant="success" dot>
                        ABIERTO
                      </Badge>
                    ) : p.estado === 'CERRADO' ? (
                      <Badge variant="neutral" className="gap-1">
                        <Lock className="h-3 w-3" /> CERRADO
                      </Badge>
                    ) : (
                      <Badge variant="destructive" className="gap-1">
                        <AlertOctagon className="h-3 w-3" /> DESACTUALIZADO
                      </Badge>
                    )

                  const metodo = p.config_igv?.metodo || 'TOTAL'
                  const porcentaje = p.config_igv?.porcentaje_recuperable || '100.0000'
                  const igvBadge =
                    metodo === 'TOTAL' ? (
                      <Badge variant="success" size="sm">
                        TOTAL ({porcentaje}%)
                      </Badge>
                    ) : metodo === 'PRORRATA' ? (
                      <Badge variant="warning" size="sm">
                        PRORRATA ({porcentaje}%)
                      </Badge>
                    ) : (
                      <Badge variant="neutral" size="sm">
                        NULO (0.0000%)
                      </Badge>
                    )

                  return (
                    <TableRow key={p.id}>
                      <TableCell numeric className="font-bold text-slate-900 text-sm">
                        {p.anio}-{String(p.mes).padStart(2, '0')}
                      </TableCell>
                      <TableCell numeric className="text-slate-600">
                        {p.fecha_inicio}
                      </TableCell>
                      <TableCell numeric className="text-slate-600">
                        {p.fecha_fin}
                      </TableCell>
                      <TableCell>{estadoBadge}</TableCell>
                      <TableCell>{igvBadge}</TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          {/* Configurar IGV */}
                          <Button
                            type="button"
                            size="xs"
                            variant="outline"
                            onClick={() => abrirModalIgv(p)}
                            title="Configurar Criterio de IGV"
                          >
                            <Percent className="h-3 w-3 mr-1" /> IGV
                          </Button>

                          {/* Cerrar período */}
                          {p.estado === 'ABIERTO' && (
                            <Button
                              type="button"
                              size="xs"
                              variant="secondary"
                              isLoading={cerrandoId === p.id}
                              onClick={() => handleCerrarPeriodo(p)}
                              title="Cerrar Período"
                            >
                              <Lock className="h-3 w-3 mr-1 text-slate-600" /> Cerrar
                            </Button>
                          )}

                          {/* Reabrir período (Solo ADMIN) */}
                          {p.estado === 'CERRADO' && (
                            <Button
                              type="button"
                              size="xs"
                              variant="outline"
                              disabled={!esAdmin}
                              onClick={() => abrirModalReapertura(p)}
                              title={
                                esAdmin
                                  ? 'Reabrir Período (Requiere motivo de auditoría)'
                                  : 'Solo Administradores pueden reabrir períodos'
                              }
                              className="text-amber-700 hover:bg-amber-50"
                            >
                              <Unlock className="h-3 w-3 mr-1" /> Reabrir
                            </Button>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  )
                })
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Modal: Crear Período */}
      {modalCrearOpen && (
        <Modal
          isOpen={modalCrearOpen}
          onClose={() => setModalCrearOpen(false)}
          title="Aperturar Nuevo Período Contable"
          description="Habilita el ingreso de comprobantes y movimientos para el mes indicado."
          icon={<CalendarRange className="h-5 w-5" />}
          footer={
            <div className="flex gap-2">
              <Button variant="secondary" onClick={() => setModalCrearOpen(false)}>
                Cancelar
              </Button>
              <Button variant="primary" onClick={handleCrearPeriodo} isLoading={guardandoPeriodo}>
                Aperturar Período
              </Button>
            </div>
          }
        >
          <form onSubmit={handleCrearPeriodo} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <Label required>Año Fiscal</Label>
                <Input
                  type="number"
                  min={2000}
                  max={2100}
                  value={anio}
                  onChange={(e) => actualizarAnioMes(Number(e.target.value), mes)}
                  required
                  className="font-mono tabular-nums"
                />
              </div>
              <div className="space-y-1.5">
                <Label required>Mes Calendario</Label>
                <Select value={mes} onChange={(e) => actualizarAnioMes(anio, Number(e.target.value))} required>
                  {[
                    'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
                    'Julio', 'Agosto', 'Setiembre', 'Octubre', 'Noviembre', 'Diciembre',
                  ].map((m, idx) => (
                    <option key={idx + 1} value={idx + 1}>
                      {String(idx + 1).padStart(2, '0')} — {m}
                    </option>
                  ))}
                </Select>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <Label required>Fecha Inicio</Label>
                <Input
                  type="date"
                  value={fechaInicio}
                  onChange={(e) => setFechaInicio(e.target.value)}
                  required
                  className="font-mono tabular-nums"
                />
              </div>
              <div className="space-y-1.5">
                <Label required>Fecha Fin</Label>
                <Input
                  type="date"
                  value={fechaFin}
                  onChange={(e) => setFechaFin(e.target.value)}
                  required
                  className="font-mono tabular-nums"
                />
              </div>
            </div>
          </form>
        </Modal>
      )}

      {/* Modal: Configurar IGV */}
      {modalIgvOpen && periodoIgv && (
        <Modal
          isOpen={modalIgvOpen}
          onClose={() => setModalIgvOpen(false)}
          title={`Criterio de Crédito Fiscal IGV — ${periodoIgv.anio}-${String(periodoIgv.mes).padStart(2, '0')}`}
          description="Define la proporción de IGV que será deducible en compras o costo directo de adquisición."
          icon={<Percent className="h-5 w-5" />}
          footer={
            <div className="flex gap-2">
              <Button variant="secondary" onClick={() => setModalIgvOpen(false)}>
                Cancelar
              </Button>
              <Button variant="primary" onClick={handleGuardarIgv} isLoading={guardandoIgv}>
                Guardar Configuración
              </Button>
            </div>
          }
        >
          <form onSubmit={handleGuardarIgv} className="space-y-4">
            <div className="space-y-1.5">
              <Label required>Método de Crédito Fiscal</Label>
              <Select value={metodoIgv} onChange={(e) => setMetodoIgv(e.target.value as MetodoIgv)}>
                <option value="TOTAL">TOTAL (100% Recuperable — Ventas Gravadas Exclusivas)</option>
                <option value="PRORRATA">PRORRATA (Porcentaje Mixto Gravado / No Gravado)</option>
                <option value="NULO">NULO (0% Recuperable — Todo al Costo/Gasto)</option>
              </Select>
            </div>

            {metodoIgv === 'PRORRATA' && (
              <div className="space-y-1.5">
                <Label required>Porcentaje Recuperable (%)</Label>
                <Input
                  type="number"
                  step="0.0001"
                  min="0.0001"
                  max="99.9999"
                  value={porcentajeProrrata}
                  onChange={(e) => setPorcentajeProrrata(e.target.value)}
                  className="font-mono tabular-nums"
                  required
                />
                <p className="text-[11px] text-slate-500">
                  El complemento (100% - %) se integrará automáticamente al costo unitario de adquisición.
                </p>
              </div>
            )}
          </form>
        </Modal>
      )}

      {/* Modal: Reabrir Período */}
      {modalReabrirOpen && periodoReabrir && (
        <Modal
          isOpen={modalReabrirOpen}
          onClose={() => setModalReabrirOpen(false)}
          title={`Reapertura de Período — ${periodoReabrir.anio}-${String(periodoReabrir.mes).padStart(2, '0')}`}
          description="Operación sensible reservada para rol Administrador con bitácora de auditoría."
          icon={<Unlock className="h-5 w-5 text-amber-600" />}
          footer={
            <div className="flex gap-2">
              <Button variant="secondary" onClick={() => setModalReabrirOpen(false)}>
                Cancelar
              </Button>
              <Button variant="destructive" onClick={handleReabrir} isLoading={reabriendo}>
                Confirmar Reapertura
              </Button>
            </div>
          }
        >
          <form onSubmit={handleReabrir} className="space-y-4">
            <div className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
              <AlertCircle className="h-4 w-4 shrink-0 text-amber-600 mt-0.5" />
              <div className="leading-relaxed">
                <strong>Advertencia de Invalidación en Cascada:</strong> Al reabrir este período, todos los períodos
                posteriores ya cerrados serán marcados automáticamente como{' '}
                <strong className="text-rose-700">DESACTUALIZADOS</strong> y deberán someterse a recálculo antes de poder
                generar reportes definitivos del Formato 13.1.
              </div>
            </div>

            <div className="space-y-1.5">
              <Label required>Motivo Detallado de Reapertura (mín. 5 caracteres)</Label>
              <textarea
                rows={3}
                required
                value={motivoReapertura}
                onChange={(e) => setMotivoReapertura(e.target.value)}
                placeholder="Ej. Inclusión de Factura extemporánea F001-00045 remitida por proveedor con fecha atrasada."
                className="w-full rounded-md border border-slate-200 bg-white p-2.5 text-xs text-slate-900 shadow-xs focus:outline-none focus:ring-2 focus:ring-slate-900 focus:border-transparent"
              />
            </div>
          </form>
        </Modal>
      )}
    </div>
  )
}

export default PeriodosPage
