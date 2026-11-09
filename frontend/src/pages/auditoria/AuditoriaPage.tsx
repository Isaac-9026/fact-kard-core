import React, { useEffect, useState, useCallback, useMemo } from 'react'
import {
  ShieldCheck,
  Search,
  Filter,
  RotateCcw,
  Code2,
  AlertCircle,
  User,
  Scale,
  Copy,
  Check,
} from 'lucide-react'
import { useAuth } from '../../context/useAuth'
import { getAuditoriaPaginadaApi, type AuditoriaItem } from '../../api/auditoria'
import { diferirCarga } from '../../utils/efectos'
import { Paginacion } from '../../components/ui/paginacion'
import {
  PAGE_SIZE_DEFECTO,
  claveConsulta,
  irAPagina,
  paginaVigente,
  paramsPaginacion,
  type EstadoPagina,
} from '../../utils/paginacion'
import type { AxiosError } from 'axios'
import { PageHeader } from '../../components/ui/page-header'
import { Button } from '../../components/ui/button'
import { Card, CardContent } from '../../components/ui/card'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '../../components/ui/table'
import { Badge } from '../../components/ui/badge'
import { Input } from '../../components/ui/input'
import { Modal } from '../../components/ui/modal'

const ENTIDADES_COMUNES = ['DOCUMENTO', 'MOVIMIENTO', 'CIERRE', 'PERIODO', 'NOTA_INTERNA', 'SALDO_INICIAL']
const ACCIONES_COMUNES = ['CREAR', 'MODIFICAR', 'ELIMINAR', 'EXTORNO']

export const AuditoriaPage: React.FC = () => {
  const { empresaActiva } = useAuth()
  const [logs, setLogs] = useState<AuditoriaItem[]>([])
  const [isLoading, setIsLoading] = useState<boolean>(true)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  // Filtros
  const [filtroEntidad, setFiltroEntidad] = useState<string>('')
  const [filtroAccion, setFiltroAccion] = useState<string>('')

  // Modal de Detalle JSON y copiado
  const [selectedLog, setSelectedLog] = useState<AuditoriaItem | null>(null)
  const [copiedSide, setCopiedSide] = useState<'before' | 'after' | null>(null)

  // Bloque 7: paginación en el servidor. Cambiar de empresa o de filtro vuelve a la página 1.
  const [total, setTotal] = useState(0)
  const [estadoPagina, setEstadoPagina] = useState<EstadoPagina>({ clave: '', page: 1 })
  const claveFiltros = claveConsulta(empresaActiva?.id, filtroEntidad.trim(), filtroAccion.trim())
  const page = paginaVigente(estadoPagina, claveFiltros)

  const fetchAuditoria = useCallback(async () => {
    if (!empresaActiva) {
      setIsLoading(false)
      return
    }

    try {
      setIsLoading(true)
      setErrorMsg(null)
      const data = await getAuditoriaPaginadaApi(
        { entidad: filtroEntidad, accion: filtroAccion },
        paramsPaginacion(page),
      )
      setLogs(data.results)
      setTotal(data.count)
    } catch (err) {
      const axiosErr = err as AxiosError<{ detail?: string }>
      if (axiosErr.response?.data?.detail) {
        setErrorMsg(axiosErr.response.data.detail)
      } else {
        setErrorMsg('Error al consultar los registros de auditoría.')
      }
    } finally {
      setIsLoading(false)
    }
  }, [empresaActiva, filtroEntidad, filtroAccion, page])

  useEffect(() => {
    diferirCarga(fetchAuditoria)
  }, [fetchAuditoria])

  const handleClearFilters = () => {
    setFiltroEntidad('')
    setFiltroAccion('')
  }

  const formatFecha = (isoString?: string | null): string => {
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

  const getActionBadgeVariant = (accion: string): 'success' | 'info' | 'destructive' | 'warning' | 'neutral' => {
    const act = accion.toUpperCase()
    if (act.includes('CREAR') || act.includes('ASIGNAR') || act.includes('REVISADO')) {
      return 'success'
    }
    if (act.includes('MODIFICAR') || act.includes('ACTUALIZAR')) {
      return 'info'
    }
    if (act.includes('ELIMINAR') || act.includes('EXTORNO') || act.includes('ANULAR') || act.includes('BLOQUEAR')) {
      return 'destructive'
    }
    return 'warning'
  }

  const formatJson = useMemo(() => {
    return (data: Record<string, unknown> | null | undefined): string => {
      if (!data || Object.keys(data).length === 0) return '{\n  // Sin datos registrados\n}'
      return JSON.stringify(data, null, 2)
    }
  }, [])

  const handleCopyJson = (side: 'before' | 'after', data: Record<string, unknown> | null | undefined) => {
    if (!data) return
    navigator.clipboard.writeText(JSON.stringify(data, null, 2))
    setCopiedSide(side)
    setTimeout(() => setCopiedSide(null), 2000)
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Registro de Auditoría Inmutable"
        description={`Bitácora legal de trazabilidad y eventos operacionales para ${
          empresaActiva ? `${empresaActiva.razon_social} (RUC ${empresaActiva.ruc})` : 'la empresa seleccionada'
        }.`}
        icon={<ShieldCheck className="h-5 w-5" />}
        badge={
          <Badge variant="success" dot className="font-semibold shadow-2xs">
            Inmutable por Trigger PostgreSQL
          </Badge>
        }
        actions={
          <Button variant="outline" size="sm" onClick={fetchAuditoria} isLoading={isLoading}>
            <RotateCcw className="h-4 w-4 mr-1.5" /> Actualizar
          </Button>
        }
      />

      {/* Regla contable informativa */}
      <div className="flex items-start gap-3 rounded-xl border border-slate-200/90 bg-white p-4 shadow-2xs">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-indigo-50 border border-indigo-100/60 text-indigo-600">
          <Scale className="h-4 w-4" />
        </div>
        <div className="text-xs text-slate-600 leading-relaxed">
          <strong className="text-slate-900 font-semibold">Garantía de Fidelidad Contable:</strong> Todo evento operacional,
          confirmación en Kardex, asignación de permisos, cierre y extorno genera un registro persistente con{' '}
          <code className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[11px] text-slate-800">valor_anterior</code> y{' '}
          <code className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[11px] text-slate-800">valor_nuevo</code>. Los triggers
          SQL inalterables <code className="font-mono text-[11px]">trg_auditoria_no_update</code> y{' '}
          <code className="font-mono text-[11px]">trg_auditoria_no_delete</code> impiden cualquier alteración física en base de datos.
        </div>
      </div>

      {/* Barra de Filtros */}
      <Card>
        <CardContent className="p-4 space-y-3">
          <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 flex-wrap">
            <div className="flex items-center gap-3 flex-1 flex-wrap">
              <div className="w-full sm:w-64">
                <Input
                  id="filtro-entidad"
                  type="text"
                  placeholder="Filtrar por Entidad (ej. DOCUMENTO)"
                  value={filtroEntidad}
                  onChange={(e) => setFiltroEntidad(e.target.value)}
                  leftIcon={<Search className="h-4 w-4" />}
                />
              </div>

              <div className="w-full sm:w-64">
                <Input
                  id="filtro-accion"
                  type="text"
                  placeholder="Filtrar por Acción (ej. CREAR)"
                  value={filtroAccion}
                  onChange={(e) => setFiltroAccion(e.target.value)}
                  leftIcon={<Filter className="h-4 w-4" />}
                />
              </div>

              {(filtroEntidad || filtroAccion) && (
                <Button variant="ghost" size="sm" onClick={handleClearFilters} className="text-slate-500">
                  <RotateCcw className="h-3.5 w-3.5 mr-1" /> Limpiar
                </Button>
              )}
            </div>

            <div className="flex items-center gap-2">
              <Badge variant="neutral" className="font-mono font-semibold">
                {total} {total === 1 ? 'registro' : 'registros'}
              </Badge>
            </div>
          </div>

          {/* Pastillas de filtro rápido */}
          <div className="flex flex-wrap items-center gap-1.5 pt-2 border-t border-slate-100 text-xs">
            <span className="text-[11px] font-medium text-slate-400">Entidad:</span>
            {ENTIDADES_COMUNES.map((ent) => {
              const activa = filtroEntidad.toUpperCase() === ent
              return (
                <button
                  key={ent}
                  type="button"
                  onClick={() => setFiltroEntidad(activa ? '' : ent)}
                  className={`inline-flex items-center rounded-md px-2 py-0.5 font-mono text-[11px] transition-colors ${
                    activa
                      ? 'bg-indigo-600 text-white font-medium shadow-2xs'
                      : 'bg-slate-100 text-slate-600 hover:bg-slate-200 hover:text-slate-900'
                  }`}
                >
                  {ent}
                </button>
              )
            })}
            <span className="mx-1 text-slate-300">|</span>
            <span className="text-[11px] font-medium text-slate-400">Acción:</span>
            {ACCIONES_COMUNES.map((acc) => {
              const activa = filtroAccion.toUpperCase() === acc
              return (
                <button
                  key={acc}
                  type="button"
                  onClick={() => setFiltroAccion(activa ? '' : acc)}
                  className={`inline-flex items-center rounded-md px-2 py-0.5 font-mono text-[11px] transition-colors ${
                    activa
                      ? 'bg-slate-800 text-white font-medium shadow-2xs'
                      : 'bg-slate-100 text-slate-600 hover:bg-slate-200 hover:text-slate-900'
                  }`}
                >
                  {acc}
                </button>
              )
            })}
          </div>
        </CardContent>
      </Card>

      {/* Error alert */}
      {errorMsg && (
        <div
          role="alert"
          className="flex items-start gap-2.5 rounded-lg border border-rose-200 bg-rose-50/90 p-3.5 text-xs text-rose-700 animate-in fade-in"
        >
          <AlertCircle className="h-4 w-4 shrink-0 text-rose-600 mt-0.5" />
          <span className="font-medium leading-relaxed">{errorMsg}</span>
        </div>
      )}

      {/* Tabla de Auditoría */}
      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="flex flex-col items-center justify-center p-12 text-slate-400 text-xs">
              <div className="h-6 w-6 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin mb-3" />
              <span>Cargando eventos de auditoría inmutable...</span>
            </div>
          ) : logs.length === 0 ? (
            <div className="p-12 text-center text-xs text-slate-500">
              <p className="font-semibold text-sm text-slate-700 mb-1">No se encontraron registros de auditoría</p>
              <p>
                {filtroEntidad || filtroAccion
                  ? 'Intenta ajustar o limpiar los filtros de búsqueda.'
                  : 'No se han registrado operaciones para esta empresa activa.'}
              </p>
            </div>
          ) : (
            <Table containerClassName="border-0 shadow-none rounded-none max-h-[580px]">
              <TableHeader>
                <TableRow>
                  <TableHead className="w-20">ID</TableHead>
                  <TableHead className="w-48 whitespace-nowrap">Fecha y Hora</TableHead>
                  <TableHead className="w-36">Usuario</TableHead>
                  <TableHead className="w-32 text-center">Acción</TableHead>
                  <TableHead className="w-36 text-center">Entidad</TableHead>
                  <TableHead className="w-24 text-center">Reg. ID</TableHead>
                  <TableHead className="min-w-[200px]">Motivo / Descripción</TableHead>
                  <TableHead className="w-24 text-center">Diff JSON</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {logs.map((log) => {
                  const hasJsonDiff = !!(log.valor_anterior || log.valor_nuevo)
                  return (
                    <TableRow key={log.id}>
                      <TableCell className="w-20 font-mono font-semibold text-slate-900 text-xs">
                        #{log.id}
                      </TableCell>
                      <TableCell className="w-48 text-slate-600 text-xs whitespace-nowrap font-mono tabular-nums">
                        {formatFecha(log.fecha)}
                      </TableCell>
                      <TableCell className="w-36">
                        <span className="inline-flex items-center gap-1.5 text-xs text-slate-700 font-medium">
                          <User className="h-3 w-3 text-slate-400 shrink-0" />
                          <span className="truncate">{log.usuario_username || `ID ${log.usuario_id || 'Sistema'}`}</span>
                        </span>
                      </TableCell>
                      <TableCell className="w-32 text-center">
                        <Badge variant={getActionBadgeVariant(log.accion)} size="sm" className="font-mono text-[10px]">
                          {log.accion}
                        </Badge>
                      </TableCell>
                      <TableCell className="w-36 text-center">
                        <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-800 font-medium border border-slate-200/60">
                          {log.entidad}
                        </code>
                      </TableCell>
                      <TableCell className="w-24 text-center font-mono font-medium text-xs text-slate-600">
                        {log.registro_id !== null && log.registro_id !== undefined ? `#${log.registro_id}` : '—'}
                      </TableCell>
                      <TableCell className="min-w-[200px] max-w-xs truncate text-slate-600 text-xs" title={log.motivo || undefined}>
                        {log.motivo || <span className="text-slate-400 italic">Sin motivo especificado</span>}
                      </TableCell>
                      <TableCell className="w-24 text-center">
                        {hasJsonDiff ? (
                          <Button
                            type="button"
                            size="xs"
                            variant="outline"
                            onClick={() => setSelectedLog(log)}
                            title="Ver diferencias JSON"
                            className="font-mono text-[11px] gap-1 shadow-2xs hover:bg-slate-100"
                          >
                            <Code2 className="h-3 w-3 text-indigo-600" /> Ver
                          </Button>
                        ) : (
                          <span className="text-slate-300 select-none">—</span>
                        )}
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          )}
          {total > 0 && (
            <Paginacion
              page={page}
              pageSize={PAGE_SIZE_DEFECTO}
              count={total}
              enPagina={logs.length}
              cargando={isLoading}
              onCambiarPagina={(nueva) => setEstadoPagina(irAPagina(claveFiltros, nueva))}
            />
          )}
        </CardContent>
      </Card>

      {/* Modal Visor JSON Diferencial */}
      {selectedLog && (
        <Modal
          isOpen={Boolean(selectedLog)}
          onClose={() => setSelectedLog(null)}
          maxWidth="4xl"
          icon={<Code2 className="h-5 w-5" />}
          title={`Detalle de Cambios — Registro #${selectedLog.id}`}
          description={`Entidad: ${selectedLog.entidad} • Acción: ${selectedLog.accion}`}
          footer={
            <Button variant="secondary" size="sm" onClick={() => setSelectedLog(null)}>
              Cerrar Visor
            </Button>
          }
        >
          <div className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Panel Valor Anterior */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between pb-1">
                  <span className="text-xs font-semibold text-rose-700 flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-full bg-rose-500" />
                    Valor Anterior (Before)
                  </span>
                  {selectedLog.valor_anterior && Object.keys(selectedLog.valor_anterior).length > 0 && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="xs"
                      onClick={() => handleCopyJson('before', selectedLog.valor_anterior)}
                      className="h-6 text-[11px] text-rose-700 hover:bg-rose-100 gap-1"
                    >
                      {copiedSide === 'before' ? <Check className="h-3 w-3 text-emerald-600" /> : <Copy className="h-3 w-3" />}
                      {copiedSide === 'before' ? 'Copiado' : 'Copiar JSON'}
                    </Button>
                  )}
                </div>
                <pre className="rounded-xl border border-rose-200 bg-rose-50/40 p-3.5 font-mono text-[11px] text-slate-800 overflow-x-auto max-h-80 leading-relaxed overscroll-contain shadow-2xs">
                  {formatJson(selectedLog.valor_anterior)}
                </pre>
              </div>

              {/* Panel Valor Nuevo */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between pb-1">
                  <span className="text-xs font-semibold text-emerald-700 flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-full bg-emerald-500" />
                    Valor Nuevo (After)
                  </span>
                  {selectedLog.valor_nuevo && Object.keys(selectedLog.valor_nuevo).length > 0 && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="xs"
                      onClick={() => handleCopyJson('after', selectedLog.valor_nuevo)}
                      className="h-6 text-[11px] text-emerald-700 hover:bg-emerald-100 gap-1"
                    >
                      {copiedSide === 'after' ? <Check className="h-3 w-3 text-emerald-600" /> : <Copy className="h-3 w-3" />}
                      {copiedSide === 'after' ? 'Copiado' : 'Copiar JSON'}
                    </Button>
                  )}
                </div>
                <pre className="rounded-xl border border-emerald-200 bg-emerald-50/40 p-3.5 font-mono text-[11px] text-slate-800 overflow-x-auto max-h-80 leading-relaxed overscroll-contain shadow-2xs">
                  {formatJson(selectedLog.valor_nuevo)}
                </pre>
              </div>
            </div>

            {selectedLog.motivo && (
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700">
                <strong className="text-slate-900">Motivo registrado:</strong> {selectedLog.motivo}
              </div>
            )}
          </div>
        </Modal>
      )}
    </div>
  )
}

export default AuditoriaPage
