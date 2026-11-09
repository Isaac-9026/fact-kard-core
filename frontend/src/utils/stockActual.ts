/**
 * Vista "Inventario": une los saldos vigentes del motor Kardex con los nombres de
 * productos y almacenes. No recalcula nada: cantidades, CPP y valores vienen del backend.
 */
export interface SaldoProductoEntrada { producto_id: number; cantidad_total: number | string; valor_total_pen: number | string; cpp_pen: number | string | null }
export interface StockAlmacenEntrada { producto_id: number; almacen_id: number; cantidad_actual: number | string }
export interface ProductoEntrada { id: number; codigo_interno: string; descripcion: string; unidad_base?: { codigo: string } | null }
export interface AlmacenEntrada { id: number; codigo: string; nombre: string }

export interface FilaStock {
  productoId: number;
  codigo: string;
  descripcion: string;
  unidad: string;
  cantidad: number;
  cpp: number | null;
  valor: number;
  almacenes: { almacenId: number; almacen: string; cantidad: number }[];
}

const numero = (v: number | string | null | undefined): number => {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
};

export const construirFilasStock = (
  saldos: SaldoProductoEntrada[],
  stocks: StockAlmacenEntrada[],
  productos: ProductoEntrada[],
  almacenes: AlmacenEntrada[],
  /** true = también productos con saldo cero (los almacenes en cero nunca se listan). */
  { incluirSinStock = false }: { incluirSinStock?: boolean } = {},
): FilaStock[] => {
  const productoPorId = new Map(productos.map((p) => [p.id, p]));
  const almacenPorId = new Map(almacenes.map((a) => [a.id, a]));
  return saldos
    .map((s) => {
      const p = productoPorId.get(s.producto_id);
      return {
        productoId: s.producto_id,
        codigo: p?.codigo_interno ?? `#${s.producto_id}`,
        descripcion: p?.descripcion ?? 'Producto no disponible',
        unidad: p?.unidad_base?.codigo ?? '',
        cantidad: numero(s.cantidad_total),
        cpp: s.cpp_pen === null || s.cpp_pen === undefined ? null : numero(s.cpp_pen),
        valor: numero(s.valor_total_pen),
        almacenes: stocks
          .filter((st) => st.producto_id === s.producto_id && numero(st.cantidad_actual) !== 0)
          .map((st) => {
            const a = almacenPorId.get(st.almacen_id);
            return { almacenId: st.almacen_id, almacen: a ? `${a.codigo} · ${a.nombre}` : `#${st.almacen_id}`, cantidad: numero(st.cantidad_actual) };
          })
          .sort((x, y) => x.almacen.localeCompare(y.almacen)),
      };
    })
    .filter((f) => incluirSinStock || f.cantidad !== 0 || f.valor !== 0)
    .sort((a, b) => a.codigo.localeCompare(b.codigo));
};
