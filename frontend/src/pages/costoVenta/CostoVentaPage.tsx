/**
 * Kardex → Costo de Venta.
 *
 *   Saldo inicial + Compras − Saldo final = Costo de venta
 *
 * Mismo formato que la hoja del dueño (Unid. / P.U. / Total), por producto y total de la
 * empresa, para un mes o un rango de meses. Los importes salen del Kardex (backend): esta
 * pantalla no calcula costos, solo los muestra. Exportación a Excel generada por el backend.
 */
import { useEffect, useMemo, useState } from 'react'
import { Calculator, CheckCircle2, AlertTriangle, Search, Info } from 'lucide-react'
import {
  obtenerCostoVenta, type CostoVentaResponse, type FilaCostoVenta,
} from '../../api/costoVenta'
import { obtenerPeriodos, type Periodo } from '../../api/periodos'
import { getProductos, type Producto } from '../../api/inventario'
import { useAuth } from '../../context/useAuth'
import { PageHeader } from '../../components/ui/page-header'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card'
import { Button } from '../../components/ui/button'
import { Label } from '../../components/ui/label'
import { Select } from '../../components/ui/select'
import { Badge } from '../../components/ui/badge'
import { AlertaFormulario } from '../../components/ui/alerta-formulario'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../components/ui/table'
import { formatearDecimal } from '../../utils/decimal'
import { mensajesDeErrorApi } from '../../utils/errores'
import {
  ETIQUETAS_COMPRA, ETIQUETAS_DESGLOSE, conceptosConImporte, cuadra, esCero, filasFormula,
  validarRangoPeriodos,
} from '../../utils/costoVenta'

const etiquetaPeriodo = (p: Pick<Periodo, 'anio' | 'mes'>) => `${p.anio}-${String(p.mes).padStart(2, '0')}`
const monto = (valor?: string | null) => formatearDecimal(valor)
const cantidad = (valor?: string | null) => formatearDecimal(valor, { min: 2, max: 8 })

function HojaFormula({ titulo, bloques, conUnidades }: {
  titulo: string
  bloques: Parameters<typeof filasFormula>[0]
  conUnidades: boolean
}) {
  return (
    <div className="overflow-x-auto">
      <Table data-testid="hoja-formula">
        <TableHeader>
          <TableRow>
            <TableHead className="w-8" />
            <TableHead>{titulo}</TableHead>
            {conUnidades && <TableHead numeric>Unid.</TableHead>}
            {conUnidades && <TableHead numeric>P.U.</TableHead>}
            <TableHead numeric>Total (S/)</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {filasFormula(bloques).map((f) => {
            const esResultado = f.clave === 'costo_venta'
            const esSubtotal = f.clave === 'subtotal'
            const esMerma = f.clave === 'mermas'
            return (
              <TableRow
                key={f.clave}
                className={esResultado ? 'bg-indigo-50 font-semibold' : esSubtotal ? 'text-slate-500' : esMerma ? 'text-amber-700' : ''}
              >
                <TableCell className="font-mono text-center text-base">{f.signo}</TableCell>
                <TableCell className={esSubtotal ? 'italic' : ''}>{f.etiqueta}</TableCell>
                {conUnidades && <TableCell numeric>{cantidad(f.cantidad)}</TableCell>}
                {conUnidades && <TableCell numeric>{monto(f.costoUnitario)}</TableCell>}
                <TableCell numeric className={esResultado ? 'text-base' : ''}>{monto(f.valor)}</TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}

function Desglose({ conceptos, diferencia, kardex, diferenciaMetodo }: {
  conceptos: { clave: string; etiqueta: string; valor: string }[]
  diferencia: string
  kardex: { costo_venta: { valor: string } }
  diferenciaMetodo: string
}) {
  const ok = cuadra(diferencia)
  return (
    <div className="space-y-2" data-testid="desglose">
      <div className="flex items-center gap-2 text-sm font-semibold text-slate-700">
        <Info className="h-4 w-4 text-slate-400" /> ¿De dónde sale el costo de venta?
      </div>
      {conceptos.length === 0 ? (
        <p className="text-xs text-slate-500">No hubo salidas de inventario en el período.</p>
      ) : (
        <ul className="divide-y divide-slate-100 rounded-md border border-slate-200 text-sm">
          {conceptos.map((c) => (
            <li key={c.clave} className="flex justify-between px-3 py-1.5">
              <span>{c.etiqueta}</span>
              <span className="font-mono tabular-nums">{monto(c.valor)}</span>
            </li>
          ))}
        </ul>
      )}
      <div className="flex items-center gap-2 text-xs">
        {ok ? (
          <Badge size="sm" variant="success"><CheckCircle2 className="mr-1 h-3 w-3" /> Cuadra con la fórmula</Badge>
        ) : (
          <Badge size="sm" variant="destructive"><AlertTriangle className="mr-1 h-3 w-3" /> Diferencia {monto(diferencia)}</Badge>
        )}
      </div>
      {!cuadra(diferenciaMetodo) && (
        <p className="text-xs text-slate-500" data-testid="referencia-kardex">
          Referencia: según el Kardex (promedio móvil, cambia con cada compra) el costo de venta es{' '}
          <span className="font-mono">{monto(kardex.costo_venta.valor)}</span>; diferencia por método{' '}
          <span className="font-mono">{monto(diferenciaMetodo)}</span>.
        </p>
      )}
    </div>
  )
}

export function CostoVentaPage() {
  const { empresaActiva } = useAuth()
  const [periodos, setPeriodos] = useState<Periodo[]>([])
  const [productos, setProductos] = useState<Producto[]>([])
  const [desde, setDesde] = useState<number | ''>('')
  const [hasta, setHasta] = useState<number | ''>('')
  const [producto, setProducto] = useState<number | ''>('')
  const [datos, setDatos] = useState<CostoVentaResponse | null>(null)
  const [seleccionado, setSeleccionado] = useState<number | null>(null)
  const [cargando, setCargando] = useState(false)
  const [error, setError] = useState<string[] | null>(null)

  useEffect(() => {
    if (!empresaActiva?.id) return
    let activo = true
    Promise.all([obtenerPeriodos(), getProductos().catch(() => [] as Producto[])])
      .then(([ps, prs]) => {
        if (!activo) return
        setPeriodos(ps)
        setProductos(prs)
        setDesde((actual) => actual || ps[0]?.id || '')
      })
      .catch((e) => activo && setError(mensajesDeErrorApi(e, 'No se pudieron cargar los períodos.')))
    return () => { activo = false }
  }, [empresaActiva?.id])

  const periodosOrdenados = useMemo(() => [...periodos].sort((a, b) => b.orden - a.orden), [periodos])

  const filtros = () => ({ periodo_id: desde as number, periodo_hasta_id: hasta || undefined, producto_id: producto || undefined })

  const consultar = async () => {
    const problema = validarRangoPeriodos(periodos, desde, hasta)
    if (problema) return setError([problema])
    setError(null)
    setCargando(true)
    try {
      const respuesta = await obtenerCostoVenta(filtros())
      setDatos(respuesta)
      setSeleccionado(respuesta.productos.length === 1 ? respuesta.productos[0].producto.id : null)
    } catch (e) {
      setDatos(null)
      setError(mensajesDeErrorApi(e, 'No se pudo calcular el costo de venta.'))
    } finally {
      setCargando(false)
    }
  }

  const hayMermas = !!datos && !esCero(datos.totales.mermas.valor)
  const filaSeleccionada: FilaCostoVenta | undefined = datos?.productos.find((f) => f.producto.id === seleccionado)
  const rango = datos
    ? datos.periodo_desde.id === datos.periodo_hasta.id
      ? datos.periodo_desde.etiqueta
      : `${datos.periodo_desde.etiqueta} a ${datos.periodo_hasta.etiqueta}`
    : ''

  return (
    <div className="space-y-6">
      <PageHeader
        title="Costo de Venta"
        description="Saldo inicial + Compras − Saldo final = Costo de venta, con un solo P.U.: el promedio ponderado del período. El Excel sale en Kardex Valorizado → Exportar Excel (hoja “Costo de Venta”)."
        icon={<Calculator className="h-5 w-5" />}
      />

      <Card>
        <CardContent className="grid grid-cols-1 gap-3 pt-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="space-y-1">
            <Label required htmlFor="cv-desde">Período</Label>
            <Select id="cv-desde" value={desde} onChange={(e) => setDesde(e.target.value ? Number(e.target.value) : '')}>
              <option value="">Seleccione…</option>
              {periodosOrdenados.map((p) => <option key={p.id} value={p.id}>{etiquetaPeriodo(p)} ({p.estado})</option>)}
            </Select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="cv-hasta">Hasta (opcional)</Label>
            <Select id="cv-hasta" value={hasta} onChange={(e) => setHasta(e.target.value ? Number(e.target.value) : '')}>
              <option value="">Solo ese mes</option>
              {periodosOrdenados.map((p) => <option key={p.id} value={p.id}>{etiquetaPeriodo(p)}</option>)}
            </Select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="cv-producto">Producto</Label>
            <Select id="cv-producto" value={producto} onChange={(e) => setProducto(e.target.value ? Number(e.target.value) : '')}>
              <option value="">Todos</option>
              {productos.map((p) => <option key={p.id} value={p.id}>{p.codigo_interno} — {p.descripcion}</option>)}
            </Select>
          </div>
          <div className="flex items-end">
            <Button variant="primary" className="w-full" onClick={consultar} isLoading={cargando}>
              <Search className="h-4 w-4" /> Calcular
            </Button>
          </div>
        </CardContent>
      </Card>

      {error && <AlertaFormulario titulo="No se pudo completar la operación" mensajes={error} />}

      {datos && (
        <>
          <Card>
            <CardHeader>
              <CardTitle>Costo de venta de la empresa — {rango}</CardTitle>
              <CardDescription>
                {datos.empresa.razon_social} · RUC {datos.empresa.ruc} · del {datos.fecha_inicio} al {datos.fecha_fin} · importes en soles
              </CardDescription>
            </CardHeader>
            <CardContent className="grid grid-cols-1 gap-6 lg:grid-cols-2">
              <div className="space-y-3">
                <HojaFormula titulo="Concepto" bloques={datos.totales} conUnidades={false} />
                {conceptosConImporte(datos.totales.compras_detalle, ETIQUETAS_COMPRA).length > 1 && (
                  <div className="text-xs text-slate-500" data-testid="detalle-compras">
                    <span className="font-semibold">Compras netas:</span>{' '}
                    {conceptosConImporte(datos.totales.compras_detalle, ETIQUETAS_COMPRA)
                      .map((c) => `${c.etiqueta} ${monto(c.valor)}`).join(' · ')}
                  </div>
                )}
              </div>
              <Desglose
                conceptos={conceptosConImporte(datos.totales.desglose, ETIQUETAS_DESGLOSE)}
                diferencia={datos.totales.diferencia}
                kardex={datos.totales.kardex}
                diferenciaMetodo={datos.totales.diferencia_metodo}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Por producto</CardTitle>
              <CardDescription>Haga clic en un producto para ver su cálculo con unidades y costo unitario.</CardDescription>
            </CardHeader>
            <CardContent className="overflow-x-auto">
              <Table data-testid="tabla-costo-venta">
                <TableHeader>
                  <TableRow>
                    <TableHead>Código</TableHead>
                    <TableHead>Producto</TableHead>
                    <TableHead>Unid.</TableHead>
                    <TableHead numeric>Saldo inicial</TableHead>
                    <TableHead numeric>+ Compras</TableHead>
                    <TableHead numeric>− Saldo final</TableHead>
                    {hayMermas && <TableHead numeric>− Mermas</TableHead>}
                    <TableHead numeric>P.U. promedio</TableHead>
                    <TableHead numeric>Unid. vendidas</TableHead>
                    <TableHead numeric>= Costo de venta</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {datos.productos.length === 0 && (
                    <TableRow><TableCell colSpan={hayMermas ? 10 : 9} className="py-8 text-center text-slate-500">Sin movimientos de inventario en el período.</TableCell></TableRow>
                  )}
                  {datos.productos.map((f) => (
                    <TableRow
                      key={f.producto.id}
                      onClick={() => setSeleccionado(f.producto.id)}
                      className={`cursor-pointer ${seleccionado === f.producto.id ? 'bg-indigo-50' : 'hover:bg-slate-50'}`}
                    >
                      <TableCell className="font-mono whitespace-nowrap">{f.producto.codigo}</TableCell>
                      <TableCell className="min-w-[180px]">{f.producto.descripcion}</TableCell>
                      <TableCell className="font-mono">{f.producto.unidad ?? '—'}</TableCell>
                      <TableCell numeric>{monto(f.saldo_inicial.valor)}</TableCell>
                      <TableCell numeric>{monto(f.compras.valor)}</TableCell>
                      <TableCell numeric>{monto(f.saldo_final.valor)}</TableCell>
                      {hayMermas && <TableCell numeric>{monto(f.mermas.valor)}</TableCell>}
                      <TableCell numeric>{monto(f.costo_promedio)}</TableCell>
                      <TableCell numeric>{cantidad(f.costo_venta.cantidad)}</TableCell>
                      <TableCell numeric className="font-semibold">{monto(f.costo_venta.valor)}</TableCell>
                    </TableRow>
                  ))}
                  {datos.productos.length > 1 && (
                    <TableRow className="bg-slate-50 font-semibold">
                      <TableCell colSpan={3}>TOTAL EMPRESA</TableCell>
                      <TableCell numeric>{monto(datos.totales.saldo_inicial.valor)}</TableCell>
                      <TableCell numeric>{monto(datos.totales.compras.valor)}</TableCell>
                      <TableCell numeric>{monto(datos.totales.saldo_final.valor)}</TableCell>
                      {hayMermas && <TableCell numeric>{monto(datos.totales.mermas.valor)}</TableCell>}
                      <TableCell numeric />
                      <TableCell numeric />
                      <TableCell numeric>{monto(datos.totales.costo_venta.valor)}</TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          {filaSeleccionada && (
            <Card data-testid="detalle-producto">
              <CardHeader>
                <CardTitle>{filaSeleccionada.producto.codigo} — {filaSeleccionada.producto.descripcion}</CardTitle>
                <CardDescription>Costo de venta {rango} · unidad {filaSeleccionada.producto.unidad ?? '—'} · P.U. = promedio ponderado del período</CardDescription>
              </CardHeader>
              <CardContent className="grid grid-cols-1 gap-6 lg:grid-cols-2">
                <HojaFormula titulo="Concepto" bloques={filaSeleccionada} conUnidades />
                <Desglose
                  conceptos={conceptosConImporte(filaSeleccionada.desglose, ETIQUETAS_DESGLOSE)}
                  diferencia={filaSeleccionada.diferencia}
                  kardex={filaSeleccionada.kardex}
                  diferenciaMetodo={filaSeleccionada.diferencia_metodo}
                />
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  )
}
