import React, { useCallback, useEffect, useMemo, useState } from 'react'
import axios from 'axios'
import {
  AlertTriangle,
  RotateCcw,
  CheckCircle2,
  AlertCircle,
  Lock,
  History,
  Eye,
  Play,
  Check,
  X,
  Search,
} from 'lucide-react'
import {
  obtenerIncidencias,
  obtenerIncidenciasPaginadas,
  obtenerRecalculosPaginados,
  resolverIncidencia,
  ejecutarRecalculo,
  type Incidencia,
  type Recalculo,
} from '../../api/kardex'
import { getProductos, type Producto } from '../../api/inventario'
import { useAuth } from '../../context/useAuth'
import { PageHeader } from '../../components/ui/page-header'
import { Button } from '../../components/ui/button'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../../components/ui/card'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '../../components/ui/table'
import { Badge } from '../../components/ui/badge'
import { Input } from '../../components/ui/input'
import { Select } from '../../components/ui/select'
import { Label } from '../../components/ui/label'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../../components/ui/tabs'
import { Modal } from '../../components/ui/modal'
import { fechaCalendarioLocal } from '../../utils/date'
import { diferirCarga } from '../../utils/efectos'
import { Paginacion } from '../../components/ui/paginacion'
import {
  PAGE_SIZE_DEFECTO, claveConsulta, irAPagina, paginaVigente, paramsPaginacion, type EstadoPagina,
} from '../../utils/paginacion'
import { formatearDecimal, restar } from '../../utils/decimal'

const formatearFechaHora = (isoString?: string | null): string => {
  if (!isoString) return '—'
  try {
    const d = new Date(isoString)
    if (isNaN(d.getTime())) return isoString
    const dia = String(d.getDate()).padStart(2, '0')
    const mes = String(d.getMonth() + 1).padStart(2, '0')
    const anio = d.getFullYear()
    let horas = d.getHours()
    const minutos = String(d.getMinutes()).padStart(2, '0')
    const segundos = String(d.getSeconds()).padStart(2, '0')
    const ampm = horas >= 12 ? 'pm.' : 'am.'
    horas = horas % 12 || 12
    const horasStr = String(horas).padStart(2, '0')
    return `${dia}/${mes}/${anio}, ${horasStr}:${minutos}:${segundos} ${ampm}`
  } catch {
    return isoString
  }
}

export const IncidenciasPage: React.FC = () => {
  const { empresaActiva, usuario } = useAuth()
  const [tab, setTab] = useState<'incidencias' | 'recalculos'>('incidencias')
  const [incidencias, setIncidencias] = useState<Incidencia[]>([])
  const [todasIncidencias, setTodasIncidencias] = useState<Incidencia[]>([])
  const [recalculos, setRecalculos] = useState<Recalculo[]>([])
  const [productos, setProductos] = useState<Producto[]>([])

  // Filtros de la bandeja
  const [filtroEstadoIncidencia, setFiltroEstadoIncidencia] = useState<'TODAS' | 'BLOQUEANTES' | 'PENDIENTES' | 'RESUELTAS' | 'DESCARTADAS'>('TODAS')
  const [busquedaIncidencia, setBusquedaIncidencia] = useState('')

  // Bloque 7: paginación en el servidor; la página vuelve a 1 al cambiar de empresa.
  const [totalIncidencias, setTotalIncidencias] = useState(0)
  const [totalRecalculos, setTotalRecalculos] = useState(0)
  const [pagIncidencias, setPagIncidencias] = useState<EstadoPagina>({ clave: '', page: 1 })
  const [pagRecalculos, setPagRecalculos] = useState<EstadoPagina>({ clave: '', page: 1 })
  const [loading, setLoading] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  // Formulario de Recálculo Manual
  const [recalculoProducto, setRecalculoProducto] = useState<string>('')
  const [recalculoFecha, setRecalculoFecha] = useState<string>(() => fechaCalendarioLocal())
  const [ejecutandoRecalculo, setEjecutandoRecalculo] = useState<boolean>(false)

  // Modal de Detalle de Recálculo
  const [recalculoSeleccionado, setRecalculoSeleccionado] = useState<Recalculo | null>(null)

  const esAdmin = Boolean(usuario?.es_admin_global || empresaActiva?.rol === 'ADMIN')

  const claveEmpresa = claveConsulta(empresaActiva?.id)
  const pageIncidencias = paginaVigente(pagIncidencias, claveEmpresa)
  const pageRecalculos = paginaVigente(pagRecalculos, claveEmpresa)

  const cargar = useCallback(async () => {
    if (!empresaActiva) return
    setLoading(true)
    try {
      const [listaIncidencias, listaRecalculos, todasInc] = await Promise.all([
        obtenerIncidenciasPaginadas(paramsPaginacion(pageIncidencias)),
        obtenerRecalculosPaginados(paramsPaginacion(pageRecalculos)),
        obtenerIncidencias().catch(() => [] as Incidencia[]),
      ])
      setIncidencias(listaIncidencias.results)
      setTotalIncidencias(listaIncidencias.count)
      setRecalculos(listaRecalculos.results)
      setTotalRecalculos(listaRecalculos.count)
      setTodasIncidencias(todasInc)
    } catch {
      setError('No se pudo cargar la información del motor Kardex.')
    } finally {
      setLoading(false)
    }
  }, [empresaActiva, pageIncidencias, pageRecalculos])

  useEffect(() => {
    diferirCarga(cargar)
  }, [cargar])

  // Catálogo de productos para el formulario de recálculo (no depende de la página).
  useEffect(() => {
    if (!empresaActiva) return
    let ignorar = false
    getProductos()
      .then((lista) => {
        if (!ignorar) setProductos(lista)
      })
      .catch(() => {
        if (!ignorar) setError('No se pudo cargar la información del motor Kardex.')
      })
    return () => {
      ignorar = true
    }
  }, [empresaActiva])

  const cambiarEstado = async (id: number, nuevoEstado: 'RESUELTA' | 'DESCARTADA') => {
    setError(null)
    setSuccess(null)
    try {
      await resolverIncidencia(id, nuevoEstado)
      setSuccess(`Incidencia #${id} marcada como ${nuevoEstado}.`)
      await cargar()
    } catch {
      setError('No se pudo actualizar el estado de la incidencia.')
    }
  }

  const handleEjecutarRecalculo = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!recalculoProducto || !recalculoFecha) {
      setError('Debe seleccionar el producto y la fecha desde la cual recalcular.')
      return
    }
    setError(null)
    setSuccess(null)
    setEjecutandoRecalculo(true)
    try {
      await ejecutarRecalculo(Number(recalculoProducto), recalculoFecha)
      setSuccess('Recálculo cronológico ejecutado exitosamente.')
      await cargar()
    } catch (err: unknown) {
      if (axios.isAxiosError(err) && err.response?.data) {
        const msg = typeof err.response.data === 'string' ? err.response.data : JSON.stringify(err.response.data)
        setError(`Error al ejecutar recálculo: ${msg}`)
      } else {
        setError('Ocurrió un error al ejecutar el recálculo.')
      }
    } finally {
      setEjecutandoRecalculo(false)
    }
  }

  const getNombreProducto = (id: number) => {
    const prod = productos.find((p) => p.id === id)
    return prod ? `${prod.codigo_interno} — ${prod.descripcion}` : `Producto #${id}`
  }

  // Métricas ejecutivas de salud contable
  const metricas = useMemo(() => {
    const fuente = todasIncidencias.length > 0 ? todasIncidencias : incidencias
    const bloqueantes = fuente.filter((i) => i.estado === 'PENDIENTE' && i.bloquea_cierre).length
    const pendientes = fuente.filter((i) => i.estado === 'PENDIENTE').length
    const resueltas = fuente.filter((i) => i.estado === 'RESUELTA').length
    const descartadas = fuente.filter((i) => i.estado === 'DESCARTADA').length
    const ultimoRecalculo = recalculos[0] ?? null
    return { bloqueantes, pendientes, resueltas, descartadas, ultimoRecalculo }
  }, [todasIncidencias, incidencias, recalculos])

  // Filtrado de incidencias
  const tieneFiltroActivo = filtroEstadoIncidencia !== 'TODAS' || busquedaIncidencia.trim().length > 0
  const listaIncidenciasAMostrar = useMemo(() => {
    if (!tieneFiltroActivo) {
      return incidencias
    }
    const fuente = todasIncidencias.length > 0 ? todasIncidencias : incidencias
    return fuente.filter((inc) => {
      if (filtroEstadoIncidencia === 'BLOQUEANTES' && (!inc.bloquea_cierre || inc.estado !== 'PENDIENTE')) return false
      if (filtroEstadoIncidencia === 'PENDIENTES' && inc.estado !== 'PENDIENTE') return false
      if (filtroEstadoIncidencia === 'RESUELTAS' && inc.estado !== 'RESUELTA') return false
      if (filtroEstadoIncidencia === 'DESCARTADAS' && inc.estado !== 'DESCARTADA') return false
      if (busquedaIncidencia.trim()) {
        const q = busquedaIncidencia.toLowerCase()
        const coincideTipo = inc.tipo.toLowerCase().includes(q)
        const coincideDesc = inc.descripcion.toLowerCase().includes(q)
        if (!coincideTipo && !coincideDesc) return false
      }
      return true
    })
  }, [tieneFiltroActivo, filtroEstadoIncidencia, busquedaIncidencia, todasIncidencias, incidencias])

  return (
    <div className="space-y-6">
      <PageHeader
        title="Incidencias y Recálculos de Kardex"
        description={`Supervisión de inconsistencias contables, validación de bloqueo de cierres y motor de recálculo cronológico para ${
          empresaActiva?.razon_social ?? 'la empresa activa'
        }.`}
        icon={<AlertTriangle className="h-5 w-5" />}
        badge={
          <Badge variant="info">Control de Calidad • Fase 7</Badge>
        }
        actions={
          <Button variant="outline" size="sm" onClick={() => void cargar()} isLoading={loading}>
            <RotateCcw className="h-4 w-4 mr-1.5" /> Actualizar
          </Button>
        }
      />

      {error && (
        <div
          role="alert"
          className="flex items-start gap-2.5 rounded-lg border border-rose-200 bg-rose-50/90 p-3.5 text-xs text-rose-700 animate-in fade-in"
        >
          <AlertCircle className="h-4 w-4 shrink-0 text-rose-600 mt-0.5" />
          <span className="font-medium leading-relaxed">{error}</span>
        </div>
      )}

      {success && (
        <div
          role="status"
          className="flex items-start gap-2.5 rounded-lg border border-emerald-200 bg-emerald-50/90 p-3.5 text-xs text-emerald-700 animate-in fade-in"
        >
          <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600 mt-0.5" />
          <span className="font-medium leading-relaxed">{success}</span>
        </div>
      )}

      {/* Tarjetas KPI de Estado Contable */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5">
        {/* KPI 1: Salud de Cierre */}
        <Card className="p-4 rounded-xl border border-slate-200/90 shadow-2xs bg-white">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
              Control Pre-Cierre
            </span>
            <span
              className={`h-8 w-8 rounded-lg flex items-center justify-center ${
                metricas.bloqueantes > 0
                  ? 'bg-rose-50 text-rose-600 border border-rose-100'
                  : 'bg-emerald-50 text-emerald-600 border border-emerald-100'
              }`}
            >
              {metricas.bloqueantes > 0 ? <Lock className="h-4 w-4" /> : <CheckCircle2 className="h-4 w-4" />}
            </span>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span
              className={`text-2xl font-bold font-mono ${
                metricas.bloqueantes > 0 ? 'text-rose-700' : 'text-emerald-700'
              }`}
            >
              {metricas.bloqueantes}
            </span>
            <span className="text-xs font-medium text-slate-600">
              {metricas.bloqueantes === 1 ? 'bloqueo crítico' : 'bloqueos críticos'}
            </span>
          </div>
          <p className="mt-1 text-[11px] text-slate-400">
            {metricas.bloqueantes > 0
              ? 'Impiden el cierre oficial del período'
              : 'Kardex habilitado para cierre contable'}
          </p>
        </Card>

        {/* KPI 2: Incidencias Pendientes */}
        <Card className="p-4 rounded-xl border border-slate-200/90 shadow-2xs bg-white">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
              Pendientes de Revisión
            </span>
            <span className="h-8 w-8 rounded-lg bg-amber-50 text-amber-600 border border-amber-100 flex items-center justify-center">
              <AlertTriangle className="h-4 w-4" />
            </span>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-slate-900">
              {metricas.pendientes}
            </span>
            <span className="text-xs font-medium text-slate-600">
              {metricas.pendientes === 1 ? 'observación activa' : 'observaciones activas'}
            </span>
          </div>
          <p className="mt-1 text-[11px] text-slate-400">
            {metricas.pendientes > 0 ? 'Por resolver o descartar por admin' : 'Sin inconsistencias pendientes'}
          </p>
        </Card>

        {/* KPI 3: Subsanadas / Resueltas */}
        <Card className="p-4 rounded-xl border border-slate-200/90 shadow-2xs bg-white">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
              Historial de Subsanación
            </span>
            <span className="h-8 w-8 rounded-lg bg-slate-50 text-slate-600 border border-slate-200 flex items-center justify-center">
              <Check className="h-4 w-4" />
            </span>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-slate-900">
              {metricas.resueltas}
            </span>
            <span className="text-xs font-medium text-slate-600">
              resueltas
            </span>
            {metricas.descartadas > 0 && (
              <span className="text-xs font-mono text-slate-400">
                ({metricas.descartadas} descartadas)
              </span>
            )}
          </div>
          <p className="mt-1 text-[11px] text-slate-400">
            Trazabilidad con usuario y timestamp
          </p>
        </Card>

        {/* KPI 4: Último Recálculo */}
        <Card className="p-4 rounded-xl border border-slate-200/90 shadow-2xs bg-white">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">
              Último Recálculo CPP
            </span>
            <span className="h-8 w-8 rounded-lg bg-indigo-50 text-indigo-600 border border-indigo-100 flex items-center justify-center">
              <History className="h-4 w-4" />
            </span>
          </div>
          <div className="mt-2 flex items-baseline gap-2 truncate">
            {metricas.ultimoRecalculo ? (
              <span className="text-base font-bold font-mono text-slate-900 truncate">
                #{metricas.ultimoRecalculo.id} · {metricas.ultimoRecalculo.fecha_desde}
              </span>
            ) : (
              <span className="text-sm font-semibold text-slate-500">Sin recálculos</span>
            )}
          </div>
          <p className="mt-1 text-[11px] text-slate-400 truncate">
            {metricas.ultimoRecalculo
              ? `${metricas.ultimoRecalculo.detalles?.length || 0} movs reevaluados · ${metricas.ultimoRecalculo.estado}`
              : 'CPP cronológico vigente en Kardex'}
          </p>
        </Card>
      </div>

      {/* Tabs */}
      <Tabs value={tab} onValueChange={(val) => setTab(val as 'incidencias' | 'recalculos')}>
        <TabsList>
          <TabsTrigger value="incidencias" icon={<AlertTriangle className="h-3.5 w-3.5" />}>
            Incidencias Contables ({totalIncidencias})
          </TabsTrigger>
          <TabsTrigger value="recalculos" icon={<History className="h-3.5 w-3.5" />}>
            Historial de Recálculos Cronológicos ({totalRecalculos})
          </TabsTrigger>
        </TabsList>

        {/* TAB 1: INCIDENCIAS */}
        <TabsContent value="incidencias" className="space-y-4">
          <Card className="rounded-xl border border-slate-200/90 shadow-2xs bg-white overflow-hidden">
            <CardHeader className="border-b border-slate-100 pb-3">
              <CardTitle>Bandeja de Incidencias Contables</CardTitle>
              <CardDescription>
                Las inconsistencias con bloqueo de cierre impiden legalmente el cierre mensual hasta ser subsanadas o descartadas.
              </CardDescription>
            </CardHeader>

            {/* Barra de Filtros de Incidencias */}
            <div className="p-3 px-4 border-b border-slate-100 bg-slate-50/50 flex flex-col sm:flex-row items-center justify-between gap-3">
              <div className="flex flex-wrap items-center gap-1.5 w-full sm:w-auto">
                <button
                  type="button"
                  onClick={() => setFiltroEstadoIncidencia('TODAS')}
                  className={`px-2.5 py-1 text-xs font-medium rounded-lg transition-colors cursor-pointer ${
                    filtroEstadoIncidencia === 'TODAS'
                      ? 'bg-slate-900 text-white shadow-2xs'
                      : 'bg-white border border-slate-200 text-slate-600 hover:bg-slate-100'
                  }`}
                >
                  Todas ({totalIncidencias})
                </button>
                <button
                  type="button"
                  onClick={() => setFiltroEstadoIncidencia('BLOQUEANTES')}
                  className={`px-2.5 py-1 text-xs font-medium rounded-lg transition-colors flex items-center gap-1 cursor-pointer ${
                    filtroEstadoIncidencia === 'BLOQUEANTES'
                      ? 'bg-rose-700 text-white shadow-2xs'
                      : 'bg-white border border-rose-200 text-rose-700 hover:bg-rose-50'
                  }`}
                >
                  <Lock className="h-3 w-3" /> Bloqueantes ({metricas.bloqueantes})
                </button>
                <button
                  type="button"
                  onClick={() => setFiltroEstadoIncidencia('PENDIENTES')}
                  className={`px-2.5 py-1 text-xs font-medium rounded-lg transition-colors cursor-pointer ${
                    filtroEstadoIncidencia === 'PENDIENTES'
                      ? 'bg-amber-600 text-white shadow-2xs'
                      : 'bg-white border border-slate-200 text-slate-600 hover:bg-slate-100'
                  }`}
                >
                  Pendientes ({metricas.pendientes})
                </button>
                <button
                  type="button"
                  onClick={() => setFiltroEstadoIncidencia('RESUELTAS')}
                  className={`px-2.5 py-1 text-xs font-medium rounded-lg transition-colors cursor-pointer ${
                    filtroEstadoIncidencia === 'RESUELTAS'
                      ? 'bg-emerald-700 text-white shadow-2xs'
                      : 'bg-white border border-slate-200 text-slate-600 hover:bg-slate-100'
                  }`}
                >
                  Resueltas ({metricas.resueltas})
                </button>
                <button
                  type="button"
                  onClick={() => setFiltroEstadoIncidencia('DESCARTADAS')}
                  className={`px-2.5 py-1 text-xs font-medium rounded-lg transition-colors cursor-pointer ${
                    filtroEstadoIncidencia === 'DESCARTADAS'
                      ? 'bg-slate-700 text-white shadow-2xs'
                      : 'bg-white border border-slate-200 text-slate-600 hover:bg-slate-100'
                  }`}
                >
                  Descartadas ({metricas.descartadas})
                </button>
              </div>

              <div className="w-full sm:w-64">
                <Input
                  placeholder="Buscar tipo o descripción..."
                  value={busquedaIncidencia}
                  onChange={(e) => setBusquedaIncidencia(e.target.value)}
                  leftIcon={<Search className="h-3.5 w-3.5 text-slate-400" />}
                  className="h-8 text-xs"
                />
              </div>
            </div>

            <CardContent className="p-0">
              {loading ? (
                <div className="flex items-center justify-center p-12 text-slate-400 text-xs">
                  Cargando incidencias...
                </div>
              ) : listaIncidenciasAMostrar.length === 0 ? (
                <div className="flex flex-col items-center justify-center p-12 text-center">
                  <div className="h-10 w-10 rounded-full bg-emerald-50 text-emerald-600 flex items-center justify-center mb-2">
                    <CheckCircle2 className="h-5 w-5" />
                  </div>
                  <p className="font-bold text-slate-800 text-sm">
                    {tieneFiltroActivo ? 'No se encontraron incidencias con los filtros aplicados' : 'No hay incidencias registradas'}
                  </p>
                  <p className="text-xs text-slate-500 max-w-sm mt-0.5">
                    {tieneFiltroActivo
                      ? 'Pruebe seleccionando otra pestaña de estado o limpiando el campo de búsqueda.'
                      : 'El inventario y los movimientos contables no presentan inconsistencias ni descalces.'}
                  </p>
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-44">Tipo</TableHead>
                      <TableHead className="w-28 text-center">Severidad</TableHead>
                      <TableHead>Descripción de la Inconsistencia</TableHead>
                      <TableHead className="w-32 text-center">Bloquea Cierre</TableHead>
                      <TableHead className="w-28 text-center">Estado</TableHead>
                      <TableHead className="w-36 text-right">Acciones</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {listaIncidenciasAMostrar.map((i) => {
                      const sevVariant =
                        i.severidad === 'CRITICA' || i.severidad === 'ERROR'
                          ? 'destructive'
                          : i.severidad === 'ADVERTENCIA'
                          ? 'warning'
                          : 'info'

                      return (
                        <TableRow key={i.id} className="hover:bg-slate-50/70 transition-colors">
                          <TableCell>
                            <code className="font-mono text-xs font-bold text-slate-900 bg-slate-100 px-2 py-0.5 rounded border border-slate-200/60">
                              {i.tipo}
                            </code>
                          </TableCell>
                          <TableCell className="text-center">
                            <Badge variant={sevVariant} size="sm">
                              {i.severidad}
                            </Badge>
                          </TableCell>
                          <TableCell>
                            <div className="font-medium text-slate-800 text-xs leading-relaxed">{i.descripcion}</div>
                            <div className="text-[10px] text-slate-400 mt-0.5 font-mono">
                              Detectado: {formatearFechaHora(i.detectado_en)}
                            </div>
                          </TableCell>
                          <TableCell className="text-center">
                            {i.bloquea_cierre ? (
                              <Badge variant="destructive" className="gap-1 font-bold">
                                <Lock className="h-3 w-3" /> BLOQUEA
                              </Badge>
                            ) : (
                              <Badge variant="neutral">No</Badge>
                            )}
                          </TableCell>
                          <TableCell className="text-center">
                            <Badge
                              variant={
                                i.estado === 'RESUELTA'
                                  ? 'success'
                                  : i.estado === 'DESCARTADA'
                                  ? 'neutral'
                                  : 'warning'
                              }
                              dot
                            >
                              {i.estado}
                            </Badge>
                          </TableCell>
                          <TableCell className="text-right">
                            {esAdmin && i.estado === 'PENDIENTE' ? (
                              <div className="flex items-center justify-end gap-1.5">
                                <Button
                                  type="button"
                                  size="xs"
                                  variant="ghost"
                                  onClick={() => void cambiarEstado(i.id, 'RESUELTA')}
                                  className="h-7 px-2.5 bg-emerald-50 hover:bg-emerald-600 text-emerald-700 hover:text-white border border-emerald-200/90 rounded-md transition-all font-semibold shadow-2xs"
                                >
                                  <Check className="h-3 w-3 mr-1" /> Resolver
                                </Button>
                                <Button
                                  type="button"
                                  size="xs"
                                  variant="ghost"
                                  onClick={() => void cambiarEstado(i.id, 'DESCARTADA')}
                                  className="h-7 px-2 hover:bg-slate-100 text-slate-500 hover:text-slate-800 rounded-md transition-colors"
                                >
                                  <X className="h-3 w-3 mr-1" /> Descartar
                                </Button>
                              </div>
                            ) : (
                              <span className="text-slate-400 text-xs font-mono">—</span>
                            )}
                          </TableCell>
                        </TableRow>
                      )
                    })}
                  </TableBody>
                </Table>
              )}

              {/* Paginación o Resumen de Filtro */}
              {!tieneFiltroActivo && totalIncidencias > 0 && (
                <Paginacion
                  page={pageIncidencias}
                  pageSize={PAGE_SIZE_DEFECTO}
                  count={totalIncidencias}
                  enPagina={incidencias.length}
                  cargando={loading}
                  etiqueta="incidencias"
                  onCambiarPagina={(page) => setPagIncidencias(irAPagina(claveEmpresa, page))}
                />
              )}
              {tieneFiltroActivo && listaIncidenciasAMostrar.length > 0 && (
                <div className="flex items-center justify-between px-4 py-2.5 border-t border-slate-100 bg-slate-50/50 text-xs text-slate-600">
                  <span>
                    Mostrando <strong className="font-mono text-slate-900">{listaIncidenciasAMostrar.length}</strong> incidencias filtradas
                  </span>
                  <button
                    type="button"
                    onClick={() => {
                      setFiltroEstadoIncidencia('TODAS')
                      setBusquedaIncidencia('')
                    }}
                    className="text-indigo-600 hover:text-indigo-800 font-semibold cursor-pointer"
                  >
                    Restablecer vista paginada
                  </button>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* TAB 2: RECÁLCULOS */}
        <TabsContent value="recalculos" className="space-y-6">
          {/* Formulario Ejecutar Recálculo Manual */}
          {esAdmin && (
            <Card className="rounded-xl border border-slate-200/90 bg-white shadow-2xs">
              <CardHeader className="pb-3 border-b border-slate-100">
                <CardTitle className="text-base text-slate-900 flex items-center gap-2">
                  <Play className="h-4 w-4 text-indigo-600" />
                  Ejecutar Recálculo Cronológico
                </CardTitle>
                <CardDescription>
                  Reevalúa el orden de prioridad y recalcula el CPP hacia adelante ante documentos extemporáneos.
                </CardDescription>
              </CardHeader>
              <CardContent className="pt-4">
                <form onSubmit={handleEjecutarRecalculo} className="grid grid-cols-1 sm:grid-cols-3 gap-4 items-end">
                  <div className="space-y-1.5">
                    <Label required>Producto a Recalcular</Label>
                    <Select
                      required
                      value={recalculoProducto}
                      onChange={(e) => setRecalculoProducto(e.target.value)}
                    >
                      <option value="">Seleccionar Producto...</option>
                      {productos.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.codigo_interno} · {p.descripcion}
                        </option>
                      ))}
                    </Select>
                  </div>

                  <div className="space-y-1.5">
                    <Label required>Fecha Inicial del Recálculo</Label>
                    <Input
                      required
                      type="date"
                      value={recalculoFecha}
                      onChange={(e) => setRecalculoFecha(e.target.value)}
                      className="font-mono tabular-nums"
                    />
                  </div>

                  <Button type="submit" variant="primary" isLoading={ejecutandoRecalculo}>
                    <Play className="h-4 w-4 mr-1.5" /> Ejecutar Recálculo
                  </Button>
                </form>
              </CardContent>
            </Card>
          )}

          {/* Tabla de Historial de Recálculos */}
          <Card className="rounded-xl border border-slate-200/90 bg-white shadow-2xs overflow-hidden">
            <CardHeader className="border-b border-slate-100 pb-3">
              <CardTitle>Historial de Recálculos Cronológicos ({totalRecalculos})</CardTitle>
              <CardDescription>
                Trazabilidad de recálculos de CPP activados de forma manual o automática por el motor M2.
              </CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-20"># ID</TableHead>
                    <TableHead>Producto Recalculado</TableHead>
                    <TableHead className="w-32">Fecha Desde</TableHead>
                    <TableHead className="w-56 whitespace-nowrap">Fecha Ejecución</TableHead>
                    <TableHead className="w-32 text-center">Estado</TableHead>
                    <TableHead numeric className="w-32">Movs Afectados</TableHead>
                    <TableHead className="w-28 text-right">Detalle</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {recalculos.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={7} className="text-center py-8 text-slate-400 text-xs">
                        No hay registros de recálculo ejecutados.
                      </TableCell>
                    </TableRow>
                  ) : (
                    recalculos.map((r) => (
                      <TableRow key={r.id} className="hover:bg-slate-50/70 transition-colors">
                        <TableCell className="font-mono font-bold text-slate-900">
                          #{r.id}
                        </TableCell>
                        <TableCell className="font-semibold text-slate-800">
                          {getNombreProducto(r.producto)}
                        </TableCell>
                        <TableCell className="font-mono text-slate-600">
                          {r.fecha_desde}
                        </TableCell>
                        <TableCell className="text-slate-600 text-xs whitespace-nowrap font-mono tabular-nums">
                          {formatearFechaHora(r.ejecutado_en)}
                        </TableCell>
                        <TableCell className="text-center">
                          <Badge variant={r.estado === 'COMPLETADO' ? 'success' : 'destructive'} dot>
                            {r.estado}
                          </Badge>
                        </TableCell>
                        <TableCell numeric className="font-bold text-slate-900 font-mono">
                          {r.detalles?.length || 0}
                        </TableCell>
                        <TableCell className="text-right">
                          <Button
                            type="button"
                            size="xs"
                            variant="outline"
                            onClick={() => setRecalculoSeleccionado(r)}
                          >
                            <Eye className="h-3 w-3 mr-1" /> Ver Diff
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
              <Paginacion
                page={pageRecalculos}
                pageSize={PAGE_SIZE_DEFECTO}
                count={totalRecalculos}
                enPagina={recalculos.length}
                cargando={loading}
                etiqueta="recálculos"
                onCambiarPagina={(page) => setPagRecalculos(irAPagina(claveEmpresa, page))}
              />
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Modal Visor de Detalle de Recálculo */}
      {recalculoSeleccionado && (
        <Modal
          isOpen={Boolean(recalculoSeleccionado)}
          onClose={() => setRecalculoSeleccionado(null)}
          maxWidth="4xl"
          icon={<History className="h-5 w-5" />}
          title={`Detalle de Recálculo #${recalculoSeleccionado.id}`}
          description={`Producto: ${getNombreProducto(recalculoSeleccionado.producto)} • Fecha Desde: ${recalculoSeleccionado.fecha_desde}`}
          footer={
            <Button variant="secondary" onClick={() => setRecalculoSeleccionado(null)}>
              Cerrar Visor
            </Button>
          }
        >
          <div className="space-y-4">
            <div className="flex items-center justify-between p-3.5 rounded-xl bg-slate-50 border border-slate-200 text-xs">
              <span className="text-slate-600">
                Movimientos Reevaluados:{' '}
                <strong className="font-mono text-slate-900 font-bold text-sm ml-1">
                  {recalculoSeleccionado.detalles?.length || 0}
                </strong>
              </span>
              <div className="flex items-center gap-2">
                <span className="text-slate-500">Estado de Ejecución:</span>
                <Badge variant="success" size="sm" dot>
                  {recalculoSeleccionado.estado}
                </Badge>
              </div>
            </div>

            <div className="overflow-x-auto rounded-lg border border-slate-200">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-36">Movimiento ID</TableHead>
                    <TableHead numeric>CPP Anterior</TableHead>
                    <TableHead className="w-12 text-center">→</TableHead>
                    <TableHead numeric>CPP Nuevo</TableHead>
                    <TableHead numeric>Diferencia Saldo</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {recalculoSeleccionado.detalles?.map((det) => (
                    <TableRow key={det.movimiento_id} className="hover:bg-slate-50/70 transition-colors">
                      <TableCell className="font-bold text-slate-800 font-mono">
                        Mov #{det.movimiento_id}
                      </TableCell>
                      <TableCell numeric className="text-slate-500 font-mono">
                        S/ {formatearDecimal(det.cpp_anterior || 0, { min: 6, max: 6 })}
                      </TableCell>
                      <TableCell className="text-center font-bold text-slate-400">→</TableCell>
                      <TableCell numeric className="font-bold text-slate-950 font-mono">
                        S/ {formatearDecimal(det.cpp_nuevo || 0, { min: 6, max: 6 })}
                      </TableCell>
                      <TableCell numeric className="font-mono font-semibold text-slate-800">
                        S/ {formatearDecimal(restar(det.saldo_nuevo || 0, det.saldo_anterior || 0).toString(), { min: 4, max: 4 })}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}

export default IncidenciasPage
