import React, { useCallback, useEffect, useState, type FormEvent } from 'react'
import axios from 'axios'
import {
  ArrowLeftRight,
  ArrowRight,
  Plus,
  Trash2,
  CheckCircle2,
  AlertCircle,
  Warehouse,
  Calendar,
  Save,
  RotateCcw,
} from 'lucide-react'
import { getAlmacenes, getProductos, type Almacen, type Producto } from '../../api/inventario'
import {
  confirmarTransferencia,
  createTransferencia,
  getTransferencias,
  type Transferencia,
} from '../../api/transferencias'
import { useAuth } from '../../context/useAuth'
import { fechaCalendarioFormulario, fechaCalendarioLocal } from '../../utils/date'
import { PageHeader } from '../../components/ui/page-header'
import { Button } from '../../components/ui/button'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../../components/ui/card'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '../../components/ui/table'
import { Badge } from '../../components/ui/badge'
import { Input } from '../../components/ui/input'
import { Select } from '../../components/ui/select'
import { Label } from '../../components/ui/label'
import { diferirCarga } from '../../utils/efectos'

interface LineaTransferencia {
  producto: string
  cantidad_base: string
}

const lineaVacia = (): LineaTransferencia => ({ producto: '', cantidad_base: '' })

const errorApi = (error: unknown): string => {
  if (!axios.isAxiosError(error)) return 'No se pudo completar la operación.'
  const data = error.response?.data
  if (typeof data === 'string') return data
  if (data && typeof data === 'object') {
    return Object.entries(data)
      .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(' ') : String(v)}`)
      .join(' | ')
  }
  return 'No se pudo completar la operación.'
}

export const TransferenciasPage: React.FC = () => {
  const { empresaActiva } = useAuth()
  const [transferencias, setTransferencias] = useState<Transferencia[]>([])
  const [almacenes, setAlmacenes] = useState<Almacen[]>([])
  const [productos, setProductos] = useState<Producto[]>([])
  const [form, setForm] = useState({
    almacen_origen: '',
    almacen_destino: '',
    fecha: fechaCalendarioLocal(),
    detalles: [lineaVacia()],
  })
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  const cargar = useCallback(async () => {
    if (!empresaActiva) return
    setLoading(true)
    try {
      const [lista, nuevosAlmacenes, nuevosProductos] = await Promise.all([
        getTransferencias(),
        getAlmacenes(),
        getProductos(),
      ])
      setTransferencias(lista)
      setAlmacenes(nuevosAlmacenes)
      setProductos(nuevosProductos)
    } catch (err) {
      setError(errorApi(err))
    } finally {
      setLoading(false)
    }
  }, [empresaActiva])

  useEffect(() => {
    diferirCarga(cargar)
  }, [cargar])

  const guardar = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setError(null)
    setSuccess(null)
    const fecha = fechaCalendarioFormulario(new FormData(event.currentTarget).get('fecha'))

    if (!form.almacen_origen || !form.almacen_destino) {
      setError('Debe seleccionar los almacenes de origen y destino.')
      return
    }

    if (form.almacen_origen === form.almacen_destino) {
      setError('El almacén destino debe ser distinto del almacén origen.')
      return
    }

    if (!fecha) {
      setError('Debe ingresar la fecha de transferencia con formato YYYY-MM-DD.')
      return
    }

    const lineasValidas = form.detalles.filter(
      (l) => l.producto && parseFloat(l.cantidad_base) > 0
    )

    if (lineasValidas.length === 0) {
      setError('Debe ingresar al menos un producto con cantidad mayor a 0.')
      return
    }

    setSaving(true)
    try {
      await createTransferencia({
        almacen_origen: Number(form.almacen_origen),
        almacen_destino: Number(form.almacen_destino),
        fecha,
        detalles: lineasValidas.map((l) => ({
          producto: Number(l.producto),
          cantidad_base: l.cantidad_base,
        })),
      })
      setForm({
        almacen_origen: '',
        almacen_destino: '',
        fecha: fechaCalendarioLocal(),
        detalles: [lineaVacia()],
      })
      setSuccess('Transferencia creada exitosamente en estado BORRADOR.')
      await cargar()
    } catch (err) {
      setError(errorApi(err))
    } finally {
      setSaving(false)
    }
  }

  const confirmar = async (transferencia: Transferencia) => {
    if (
      !window.confirm(
        `¿Confirmar el traslado #${transferencia.id}? Se generará la salida en ${transferencia.almacen_origen_nombre} y la entrada en ${transferencia.almacen_destino_nombre} sin alterar el CPP global.`
      )
    ) {
      return
    }
    setSaving(true)
    setError(null)
    setSuccess(null)
    try {
      await confirmarTransferencia(transferencia.id)
      setSuccess(`Traslado #${transferencia.id} confirmado correctamente en Kardex.`)
      await cargar()
    } catch (err) {
      setError(errorApi(err))
    } finally {
      setSaving(false)
    }
  }

  const actualizarLinea = (indice: number, campo: keyof LineaTransferencia, valor: string) => {
    setForm((actual) => ({
      ...actual,
      detalles: actual.detalles.map((linea, posicion) =>
        posicion === indice ? { ...linea, [campo]: valor } : linea
      ),
    }))
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Transferencias entre Almacenes"
        description={`Traslados atómicos de inventario sin alteración del CPP global para ${
          empresaActiva?.razon_social ?? 'la empresa activa'
        }.`}
        icon={<ArrowLeftRight className="h-5 w-5" />}
        badge={<Badge variant="info">Fase 7 • Motor Kardex</Badge>}
        actions={
          <Button variant="outline" size="sm" onClick={cargar} isLoading={loading}>
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

      {/* Formulario de Nueva Transferencia */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-50 border border-indigo-100 text-indigo-600">
              <ArrowLeftRight className="h-4 w-4" />
            </div>
            <div>
              <CardTitle className="text-base">Nueva Transferencia de Inventario</CardTitle>
              <CardDescription>
                Registre el traslado en estado BORRADOR y confírmelo cuando el stock físico esté verificado.
              </CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <form onSubmit={guardar} className="space-y-5">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 items-center">
              <div className="space-y-1.5">
                <Label required>Almacén Origen (Salida)</Label>
                <Select
                  required
                  value={form.almacen_origen}
                  onChange={(e) => setForm({ ...form, almacen_origen: e.target.value })}
                  leftIcon={<Warehouse className="h-4 w-4" />}
                >
                  <option value="">Seleccionar Origen</option>
                  {almacenes.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.codigo} · {a.nombre}
                    </option>
                  ))}
                </Select>
              </div>

              <div className="space-y-1.5">
                <Label required>Almacén Destino (Entrada)</Label>
                <Select
                  required
                  value={form.almacen_destino}
                  onChange={(e) => setForm({ ...form, almacen_destino: e.target.value })}
                  leftIcon={<Warehouse className="h-4 w-4" />}
                >
                  <option value="">Seleccionar Destino</option>
                  {almacenes
                    .filter((a) => String(a.id) !== form.almacen_origen)
                    .map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.codigo} · {a.nombre}
                      </option>
                    ))}
                </Select>
              </div>

              <div className="space-y-1.5">
                <Label required>Fecha del Traslado</Label>
                <Input
                  required
                  name="fecha"
                  type="date"
                  value={form.fecha}
                  onChange={(e) => setForm({ ...form, fecha: e.target.value })}
                  className="font-mono tabular-nums"
                  leftIcon={<Calendar className="h-4 w-4" />}
                />
              </div>
            </div>

            {/* Líneas de Traslado */}
            <div className="space-y-2 pt-2 border-t border-slate-100">
              <div className="flex items-center justify-between">
                <Label className="text-xs font-bold uppercase tracking-wider text-slate-700">
                  Mercancías a Trasladar
                </Label>
                <Button
                  type="button"
                  size="xs"
                  variant="secondary"
                  onClick={() => setForm({ ...form, detalles: [...form.detalles, lineaVacia()] })}
                >
                  <Plus className="h-3 w-3 mr-1" /> Agregar Producto
                </Button>
              </div>

              <div className="space-y-2">
                {form.detalles.map((linea, idx) => (
                  <div
                    key={idx}
                    className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2.5 p-2.5 rounded-lg border border-slate-200 bg-slate-50/50"
                  >
                    <span className="font-mono text-xs font-bold text-slate-400 px-1">{idx + 1}</span>

                    <div className="flex-1">
                      <Select
                        required
                        value={linea.producto}
                        onChange={(e) => actualizarLinea(idx, 'producto', e.target.value)}
                      >
                        <option value="">Seleccionar Producto...</option>
                        {productos.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.codigo_interno} · {p.descripcion}
                          </option>
                        ))}
                      </Select>
                    </div>

                    <div className="w-full sm:w-44">
                      <Input
                        required
                        type="number"
                        step="0.0001"
                        min="0.0001"
                        placeholder="Cantidad Base"
                        value={linea.cantidad_base}
                        onChange={(e) => actualizarLinea(idx, 'cantidad_base', e.target.value)}
                        className="font-mono tabular-nums text-right"
                      />
                    </div>

                    <Button
                      type="button"
                      size="icon-sm"
                      variant="ghost"
                      disabled={form.detalles.length === 1}
                      onClick={() =>
                        setForm({
                          ...form,
                          detalles: form.detalles.filter((_, pos) => pos !== idx),
                        })
                      }
                      className="text-slate-400 hover:text-rose-600"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                ))}
              </div>
            </div>

            <div className="flex justify-end pt-2">
              <Button type="submit" variant="primary" isLoading={saving}>
                <Save className="h-4 w-4 mr-1.5" /> Registrar Traslado en Borrador
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      {/* Tabla de Historial de Transferencias */}
      <Card>
        <CardHeader>
          <CardTitle>Historial de Transferencias ({transferencias.length})</CardTitle>
          <CardDescription>
            Trazabilidad de traslados confirmados y pendientes entre almacenes.
          </CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-16"># ID</TableHead>
                <TableHead className="w-28">Fecha</TableHead>
                <TableHead>Flujo de Traslado (Origen → Destino)</TableHead>
                <TableHead numeric className="w-20">Líneas</TableHead>
                <TableHead className="w-32">Estado</TableHead>
                <TableHead className="text-right">Acción</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {transferencias.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-center py-8 text-slate-400 text-xs">
                    No hay traslados registrados para esta empresa.
                  </TableCell>
                </TableRow>
              ) : (
                transferencias.map((t) => (
                  <TableRow key={t.id}>
                    <TableCell numeric className="font-bold text-slate-900">
                      #{t.id}
                    </TableCell>
                    <TableCell numeric className="text-slate-600">
                      {t.fecha}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2 text-xs">
                        <span className="font-semibold text-slate-800">
                          {t.almacen_origen_nombre || `Alm #${t.almacen_origen}`}
                        </span>
                        <ArrowRight className="h-3.5 w-3.5 text-indigo-600 shrink-0" />
                        <span className="font-semibold text-slate-800">
                          {t.almacen_destino_nombre || `Alm #${t.almacen_destino}`}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell numeric className="font-bold text-slate-700">
                      {t.numero_lineas}
                    </TableCell>
                    <TableCell>
                      <Badge variant={t.estado === 'CONFIRMADO' ? 'success' : 'warning'} dot>
                        {t.estado}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      {t.estado === 'BORRADOR' ? (
                        <Button
                          type="button"
                          size="xs"
                          variant="primary"
                          onClick={() => void confirmar(t)}
                          isLoading={saving}
                        >
                          <CheckCircle2 className="h-3 w-3 mr-1" /> Confirmar Traslado
                        </Button>
                      ) : (
                        <span className="text-slate-400 text-xs">Aplicado al Kardex</span>
                      )}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}

export default TransferenciasPage
