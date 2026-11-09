import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Warehouse,
  RotateCcw,
  Search,
  AlertCircle,
  Coins,
  Boxes,
  CheckCircle2,
  AlertTriangle,
  Inbox,
  Loader2,
  Filter,
} from 'lucide-react';
import { useAuth } from '../../context/useAuth';
import { obtenerSaldosActuales } from '../../api/kardex';
import { getAlmacenes, getProductos, type Almacen } from '../../api/inventario';
import { construirFilasStock, type FilaStock } from '../../utils/stockActual';
import { diferirCarga } from '../../utils/efectos';
import { mensajeDeError } from '../../utils/errores';
import { PageHeader } from '../../components/ui/page-header';
import { Button } from '../../components/ui/button';
import { Card, CardHeader, CardContent } from '../../components/ui/card';
import { Badge } from '../../components/ui/badge';
import { Input } from '../../components/ui/input';
import { Select } from '../../components/ui/select';
import { formatearDecimal, sumar } from '../../utils/decimal';

// Redondeo decimal ROUND_HALF_UP (sin pasar por float)
const formatQty = (n: number) => formatearDecimal(n, { min: 2, max: 6 });
const formatCost = (n: number | null) => (n !== null ? formatearDecimal(n, { min: 4, max: 6 }) : '—');
const formatMoney = (n: number) => formatearDecimal(n);

/**
 * Inventario (Stock Actual y Valorización):
 * Lectura de los saldos vigentes que mantiene el motor Kardex en tiempo real.
 */
export const StockActualPage: React.FC = () => {
  const { empresaActiva } = useAuth();
  const [filas, setFilas] = useState<FilaStock[]>([]);
  const [almacenes, setAlmacenes] = useState<Almacen[]>([]);
  const [almacenId, setAlmacenId] = useState('');
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busqueda, setBusqueda] = useState('');
  const [mostrarSinStock, setMostrarSinStock] = useState(false);

  const empresaId = empresaActiva?.id;
  const cargar = useCallback(async () => {
    if (!empresaId) return;
    setCargando(true);
    setError(null);
    try {
      const [saldos, productos, alms] = await Promise.all([
        obtenerSaldosActuales(),
        getProductos(),
        getAlmacenes(),
      ]);
      setAlmacenes(alms);
      setFilas(construirFilasStock(saldos.saldos_cpp, saldos.stocks_almacen, productos, alms, { incluirSinStock: true }));
    } catch (err) {
      setError(mensajeDeError(err, ['detail'], 'No se pudo cargar el stock actual.'));
    } finally {
      setCargando(false);
    }
  }, [empresaId]);

  useEffect(() => {
    diferirCarga(cargar);
  }, [cargar]);

  const visibles = useMemo(() => {
    const q = busqueda.trim().toLowerCase();
    const almFiltro = almacenId ? Number(almacenId) : null;

    return filas.filter((f) => {
      if (!mostrarSinStock && f.cantidad === 0 && f.valor === 0) return false;
      if (almFiltro !== null) {
        const tieneEnAlmacen = f.almacenes.some((a) => a.almacenId === almFiltro && a.cantidad > 0);
        if (!tieneEnAlmacen) return false;
      }
      if (!q) return true;
      return f.codigo.toLowerCase().includes(q) || f.descripcion.toLowerCase().includes(q);
    });
  }, [filas, busqueda, mostrarSinStock, almacenId]);

  const { totalValor, totalCantidad, conStock, sinStock } = useMemo(() => {
    let sumVal = sumar(0);
    let sumCant = sumar(0);
    let cStock = 0;
    let sStock = 0;

    for (const f of visibles) {
      sumVal = sumar(sumVal, f.valor);
      sumCant = sumar(sumCant, f.cantidad);
      if (f.cantidad > 0) {
        cStock += 1;
      } else {
        sStock += 1;
      }
    }

    return {
      totalValor: sumVal,
      totalCantidad: sumCant,
      conStock: cStock,
      sinStock: sStock,
    };
  }, [visibles]);

  return (
    <div className="space-y-4">
      {/* 1. Encabezado principal */}
      <PageHeader
        title="Stock Actual & Valorización de Existencias"
        description="Saldos físicos vigentes y valuación contable en Costo Promedio Ponderado (CPP)"
        icon={Warehouse}
        badge={
          <Badge variant="neutral" className="font-mono text-xs">
            CPP en PEN
          </Badge>
        }
        actions={
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void cargar()}
            disabled={cargando}
            className="shadow-xs h-9 text-xs"
          >
            {cargando ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" /> : <RotateCcw className="h-3.5 w-3.5 mr-1.5" />}
            Actualizar
          </Button>
        }
      />

      {/* 2. Alerta de Error */}
      {error && (
        <div role="alert" className="flex items-start gap-2.5 rounded-lg border border-rose-200 bg-rose-50 p-3.5 text-xs text-rose-800">
          <AlertCircle className="h-4 w-4 shrink-0 text-rose-600 mt-0.5" />
          <span className="font-medium leading-relaxed">{error}</span>
        </div>
      )}

      {/* 3. Cinta de Resumen Financiero (KPIs de Alta Densidad) */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="p-3.5 rounded-xl border border-slate-200/90 bg-white shadow-2xs">
          <div className="flex items-center justify-between text-slate-500 mb-1">
            <span className="text-[11px] font-bold uppercase tracking-wider">Valor Total Inventario</span>
            <Coins className="h-4 w-4 text-emerald-600 shrink-0" />
          </div>
          <div className="font-mono text-lg sm:text-xl font-black text-slate-950 tabular-nums">
            S/ {formatearDecimal(String(totalValor))}
          </div>
          <span className="text-[11px] text-slate-400 mt-0.5 block">Valuación oficial CPP</span>
        </div>

        <div className="p-3.5 rounded-xl border border-slate-200/90 bg-white shadow-2xs">
          <div className="flex items-center justify-between text-slate-500 mb-1">
            <span className="text-[11px] font-bold uppercase tracking-wider">Existencias Físicas</span>
            <Boxes className="h-4 w-4 text-indigo-600 shrink-0" />
          </div>
          <div className="font-mono text-lg sm:text-xl font-bold text-slate-900 tabular-nums">
            {formatearDecimal(String(totalCantidad), { min: 2, max: 2 })}
          </div>
          <span className="text-[11px] text-slate-400 mt-0.5 block">Unidades totales disponibles</span>
        </div>

        <div className="p-3.5 rounded-xl border border-slate-200/90 bg-white shadow-2xs">
          <div className="flex items-center justify-between text-slate-500 mb-1">
            <span className="text-[11px] font-bold uppercase tracking-wider">Productos con Stock</span>
            <CheckCircle2 className="h-4 w-4 text-emerald-600 shrink-0" />
          </div>
          <div className="font-mono text-lg sm:text-xl font-bold text-slate-900 tabular-nums">
            {conStock}
          </div>
          <span className="text-[11px] text-slate-400 mt-0.5 block">Ítems con existencia activa</span>
        </div>

        <div className="p-3.5 rounded-xl border border-slate-200/90 bg-white shadow-2xs">
          <div className="flex items-center justify-between text-slate-500 mb-1">
            <span className="text-[11px] font-bold uppercase tracking-wider">Sin Existencia / Agotados</span>
            <AlertTriangle className="h-4 w-4 text-amber-600 shrink-0" />
          </div>
          <div className="font-mono text-lg sm:text-xl font-bold text-amber-700 tabular-nums">
            {sinStock}
          </div>
          <span className="text-[11px] text-slate-400 mt-0.5 block">Ítems con stock 0.00</span>
        </div>
      </div>

      {/* 4. Barra de Filtros y Búsqueda Compacta */}
      <div className="p-3.5 bg-white rounded-xl border border-slate-200/90 shadow-2xs">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex flex-col sm:flex-row sm:items-center gap-3 flex-1">
            {/* Buscador en tiempo real */}
            <div className="w-full sm:w-80">
              <Input
                placeholder="Buscar por código o descripción..."
                value={busqueda}
                onChange={(e) => setBusqueda(e.target.value)}
                leftIcon={<Search className="h-3.5 w-3.5 text-slate-400" />}
                className="h-9 text-xs"
              />
            </div>

            {/* Selector de Almacén */}
            <div className="w-full sm:w-64">
              <Select
                value={almacenId}
                onChange={(e) => setAlmacenId(e.target.value)}
                className="h-9 text-xs"
              >
                <option value="">Todos los almacenes</option>
                {almacenes.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.codigo} · {a.nombre}
                  </option>
                ))}
              </Select>
            </div>
          </div>

          {/* Toggle para mostrar u ocultar productos en 0 */}
          <label className="inline-flex items-center gap-2 text-xs font-medium text-slate-700 cursor-pointer select-none shrink-0 bg-slate-50 px-3 py-1.5 rounded-lg border border-slate-200/80 hover:bg-slate-100 transition-colors">
            <input
              type="checkbox"
              checked={mostrarSinStock}
              onChange={(e) => setMostrarSinStock(e.target.checked)}
              className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 h-3.5 w-3.5"
            />
            <span>Mostrar productos sin stock</span>
          </label>
        </div>
      </div>

      {/* 5. Tabla de Inventario de Alta Densidad */}
      <Card className="shadow-2xs border-slate-200/90 overflow-hidden">
        <CardHeader className="py-2.5 px-4 border-b border-slate-200 bg-slate-50/60 flex flex-row items-center justify-between">
          <div className="flex items-center gap-2">
            <Filter className="h-3.5 w-3.5 text-slate-500 shrink-0" />
            <span className="text-xs font-semibold text-slate-800">
              Inventario Físico & Valorado
            </span>
            <span className="text-slate-300">·</span>
            <span className="text-xs text-slate-500">
              Mostrando <strong className="font-mono text-slate-900 font-bold">{visibles.length}</strong> producto(s)
            </span>
          </div>

          {cargando && (
            <div className="flex items-center gap-1.5 text-xs text-slate-400">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              <span>Actualizando datos...</span>
            </div>
          )}
        </CardHeader>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-xs text-left border-collapse">
              <thead>
                <tr className="bg-slate-100 text-[11px] font-semibold uppercase tracking-wider text-slate-600 border-b border-slate-200">
                  <th className="py-2.5 px-3 w-32">Código</th>
                  <th className="py-2.5 px-3">Descripción</th>
                  <th className="py-2.5 px-3 w-20 text-center">Unidad</th>
                  <th className="py-2.5 px-3 w-28 text-center">Estado</th>
                  <th className="py-2.5 px-3 w-32 text-right">Cantidad Total</th>
                  <th className="py-2.5 px-3 w-32 text-right">CPP (PEN)</th>
                  <th className="py-2.5 px-3 w-36 text-right">Valor Total (PEN)</th>
                  <th className="py-2.5 px-3">Stock por Almacén</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 font-mono tabular-nums text-xs">
                {visibles.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="text-center py-12 text-slate-400 text-xs font-sans">
                      {cargando ? (
                        <div className="flex items-center justify-center gap-2">
                          <Loader2 className="h-4 w-4 animate-spin text-slate-400" />
                          <span>Cargando stock...</span>
                        </div>
                      ) : (
                        <div className="space-y-1">
                          <Inbox className="h-6 w-6 text-slate-300 mx-auto mb-1" />
                          <p className="font-semibold text-slate-700">No hay productos con stock para los filtros seleccionados.</p>
                          <p className="text-[11px] text-slate-400">
                            Ajuste el término de búsqueda o active la opción de mostrar productos sin stock.
                          </p>
                        </div>
                      )}
                    </td>
                  </tr>
                ) : (
                  visibles.map((f) => {
                    const tieneStock = f.cantidad > 0;
                    return (
                      <tr key={f.productoId} className="hover:bg-slate-50 transition-colors">
                        <td className="py-2.5 px-3">
                          <span className="font-mono font-bold bg-slate-100 text-slate-800 px-1.5 py-0.5 rounded border border-slate-200 text-xs">
                            {f.codigo}
                          </span>
                        </td>
                        <td className="py-2.5 px-3 font-sans font-medium text-slate-800">
                          {f.descripcion}
                        </td>
                        <td className="py-2.5 px-3 text-center text-slate-500 font-mono font-semibold">
                          {f.unidad || '—'}
                        </td>
                        <td className="py-2.5 px-3 text-center font-sans">
                          {tieneStock ? (
                            <Badge variant="success" size="xs" dot>
                              En Stock
                            </Badge>
                          ) : (
                            <Badge variant="neutral" size="xs">
                              Agotado
                            </Badge>
                          )}
                        </td>
                        <td className="py-2.5 px-3 text-right font-bold text-slate-900">
                          {formatQty(f.cantidad)}
                        </td>
                        <td className="py-2.5 px-3 text-right text-slate-700">
                          {formatCost(f.cpp)}
                        </td>
                        <td className="py-2.5 px-3 text-right font-black text-slate-950">
                          S/ {formatMoney(f.valor)}
                        </td>
                        <td className="py-2.5 px-3 font-sans">
                          <div className="flex flex-wrap gap-1">
                            {f.almacenes.length === 0 ? (
                              <span className="text-xs text-slate-400">—</span>
                            ) : (
                              f.almacenes.map((a) => (
                                <Badge
                                  key={a.almacenId}
                                  variant="neutral"
                                  size="sm"
                                  className="font-mono tabular-nums bg-slate-50 text-slate-700 border-slate-200"
                                >
                                  {a.almacen}: {formatQty(a.cantidad)}
                                </Badge>
                              ))
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export default StockActualPage;
