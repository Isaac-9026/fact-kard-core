/**
 * Datos de los gráficos del dashboard. Los importes llegan como texto decimal: el número
 * solo se usa para dibujar (alto de barras, ángulos); lo que se lee siempre sale del texto original.
 */
import type {
  GraficosDashboardResponse, Kpi, ProductoInventario, ProductoVenta, PuntoMensual, SectorParticipacion,
} from '../api/dashboard.ts';
import { comparar, formatearDecimal, restar } from './decimal.ts';

const MESES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Set', 'Oct', 'Nov', 'Dic'];
const MESES_LARGOS = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'setiembre',
  'octubre', 'noviembre', 'diciembre'];

export const COLORES = {
  ventas: '#2a78d6',
  costoVenta: '#eb6834',
  margen: '#1baf7a',
  compras: '#008300',
  inventario: '#475569',
  otros: '#94a3b8',
} as const;

export const COLORES_PARTICIPACION = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4'] as const;

/** Solo para geometría del gráfico; nunca para mostrar ni para operar importes. */
export const aNumeroGrafico = (texto: string | null | undefined): number => {
  const n = Number(texto);
  return Number.isFinite(n) ? n : 0;
};

export const etiquetaMes = (anio: number, mes: number): string => `${MESES[mes - 1] ?? mes} ${String(anio).slice(-2)}`;

export const nombreMes = (anio: number, mes: number): string => `${MESES_LARGOS[mes - 1] ?? mes} ${anio}`;

export const recortar = (texto: string, maximo = 18): string =>
  texto.length > maximo ? `${texto.slice(0, maximo - 1).trimEnd()}…` : texto;

export type Tendencia = 'sube' | 'baja' | 'igual' | 'sin-dato';

export const tendencia = (kpi: Pick<Kpi, 'variacion_pct'> | null | undefined): Tendencia => {
  if (!kpi?.variacion_pct) return 'sin-dato';
  const signo = comparar(kpi.variacion_pct, '0');
  return signo > 0 ? 'sube' : signo < 0 ? 'baja' : 'igual';
};

export const esNegativo = (texto: string | null | undefined): boolean => Boolean(texto) && comparar(texto, '0') < 0;

export interface BarraMensual {
  id: number;
  mes: string;
  ventas: number;
  costoVenta: number;
  margen: number;
  compras: number;
  ventasTexto: string;
  costoVentaTexto: string;
  margenTexto: string;
  comprasTexto: string;
  margenPct: string | null;
}

export const serieMensualGrafico = (serie: PuntoMensual[]): BarraMensual[] =>
  serie.map((p) => ({
    id: p.periodo.id,
    mes: etiquetaMes(p.periodo.anio, p.periodo.mes),
    ventas: aNumeroGrafico(p.ventas),
    costoVenta: aNumeroGrafico(p.costo_venta),
    margen: aNumeroGrafico(p.margen),
    compras: aNumeroGrafico(p.compras),
    ventasTexto: p.ventas,
    costoVentaTexto: p.costo_venta,
    margenTexto: p.margen,
    comprasTexto: p.compras,
    margenPct: p.margen_pct,
  }));

export const haySerie = (barras: BarraMensual[]): boolean =>
  barras.some((b) => b.ventas !== 0 || b.costoVenta !== 0 || b.compras !== 0);

export interface BarraProducto {
  id: number; nombre: string; detalle: string; valorTexto: string; cantidadTexto: string;
  diasStock: string | null; ancho: number;
}

/** Inventario como lista de barras: el ancho (0–100) es relativo al producto de mayor valor. */
export const topInventarioGrafico = (top: ProductoInventario[]): BarraProducto[] => {
  const maximo = Math.max(0, ...top.map((t) => aNumeroGrafico(t.valor)));
  return top.map((t) => ({
    id: t.producto.id,
    nombre: t.producto.descripcion,
    detalle: `${t.producto.codigo} · ${t.producto.descripcion}`,
    valorTexto: t.valor,
    cantidadTexto: t.cantidad,
    diasStock: t.dias_stock,
    ancho: maximo > 0 ? Math.max(2, Math.round((aNumeroGrafico(t.valor) / maximo) * 100)) : 0,
  }));
};

export type CampoSerie = 'ventas' | 'costo_venta' | 'margen' | 'compras';

/** Valores de la mini tendencia de una tarjeta (solo geometría). */
export const tendenciaKpi = (serie: PuntoMensual[], campo: CampoSerie): { i: number; v: number }[] =>
  serie.map((p, i) => ({ i, v: aNumeroGrafico(p[campo]) }));

/** Ancho (0–100) de la barrita de margen % en la tabla de productos. */
export const anchoMargen = (pct: string | null): number => {
  if (pct == null) return 0;
  const n = Math.abs(aNumeroGrafico(pct));
  return n === 0 ? 0 : Math.max(3, Math.min(100, Math.round(n)));
};

export type TonoDestacado = 'bueno' | 'malo' | 'neutro';
export interface Destacado { clave: string; texto: string; tono: TonoDestacado }

const soles = (texto: string) => `S/ ${formatearDecimal(texto)}`;
const porc = (texto: string) => `${formatearDecimal(texto)} %`;

/** Frases del panel "Lo destacado", armadas solo con los datos del endpoint. */
export const destacados = (datos: GraficosDashboardResponse): Destacado[] => {
  const salida: Destacado[] = [];
  const { kpis, mejor_mes: mejor, productos, participacion, inventario, producto } = datos;
  if (mejor) {
    salida.push({
      clave: 'mejor', tono: 'neutro',
      texto: `Mejor mes: ${nombreMes(mejor.periodo.anio, mejor.periodo.mes)} con ${soles(mejor.ventas)} en ventas.`,
    });
  }
  const conVentas = productos.filter((p) => comparar(p.ventas, '0') > 0);
  if (!producto && conVentas.length) {
    const top = [...conVentas].sort((a, b) => comparar(b.ventas, a.ventas))[0];
    const pct = participacion.find((s) => s.nombre === top.producto.descripcion)?.porcentaje;
    salida.push({
      clave: 'top', tono: 'bueno',
      texto: `Lo que más vende: ${top.producto.descripcion}${pct ? ` (${porc(pct)} de las ventas)` : ''}.`,
    });
  }
  const conMargen = conVentas.filter((p) => p.margen_pct != null);
  if (conMargen.length) {
    const peor = [...conMargen].sort((a, b) => comparar(a.margen_pct, b.margen_pct))[0];
    const negativo = comparar(peor.margen, '0') < 0;
    salida.push({
      clave: 'margen', tono: negativo ? 'malo' : 'neutro',
      texto: negativo
        ? `Pierdes dinero con ${peor.producto.descripcion}: margen ${porc(peor.margen_pct ?? '0')}.`
        : producto
          ? `Margen del producto: ${porc(peor.margen_pct ?? '0')}.`
          : `Menor margen: ${peor.producto.descripcion} con ${porc(peor.margen_pct ?? '0')}.`,
    });
  }
  if (kpis && (comparar(kpis.compras.actual, '0') !== 0 || comparar(kpis.costo_venta.actual, '0') !== 0)) {
    const diferencia = restar(kpis.compras.actual, kpis.costo_venta.actual);
    const signo = diferencia.cmp(0);
    salida.push({
      clave: 'compras', tono: 'neutro',
      texto: signo > 0
        ? `Compraste ${soles(diferencia.toString())} más de lo que salió al costo: el inventario crece.`
        : signo < 0
          ? `Salió ${soles(diferencia.abs().toString())} más de lo que compraste: el inventario baja.`
          : 'Compraste lo mismo que salió al costo: el inventario se mantiene.',
    });
  }
  const conDias = inventario.top_productos.filter((t) => t.dias_stock != null);
  const quietos = inventario.top_productos.filter((t) => t.dias_stock == null);
  if (conDias.length) {
    const largo = [...conDias].sort((a, b) => comparar(b.dias_stock, a.dias_stock))[0];
    salida.push({
      clave: 'stock', tono: 'neutro',
      texto: `${largo.producto.descripcion}: stock para unos ${largo.dias_stock} días al ritmo de venta del mes.`,
    });
  }
  if (kpis && quietos.length && conVentas.length) {
    salida.push({
      clave: 'quietos', tono: 'malo',
      texto: quietos.length === 1
        ? `${quietos[0].producto.descripcion} tiene stock pero no se vendió este mes.`
        : `${quietos.length} productos con stock no se vendieron este mes.`,
    });
  }
  return salida;
};

export interface SectorDona { nombre: string; valor: number; ventasTexto: string; porcentaje: string | null; color: string }

export const participacionGrafico = (sectores: SectorParticipacion[]): SectorDona[] =>
  sectores.map((s, i) => ({
    nombre: s.nombre,
    valor: aNumeroGrafico(s.ventas),
    ventasTexto: s.ventas,
    porcentaje: s.porcentaje,
    color: s.nombre === 'Otros' || s.nombre === 'Resto de productos' ? COLORES.otros : COLORES_PARTICIPACION[i % COLORES_PARTICIPACION.length],
  }));

export type ColumnaProducto = 'ventas' | 'costo_venta' | 'margen' | 'margen_pct' | 'unidades';

export const ordenarProductos = (
  filas: ProductoVenta[], columna: ColumnaProducto, descendente = true,
): ProductoVenta[] =>
  [...filas].sort((a, b) => {
    const r = comparar(a[columna] ?? '-999999999', b[columna] ?? '-999999999');
    return (descendente ? -r : r) || a.producto.id - b.producto.id;
  });

const normalizar = (texto: string): string => texto.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();

export interface OpcionProducto { id: number; codigo_interno: string; descripcion: string }

export const filtrarProductos = <T extends OpcionProducto>(lista: T[], texto: string, maximo = 50): T[] => {
  const partes = normalizar(texto).split(/\s+/).filter(Boolean);
  const coincide = (p: T) => {
    const base = normalizar(`${p.codigo_interno} ${p.descripcion}`);
    return partes.every((parte) => base.includes(parte));
  };
  return (partes.length ? lista.filter(coincide) : lista).slice(0, maximo);
};
