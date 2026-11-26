/**
 * Kardex → Costo de Venta «Por año»: el costo de cada mes según el Kardex (saldo inicial + compras
 * − saldo final) y su suma. La comparación con el promedio ponderado de cada mes está oculta por
 * defecto y se muestra con un botón. Es el mismo cálculo de la hoja «Costo de Venta» del Excel
 * (que conserva sus columnas). Solo consulta: los importes vienen del backend.
 */
import { useState } from 'react'
import { Eye, EyeOff, Search } from 'lucide-react'
import { obtenerCostoVentaAnual, type CostoVentaAnualResponse } from '../../api/costoVenta'
import type { Periodo } from '../../api/periodos'
import type { Producto } from '../../api/inventario'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card'
import { Button } from '../../components/ui/button'
import { Label } from '../../components/ui/label'
import { Select } from '../../components/ui/select'
import { AlertaFormulario } from '../../components/ui/alerta-formulario'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../../components/ui/table'
import { formatearDecimal } from '../../utils/decimal'
import { mensajesDeErrorApi } from '../../utils/errores'
import { aniosDePeriodos, conSigno, esCero, textosComparacion } from '../../utils/costoVenta'

const monto = (valor?: string | null) => formatearDecimal(valor)

const COLUMNAS: { clave: 'saldo_inicial' | 'compras' | 'saldo_final' | 'no_atribuibles'; titulo: string }[] = [
  { clave: 'saldo_inicial', titulo: 'Saldo inicial' },
  { clave: 'compras', titulo: '+ Compras' },
  { clave: 'saldo_final', titulo: '− Saldo final (Kardex)' },
  { clave: 'no_atribuibles', titulo: '− Salidas que no son ventas' },
]

export function CostoVentaAnual({ periodos, productos }: { periodos: Periodo[]; productos: Producto[] }) {
  const anios = aniosDePeriodos(periodos)
  const [anio, setAnio] = useState<number | ''>('')
  const [producto, setProducto] = useState<number | ''>('')
  const [datos, setDatos] = useState<CostoVentaAnualResponse | null>(null)
  const [cargando, setCargando] = useState(false)
  const [error, setError] = useState<string[] | null>(null)
  const [verComparacion, setVerComparacion] = useState(false)
  const textos = textosComparacion(false)
  const anioElegido = anio || anios[0] || ''

  const consultar = async () => {
    if (!anioElegido) return setError(['Seleccione el año.'])
    setError(null)
    setCargando(true)
    try {
      setDatos(await obtenerCostoVentaAnual({ anio: anioElegido, producto_id: producto || undefined }))
    } catch (e) {
      setDatos(null)
      setError(mensajesDeErrorApi(e, 'No se pudo calcular el costo de venta del año.'))
    } finally {
      setCargando(false)
    }
  }

  const hayNoVentas = !!datos && !esCero(datos.total.no_atribuibles)
  const nombreProducto = datos?.producto_id
    ? productos.find((p) => p.id === datos.producto_id)?.codigo_interno ?? `#${datos.producto_id}`
    : 'todos los productos'

  return (
    <>
      <Card>
        <CardContent className="grid grid-cols-1 gap-3 pt-4 sm:grid-cols-3">
          <div className="space-y-1">
            <Label required htmlFor="cv-anio">Año</Label>
            <Select id="cv-anio" value={anioElegido} onChange={(e) => { setAnio(e.target.value ? Number(e.target.value) : ''); setDatos(null) }}>
              {anios.length === 0 && <option value="">Sin períodos</option>}
              {anios.map((a) => <option key={a} value={a}>{a}</option>)}
            </Select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="cv-anio-producto">Producto</Label>
            <Select id="cv-anio-producto" value={producto} onChange={(e) => { setProducto(e.target.value ? Number(e.target.value) : ''); setDatos(null) }}>
              <option value="">Todos</option>
              {productos.map((p) => <option key={p.id} value={p.id}>{p.codigo_interno} — {p.descripcion}</option>)}
            </Select>
          </div>
          <div className="flex items-end">
            <Button variant="primary" className="w-full" onClick={consultar} isLoading={cargando} disabled={!anioElegido}>
              <Search className="h-4 w-4" /> Calcular
            </Button>
          </div>
        </CardContent>
      </Card>

      {error && <AlertaFormulario titulo="No se pudo completar la operación" mensajes={error} />}

      {datos && (
        <Card data-testid="costo-venta-anual">
          <CardHeader>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <CardTitle>Costo de venta {datos.anio} — {nombreProducto}</CardTitle>
              <Button
                variant="outline" size="sm" onClick={() => setVerComparacion((v) => !v)}
                aria-pressed={verComparacion} data-testid="boton-comparacion"
              >
                {verComparacion ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                {verComparacion ? textos.ocultar : textos.ver}
              </Button>
            </div>
            <CardDescription>
              {datos.empresa.razon_social} · RUC {datos.empresa.ruc} · importes en soles
              <span className="mt-1 block text-[11px] text-slate-500" data-testid="metodo-costo-venta">
                <b>Método: suma mensual del costo según Kardex.</b> Cada mes = saldo inicial + compras − saldo final según el Kardex,
                menos las salidas que no son ventas.
                {verComparacion && ' Las columnas amarillas comparan con el promedio ponderado de cada mes.'}
              </span>
            </CardDescription>
          </CardHeader>
          <CardContent className="overflow-x-auto p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Mes</TableHead>
                  {COLUMNAS.filter((c) => c.clave !== 'no_atribuibles' || hayNoVentas).map((c) => (
                    <TableHead key={c.clave} numeric>{c.titulo}</TableHead>
                  ))}
                  <TableHead numeric>Costo de venta (Kardex)</TableHead>
                  {verComparacion && <TableHead numeric className="bg-amber-50">{textos.columnaPromedio}</TableHead>}
                  {verComparacion && <TableHead numeric className="bg-amber-50">{textos.columnaDiferencia}</TableHead>}
                </TableRow>
              </TableHeader>
              <TableBody>
                {datos.meses.map((m) => (
                  <TableRow key={m.periodo.id}>
                    <TableCell className="whitespace-nowrap font-mono">{m.periodo.etiqueta}</TableCell>
                    {COLUMNAS.filter((c) => c.clave !== 'no_atribuibles' || hayNoVentas).map((c) => (
                      <TableCell key={c.clave} numeric>{monto(m[c.clave])}</TableCell>
                    ))}
                    <TableCell numeric className="font-semibold">{monto(m.costo_venta)}</TableCell>
                    {verComparacion && <TableCell numeric className="bg-amber-50/40 text-slate-600">{monto(m.costo_venta_promedio)}</TableCell>}
                    {verComparacion && (
                      <TableCell numeric className={`bg-amber-50/40 ${esCero(m.diferencia_metodo) ? 'text-slate-400' : 'text-amber-700'}`}>
                        {conSigno(monto(m.diferencia_metodo))}
                      </TableCell>
                    )}
                  </TableRow>
                ))}
                <TableRow className="bg-indigo-50 font-semibold" data-testid="total-anual">
                  <TableCell className="whitespace-nowrap">Total {datos.anio}</TableCell>
                  {COLUMNAS.filter((c) => c.clave !== 'no_atribuibles' || hayNoVentas).map((c) => (
                    <TableCell key={c.clave} numeric>{monto(datos.total[c.clave])}</TableCell>
                  ))}
                  <TableCell numeric className="text-base" data-testid="costo-kardex-total">{monto(datos.total.costo_venta)}</TableCell>
                  {verComparacion && <TableCell numeric data-testid="promedio-total">{monto(datos.total.costo_venta_promedio)}</TableCell>}
                  {verComparacion && (
                    <TableCell numeric className="text-amber-700" data-testid="diferencia-total">{conSigno(monto(datos.total.diferencia_metodo))}</TableCell>
                  )}
                </TableRow>
              </TableBody>
            </Table>
            <p className="px-4 py-3 text-xs text-slate-500">
              En la fila Total, el saldo inicial es el de enero y el saldo final el del último mes; compras, salidas y costos son la suma de los meses.
              El costo según Kardex cuadra con el inventario valorizado{verComparacion ? '; el promedio mensual es solo una comparación.' : '.'}
            </p>
          </CardContent>
        </Card>
      )}
    </>
  )
}
