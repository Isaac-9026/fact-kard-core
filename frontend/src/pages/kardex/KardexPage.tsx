import React, { useEffect, useState, useMemo, useCallback, type FormEvent } from 'react';
import { useAuth } from '../../context/useAuth';
import {
  obtenerKardexValorizado,
  exportarKardexExcel,
  type KardexFila,
  type KardexResumen,
  type KardexFiltros,
} from '../../api/reportes';
import { getProductos, getAlmacenes, type Producto, type Almacen } from '../../api/inventario';
import { obtenerPeriodos, type Periodo } from '../../api/periodos';
import { obtenerTiposOperacion, type TipoOperacion } from '../../api/catalogos';
import { filtrosKardexDesdeFormulario } from '../../utils/kardexFiltros';
import { mensajeDeError } from '../../utils/errores';
import { paramsPaginacion } from '../../utils/paginacion';
import { Paginacion } from '../../components/ui/paginacion';

// Bloque 7: el Kardex se pide por páginas; el resumen y el saldo inicial siguen siendo del
// rango completo (los calcula el backend). Excel y Formato 13.1 no se paginan.
const KARDEX_PAGE_SIZE = 100;
import {
  BookOpenCheck,
  FileSpreadsheet,
  Package,
  Scale,
  Coins,
  Activity,
  Calendar,
  Search,
  RotateCcw,
  Loader2,
  Inbox,
  AlertCircle,
} from 'lucide-react';
import { PageHeader } from '../../components/ui/page-header';
import {
  SIN_DATO, filaSaldoInicialKardex, guardarPeriodo, leerPeriodoGuardado, periodoInicialKardex, textoCppFinal,
  type SaldoInicialProducto,
} from '../../utils/kardexVista';
import { KpiCard } from '../../components/ui/card';
import { Badge } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Select } from '../../components/ui/select';
import { Label } from '../../components/ui/label';
import { formatearDecimal } from '../../utils/decimal';

// Bloque 9: formato con redondeo decimal ROUND_HALF_UP (sin pasar por float).
const formatear = (val: string | null | undefined, min: number, max: number): string => {
  if (val === null || val === undefined || val === '') return '—';
  return formatearDecimal(val, { min, max, vacio: String(val) });
};
const formatQty = (val: string | null | undefined): string => formatear(val, 2, 6);
const formatCost = (val: string | null | undefined): string => formatear(val, 4, 6);
const formatMoney = (val: string | null | undefined): string => formatear(val, 2, 2);

export const KardexPage: React.FC = () => {
  const { empresaActiva } = useAuth();

  // Catálogos para filtros
  const [productos, setProductos] = useState<Producto[]>([]);
  const [almacenes, setAlmacenes] = useState<Almacen[]>([]);
  const [periodos, setPeriodos] = useState<Periodo[]>([]);
  const [tiposOperacion, setTiposOperacion] = useState<TipoOperacion[]>([]);

  // Estado de filtros
  const [productoId, setProductoId] = useState<string>('');
  const [periodoId, setPeriodoId] = useState<string>('');
  const [almacenId, setAlmacenId] = useState<string>('');
  const [tipoOperacionId, setTipoOperacionId] = useState<string>('');
  const [fechaDesde, setFechaDesde] = useState<string>('');
  const [fechaHasta, setFechaHasta] = useState<string>('');

  // Estado de resultados
  const [movimientos, setMovimientos] = useState<KardexFila[]>([]);
  const [resumen, setResumen] = useState<KardexResumen | null>(null);
  const [saldosIniciales, setSaldosIniciales] = useState<SaldoInicialProducto[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [exporting, setExporting] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  // Última consulta aplicada (filtros + página) y total de movimientos del rango.
  const [consulta, setConsulta] = useState<{ filtros: KardexFiltros; page: number }>({ filtros: {}, page: 1 });
  const [totalMovimientos, setTotalMovimientos] = useState(0);

  const saldoInicial = filaSaldoInicialKardex(resumen, saldosIniciales);
  // El saldo inicial va antes del primer movimiento: solo se muestra en la página 1.
  const mostrarSaldoInicial = saldoInicial.mostrar && consulta.page === 1;

  // Ejecución de la consulta contable con una instantánea estable de filtros.
  // Nuevos filtros o cambio de empresa: página 1. La navegación pasa la página pedida.
  const cargarKardex = useCallback(async (filtros: KardexFiltros, page: number = 1) => {
    setLoading(true);
    setError(null);
    setConsulta({ filtros, page });
    try {
      const res = await obtenerKardexValorizado(filtros, paramsPaginacion(page, KARDEX_PAGE_SIZE));
      setMovimientos(res.movimientos);
      setTotalMovimientos(res.paginacion?.count ?? res.movimientos.length);
      setResumen(res.resumen);
      setSaldosIniciales(res.saldos_iniciales ?? []);
    } catch (err) {
      console.error('Error al consultar Kardex', err);
      setError(
        mensajeDeError(
          err,
          ['detail', 'message'],
          'No se pudo cargar el Kardex Valorizado. Verifique los filtros y conexión.'
        )
      );
    } finally {
      setLoading(false);
    }
  }, []);

  // Carga inicial de catálogos y del reporte de la empresa activa.
  useEffect(() => {
    let isMounted = true;
    const cargarCatalogos = async () => {
      try {
        const [prodsData, almsData, persData, opsData] = await Promise.all([
          getProductos().catch(() => []),
          getAlmacenes().catch(() => []),
          obtenerPeriodos().catch(() => []),
          obtenerTiposOperacion().catch(() => []),
        ]);
        if (isMounted) {
          setProductos(prodsData);
          setAlmacenes(almsData);
          setPeriodos(persData);
          setTiposOperacion(opsData);

          // Bloque 4: última selección válida de esta pestaña; si no, el último abierto.
          const inicial = periodoInicialKardex(persData, leerPeriodoGuardado(empresaActiva?.id));
          setPeriodoId(inicial);
          void cargarKardex({ periodo_id: inicial ? Number(inicial) : undefined });
        }
      } catch (err) {
        console.error('Error al cargar catálogos de Kardex', err);
      }
    };
    cargarCatalogos();
    return () => {
      isMounted = false;
    };
  }, [empresaActiva?.id, cargarKardex]);

  const handleActualizarConsulta = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const filtros = filtrosKardexDesdeFormulario(new FormData(event.currentTarget));
    setProductoId(filtros.producto_id ? String(filtros.producto_id) : '');
    setPeriodoId(filtros.periodo_id ? String(filtros.periodo_id) : '');
    setAlmacenId(filtros.almacen_id ? String(filtros.almacen_id) : '');
    setTipoOperacionId(filtros.tipo_operacion_id ? String(filtros.tipo_operacion_id) : '');
    setFechaDesde(filtros.fecha_desde ?? '');
    setFechaHasta(filtros.fecha_hasta ?? '');
    guardarPeriodo(empresaActiva?.id, filtros.periodo_id ? String(filtros.periodo_id) : '');
    void cargarKardex(filtros);
  };

  // Exportar a Excel
  const handleExportarExcel = async () => {
    setExporting(true);
    try {
      const filtros: KardexFiltros = {
        producto_id: productoId ? Number(productoId) : undefined,
        periodo_id: periodoId ? Number(periodoId) : undefined,
        almacen_id: almacenId ? Number(almacenId) : undefined,
        tipo_operacion_id: tipoOperacionId ? Number(tipoOperacionId) : undefined,
        fecha_desde: fechaDesde || undefined,
        fecha_hasta: fechaHasta || undefined,
      };
      await exportarKardexExcel(filtros);
    } catch (err) {
      console.error('Error al exportar Excel', err);
      alert('Error al generar el archivo Excel. Por favor intente nuevamente.');
    } finally {
      setExporting(false);
    }
  };

  const handleLimpiarFiltros = () => {
    setProductoId('');
    setPeriodoId('');
    setAlmacenId('');
    setTipoOperacionId('');
    setFechaDesde('');
    setFechaHasta('');
    void cargarKardex({});
  };

  const productoSeleccionado = useMemo(() => {
    if (!productoId) return null;
    return productos.find((p) => String(p.id) === String(productoId));
  }, [productoId, productos]);

  return (
    <div className="space-y-4">
      {/* 1. Encabezado principal compacto */}
      <PageHeader
        title="Kardex Permanente Valorizado"
        description={`Control contable con Costo Promedio Ponderado Móvil (CPP Global en PEN) · ${
          empresaActiva?.razon_social ?? 'Empresa Activa'
        }${empresaActiva?.ruc ? ` · RUC: ${empresaActiva.ruc}` : ''}`}
        icon={BookOpenCheck}
        badge={
          <div className="flex items-center gap-1.5 flex-wrap">
            <Badge variant="info" size="xs">Fase 8 · Bloque 5</Badge>
            <Badge variant="success" size="xs" dot>SUNAT Formato 13.1</Badge>
          </div>
        }
      />

      {/* 2. Toolbar Financiero: Grid Responsivo 4 Columnas + Barra de Acciones Dedicada */}
      <div className="bg-white rounded-lg border border-slate-200/90 shadow-2xs p-3.5 space-y-3">
        <form onSubmit={handleActualizarConsulta} className="space-y-3">
          {/* Fila 1: Selectores Principales */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            {/* Producto */}
            <div className="space-y-1">
              <div className="flex items-center justify-between">
                <Label htmlFor="kardex-producto" className="text-[11px] font-semibold text-slate-600 uppercase tracking-wider">
                  Producto / Existencia
                </Label>
                {productoSeleccionado && (
                  <span className="text-[10px] font-mono font-semibold text-indigo-600 truncate max-w-[90px]" title={productoSeleccionado.codigo_interno}>
                    {productoSeleccionado.codigo_interno}
                  </span>
                )}
              </div>
              <Select
                id="kardex-producto"
                name="producto_id"
                value={productoId}
                onChange={(e) => setProductoId(e.target.value)}
                className="h-8 text-xs w-full"
              >
                <option value="">Todos los productos</option>
                {productos.map((prod) => (
                  <option key={prod.id} value={prod.id}>
                    {prod.codigo_interno} — {prod.descripcion}
                  </option>
                ))}
              </Select>
            </div>

            {/* Período Contable */}
            <div className="space-y-1">
              <Label htmlFor="kardex-periodo" className="text-[11px] font-semibold text-slate-600 uppercase tracking-wider">
                Período Contable
              </Label>
              <Select
                id="kardex-periodo"
                name="periodo_id"
                value={periodoId}
                onChange={(e) => setPeriodoId(e.target.value)}
                className="h-8 text-xs w-full"
              >
                <option value="">Todos los períodos</option>
                {periodos.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.anio}-{String(p.mes).padStart(2, '0')} ({p.estado})
                  </option>
                ))}
              </Select>
            </div>

            {/* Almacén */}
            <div className="space-y-1">
              <Label htmlFor="kardex-almacen" className="text-[11px] font-semibold text-slate-600 uppercase tracking-wider">
                Almacén
              </Label>
              <Select
                id="kardex-almacen"
                name="almacen_id"
                value={almacenId}
                onChange={(e) => setAlmacenId(e.target.value)}
                className="h-8 text-xs w-full"
              >
                <option value="">Todos (Consolidado)</option>
                {almacenes.map((alm) => (
                  <option key={alm.id} value={alm.id}>
                    {alm.codigo} — {alm.nombre}
                  </option>
                ))}
              </Select>
            </div>

            {/* Tipo de Operación */}
            <div className="space-y-1">
              <Label htmlFor="kardex-operacion" className="text-[11px] font-semibold text-slate-600 uppercase tracking-wider">
                Tipo de Operación
              </Label>
              <Select
                id="kardex-operacion"
                name="tipo_operacion_id"
                value={tipoOperacionId}
                onChange={(e) => setTipoOperacionId(e.target.value)}
                className="h-8 text-xs w-full"
              >
                <option value="">Todas las operaciones</option>
                {tiposOperacion.map((op) => (
                  <option key={op.id} value={op.id}>
                    {op.codigo_sunat || op.codigo_interno} — {op.descripcion}
                  </option>
                ))}
              </Select>
            </div>
          </div>

          {/* Fila 2: Sub-toolbar de Rango de Fechas + Botones de Acción (Separados e Independientes) */}
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 pt-2.5 border-t border-slate-100">
            {/* Fechas */}
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider flex items-center gap-1 shrink-0">
                <Calendar className="h-3.5 w-3.5 text-slate-400" />
                Rango Fechas:
              </span>
              <div className="flex items-center gap-1.5">
                <Input
                  id="kardex-desde"
                  type="date"
                  name="fecha_desde"
                  value={fechaDesde}
                  onChange={(e) => setFechaDesde(e.target.value)}
                  className="h-7 w-32 text-xs py-0 px-2"
                  placeholder="Desde"
                />
                <span className="text-slate-400 text-xs">—</span>
                <Input
                  id="kardex-hasta"
                  type="date"
                  name="fecha_hasta"
                  value={fechaHasta}
                  onChange={(e) => setFechaHasta(e.target.value)}
                  className="h-7 w-32 text-xs py-0 px-2"
                  placeholder="Hasta"
                />
              </div>
              {productoSeleccionado && (
                <div className="hidden xl:flex items-center gap-1 text-[11px] text-slate-600 bg-slate-50 border border-slate-200/80 rounded px-2 py-0.5">
                  <span className="font-semibold text-slate-700">Producto:</span>
                  <span className="font-mono text-indigo-700 font-medium">{productoSeleccionado.codigo_interno}</span>
                  <span className="text-slate-400">·</span>
                  <span className="truncate max-w-[200px]">{productoSeleccionado.descripcion}</span>
                </div>
              )}
            </div>

            {/* Grupo de Botones de Acción */}
            <div className="flex items-center gap-2 shrink-0 self-end md:self-auto">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={handleLimpiarFiltros}
                disabled={loading}
                className="h-8 px-2.5 text-xs text-slate-600 hover:text-slate-900"
                title="Limpiar filtros de búsqueda"
              >
                <RotateCcw className="h-3.5 w-3.5 mr-1 text-slate-500" />
                Limpiar
              </Button>
              <Button
                type="submit"
                variant="primary"
                size="sm"
                disabled={loading}
                className="h-8 px-3.5 text-xs font-semibold shadow-xs"
              >
                {loading ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />
                ) : (
                  <Search className="h-3.5 w-3.5 mr-1.5" />
                )}
                Actualizar Consulta
              </Button>
              <Button
                type="button"
                onClick={handleExportarExcel}
                disabled={exporting || loading}
                variant="success"
                size="sm"
                className="h-8 px-3 text-xs font-semibold shadow-xs"
                title="Exportar Kardex Oficial en Excel (.xlsx)"
              >
                {exporting ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />
                ) : (
                  <FileSpreadsheet className="h-3.5 w-3.5 mr-1.5" />
                )}
                {exporting ? 'Exportando...' : 'Exportar Excel'}
              </Button>
            </div>
          </div>
        </form>
      </div>

      {/* 3. Cinta Horizontal de 4 Indicadores Compactos */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <KpiCard
          title="Stock Físico Actual"
          value={loading ? '...' : formatQty(resumen?.saldo_final_cantidad)}
          subtitle={
            productoSeleccionado
              ? `${productoSeleccionado.codigo_interno} · Unidad Base`
              : 'Balance físico acumulado'
          }
          icon={Package}
        />
        <KpiCard
          title="CPP Global Vigente"
          value={loading ? '...' : resumen ? textoCppFinal(resumen.cpp_final, formatCost) : SIN_DATO}
          subtitle="Costo Promedio Ponderado (6 dec.)"
          icon={Scale}
          badge={<Badge variant="info" size="xs">PEN</Badge>}
        />
        <KpiCard
          title="Saldo Valorizado Total"
          value={loading ? '...' : `S/ ${formatMoney(resumen?.saldo_final_valor)}`}
          subtitle="Valor monetario contable en PEN"
          icon={Coins}
        />
        <KpiCard
          title="Total de Movimientos"
          value={loading ? '...' : totalMovimientos.toLocaleString()}
          subtitle={
            loading
              ? '...'
              : `Entradas: ${formatQty(resumen?.total_entradas_cantidad)} | Salidas: ${formatQty(resumen?.total_salidas_cantidad)}`
          }
          icon={Activity}
          badge={
            <Badge variant="neutral" size="xs" className="font-mono">
              pág. {consulta.page}
            </Badge>
          }
        />
      </div>

      {/* 4. Mensaje de Error */}
      {error && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-800 flex items-start gap-2.5">
          <AlertCircle className="h-4 w-4 text-rose-600 shrink-0 mt-0.5" />
          <div>
            <p className="font-semibold">Error al consultar Kardex Valorizado</p>
            <p className="mt-0.5">{error}</p>
          </div>
        </div>
      )}

      {/* 5. Tabla Oficial de Kardex Valorizado */}
      <div className="rounded-lg border border-slate-200/90 bg-white shadow-2xs overflow-hidden">
        <div className="py-2 px-3 border-b border-slate-200 bg-slate-50/70 flex flex-row items-center justify-between gap-3">
          <div>
            <div className="flex items-center gap-1.5">
              <BookOpenCheck className="h-3.5 w-3.5 text-slate-700" />
              <h3 className="text-xs font-bold text-slate-900 uppercase tracking-wide">
                Movimientos Contables Registrados
              </h3>
            </div>
            <p className="text-[11px] text-slate-500 mt-0.5">
              <span className="font-mono font-semibold text-slate-900">{totalMovimientos}</span>{' '}
              movimiento(s) valorizados cronológicamente por el motor CPP
            </p>
          </div>
          <div className="flex items-center gap-2.5 text-[10px] font-medium">
            <span className="flex items-center gap-1 text-slate-600">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
              Entrada
            </span>
            <span className="flex items-center gap-1 text-slate-600">
              <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
              Salida
            </span>
            <span className="flex items-center gap-1 text-slate-600">
              <span className="h-1.5 w-1.5 rounded-full bg-indigo-500" />
              Ajuste Valor
            </span>
          </div>
        </div>

        {loading ? (
          <div className="py-20 flex flex-col items-center justify-center text-slate-500">
            <Loader2 className="h-8 w-8 animate-spin text-slate-900 mb-3" />
            <p className="text-xs font-medium">Procesando y valorizando movimientos de Kardex...</p>
          </div>
        ) : movimientos.length === 0 && !saldoInicial.mostrar ? (
          <div className="py-16 text-center">
            <div className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-slate-100 text-slate-400 mb-2.5">
              <Inbox className="h-5 w-5" />
            </div>
            <h3 className="text-xs font-semibold text-slate-900">No se encontraron movimientos registrados</h3>
            <p className="text-[11px] text-slate-500 max-w-md mx-auto mt-0.5">
              No hay operaciones registradas para los filtros seleccionados o el producto aún no tiene movimientos confirmados.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto max-h-[640px] relative">
            <table className="w-full text-xs text-left border-collapse">
              <thead className="sticky top-0 z-10 select-none">
                {/* Nivel 1: Agrupación oficial con estilo B2B */}
                <tr className="text-[10px] font-bold uppercase tracking-wider text-center border-b border-slate-200">
                  <th colSpan={5} className="py-1 px-2 bg-slate-100/95 text-slate-700">
                    Datos de la Operación
                  </th>
                  <th colSpan={3} className="py-1 px-1.5 bg-emerald-50/90 text-emerald-900 border-l border-slate-200">
                    Entradas
                  </th>
                  <th colSpan={3} className="py-1 px-1.5 bg-amber-50/90 text-amber-900 border-l border-slate-200">
                    Salidas
                  </th>
                  <th colSpan={3} className="py-1 px-1.5 bg-indigo-50/90 text-indigo-950 font-extrabold border-l border-slate-200">
                    Saldo Final Valorizado
                  </th>
                </tr>

                {/* Nivel 2: Subcolumnas Proporcionales con Moneda en Cabecera */}
                <tr className="bg-slate-100/90 text-[10px] font-semibold text-slate-600 border-b border-slate-200">
                  <th className="py-1.5 px-2 text-center w-[84px] shrink-0">Fecha</th>
                  <th className="py-1.5 px-2 text-left min-w-[95px]">Doc. Ref.</th>
                  <th className="py-1.5 px-2 text-left min-w-[110px]">Tipo Op.</th>
                  <th className="py-1.5 px-1 text-center w-[46px]">Nat.</th>
                  <th className="py-1.5 px-1.5 text-center w-[65px]">Almacén</th>

                  {/* Entradas */}
                  <th className="py-1.5 px-2 text-right bg-emerald-50/70 text-emerald-900 border-l border-slate-200 min-w-[75px]">Cantidad</th>
                  <th className="py-1.5 px-2 text-right bg-emerald-50/70 text-emerald-900 min-w-[75px]">Costo Unit.</th>
                  <th className="py-1.5 px-2 text-right bg-emerald-50/70 text-emerald-900 font-bold min-w-[85px]">Total (PEN)</th>

                  {/* Salidas */}
                  <th className="py-1.5 px-2 text-right bg-amber-50/70 text-amber-900 border-l border-slate-200 min-w-[75px]">Cantidad</th>
                  <th className="py-1.5 px-2 text-right bg-amber-50/70 text-amber-900 min-w-[75px]">Costo Unit.</th>
                  <th className="py-1.5 px-2 text-right bg-amber-50/70 text-amber-900 font-bold min-w-[85px]">Total (PEN)</th>

                  {/* Saldo Final */}
                  <th className="py-1.5 px-2 text-right bg-indigo-50/70 text-indigo-950 border-l border-slate-200 min-w-[75px]">Cantidad</th>
                  <th className="py-1.5 px-2 text-right bg-indigo-50/70 text-indigo-950 min-w-[75px]">C.P.P.</th>
                  <th className="py-1.5 px-2 text-right bg-indigo-50/70 text-indigo-950 font-bold min-w-[88px]">Total (PEN)</th>
                </tr>
              </thead>

              <tbody className="divide-y divide-slate-200/70 text-[11px]">
                {mostrarSaldoInicial && (
                  <tr className="bg-slate-50/90 font-semibold text-slate-700">
                    <td colSpan={5} className="py-1.5 px-2.5 text-right text-[11px] font-sans">
                      SALDO INICIAL
                      {resumen?.ambito_saldo === 'ALMACEN' && (
                        <span className="ml-1 text-[10px] font-normal text-slate-500">(stock alm. × CPP)</span>
                      )}
                    </td>
                    <td colSpan={3} className="py-1.5 px-2 text-center text-slate-300 border-l border-slate-200 bg-emerald-50/10 font-mono select-none">—</td>
                    <td colSpan={3} className="py-1.5 px-2 text-center text-slate-300 border-l border-slate-200 bg-amber-50/10 font-mono select-none">—</td>
                    <td className="py-1.5 px-2 text-right font-mono tabular-nums border-l border-slate-200 bg-indigo-50/30 text-slate-900">{formatQty(saldoInicial.cantidad)}</td>
                    <td className="py-1.5 px-2 text-right font-mono tabular-nums bg-indigo-50/30 text-slate-800">{formatCost(saldoInicial.cpp)}</td>
                    <td className="py-1.5 px-2 text-right font-mono tabular-nums bg-indigo-50/30 font-bold text-slate-950">{formatMoney(saldoInicial.valor)}</td>
                  </tr>
                )}
                {mostrarSaldoInicial && movimientos.length === 0 && (
                  <tr>
                    <td colSpan={14} className="py-3 px-3 text-center text-slate-400">
                      Sin movimientos en el rango; el saldo final es el saldo inicial.
                    </td>
                  </tr>
                )}
                {movimientos.map((mov) => {
                  const isEntrada = mov.naturaleza === 'ENTRADA';
                  const isSalida = mov.naturaleza === 'SALIDA';
                  const isAjuste = mov.naturaleza === 'AJUSTE_VALOR';

                  return (
                    <tr
                      key={mov.id}
                      className="even:bg-slate-50/40 hover:bg-indigo-50/30 transition-colors duration-75"
                    >
                      {/* Fecha */}
                      <td className="py-1.5 px-2 text-center font-mono tabular-nums whitespace-nowrap text-slate-700">
                        {mov.fecha}
                      </td>

                      {/* Documento Ref */}
                      <td className="py-1.5 px-2 font-medium text-slate-900">
                        <div className="flex items-center gap-1 truncate max-w-[110px]" title={mov.documento_referencia || '—'}>
                          <span className="font-mono tabular-nums truncate">{mov.documento_referencia || '—'}</span>
                          {mov.es_extorno && (
                            <Badge variant="warning" size="xs" className="px-1 py-0 text-[8px]">EXT</Badge>
                          )}
                          {mov.generado_por_motor && (
                            <Badge variant="info" size="xs" className="px-1 py-0 text-[8px]">MOT</Badge>
                          )}
                        </div>
                      </td>

                      {/* Tipo Operación */}
                      <td className="py-1.5 px-2 max-w-[120px]" title={`${mov.tipo_operacion_codigo} — ${mov.tipo_operacion_descripcion}`}>
                        <div className="truncate">
                          <span className="font-mono font-bold text-slate-900">{mov.tipo_operacion_codigo}</span>{' '}
                          <span className="text-slate-500 text-[10px]">{mov.tipo_operacion_descripcion}</span>
                        </div>
                      </td>

                      {/* Naturaleza */}
                      <td className="py-1.5 px-1 text-center" title={mov.naturaleza}>
                        <Badge
                          variant={isEntrada ? 'success' : isSalida ? 'warning' : 'info'}
                          size="xs"
                          className="px-1.5 py-0 text-[9px] font-semibold font-mono uppercase"
                        >
                          {isEntrada ? 'ENT' : isSalida ? 'SAL' : 'AJU'}
                        </Badge>
                      </td>

                      {/* Almacén */}
                      <td className="py-1.5 px-1.5 text-center text-slate-600 truncate" title={`${mov.almacen_codigo} — ${mov.almacen_nombre}`}>
                        <span className="font-mono font-medium text-slate-800 text-[10px]">{mov.almacen_codigo}</span>
                      </td>

                      {/* Bloque Entradas */}
                      <td className={`py-1.5 px-2 text-right font-mono tabular-nums border-l border-slate-200 bg-emerald-50/20 ${
                        isEntrada || (isAjuste && mov.entrada_valor) ? 'text-emerald-700 font-semibold' : 'text-slate-300'
                      }`}>
                        {mov.entrada_cantidad ? formatQty(mov.entrada_cantidad) : <span className="text-slate-300 font-mono select-none">—</span>}
                      </td>
                      <td className="py-1.5 px-2 text-right font-mono tabular-nums bg-emerald-50/20 text-slate-600">
                        {mov.entrada_costo_unitario ? formatCost(mov.entrada_costo_unitario) : <span className="text-slate-300 font-mono select-none">—</span>}
                      </td>
                      <td className={`py-1.5 px-2 text-right font-mono tabular-nums bg-emerald-50/20 ${
                        isEntrada || (isAjuste && mov.entrada_valor) ? 'text-emerald-700 font-bold' : 'text-slate-300'
                      }`}>
                        {mov.entrada_valor ? formatMoney(mov.entrada_valor) : <span className="text-slate-300 font-mono select-none">—</span>}
                      </td>

                      {/* Bloque Salidas */}
                      <td className={`py-1.5 px-2 text-right font-mono tabular-nums border-l border-slate-200 bg-amber-50/20 ${
                        isSalida || (isAjuste && mov.salida_valor) ? 'text-amber-800 font-semibold' : 'text-slate-300'
                      }`}>
                        {mov.salida_cantidad ? formatQty(mov.salida_cantidad) : <span className="text-slate-300 font-mono select-none">—</span>}
                      </td>
                      <td className="py-1.5 px-2 text-right font-mono tabular-nums bg-amber-50/20 text-slate-600">
                        {mov.salida_costo_unitario ? formatCost(mov.salida_costo_unitario) : <span className="text-slate-300 font-mono select-none">—</span>}
                      </td>
                      <td className={`py-1.5 px-2 text-right font-mono tabular-nums bg-amber-50/20 ${
                        isSalida || (isAjuste && mov.salida_valor) ? 'text-amber-800 font-bold' : 'text-slate-300'
                      }`}>
                        {mov.salida_valor ? formatMoney(mov.salida_valor) : <span className="text-slate-300 font-mono select-none">—</span>}
                      </td>

                      {/* Bloque Saldo Final */}
                      <td className="py-1.5 px-2 text-right font-mono tabular-nums font-semibold text-slate-900 border-l border-slate-200 bg-indigo-50/25">
                        {formatQty(mov.saldo_cantidad)}
                      </td>
                      <td className="py-1.5 px-2 text-right font-mono tabular-nums text-slate-800 bg-indigo-50/25">
                        {formatCost(mov.cpp)}
                      </td>
                      <td className="py-1.5 px-2 text-right font-mono tabular-nums font-bold text-slate-950 bg-indigo-50/25">
                        {formatMoney(mov.saldo_valor)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>

              {/* Pie de tabla con totales oficiales */}
              {resumen && (
                <tfoot>
                  <tr className="bg-slate-100/95 font-semibold border-t-2 border-slate-900 text-[11px]">
                    <td colSpan={5} className="py-2 px-2.5 text-right font-bold text-slate-900">
                      TOTALES DEL PERÍODO (PEN):
                    </td>
                    <td className="py-2 px-2 text-right font-mono tabular-nums font-bold text-emerald-800 border-l border-slate-200 bg-emerald-50/50">
                      {formatQty(resumen.total_entradas_cantidad)}
                    </td>
                    <td className="py-2 px-2 text-center text-slate-300 bg-emerald-50/50 font-mono select-none">—</td>
                    <td className="py-2 px-2 text-right font-mono tabular-nums font-bold text-emerald-800 bg-emerald-50/50">
                      {formatMoney(resumen.total_entradas_valor)}
                    </td>

                    <td className="py-2 px-2 text-right font-mono tabular-nums font-bold text-amber-900 border-l border-slate-200 bg-amber-50/50">
                      {formatQty(resumen.total_salidas_cantidad)}
                    </td>
                    <td className="py-2 px-2 text-center text-slate-300 bg-amber-50/50 font-mono select-none">—</td>
                    <td className="py-2 px-2 text-right font-mono tabular-nums font-bold text-amber-900 bg-amber-50/50">
                      {formatMoney(resumen.total_salidas_valor)}
                    </td>

                    <td className="py-2 px-2 text-right font-mono tabular-nums font-extrabold text-slate-950 border-l border-slate-200 bg-indigo-50/50">
                      {formatQty(resumen.saldo_final_cantidad)}
                    </td>
                    <td className="py-2 px-2 text-right font-mono tabular-nums font-bold text-slate-900 bg-indigo-50/50">
                      {formatCost(resumen.cpp_final)}
                    </td>
                    <td className="py-2 px-2 text-right font-mono tabular-nums font-extrabold text-slate-950 bg-indigo-50/50">
                      {formatMoney(resumen.saldo_final_valor)}
                    </td>
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
        )}
        {!loading && totalMovimientos > 0 && (
          <div className="border-t border-slate-200 bg-white">
            <Paginacion
              page={consulta.page}
              pageSize={KARDEX_PAGE_SIZE}
              count={totalMovimientos}
              enPagina={movimientos.length}
              cargando={loading}
              etiqueta="movimientos"
              onCambiarPagina={(page) => void cargarKardex(consulta.filtros, page)}
            />
          </div>
        )}
      </div>
    </div>
  );
};
