/**
 * Bloque 16 — series de comprobantes de venta por establecimiento (F001, B001...).
 * El correlativo lo asigna el backend al registrar la venta; aquí solo se administran.
 */
import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Hash, Plus, Trash2 } from 'lucide-react'
import type { Establecimiento } from '../../api/empresas'
import { obtenerTiposComprobante, type TipoComprobante } from '../../api/catalogos'
import { actualizarSerie, crearSerie, eliminarSerie, obtenerSeries, type SerieComprobante } from '../../api/finanzas'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../ui/card'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { Label } from '../ui/label'
import { Select } from '../ui/select'
import { Badge } from '../ui/badge'
import { AlertaFormulario } from '../ui/alerta-formulario'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../ui/table'
import { mensajesDeErrorApi } from '../../utils/errores'
import { diferirCarga } from '../../utils/efectos'

const TIPOS_CON_SERIE = ['01', '03', '07', '08']
const FORM_INICIAL = { establecimiento: '', tipo_comprobante: '', serie: '', ultimo_correlativo: '0', activo: true }

export function SeriesComprobantePanel({ establecimientos, esAdmin }: { establecimientos: Establecimiento[]; esAdmin: boolean }) {
  const [series, setSeries] = useState<SerieComprobante[]>([])
  const [tipos, setTipos] = useState<TipoComprobante[]>([])
  const [form, setForm] = useState(FORM_INICIAL)
  const [errores, setErrores] = useState<string[] | null>(null)
  const [aviso, setAviso] = useState('')
  const [guardando, setGuardando] = useState(false)

  const cargar = useCallback(async () => {
    try {
      setSeries(await obtenerSeries())
    } catch (e) {
      setErrores(mensajesDeErrorApi(e, 'No se pudieron cargar las series.'))
    }
  }, [])

  useEffect(() => {
    diferirCarga(cargar)
    obtenerTiposComprobante()
      .then((t) => setTipos(t.filter((x) => TIPOS_CON_SERIE.includes(x.codigo_sunat))))
      .catch(() => setTipos([]))
  }, [cargar])

  const ejecutar = async (accion: () => Promise<unknown>, mensaje: string) => {
    setErrores(null)
    setAviso('')
    setGuardando(true)
    try {
      await accion()
      setAviso(mensaje)
      await cargar()
      return true
    } catch (e) {
      setErrores(mensajesDeErrorApi(e, 'No se pudo guardar la serie.'))
      return false
    } finally {
      setGuardando(false)
    }
  }

  const guardar = async (event: FormEvent) => {
    event.preventDefault()
    const ultimo = form.ultimo_correlativo.trim() || '0'
    if (!/^\d{1,8}$/.test(ultimo)) return setErrores(['El último correlativo debe ser un entero entre 0 y 99999999.'])
    const ok = await ejecutar(() => crearSerie({
      establecimiento: Number(form.establecimiento),
      tipo_comprobante: Number(form.tipo_comprobante),
      serie: form.serie.trim().toUpperCase(),
      ultimo_correlativo: Number(ultimo),
      activo: form.activo,
    }), 'Serie creada.')
    if (ok) setForm(FORM_INICIAL)
  }

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
      {esAdmin && (
        <Card className="lg:col-span-1">
          <CardHeader>
            <CardTitle>Nueva serie</CardTitle>
            <CardDescription>4 caracteres: F001 para facturas, B001 para boletas. El número se asigna solo.</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={guardar} className="space-y-4">
              <div className="space-y-1.5">
                <Label required htmlFor="serie-establecimiento">Establecimiento</Label>
                <Select id="serie-establecimiento" required value={form.establecimiento} onChange={(e) => setForm({ ...form, establecimiento: e.target.value })}>
                  <option value="">Seleccionar…</option>
                  {establecimientos.filter((e) => e.activo).map((e) => <option key={e.id} value={e.id}>{e.codigo_sunat} — {e.nombre}</option>)}
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label required htmlFor="serie-tipo">Tipo de comprobante</Label>
                <Select id="serie-tipo" required value={form.tipo_comprobante} onChange={(e) => setForm({ ...form, tipo_comprobante: e.target.value })}>
                  <option value="">Seleccionar…</option>
                  {tipos.map((t) => <option key={t.id} value={t.id}>{t.codigo_sunat} — {t.descripcion}</option>)}
                </Select>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label required htmlFor="serie-codigo">Serie</Label>
                  <Input id="serie-codigo" required maxLength={4} placeholder="F001" className="font-mono uppercase" value={form.serie} onChange={(e) => setForm({ ...form, serie: e.target.value.toUpperCase() })} />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="serie-ultimo">Último N° emitido</Label>
                  <Input id="serie-ultimo" inputMode="numeric" maxLength={8} className="font-mono tabular-nums" value={form.ultimo_correlativo} onChange={(e) => setForm({ ...form, ultimo_correlativo: e.target.value })} />
                </div>
              </div>
              <label className="flex items-center gap-2 text-sm text-slate-700">
                <input type="checkbox" checked={form.activo} onChange={(e) => setForm({ ...form, activo: e.target.checked })} /> Activa
              </label>
              <Button type="submit" variant="primary" className="w-full" isLoading={guardando}>
                <Plus className="h-4 w-4" /> Crear serie
              </Button>
            </form>
          </CardContent>
        </Card>
      )}

      <Card className={esAdmin ? 'lg:col-span-2' : 'lg:col-span-3'}>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Hash className="h-4 w-4" /> Series de comprobantes ({series.length})</CardTitle>
          <CardDescription>Una serie en uso no cambia de código, tipo ni establecimiento; puede desactivarse.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {errores && <AlertaFormulario titulo="No se pudo completar la operación" mensajes={errores} />}
          {aviso && <p className="text-xs text-emerald-700" role="status">{aviso}</p>}
          <div className="overflow-x-auto">
            <Table data-testid="tabla-series">
              <TableHeader>
                <TableRow>
                  <TableHead>Serie</TableHead><TableHead>Tipo</TableHead><TableHead>Establecimiento</TableHead>
                  <TableHead numeric>Último</TableHead><TableHead>Siguiente</TableHead><TableHead>Estado</TableHead><TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {series.length === 0 && (
                  <TableRow><TableCell colSpan={7} className="py-6 text-center text-slate-500">Sin series. Las ventas usarán serie y número manuales.</TableCell></TableRow>
                )}
                {series.map((s) => (
                  <TableRow key={s.id}>
                    <TableCell className="font-mono font-bold">{s.serie}</TableCell>
                    <TableCell className="text-xs">{s.tipo_comprobante_codigo} — {s.tipo_comprobante_descripcion}</TableCell>
                    <TableCell className="text-xs">{s.establecimiento_codigo} — {s.establecimiento_nombre}</TableCell>
                    <TableCell numeric>{s.ultimo_correlativo}</TableCell>
                    <TableCell className="font-mono">{s.serie}-{s.siguiente_numero}</TableCell>
                    <TableCell><Badge size="sm" variant={s.activo ? 'success' : 'neutral'}>{s.activo ? 'ACTIVA' : 'INACTIVA'}</Badge></TableCell>
                    <TableCell className="text-right whitespace-nowrap">
                      {esAdmin && (
                        <>
                          <Button size="xs" variant="outline" disabled={guardando}
                            onClick={() => ejecutar(() => actualizarSerie(s.id, { activo: !s.activo }), s.activo ? 'Serie desactivada.' : 'Serie activada.')}>
                            {s.activo ? 'Desactivar' : 'Activar'}
                          </Button>
                          {!s.en_uso && (
                            <Button size="xs" variant="ghost" title="Eliminar serie sin uso" disabled={guardando}
                              onClick={() => ejecutar(() => eliminarSerie(s.id), 'Serie eliminada.')}>
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                          )}
                        </>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
