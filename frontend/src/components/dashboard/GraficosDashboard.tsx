import React, { useEffect, useMemo, useState } from 'react';
import {
  Bar, CartesianGrid, Cell, ComposedChart, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts';
import {
  ArrowDownRight, ArrowUpRight, BarChart3, Boxes, ChevronDown, ChevronUp, Clock, Coins, Lightbulb, Minus, PackageX,
  PieChart as IconoDona, ShoppingCart, Star, Tag, TrendingUp, Trophy, Wallet,
} from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../ui/card';
import { obtenerGraficosDashboard, type GraficosDashboardResponse, type Kpi } from '../../api/dashboard';
import { getProductos } from '../../api/inventario';
import { SelectorProducto } from './SelectorProducto';
import { comparar, formatearDecimal } from '../../utils/decimal';
import {
  COLORES, anchoMargen, destacados, esNegativo, etiquetaMes, haySerie, nombreMes, ordenarProductos, participacionGrafico,
  serieMensualGrafico, tendencia, tendenciaKpi, topInventarioGrafico, type BarraProducto, type ColumnaProducto,
  type Destacado, type OpcionProducto, type TonoDestacado,
} from '../../utils/graficosDashboard';

const unDecimal = new Intl.NumberFormat('es-PE', { maximumFractionDigits: 1 });
const eje = (v: number) => (Math.abs(v) >= 1_000_000 ? `${unDecimal.format(v / 1_000_000)} M`
  : Math.abs(v) >= 1_000 ? `${unDecimal.format(v / 1_000)} mil` : unDecimal.format(v));
const soles = (texto: string | null | undefined) => (texto == null ? '—' : `S/ ${formatearDecimal(texto)}`);
const pct = (texto: string | null | undefined) => (texto == null ? '—' : `${formatearDecimal(texto)} %`);
const cantidad = (texto: string | null | undefined) => formatearDecimal(texto, { min: 0, max: 2 });

const leyenda = (valor: string) => <span className="text-slate-600">{valor}</span>;
const EJE_TICK = { fontSize: 11, fill: '#64748b' };
const GRID = '#e2e8f0';

interface FilaTooltip { name?: string | number; color?: string; dataKey?: string | number; payload?: Record<string, unknown> }
interface PropsTooltip { active?: boolean; payload?: readonly FilaTooltip[]; label?: string | number }

const CajaTooltip: React.FC<{ titulo?: React.ReactNode; children: React.ReactNode }> = ({ titulo, children }) => (
  <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-lg">
    {titulo && <p className="mb-1.5 font-semibold text-slate-900">{titulo}</p>}
    <div className="space-y-1">{children}</div>
  </div>
);

const FilaValor: React.FC<{ color?: string; nombre: React.ReactNode; valor: string }> = ({ color, nombre, valor }) => (
  <p className="flex items-center justify-between gap-4 text-slate-600">
    <span className="flex items-center gap-1.5">
      {color && <span className="h-2 w-2 rounded-full" style={{ background: color }} />}{nombre}
    </span>
    <span className="font-mono font-semibold text-slate-900 tabular-nums">{valor}</span>
  </p>
);

const TooltipMensual: React.FC<PropsTooltip & { conMargen?: boolean }> = ({ active, payload, label, conMargen }) => {
  if (!active || !payload?.length) return null;
  const datos = payload[0].payload ?? {};
  return (
    <CajaTooltip titulo={label}>
      {payload.map((fila) => (
        <FilaValor key={String(fila.dataKey)} color={fila.color} nombre={fila.name}
          valor={soles(String(datos[`${String(fila.dataKey)}Texto`] ?? '0'))} />
      ))}
      {conMargen && <FilaValor nombre="Margen %" valor={pct(datos.margenPct as string | null)} />}
    </CajaTooltip>
  );
};

const TooltipDona: React.FC<PropsTooltip> = ({ active, payload }) => {
  const fila = payload?.[0]?.payload;
  if (!active || !fila) return null;
  return (
    <CajaTooltip titulo={String(fila.nombre)}>
      <FilaValor nombre="Ventas" valor={soles(String(fila.ventasTexto))} />
      <FilaValor nombre="Participación" valor={pct(fila.porcentaje as string | null)} />
    </CajaTooltip>
  );
};

const SinDatos: React.FC<{ texto: string }> = ({ texto }) => (
  <div className="flex h-full min-h-40 items-center justify-center rounded-lg border border-dashed border-slate-200 text-xs text-slate-500">
    {texto}
  </div>
);

const Panel: React.FC<{
  titulo: string; descripcion: string; icono: React.ReactNode; className?: string; extra?: React.ReactNode;
  children: React.ReactNode;
}> = ({ titulo, descripcion, icono, className, extra, children }) => (
  <Card className={`border-slate-200/90 shadow-2xs overflow-hidden ${className ?? ''}`}>
    <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0 border-b border-slate-100 px-4 py-3">
      <div>
        <CardTitle className="flex items-center gap-2 text-sm font-semibold text-slate-900">{icono}{titulo}</CardTitle>
        <CardDescription className="mt-0.5 text-xs">{descripcion}</CardDescription>
      </div>
      {extra}
    </CardHeader>
    <CardContent className="p-4">{children}</CardContent>
  </Card>
);

const Variacion: React.FC<{ kpi: Kpi; invertir?: boolean; mesAnterior: string | null }> = ({ kpi, invertir, mesAnterior }) => {
  const t = tendencia(kpi);
  if (t === 'sin-dato') return <span className="text-[11px] text-slate-400">Sin mes anterior para comparar</span>;
  const bueno = t === 'igual' ? null : (t === 'sube') !== Boolean(invertir);
  const estilo = bueno === null ? 'bg-slate-100 text-slate-600' : bueno ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700';
  const Icono = t === 'sube' ? ArrowUpRight : t === 'baja' ? ArrowDownRight : Minus;
  return (
    <span className="flex items-center gap-1.5 whitespace-nowrap text-[11px] text-slate-500">
      <span className={`inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 font-semibold ${estilo}`}>
        <Icono className="h-3 w-3" />{formatearDecimal(kpi.variacion_pct ?? '0', { min: 1, max: 1 })} %
      </span>
      vs {mesAnterior ?? 'mes anterior'}
    </span>
  );
};

const MiniTendencia: React.FC<{ puntos: { i: number; v: number }[]; color: string }> = ({ puntos, color }) => (
  <div className="h-7 w-16 shrink-0" aria-hidden="true">
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={puntos} margin={{ top: 3, right: 3, bottom: 3, left: 3 }}>
        <Line dataKey="v" type="monotone" stroke={color} strokeWidth={2} dot={false} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  </div>
);

const TarjetaKpi: React.FC<{
  titulo: string; valor: string; icono: React.ReactNode; acento: string; pie: React.ReactNode; detalle?: React.ReactNode;
  puntos?: { i: number; v: number }[];
}> = ({ titulo, valor, icono, acento, pie, detalle, puntos }) => (
  <div className="relative overflow-hidden rounded-xl border border-slate-200/90 bg-white p-4 shadow-2xs">
    <span className="absolute inset-y-0 left-0 w-1" style={{ background: acento }} />
    <div className="flex items-start justify-between gap-2">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{titulo}</p>
      <span className="rounded-lg p-1.5" style={{ background: `${acento}14`, color: acento }}>{icono}</span>
    </div>
    <p className="mt-1 whitespace-nowrap font-mono text-xl font-bold text-slate-900 tabular-nums">{valor}</p>
    {detalle && <p className="text-[11px] text-slate-500">{detalle}</p>}
    <div className="mt-2 flex items-center justify-between gap-2">
      {pie}
      {puntos && puntos.length > 1 && <MiniTendencia puntos={puntos} color={acento} />}
    </div>
  </div>
);

const ICONOS_DESTACADO: Record<string, React.ReactNode> = {
  mejor: <Trophy className="h-3.5 w-3.5" />,
  top: <Star className="h-3.5 w-3.5" />,
  margen: <Wallet className="h-3.5 w-3.5" />,
  compras: <ShoppingCart className="h-3.5 w-3.5" />,
  stock: <Clock className="h-3.5 w-3.5" />,
  quietos: <PackageX className="h-3.5 w-3.5" />,
};

const ESTILO_TONO: Record<TonoDestacado, string> = {
  bueno: 'bg-emerald-50 text-emerald-700',
  malo: 'bg-rose-50 text-rose-700',
  neutro: 'bg-slate-100 text-slate-600',
};

const LoDestacado: React.FC<{ frases: Destacado[] }> = ({ frases }) => (
  frases.length ? (
    <ul className="space-y-3">
      {frases.map((f) => (
        <li key={f.clave} className="flex items-start gap-2.5 text-xs leading-relaxed text-slate-700">
          <span className={`mt-0.5 shrink-0 rounded-md p-1 ${ESTILO_TONO[f.tono]}`}>{ICONOS_DESTACADO[f.clave]}</span>
          <span className={f.tono === 'malo' ? 'text-rose-800' : ''}>{f.texto}</span>
        </li>
      ))}
    </ul>
  ) : <SinDatos texto="Registra ventas y compras para ver lo destacado del mes." />
);

const ListaInventario: React.FC<{ filas: BarraProducto[]; hayVentas: boolean }> = ({ filas, hayVentas }) => (
  <ul className="space-y-2.5">
    {filas.map((f) => (
      <li key={f.id} className="text-xs" title={f.detalle}>
        <div className="flex items-center justify-between gap-2">
          <span className="truncate text-slate-700">{f.nombre}</span>
          <span className="shrink-0 font-mono font-semibold tabular-nums text-slate-900">{soles(f.valorTexto)}</span>
        </div>
        <div className="mt-1 flex items-center gap-2">
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100">
            <div className="h-full rounded-full" style={{ width: `${f.ancho}%`, background: COLORES.inventario }} />
          </div>
          <span className={`w-36 shrink-0 whitespace-nowrap text-right text-[11px] ${f.diasStock == null && hayVentas ? 'text-rose-600' : 'text-slate-500'}`}>
            {f.diasStock != null ? `~${f.diasStock} días · ${cantidad(f.cantidadTexto)} u.` : hayVentas ? 'Sin ventas en el mes' : `${cantidad(f.cantidadTexto)} u.`}
          </span>
        </div>
      </li>
    ))}
  </ul>
);

const ENCABEZADOS: { columna: ColumnaProducto | null; texto: string; clase?: string }[] = [
  { columna: null, texto: 'Producto', clase: 'text-left' },
  { columna: 'unidades', texto: 'Unid. vendidas' },
  { columna: 'ventas', texto: 'Ventas' },
  { columna: 'costo_venta', texto: 'Costo de venta' },
  { columna: null, texto: 'Costo unit.' },
  { columna: 'margen', texto: 'Margen' },
  { columna: 'margen_pct', texto: 'Margen %' },
];

const TablaProductos: React.FC<{ datos: GraficosDashboardResponse; onElegir: (id: number) => void }> = ({ datos, onElegir }) => {
  const [orden, setOrden] = useState<{ columna: ColumnaProducto; desc: boolean }>({ columna: 'ventas', desc: true });
  const [todos, setTodos] = useState(false);
  const filas = useMemo(() => ordenarProductos(datos.productos, orden.columna, orden.desc), [datos.productos, orden]);
  const visibles = todos ? filas : filas.slice(0, 8);
  if (!filas.length) return <SinDatos texto="Sin ventas ni costo de venta en el período." />;
  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full whitespace-nowrap text-xs">
          <thead>
            <tr className="border-b border-slate-200 text-[11px] uppercase tracking-wide text-slate-500">
              {ENCABEZADOS.map((e) => (
                <th key={e.texto} className={`px-2 py-2 font-semibold ${e.clase ?? 'text-right'}`}>
                  {e.columna ? (
                    <button type="button" className="inline-flex items-center gap-0.5 hover:text-slate-900"
                      onClick={() => setOrden((o) => ({ columna: e.columna!, desc: o.columna === e.columna ? !o.desc : true }))}>
                      {e.texto}
                      {orden.columna === e.columna && (orden.desc ? <ChevronDown className="h-3 w-3" /> : <ChevronUp className="h-3 w-3" />)}
                    </button>
                  ) : e.texto}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visibles.map((f) => {
              const negativo = esNegativo(f.margen);
              return (
                <tr key={f.producto.id} onClick={() => onElegir(f.producto.id)} title="Ver solo este producto"
                  className="cursor-pointer border-b border-slate-100 last:border-0 hover:bg-blue-50/50">
                  <td className="max-w-64 px-2 py-2">
                    <p className="truncate font-medium text-slate-800" title={f.producto.descripcion}>{f.producto.descripcion}</p>
                    <p className="font-mono text-[10px] text-slate-400">{f.producto.codigo}</p>
                  </td>
                  <td className="px-2 py-2 text-right font-mono tabular-nums text-slate-700">
                    {cantidad(f.unidades)} <span className="text-slate-400">{f.unidad ?? ''}</span>
                  </td>
                  <td className="px-2 py-2 text-right font-mono font-semibold tabular-nums text-slate-900">{soles(f.ventas)}</td>
                  <td className="px-2 py-2 text-right font-mono tabular-nums text-slate-700">{soles(f.costo_venta)}</td>
                  <td className="px-2 py-2 text-right font-mono tabular-nums text-slate-500">
                    {f.costo_unitario ? `S/ ${formatearDecimal(f.costo_unitario, { min: 2, max: 4 })}` : '—'}
                  </td>
                  <td className={`px-2 py-2 text-right font-mono font-semibold tabular-nums ${negativo ? 'text-rose-600' : 'text-emerald-700'}`}>
                    {soles(f.margen)}
                  </td>
                  <td className="px-2 py-2">
                    <div className="flex items-center justify-end gap-2">
                      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-100">
                        <div className={`h-full rounded-full ${negativo ? 'bg-rose-500' : 'bg-emerald-500'}`}
                          style={{ width: `${anchoMargen(f.margen_pct)}%` }} />
                      </div>
                      <span className={`w-16 text-right font-mono font-semibold tabular-nums ${
                        f.margen_pct == null ? 'text-slate-400' : negativo ? 'text-rose-700' : 'text-emerald-700'}`}>
                        {pct(f.margen_pct)}
                      </span>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {filas.length > 8 && (
        <button type="button" onClick={() => setTodos((t) => !t)}
          className="mt-2 text-xs font-medium text-blue-600 hover:text-blue-700">
          {todos ? 'Ver menos' : `Ver los ${filas.length} productos`}
        </button>
      )}
    </div>
  );
};

const Selector: React.FC<{ meses: number; onCambio: (m: number) => void }> = ({ meses, onCambio }) => (
  <div className="inline-flex rounded-lg border border-slate-200 bg-slate-50 p-0.5 text-[11px] font-medium">
    {[6, 12].map((m) => (
      <button key={m} type="button" onClick={() => onCambio(m)}
        className={`rounded-md px-2.5 py-1 transition-colors ${meses === m ? 'bg-white text-slate-900 shadow-xs' : 'text-slate-500 hover:text-slate-800'}`}>
        {m} meses
      </button>
    ))}
  </div>
);

/** Dashboard de ventas, costo de venta, margen e inventario. Se carga aparte para no sumar recharts al resto. */
const GraficosDashboard: React.FC<{ periodoId: number | null; empresaId: number; recarga: number }> = ({
  periodoId, empresaId, recarga,
}) => {
  const [datos, setDatos] = useState<GraficosDashboardResponse | null>(null);
  const [error, setError] = useState(false);
  const [meses, setMeses] = useState(6);
  const [productoId, setProductoId] = useState<number | null>(null);
  const [productos, setProductos] = useState<OpcionProducto[]>([]);
  const [empresaFiltro, setEmpresaFiltro] = useState(empresaId);

  if (empresaFiltro !== empresaId) {
    setEmpresaFiltro(empresaId);
    setProductoId(null);
  }

  useEffect(() => {
    let vigente = true;
    getProductos()
      .then((lista) => { if (vigente) setProductos(lista); })
      .catch(() => { if (vigente) setProductos([]); });
    return () => { vigente = false; };
  }, [empresaId]);

  useEffect(() => {
    let vigente = true;
    obtenerGraficosDashboard(periodoId, meses, productoId)
      .then((r) => { if (vigente) { setDatos(r); setError(false); } })
      .catch(() => { if (vigente) setError(true); });
    return () => { vigente = false; };
  }, [periodoId, empresaId, recarga, meses, productoId]);

  const elegirProducto = (id: number | null) => {
    setProductoId(id);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  if (error) {
    return (
      <div role="status" className="rounded-lg border border-amber-200 bg-amber-50/90 p-3 text-xs text-amber-800">
        No se pudieron cargar los indicadores. Use “Actualizar” para reintentar.
      </div>
    );
  }
  if (!datos) return <div className="h-96 animate-pulse rounded-xl border border-slate-200 bg-slate-50" />;

  const barras = serieMensualGrafico(datos.serie_mensual);
  const inventario = topInventarioGrafico(datos.inventario.top_productos);
  const dona = participacionGrafico(datos.participacion);
  const k = datos.kpis;
  const serie = datos.serie_mensual;
  const previo = serie.length > 1 ? serie[serie.length - 2].periodo : null;
  const mesAnterior = previo ? etiquetaMes(previo.anio, previo.mes) : null;
  const mesActual = datos.periodo ? nombreMes(datos.periodo.anio, datos.periodo.mes) : 'sin período';
  const mejor = datos.mejor_mes;
  const filtro = datos.producto;
  const stockProducto = filtro ? datos.inventario.top_productos[0]?.cantidad ?? '0' : null;

  return (
    <div className="space-y-4" data-testid="dashboard-graficos">
      <div className="flex flex-wrap items-center gap-3">
        <SelectorProducto productos={productos} valor={productoId} onCambio={elegirProducto} />
        {filtro ? (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-blue-50 px-3 py-1 text-xs text-blue-800 ring-1 ring-blue-100">
            Viendo solo <span className="font-semibold">{filtro.descripcion}</span>
            <span className="font-mono text-[10px] text-blue-500">{filtro.codigo}</span>
          </span>
        ) : (
          <span className="text-xs text-slate-400">Elige un producto o haz clic en una fila de la tabla para ver solo ese producto.</span>
        )}
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5" data-testid="dashboard-kpis">
        <TarjetaKpi titulo="Ventas netas" puntos={tendenciaKpi(serie, 'ventas')} valor={soles(k?.ventas.actual)} acento={COLORES.ventas}
          icono={<TrendingUp className="h-4 w-4" />}
          detalle={`${k?.comprobantes ?? 0} ${k?.comprobantes === 1 ? 'comprobante' : 'comprobantes'} · sin IGV`}
          pie={k ? <Variacion kpi={k.ventas} mesAnterior={mesAnterior} /> : null} />
        <TarjetaKpi titulo="Costo de venta" puntos={tendenciaKpi(serie, 'costo_venta')} valor={soles(k?.costo_venta.actual)} acento={COLORES.costoVenta}
          icono={<Tag className="h-4 w-4" />} detalle="Promedio ponderado del mes"
          pie={k ? <Variacion kpi={k.costo_venta} invertir mesAnterior={mesAnterior} /> : null} />
        <TarjetaKpi titulo="Margen bruto" puntos={tendenciaKpi(serie, 'margen')} valor={soles(k?.margen.actual)} acento={COLORES.margen}
          icono={<Wallet className="h-4 w-4" />} detalle={`${pct(k?.margen_pct)} de las ventas`}
          pie={k ? <Variacion kpi={k.margen} mesAnterior={mesAnterior} /> : null} />
        <TarjetaKpi titulo="Compras" puntos={tendenciaKpi(serie, 'compras')} valor={soles(k?.compras.actual)} acento={COLORES.compras}
          icono={<ShoppingCart className="h-4 w-4" />} detalle="Ingresos valorizados al Kardex"
          pie={k ? <Variacion kpi={k.compras} invertir mesAnterior={mesAnterior} /> : null} />
        <TarjetaKpi titulo="Valor del inventario" valor={soles(datos.inventario.valor_total)} acento={COLORES.inventario}
          icono={<Coins className="h-4 w-4" />}
          detalle={stockProducto !== null ? `Stock: ${cantidad(stockProducto)} unidades` : `${datos.inventario.productos_con_stock} productos con stock`}
          pie={<span className="text-[11px] text-slate-400">Saldo actual CPP · PEN</span>} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        <Panel
          className="lg:col-span-8"
          titulo="Ventas, costo de venta y margen por mes"
          descripcion="S/ sin IGV · las notas de crédito restan"
          icono={<BarChart3 className="h-4 w-4 text-blue-600" />}
          extra={<Selector meses={meses} onCambio={setMeses} />}
        >
          {haySerie(barras) ? (
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={barras} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} barGap={2}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={GRID} />
                  <XAxis dataKey="mes" tick={{ ...EJE_TICK, fill: '#475569' }} tickLine={false} axisLine={false} />
                  <YAxis tickFormatter={eje} tick={EJE_TICK} tickLine={false} axisLine={false} width={56} />
                  <Tooltip content={<TooltipMensual conMargen />} cursor={{ fill: '#f1f5f9' }} />
                  <Legend iconType="circle" iconSize={8} itemSorter={null} formatter={leyenda} wrapperStyle={{ fontSize: 12 }} />
                  <Bar dataKey="ventas" name="Ventas" fill={COLORES.ventas} radius={[4, 4, 0, 0]} maxBarSize={30}>
                    {barras.map((b) => (
                      <Cell key={b.id} fill={COLORES.ventas} fillOpacity={mejor && b.id === mejor.periodo.id ? 1 : 0.85} />
                    ))}
                  </Bar>
                  <Bar dataKey="costoVenta" name="Costo de venta" fill={COLORES.costoVenta} radius={[4, 4, 0, 0]} maxBarSize={30} />
                  <Line dataKey="margen" name="Margen bruto" type="monotone" stroke={COLORES.margen} strokeWidth={2}
                    dot={{ r: 4, strokeWidth: 2, fill: '#fff' }} activeDot={{ r: 5 }} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          ) : <SinDatos texto="Aún no hay ventas ni compras confirmadas." />}
        </Panel>

        <Panel
          className="lg:col-span-4"
          titulo="Lo destacado"
          descripcion={filtro ? `${filtro.descripcion} · ${mesActual}` : `Lo que tienes que saber de ${mesActual}`}
          icono={<Lightbulb className="h-4 w-4 text-amber-500" />}
        >
          <LoDestacado frases={destacados(datos)} />
        </Panel>
      </div>

      <Panel
        titulo="Rentabilidad por producto"
        descripcion={`Costo de venta real (promedio ponderado del mes) frente a lo vendido · ${mesActual}`}
        icono={<Wallet className="h-4 w-4 text-emerald-600" />}
      >
        <TablaProductos datos={datos} onElegir={elegirProducto} />
      </Panel>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        <Panel
          className="lg:col-span-4"
          titulo={filtro ? 'Peso en las ventas del mes' : 'Participación en ventas'}
          descripcion={filtro ? `Frente al resto de productos · ${mesActual}` : `Productos que más venden · ${mesActual}`}
          icono={<IconoDona className="h-4 w-4 text-blue-600" />}
        >
          {dona.length ? (
            <div>
              <div className="relative h-44">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={dona} dataKey="valor" nameKey="nombre" innerRadius="68%" outerRadius="92%" paddingAngle={2}
                      stroke="#fff" strokeWidth={2}>
                      {dona.map((s) => <Cell key={s.nombre} fill={s.color} />)}
                    </Pie>
                    <Tooltip content={<TooltipDona />} />
                  </PieChart>
                </ResponsiveContainer>
                <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
                  <p className="text-[10px] uppercase tracking-wide text-slate-400">{filtro ? 'Participa' : 'Ventas'}</p>
                  <p className="font-mono text-[11px] font-bold text-slate-900 tabular-nums">
                    {filtro ? pct(dona[0]?.porcentaje) : soles(k?.ventas.actual)}
                  </p>
                </div>
              </div>
              <ul className="mt-3 space-y-1.5">
                {dona.map((s) => (
                  <li key={s.nombre} className="flex items-center justify-between gap-2 text-xs">
                    <span className="flex min-w-0 items-center gap-2 text-slate-700">
                      <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: s.color }} />
                      <span className="truncate" title={s.nombre}>{s.nombre}</span>
                    </span>
                    <span className="shrink-0 font-mono font-semibold tabular-nums text-slate-900">{pct(s.porcentaje)}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : <SinDatos texto="Sin ventas en el período." />}
        </Panel>
        <Panel
          className="lg:col-span-4"
          titulo="Inventario valorizado"
          descripcion={`Valor en almacén y cuántos días alcanza al ritmo de venta · total ${soles(datos.inventario.valor_total)}`}
          icono={<Boxes className="h-4 w-4 text-slate-600" />}
        >
          {inventario.length
            ? <ListaInventario filas={inventario} hayVentas={comparar(k?.ventas.actual ?? '0', '0') > 0} />
            : <SinDatos texto="Sin existencias valorizadas." />}
        </Panel>
        <Panel
          className="lg:col-span-4"
          titulo="Compras vs. ventas"
          descripcion="Lo que entra al almacén frente a lo que se vende · S/"
          icono={<ShoppingCart className="h-4 w-4 text-green-700" />}
        >
          {haySerie(barras) ? (
            <div className="h-60">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={barras} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke={GRID} />
                  <XAxis dataKey="mes" tick={{ ...EJE_TICK, fill: '#475569' }} tickLine={false} axisLine={false} />
                  <YAxis tickFormatter={eje} tick={EJE_TICK} tickLine={false} axisLine={false} width={56} />
                  <Tooltip content={<TooltipMensual />} />
                  <Legend iconType="circle" iconSize={8} itemSorter={null} formatter={leyenda} wrapperStyle={{ fontSize: 12 }} />
                  <Line dataKey="ventas" name="Ventas" type="monotone" stroke={COLORES.ventas} strokeWidth={2}
                    dot={{ r: 4, strokeWidth: 2, fill: '#fff' }} />
                  <Line dataKey="compras" name="Compras" type="monotone" stroke={COLORES.compras} strokeWidth={2}
                    dot={{ r: 4, strokeWidth: 2, fill: '#fff' }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : <SinDatos texto="Sin movimientos todavía." />}
        </Panel>
      </div>
    </div>
  );
};

export default GraficosDashboard;
