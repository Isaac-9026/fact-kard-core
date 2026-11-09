/**
 * Bloque 16 — Registro de ventas y Registro de compras por período (reporte comercial interno,
 * no es PLE/SIRE). Pantalla con filtros y descarga Excel generada por el backend.
 */
import { useEffect, useState } from 'react'
import { BookText, FileDown, Search } from 'lucide-react'
import { descargarRegistroExcel, obtenerRegistro, type RegistroComercial } from '../../api/finanzas'
import { obtenerPeriodos, type Periodo } from '../../api/periodos'
import { useAuth } from '../../context/useAuth'
import { PageHeader } from '../../components/ui/page-header'
import { Card, CardContent } from '../../components/ui/card'
import { Button } from '../../components/ui/button'
import { Label } from '../../components/ui/label'
import { Select } from '../../components/ui/select'
import { Badge } from '../../components/ui/badge'
import { Tabs, TabsList, TabsTrigger } from '../../components/ui/tabs'
import { AlertaFormulario } from '../../components/ui/alerta-formulario'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../components/ui/table'
import { formatearDecimal } from '../../utils/decimal'
import { mensajesDeErrorApi } from '../../utils/errores'
import { ErrorExportacion, TIPO_XLSX, descargarBlob, esXlsx, mensajeErrorExportacion, nombreSeguro } from '../../utils/descargaArchivo'

type Clase = 'VENTA' | 'COMPRA'

export function RegistroComercialPage() {
  const { empresaActiva } = useAuth()
  const [clase, setClase] = useState<Clase>('VENTA')
  const [periodos, setPeriodos] = useState<Periodo[]>([])
  const [periodo, setPeriodo] = useState<number | ''>('')
  const [estado, setEstado] = useState('')
  const [datos, setDatos] = useState<RegistroComercial | null>(null)
  const [cargando, setCargando] = useState(false)
  const [exportando, setExportando] = useState(false)
  const [error, setError] = useState<string[] | null>(null)

  useEffect(() => {
    if (!empresaActiva?.id) return
    obtenerPeriodos()
      .then((ps) => { setPeriodos(ps); setPeriodo((actual) => actual || ps[0]?.id || '') })
      .catch(() => setPeriodos([]))
  }, [empresaActiva?.id])

  const consultar = async () => {
    if (!periodo) return setError(['Seleccione un período.'])
    setError(null)
    setCargando(true)
    try {
      setDatos(await obtenerRegistro(clase, periodo, estado || undefined))
    } catch (e) {
      setDatos(null)
      setError(mensajesDeErrorApi(e, 'No se pudo generar el registro.'))
    } finally {
      setCargando(false)
    }
  }

  const exportar = async () => {
    if (!periodo) return setError(['Seleccione un período.'])
    setError(null)
    setExportando(true)
    const base = clase === 'VENTA' ? 'No se pudo exportar el registro de ventas.' : 'No se pudo exportar el registro de compras.'
    try {
      const blob = await descargarRegistroExcel(clase, periodo, estado || undefined)
      if (!(blob instanceof Blob) || !(await esXlsx(blob))) throw new ErrorExportacion('La respuesta del servidor no es un archivo Excel válido.')
      const p = periodos.find((x) => x.id === periodo)
      const nombre = `${nombreSeguro([clase === 'VENTA' ? 'Registro_Ventas' : 'Registro_Compras',
        p ? `${p.anio}-${String(p.mes).padStart(2, '0')}` : '', empresaActiva?.ruc ?? ''].filter(Boolean).join('_'))}.xlsx`
      descargarBlob(blob.type === TIPO_XLSX ? blob : new Blob([blob], { type: TIPO_XLSX }), nombre)
    } catch (e) {
      setError([await mensajeErrorExportacion(e, base)])
    } finally {
      setExportando(false)
    }
  }

  const rol = clase === 'VENTA' ? 'Cliente' : 'Proveedor'

  return (
    <div className="space-y-6">
      <PageHeader
        title="Registro de ventas y compras"
        description="Comprobantes del período con base, IGV, total y condición. Reporte comercial interno (no es PLE/SIRE)."
        icon={<BookText className="h-5 w-5" />}
      />

      <Tabs value={clase} onValueChange={(v) => { setClase(v as Clase); setDatos(null) }}>
        <TabsList>
          <TabsTrigger value="VENTA">Registro de ventas</TabsTrigger>
          <TabsTrigger value="COMPRA">Registro de compras</TabsTrigger>
        </TabsList>
      </Tabs>

      <Card>
        <CardContent className="grid grid-cols-1 gap-3 pt-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="space-y-1">
            <Label required htmlFor="r-periodo">Período</Label>
            <Select id="r-periodo" value={periodo} onChange={(e) => setPeriodo(e.target.value ? Number(e.target.value) : '')}>
              <option value="">Seleccione…</option>
              {periodos.map((p) => <option key={p.id} value={p.id}>{p.anio}-{String(p.mes).padStart(2, '0')} ({p.estado})</option>)}
            </Select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="r-estado">Estado</Label>
            <Select id="r-estado" value={estado} onChange={(e) => setEstado(e.target.value)}>
              <option value="">Confirmados y anulados</option>
              <option value="CONFIRMADO">Solo confirmados</option>
              <option value="ANULADO">Solo anulados</option>
              <option value="BORRADOR">Borradores</option>
            </Select>
          </div>
          <div className="flex items-end">
            <Button variant="primary" className="w-full" onClick={consultar} isLoading={cargando}>
              <Search className="h-4 w-4" /> Consultar
            </Button>
          </div>
          <div className="flex items-end">
            <Button variant="secondary" className="w-full" onClick={exportar} isLoading={exportando}>
              <FileDown className="h-4 w-4" /> Exportar Excel
            </Button>
          </div>
        </CardContent>
      </Card>

      {error && <AlertaFormulario titulo="No se pudo completar la operación" mensajes={error} />}

      {datos && (
        <Card>
          <CardContent className="space-y-3 pt-4">
            <div className="flex flex-wrap gap-3 text-xs" data-testid="totales-registro">
              {Object.entries(datos.totales).map(([m, t]) => (
                <div key={m} className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 font-mono tabular-nums">
                  <span className="font-sans font-semibold">{m}</span> · {t.comprobantes} confirmados · Base {formatearDecimal(t.base)} · IGV {formatearDecimal(t.igv)} · <strong>Total {formatearDecimal(t.total)}</strong>
                </div>
              ))}
              {Object.keys(datos.totales).length === 0 && <span className="text-slate-500">Sin comprobantes confirmados en el período.</span>}
            </div>
            <div className="overflow-x-auto">
              <Table data-testid="tabla-registro">
                <TableHeader>
                  <TableRow>
                    <TableHead>Fecha</TableHead><TableHead>Tipo</TableHead><TableHead>Serie-Número</TableHead>
                    <TableHead>{rol}</TableHead><TableHead>Moneda</TableHead>
                    <TableHead numeric>Base</TableHead><TableHead numeric>IGV</TableHead><TableHead numeric>Total</TableHead>
                    <TableHead>Condición</TableHead><TableHead>Estado</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {datos.filas.length === 0 && (
                    <TableRow><TableCell colSpan={10} className="py-8 text-center text-slate-500">Sin comprobantes en el período.</TableCell></TableRow>
                  )}
                  {datos.filas.map((f) => (
                    <TableRow key={f.id} className={f.estado === 'ANULADO' ? 'text-slate-400' : ''}>
                      <TableCell className="font-mono whitespace-nowrap">{f.fecha_emision}</TableCell>
                      <TableCell className="font-mono">{f.tipo_comprobante_codigo}</TableCell>
                      <TableCell className="font-mono whitespace-nowrap">{f.serie}-{f.numero}</TableCell>
                      <TableCell className="min-w-[180px]">
                        <span className="block">{f.tercero_razon_social || '—'}</span>
                        <span className="font-mono text-[11px] text-slate-500">{f.tercero_numero_documento}</span>
                      </TableCell>
                      <TableCell>{f.moneda_codigo}</TableCell>
                      <TableCell numeric>{formatearDecimal(f.base)}</TableCell>
                      <TableCell numeric>{formatearDecimal(f.igv)}</TableCell>
                      <TableCell numeric className="font-semibold">{formatearDecimal(f.total)}</TableCell>
                      <TableCell>{f.condicion_pago === 'CREDITO' ? 'Crédito' : 'Contado'}</TableCell>
                      <TableCell>
                        <Badge size="sm" variant={f.estado === 'CONFIRMADO' ? 'success' : f.estado === 'ANULADO' ? 'destructive' : 'neutral'}>{f.estado}</Badge>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
