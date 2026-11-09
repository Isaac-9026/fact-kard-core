import React, { useEffect, useState } from 'react';
import { obtenerEstablecimientos, type Establecimiento } from '../../api/empresas';
import { getProductos, type Producto } from '../../api/inventario';
import { obtenerPeriodos, type Periodo } from '../../api/periodos';
import {
  compararPiloto,
  descargarFormato131,
  obtenerFormato131,
  obtenerPiloto,
  type Formato131Response,
  type PilotoReal,
  type PilotoResultado,
} from '../../api/formato131';
import { useAuth } from '../../context/useAuth';
import {
  FileCheck2,
  FileDown,
  Search,
  Scale,
  Gauge,
  RotateCcw,
  AlertCircle,
  CheckCircle2,
  Inbox,
  Loader2,
  ShieldCheck,
  TrendingDown,
  Info,
  Clock,
  Zap,
  Check,
} from 'lucide-react';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../../components/ui/card';
import { Badge } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { Input } from '../../components/ui/input';
import { Select } from '../../components/ui/select';
import { Label } from '../../components/ui/label';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../../components/ui/tabs';
import { filaSaldoFinal, filaSaldoInicial } from '../../utils/formato131Saldos';
import { mensajeErrorExportacion, nombreArchivoFormato131 } from '../../utils/descargaArchivo';

const apiError = (error: unknown) => {
  const data = (error as { response?: { data?: Record<string, string | string[]> | string } }).response?.data;
  if (!data || typeof data === 'string') return 'No se pudo completar la operación. Intente nuevamente.';
  return Object.values(data).flat().join(' ');
};

const n = (value?: string | null) => (value !== null && value !== undefined && value !== '' ? value : '—');

const isZeroDiff = (val?: string | null) => {
  if (!val) return false;
  const s = val.trim();
  return s === '0' || /^0(\.0+)?$/.test(s);
};

export const Formato131Page: React.FC = () => {
  const { empresaActiva } = useAuth();
  const [tab, setTab] = useState<'formato' | 'piloto'>('formato');
  const [periodos, setPeriodos] = useState<Periodo[]>([]);
  const [establecimientos, setEstablecimientos] = useState<Establecimiento[]>([]);
  const [productos, setProductos] = useState<Producto[]>([]);
  const [periodo, setPeriodo] = useState('');
  const [establecimiento, setEstablecimiento] = useState('');
  const [producto, setProducto] = useState('');
  const [reporte, setReporte] = useState<Formato131Response | null>(null);
  const [real, setReal] = useState<PilotoReal | null>(null);
  const [resultado, setResultado] = useState<PilotoResultado | null>(null);
  const [form, setForm] = useState({
    cantidad_esperada: '',
    cpp_esperado: '',
    valor_esperado: '',
    tiempo_manual_segundos: '',
    tiempo_factkard_segundos: '',
  });
  const [busy, setBusy] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState('');
  // Bloque 13: el aviso dice si falló la consulta o la exportación.
  const [errorTitulo, setErrorTitulo] = useState('Error al consultar');

  useEffect(() => {
    let active = true;
    Promise.all([obtenerPeriodos(), obtenerEstablecimientos(), getProductos()])
      .then(([p, e, pr]) => {
        if (!active) return;
        setPeriodos(p);
        setEstablecimientos(e);
        setProductos(pr);
        setPeriodo(p[0] ? String(p[0].id) : '');
        setProducto(pr[0] ? String(pr[0].id) : '');
      })
      .catch((e) => active && setError(apiError(e)));
    return () => {
      active = false;
    };
  }, [empresaActiva?.id]);

  const consultar = async () => {
    setErrorTitulo('Error al consultar');
    if (!periodo) return setError('Selecciona un período contable para generar el reporte.');
    setBusy(true);
    setError('');
    try {
      setReporte(
        await obtenerFormato131({
          periodo_id: periodo,
          establecimiento_id: establecimiento || undefined,
          producto_id: producto || undefined,
        })
      );
    } catch (e) {
      setError(apiError(e));
    } finally {
      setBusy(false);
    }
  };

  const descargarExcel = async () => {
    setErrorTitulo('Error al exportar');
    if (!periodo) return setError('Selecciona un período contable.');
    setExporting(true);
    setError('');
    const p = periodos.find((x) => String(x.id) === String(periodo));
    const nombre = nombreArchivoFormato131({
      periodo: p ? `${p.anio}-${String(p.mes).padStart(2, '0')}` : `periodo_${periodo}`,
      ruc: empresaActiva?.ruc,
    });
    try {
      await descargarFormato131({
        periodo_id: periodo,
        establecimiento_id: establecimiento || undefined,
        producto_id: producto || undefined,
      }, nombre);
    } catch (e) {
      // Antes: el cuerpo del error es un Blob y apiError() devolvía '' → no se mostraba nada.
      setError(await mensajeErrorExportacion(e));
    } finally {
      setExporting(false);
    }
  };

  const consultarReal = async () => {
    if (!periodo || !producto) return setError('Seleccione un período y un producto.');
    setBusy(true);
    setError('');
    setResultado(null);
    try {
      setReal(await obtenerPiloto(periodo, producto));
    } catch (e) {
      setError(apiError(e));
    } finally {
      setBusy(false);
    }
  };

  const comparar = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      const data = await compararPiloto({
        periodo_id: periodo,
        producto_id: producto,
        ...form,
      });
      setReal(data);
      setResultado(data);
    } catch (e) {
      setError(apiError(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* 1. Encabezado principal y Navegación de Pestañas Integrada (Compacto, sin scroll) */}
      <Tabs value={tab} onValueChange={(v) => setTab(v as 'formato' | 'piloto')}>
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-slate-200">
          <div>
            <h1 className="text-lg sm:text-xl font-bold tracking-tight text-slate-900 flex items-center gap-2">
              <FileCheck2 className="h-5 w-5 text-indigo-600 shrink-0" />
              Kardex Valorizado (Formato 13.1)
            </h1>
            <p className="text-xs text-slate-500 mt-0.5">
              Registro de inventario permanente valorizado y conciliación paralela
            </p>
          </div>

          {/* Selector de Pestañas Compacto (Sin scroll vertical ni desbordamientos) */}
          <div className="flex items-center gap-2 shrink-0">
            <TabsList className="inline-flex items-center h-9 p-1 overflow-hidden bg-slate-100 border border-slate-200/80 rounded-lg shadow-2xs">
              <TabsTrigger value="formato" className="h-7 gap-1.5 px-3 text-xs font-semibold leading-none">
                <FileCheck2 className="h-3.5 w-3.5" />
                Formato 13.1
              </TabsTrigger>
              <TabsTrigger value="piloto" className="h-7 gap-1.5 px-3 text-xs font-semibold leading-none">
                <Gauge className="h-3.5 w-3.5" />
                Piloto Paralelo
              </TabsTrigger>
            </TabsList>

            {tab === 'formato' && (
              <Button
                type="button"
                variant="success"
                size="sm"
                disabled={!periodo || busy || exporting}
                onClick={descargarExcel}
                className="shadow-xs h-9 text-xs font-semibold"
                title="Exportar archivo oficial en formato Excel (.xlsx)"
              >
                {exporting ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />
                ) : (
                  <FileDown className="h-3.5 w-3.5 mr-1.5" />
                )}
                {exporting ? 'Generando Excel...' : 'Exportar Excel'}
              </Button>
            )}
          </div>
        </div>

        {/* 2. Alertas */}
        {error && (
          <div role="alert" className="mt-3 rounded-lg border border-rose-200 bg-rose-50 p-3.5 text-xs text-rose-800 flex items-start gap-2.5">
            <AlertCircle className="h-4 w-4 text-rose-600 shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold">{errorTitulo}</p>
              <p className="mt-0.5">{error}</p>
            </div>
          </div>
        )}

        {/* ==================================================================== */}
        {/* PESTAÑA 1: REPORTE REGLAMENTARIO FORMATO 13.1                        */}
        {/* ==================================================================== */}
        <TabsContent value="formato" className="space-y-4 pt-1 mt-3">
          {/* Barra de Filtros Compacta de Alta Densidad */}
          <div className="bg-white p-3.5 rounded-xl border border-slate-200/90 shadow-2xs">
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-12 gap-3 items-end">
              <div className="space-y-1 lg:col-span-3">
                <Label htmlFor="f131-periodo" className="text-xs font-semibold text-slate-700">
                  Período Contable
                </Label>
                <Select
                  id="f131-periodo"
                  value={periodo}
                  onChange={(e) => setPeriodo(e.target.value)}
                  className="h-9 text-xs"
                >
                  <option value="">Seleccione un período...</option>
                  {periodos.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.anio}-{String(p.mes).padStart(2, '0')} · {p.estado}
                    </option>
                  ))}
                </Select>
              </div>

              <div className="space-y-1 lg:col-span-3">
                <Label htmlFor="f131-establecimiento" className="text-xs font-semibold text-slate-700">
                  Establecimiento SUNAT
                </Label>
                <Select
                  id="f131-establecimiento"
                  value={establecimiento}
                  onChange={(e) => setEstablecimiento(e.target.value)}
                  className="h-9 text-xs"
                >
                  <option value="">Todos los establecimientos</option>
                  {establecimientos.map((e) => (
                    <option key={e.id} value={e.id}>
                      {e.codigo_sunat} · {e.nombre}
                    </option>
                  ))}
                </Select>
              </div>

              <div className="space-y-1 lg:col-span-4">
                <Label htmlFor="f131-producto" className="text-xs font-semibold text-slate-700">
                  Producto / Existencia
                </Label>
                <Select
                  id="f131-producto"
                  value={producto}
                  onChange={(e) => setProducto(e.target.value)}
                  className="h-9 text-xs"
                >
                  <option value="">Todos los productos</option>
                  {productos.map((pr) => (
                    <option key={pr.id} value={pr.id}>
                      {pr.codigo_interno} · {pr.descripcion}
                    </option>
                  ))}
                </Select>
              </div>

              <div className="lg:col-span-2">
                <Button
                  type="button"
                  variant="primary"
                  disabled={busy || !periodo}
                  onClick={consultar}
                  className="w-full h-9 text-xs font-semibold shadow-xs"
                >
                  {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" /> : <Search className="h-3.5 w-3.5 mr-1.5" />}
                  {busy ? 'Consultando...' : 'Consultar Libro'}
                </Button>
              </div>
            </div>
          </div>

          {/* Estado Inicial o Vacío */}
          {!reporte && (
            <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50/50 py-12 text-center">
              <div className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-slate-100 text-slate-400 mb-2">
                <FileCheck2 className="h-5 w-5 text-slate-500" />
              </div>
              <h3 className="text-xs font-semibold text-slate-900">Seleccione los filtros para consultar el reporte oficial</h3>
              <p className="text-[11px] text-slate-500 max-w-md mx-auto mt-0.5">
                Emisión reglamentaria de kardex permanente valorizado bajo normativa SUNAT Res. 234-2006.
              </p>
            </div>
          )}

          {reporte && reporte.reportes.length === 0 && (
            <div className="rounded-xl border border-slate-200 bg-white py-12 text-center">
              <div className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-slate-100 text-slate-400 mb-2">
                <Inbox className="h-5 w-5" />
              </div>
              <h3 className="text-xs font-semibold text-slate-900">Sin movimientos registrados</h3>
              <p className="text-[11px] text-slate-500 max-w-md mx-auto mt-0.5">
                No existen operaciones para el período y filtros seleccionados.
              </p>
            </div>
          )}

          {/* Listado de reportes oficiales por existencia */}
          {reporte?.reportes.map((r) => (
            <div key={`${r.cabecera.establecimiento.id}-${r.cabecera.producto_id}`} className="shadow-2xs rounded-xl overflow-hidden border border-slate-200 bg-white">
              {/* ============================================================ */}
              {/* CABECERA DE LA EXISTENCIA (DATOS ESENCIALES SIN DUPLICADOS) */}
              {/* ============================================================ */}
              <div className="border-b border-slate-200 bg-slate-50/75 px-4 py-3">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  {/* Identificación de la Existencia (Esencial e importante) */}
                  <div className="space-y-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-mono font-bold text-xs bg-white text-slate-900 px-2 py-0.5 rounded border border-slate-300 shadow-2xs tabular-nums">
                        {r.cabecera.codigo_existencia}
                      </span>
                      <h2 className="font-bold text-sm text-slate-900 leading-tight">
                        {r.cabecera.descripcion_existencia}
                      </h2>
                    </div>

                    {/* Metadatos Técnicos SUNAT (Sin repetir RUC, Razón Social ni Período ya filtrado) */}
                    <div className="flex items-center gap-2.5 text-xs text-slate-600 flex-wrap">
                      <div className="flex items-center gap-1">
                        <span className="text-slate-400 font-medium">Establecimiento:</span>
                        <span className="font-medium text-slate-800">
                          <span className="font-mono font-bold text-slate-700">{r.cabecera.establecimiento.codigo_sunat}</span> · {r.cabecera.establecimiento.nombre}
                        </span>
                      </div>
                      <span className="text-slate-300">·</span>
                      <div className="flex items-center gap-1">
                        <span className="text-slate-400 font-medium">Tipo:</span>
                        <span className="text-slate-700">
                          <span className="font-mono font-bold text-slate-800">{r.cabecera.tipo_existencia.codigo}</span> · {r.cabecera.tipo_existencia.descripcion}
                        </span>
                      </div>
                      <span className="text-slate-300">·</span>
                      <div className="flex items-center gap-1">
                        <span className="text-slate-400 font-medium">Unidad:</span>
                        <span className="text-slate-700">
                          <span className="font-mono font-bold text-slate-800">{r.cabecera.unidad_medida.codigo}</span> · {r.cabecera.unidad_medida.descripcion}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Sello de Auditoría Criptográfica o Estado Preliminar */}
                  <div className="shrink-0 flex items-center gap-2">
                    {reporte.fuente_cierre ? (
                      <div className="inline-flex items-center gap-2 text-xs bg-slate-50 px-2.5 py-1 rounded-md border border-slate-200/80">
                        <div className="flex items-center gap-1.5 font-medium text-slate-800">
                          <ShieldCheck className="h-3.5 w-3.5 text-emerald-600 shrink-0" />
                          <span>Cierre v{reporte.fuente_cierre.version}</span>
                        </div>
                        <span className="text-slate-200">|</span>
                        <div className="flex items-center gap-1">
                          <span className="font-mono text-[11px] text-slate-400">SHA-256:</span>
                          <code className="font-mono text-[11px] font-semibold text-slate-700 bg-white px-1.5 py-0.5 rounded border border-slate-200/80">
                            {reporte.fuente_cierre.hash.slice(0, 16)}…
                          </code>
                        </div>
                      </div>
                    ) : (
                      <Badge variant="neutral" size="sm" className="font-medium text-slate-600 bg-slate-100 border border-slate-200/80">
                        Cálculo Preliminar
                      </Badge>
                    )}
                  </div>
                </div>
              </div>

              {/* ============================================================ */}
              {/* TABLA OFICIAL DE MOVIMIENTOS SUNAT                           */}
              {/* ============================================================ */}
              <div className="overflow-x-auto bg-white overscroll-contain">
                <table className="w-full text-xs text-left border-collapse">
                  <thead>
                    <tr className="bg-slate-100 text-[11px] font-bold text-slate-800 uppercase tracking-wider text-center border-b border-slate-300">
                      <th rowSpan={2} className="py-2.5 px-3 border-r border-slate-200 w-24">Fecha</th>
                      <th colSpan={3} className="py-1.5 px-3 border-r border-slate-200 bg-slate-100/90 text-slate-700">
                        Documento de Traslado / Comprobante
                      </th>
                      <th rowSpan={2} className="py-2.5 px-3 border-r border-slate-300 w-20">Tipo Op.</th>
                      <th colSpan={3} className="py-1.5 px-3 border-r border-slate-300 bg-slate-100 text-slate-800 font-bold">
                        Entradas
                      </th>
                      <th colSpan={3} className="py-1.5 px-3 border-r border-slate-300 bg-slate-100 text-slate-800 font-bold">
                        Salidas
                      </th>
                      <th colSpan={3} className="py-1.5 px-3 bg-slate-100 text-slate-900 font-extrabold">
                        Saldo Final
                      </th>
                    </tr>
                    <tr className="bg-slate-50 text-[10px] font-semibold text-slate-600 border-b border-slate-300">
                      {/* Documento */}
                      <th className="py-1.5 px-2 text-center">Tipo</th>
                      <th className="py-1.5 px-2 text-center">Serie</th>
                      <th className="py-1.5 px-2 text-center border-r border-slate-200">Número</th>

                      {/* Entradas */}
                      <th className="py-1.5 px-2.5 text-right font-mono">Cantidad</th>
                      <th className="py-1.5 px-2.5 text-right font-mono">Costo Unit.</th>
                      <th className="py-1.5 px-2.5 text-right font-mono border-r border-slate-300 font-bold">Costo Total</th>

                      {/* Salidas */}
                      <th className="py-1.5 px-2.5 text-right font-mono">Cantidad</th>
                      <th className="py-1.5 px-2.5 text-right font-mono">Costo Unit.</th>
                      <th className="py-1.5 px-2.5 text-right font-mono border-r border-slate-300 font-bold">Costo Total</th>

                      {/* Saldo Final */}
                      <th className="py-1.5 px-2.5 text-right font-mono">Cantidad</th>
                      <th className="py-1.5 px-2.5 text-right font-mono">Costo Unit.</th>
                      <th className="py-1.5 px-2.5 text-right font-mono font-bold text-slate-900">Costo Total</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 font-mono tabular-nums text-[11px]">
                    {(() => {
                      // Si ya existe un movimiento de Saldo Inicial en la lista (Op. 16 o serie SI),
                      // o si el arrastre previo es cero, no mostramos fila fantasma adicional.
                      const tieneMovSaldoInicial = r.movimientos.some(
                        (m) => m.tipo_operacion === '16' || m.documento?.serie === 'SI'
                      );
                      const ini = filaSaldoInicial(r);
                      const tieneArrastre =
                        ini.cantidad !== '—' &&
                        ini.cantidad !== '0.00000000' &&
                        ini.cantidad !== '0' &&
                        (ini.costoTotal !== '—' && ini.costoTotal !== '0.00000000' && ini.costoTotal !== '0');

                      if (tieneMovSaldoInicial || !tieneArrastre) return null;

                      return (
                        <tr className="bg-slate-50/80 font-semibold text-slate-900 border-b border-slate-200">
                          <td colSpan={5} className="py-2.5 px-3 text-left font-sans text-xs uppercase tracking-wide text-slate-800 font-bold border-r border-slate-300">
                            Saldo Inicial del Período
                          </td>
                          {/* Entradas del saldo inicial: completamente vacío */}
                          <td colSpan={3} className="border-r border-slate-300" />
                          {/* Salidas del saldo inicial: completamente vacío */}
                          <td colSpan={3} className="border-r border-slate-300" />
                          {/* Saldo Final Valorizado: de frente muestra los valores */}
                          <td className="py-2.5 px-2.5 text-right font-mono tabular-nums text-slate-900 font-bold">{ini.cantidad}</td>
                          <td className="py-2.5 px-2.5 text-right font-mono tabular-nums text-slate-700">{ini.costoUnitario}</td>
                          <td className="py-2.5 px-2.5 text-right font-mono tabular-nums font-extrabold text-slate-950">{ini.costoTotal}</td>
                        </tr>
                      );
                    })()}
                    {r.movimientos.length === 0 && (
                      <tr>
                        <td colSpan={14} className="py-8 px-3 text-center font-sans text-slate-400 italic">
                          Sin movimientos registrados en este establecimiento durante el período
                        </td>
                      </tr>
                    )}
                    {r.movimientos.map((m) => {
                      const esSaldoInicial = m.tipo_operacion === '16' || m.documento?.serie === 'SI';

                      return (
                        <tr key={m.movimiento_id} className="hover:bg-slate-50/80 transition-colors border-b border-slate-100">
                          <td className="py-2 px-3 text-center text-slate-700 whitespace-nowrap font-mono tabular-nums border-r border-slate-100">{m.fecha_emision}</td>
                          <td className="py-2 px-2 text-center font-mono tabular-nums text-slate-700">{m.documento.tipo_documento}</td>
                          <td className="py-2 px-2 text-center text-slate-600 font-mono tabular-nums">{m.documento.serie || '—'}</td>
                          <td className="py-2 px-2 text-center border-r border-slate-200 text-slate-800 font-mono tabular-nums">{m.documento.numero || '—'}</td>
                          <td className="py-2 px-3 text-center border-r border-slate-300 font-mono font-medium text-slate-700">
                            {m.tipo_operacion || '—'}
                          </td>

                          {/* Entradas (En Saldo Inicial va vacío para reflejarse directamente en Saldo Final) */}
                          <td className="py-2 px-2.5 text-right font-mono tabular-nums text-slate-900">
                            {esSaldoInicial ? <span className="text-slate-300 select-none font-mono">—</span> : n(m.entrada?.cantidad)}
                          </td>
                          <td className="py-2 px-2.5 text-right font-mono tabular-nums text-slate-600">
                            {esSaldoInicial ? <span className="text-slate-300 select-none font-mono">—</span> : n(m.entrada?.costo_unitario)}
                          </td>
                          <td className="py-2 px-2.5 text-right font-mono tabular-nums border-r border-slate-300 font-semibold text-slate-900">
                            {esSaldoInicial ? <span className="text-slate-300 select-none font-mono">—</span> : n(m.entrada?.costo_total)}
                          </td>

                          {/* Salidas */}
                          <td className="py-2 px-2.5 text-right font-mono tabular-nums text-slate-900">
                            {esSaldoInicial ? <span className="text-slate-300 select-none font-mono">—</span> : n(m.salida?.cantidad)}
                          </td>
                          <td className="py-2 px-2.5 text-right font-mono tabular-nums text-slate-600">
                            {esSaldoInicial ? <span className="text-slate-300 select-none font-mono">—</span> : n(m.salida?.costo_unitario)}
                          </td>
                          <td className="py-2 px-2.5 text-right font-mono tabular-nums border-r border-slate-300 font-semibold text-slate-900">
                            {esSaldoInicial ? <span className="text-slate-300 select-none font-mono">—</span> : n(m.salida?.costo_total)}
                          </td>

                          {/* Saldo Final (Refleja directamente el saldo inicial o acumulado) */}
                          <td className="py-2 px-2.5 text-right font-mono tabular-nums font-bold text-slate-900">{n(m.saldo_final.cantidad)}</td>
                          <td className="py-2 px-2.5 text-right font-mono tabular-nums text-slate-700">{n(m.saldo_final.costo_unitario)}</td>
                          <td className="py-2 px-2.5 text-right font-mono tabular-nums font-bold text-slate-950">
                            {n(m.saldo_final.costo_total)}
                          </td>
                        </tr>
                      );
                    })}
                    {(() => {
                      const fin = filaSaldoFinal(r);
                      return (
                        <tr className="bg-slate-100/90 font-semibold text-slate-900 border-t-2 border-slate-800">
                          <td colSpan={5} className="py-2.5 px-3 text-left font-sans text-xs uppercase tracking-wide text-slate-900 font-bold border-r border-slate-300">
                            Saldo Final del Período
                          </td>
                          {/* Entradas: vacío */}
                          <td colSpan={3} className="border-r border-slate-300" />
                          {/* Salidas: vacío */}
                          <td colSpan={3} className="border-r border-slate-300" />
                          {/* Saldo Final */}
                          <td className="py-2.5 px-2.5 text-right text-slate-950 font-bold font-mono tabular-nums">{fin.cantidad}</td>
                          <td className="py-2.5 px-2.5 text-right text-slate-900 font-mono tabular-nums">{fin.costoUnitario}</td>
                          <td className="py-2.5 px-2.5 text-right font-black text-slate-950 text-xs font-mono tabular-nums">{fin.costoTotal}</td>
                        </tr>
                      );
                    })()}
                  </tbody>
                </table>
              </div>

              {/* Microdiferencia de cierre si aplica */}
              {r.microdiferencia_cierre !== '0.00000000' && (
                <div className="bg-amber-50 border-t border-amber-200 px-4 py-2 text-xs text-amber-800 flex items-center gap-2">
                  <Info className="h-4 w-4 text-amber-600 shrink-0" />
                  <span>
                    <strong>
                      {r.fuente_saldo_final === 'CALCULADO'
                        ? 'Ajuste de redondeo del reparto por establecimiento:'
                        : 'Microdiferencia oficial asignada al establecimiento principal:'}
                    </strong>{' '}
                    S/ <code className="font-mono tabular-nums font-semibold">{r.microdiferencia_cierre}</code>{' '}
                    {r.fuente_saldo_final === 'CALCULADO'
                      ? '(el total de la empresa es el saldo contable real; no es una diferencia contable).'
                      : '(absorbida por redondeo contable).'}
                  </span>
                </div>
              )}
            </div>
          ))}
        </TabsContent>

        {/* ==================================================================== */}
        {/* PESTAÑA 2: LABORATORIO DE PILOTO PARALELO                            */}
        {/* ==================================================================== */}
        <TabsContent value="piloto" className="space-y-4 pt-1 mt-3">
          {/* Fila Superior: Configuración y Entrada de Parámetros */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
            {/* Formulario de Contraste */}
            <Card className="lg:col-span-6">
              <CardHeader className="pb-3 border-b border-slate-100">
                <CardTitle className="text-sm font-semibold text-slate-900 flex items-center gap-2">
                  <Scale className="h-4 w-4 text-indigo-600" />
                  Contraste con el Proceso Actual / Sistema Anterior
                </CardTitle>
                <CardDescription className="text-xs">
                  Ingrese los valores calculados manualmente por el contador o extraídos del ERP previo para validar la exactitud de FACT-KARD.
                </CardDescription>
              </CardHeader>
              <CardContent className="pt-3.5">
                <form onSubmit={comparar} className="space-y-3.5">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div className="space-y-1">
                      <Label htmlFor="piloto-periodo" className="text-xs font-semibold text-slate-700">Período a Evaluar</Label>
                      <Select
                        id="piloto-periodo"
                        value={periodo}
                        onChange={(e) => setPeriodo(e.target.value)}
                        className="h-9 text-xs"
                      >
                        <option value="">Seleccione...</option>
                        {periodos.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.anio}-{String(p.mes).padStart(2, '0')} · {p.estado}
                          </option>
                        ))}
                      </Select>
                    </div>

                    <div className="space-y-1">
                      <Label htmlFor="piloto-producto" className="text-xs font-semibold text-slate-700">Producto de Muestra</Label>
                      <Select
                        id="piloto-producto"
                        value={producto}
                        onChange={(e) => setProducto(e.target.value)}
                        className="h-9 text-xs"
                      >
                        <option value="">Seleccione...</option>
                        {productos.map((pr) => (
                          <option key={pr.id} value={pr.id}>
                            {pr.codigo_interno} · {pr.descripcion}
                          </option>
                        ))}
                      </Select>
                    </div>
                  </div>

                  <div className="flex justify-end">
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={consultarReal}
                      disabled={busy || !periodo || !producto}
                      className="text-xs text-indigo-600 hover:text-indigo-700 p-0 h-auto"
                    >
                      <RotateCcw className="h-3 w-3 mr-1" />
                      Consultar valores FACT-KARD en tiempo real
                    </Button>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-2 border-t border-slate-100">
                    <div className="space-y-1">
                      <Label htmlFor="piloto-cant" className="text-xs font-semibold text-slate-700">Cantidad Esperada</Label>
                      <Input
                        id="piloto-cant"
                        required
                        inputMode="decimal"
                        value={form.cantidad_esperada}
                        onChange={(e) => setForm((v) => ({ ...v, cantidad_esperada: e.target.value }))}
                        placeholder="Ej. 100.00"
                        className="font-mono tabular-nums h-9 text-xs"
                      />
                    </div>
                    <div className="space-y-1">
                      <Label htmlFor="piloto-cpp" className="text-xs font-semibold text-slate-700">CPP Esperado (PEN)</Label>
                      <Input
                        id="piloto-cpp"
                        required
                        inputMode="decimal"
                        value={form.cpp_esperado}
                        onChange={(e) => setForm((v) => ({ ...v, cpp_esperado: e.target.value }))}
                        placeholder="Ej. 12.500000"
                        className="font-mono tabular-nums h-9 text-xs"
                      />
                    </div>
                    <div className="space-y-1">
                      <Label htmlFor="piloto-val" className="text-xs font-semibold text-slate-700">Valor Esperado (S/)</Label>
                      <Input
                        id="piloto-val"
                        required
                        inputMode="decimal"
                        value={form.valor_esperado}
                        onChange={(e) => setForm((v) => ({ ...v, valor_esperado: e.target.value }))}
                        placeholder="Ej. 1250.00"
                        className="font-mono tabular-nums h-9 text-xs"
                      />
                    </div>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1">
                    <div className="space-y-1">
                      <Label htmlFor="piloto-t-man" className="text-xs font-semibold text-slate-700">Tiempo Manual Previo (segundos)</Label>
                      <Input
                        id="piloto-t-man"
                        required
                        inputMode="numeric"
                        value={form.tiempo_manual_segundos}
                        onChange={(e) => setForm((v) => ({ ...v, tiempo_manual_segundos: e.target.value }))}
                        placeholder="Ej. 1800 (30 min)"
                        className="font-mono tabular-nums h-9 text-xs"
                      />
                    </div>
                    <div className="space-y-1">
                      <Label htmlFor="piloto-t-fk" className="text-xs font-semibold text-slate-700">Tiempo FACT-KARD (segundos)</Label>
                      <Input
                        id="piloto-t-fk"
                        required
                        inputMode="numeric"
                        value={form.tiempo_factkard_segundos}
                        onChange={(e) => setForm((v) => ({ ...v, tiempo_factkard_segundos: e.target.value }))}
                        placeholder="Ej. 5 (5 seg)"
                        className="font-mono tabular-nums h-9 text-xs"
                      />
                    </div>
                  </div>

                  <div className="pt-2">
                    <Button
                      type="submit"
                      variant="primary"
                      disabled={busy}
                      className="w-full h-9 font-semibold text-xs shadow-xs"
                    >
                      {busy ? <Loader2 className="h-4 w-4 animate-spin mr-1.5" /> : <Gauge className="h-4 w-4 mr-1.5" />}
                      {busy ? 'Comparando...' : 'Comparar Resultados y Medir Eficiencia'}
                    </Button>
                  </div>
                </form>
              </CardContent>
            </Card>

            {/* Métrica Destacada: % de Reducción de Tiempo Operativo */}
            <div className="lg:col-span-6 space-y-4">
              <Card className="border-slate-200 bg-white shadow-2xs">
                <CardHeader className="pb-2.5 border-b border-slate-100">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-sm font-semibold text-slate-900 flex items-center gap-2">
                      <TrendingDown className="h-4 w-4 text-emerald-600" />
                      Eficiencia & Reducción de Tiempo Operativo
                    </CardTitle>
                    {resultado && (
                      <Badge variant="success" dot className="font-mono text-xs">
                        Benchmark Activo
                      </Badge>
                    )}
                  </div>
                </CardHeader>
                <CardContent className="pt-4">
                  {resultado ? (
                    <div className="space-y-3.5">
                      {/* Gran métrica de eficiencia */}
                      <div className="p-4 rounded-xl bg-emerald-50/70 border border-emerald-200 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                        <div>
                          <span className="text-[11px] font-bold text-emerald-800 uppercase tracking-wider block">
                            Reducción de Tiempo Operativo
                          </span>
                          <p className="text-xs text-emerald-700/90 mt-0.5">
                            Ahorro directo en horas hombre de cálculo contable y conciliación de inventarios
                          </p>
                        </div>
                        <div className="text-right shrink-0">
                          <span className="font-mono text-4xl sm:text-5xl font-black text-emerald-600 tabular-nums">
                            {resultado.reduccion_porcentaje}%
                          </span>
                        </div>
                      </div>

                      {/* Comparativa de tiempos */}
                      <div className="grid grid-cols-2 gap-3 text-xs">
                        <div className="p-3 rounded-lg border border-slate-200 bg-slate-50/50">
                          <span className="text-[10px] uppercase font-bold text-slate-400 block mb-1">
                            Tiempo Proceso Previo
                          </span>
                          <div className="flex items-center gap-1.5">
                            <Clock className="h-4 w-4 text-slate-400 shrink-0" />
                            <span className="font-mono text-sm font-bold text-slate-700 tabular-nums">
                              {form.tiempo_manual_segundos || '—'} s
                            </span>
                          </div>
                        </div>

                        <div className="p-3 rounded-lg border border-emerald-200 bg-emerald-50/30">
                          <span className="text-[10px] uppercase font-bold text-emerald-800 block mb-1">
                            Tiempo Motor FACT-KARD
                          </span>
                          <div className="flex items-center gap-1.5">
                            <Zap className="h-4 w-4 text-emerald-600 shrink-0" />
                            <span className="font-mono text-sm font-bold text-emerald-950 tabular-nums">
                              {form.tiempo_factkard_segundos || '—'} s
                            </span>
                            <span className="text-[10px] text-emerald-700 font-semibold bg-emerald-100/80 px-1 rounded">
                              Instantáneo
                            </span>
                          </div>
                        </div>
                      </div>

                      {/* Estado general del cuadre */}
                      <div
                        className={`rounded-lg p-3 border text-xs flex items-center gap-2.5 ${
                          resultado.cuadra_100
                            ? 'bg-emerald-50 border-emerald-300 text-emerald-900 font-medium'
                            : 'bg-amber-50 border-amber-300 text-amber-900 font-medium'
                        }`}
                      >
                        {resultado.cuadra_100 ? (
                          <CheckCircle2 className="h-5 w-5 text-emerald-600 shrink-0" />
                        ) : (
                          <AlertCircle className="h-5 w-5 text-amber-600 shrink-0" />
                        )}
                        <div>
                          <strong>
                            {resultado.cuadra_100
                              ? 'CUADRE CONTABLE PERFECTO (100% MATCH)'
                              : 'DISCREPANCIA DETECTADA — REQUIERE CONCILIACIÓN'}
                          </strong>
                          <p className="text-[11px] opacity-90 mt-0.5">
                            {resultado.cuadra_100
                              ? 'El motor FACT-KARD calculó exactamente los mismos valores requeridos sin desviación.'
                              : 'Existen diferencias numéricas entre la hoja manual y los movimientos del motor oficial.'}
                          </p>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="py-10 text-center text-xs text-slate-400">
                      <Gauge className="h-8 w-8 mx-auto text-slate-300 mb-2" />
                      Complete el formulario y ejecute la comparación para visualizar la reducción porcentual de tiempo y el contraste contable.
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>
          </div>

          {/* ================================================================= */}
          {/* MESA DE CONCILIACIÓN LADO A LADO (Manual Excel vs Motor FACT-KARD)*/}
          {/* ================================================================= */}
          <Card className="overflow-hidden">
            <CardHeader className="pb-3 border-b border-slate-100 bg-slate-50/50">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                <div>
                  <CardTitle className="text-sm font-semibold text-slate-900 flex items-center gap-2">
                    <Scale className="h-4 w-4 text-indigo-600" />
                    Mesa de Conciliación Lado a Lado (Manual Excel vs Motor FACT-KARD)
                  </CardTitle>
                  <CardDescription className="text-xs">
                    Comparación exhaustiva campo a campo con cálculo en tiempo real de tolerancias y deltas contables
                  </CardDescription>
                </div>
                {real && (
                  <Badge variant="outline" className="font-mono text-xs bg-white text-slate-700">
                    Fuente: {real.fuente.replaceAll('_', ' ')}
                  </Badge>
                )}
              </div>
            </CardHeader>
            <div className="overflow-x-auto">
              <table className="w-full text-xs text-left border-collapse">
                <thead>
                  <tr className="bg-slate-100 text-[11px] font-bold text-slate-700 uppercase tracking-wider border-b border-slate-200">
                    <th className="py-2.5 px-4 w-48">Variable Contable</th>
                    <th className="py-2.5 px-4 text-right bg-slate-50 border-r border-slate-200">
                      Manual / Hoja Excel Previa
                    </th>
                    <th className="py-2.5 px-4 text-right bg-slate-100/80 text-slate-900 border-r border-slate-200 font-bold">
                      Motor Oficial FACT-KARD
                    </th>
                    <th className="py-2.5 px-4 text-right bg-slate-50 border-r border-slate-200">
                      Diferencia (Δ Absoluta)
                    </th>
                    <th className="py-2.5 px-4 text-center">Estado de Conciliación</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 font-mono tabular-nums text-xs">
                  {/* Fila 1: Cantidad Física */}
                  <tr className="hover:bg-slate-50 transition-colors">
                    <td className="py-3 px-4 font-sans font-semibold text-slate-900">
                      Cantidad Física en Stock
                    </td>
                    <td className="py-3 px-4 text-right text-slate-700 font-medium border-r border-slate-200 bg-slate-50/30">
                      {form.cantidad_esperada || '—'}
                    </td>
                    <td className="py-3 px-4 text-right text-slate-950 font-bold border-r border-slate-200 bg-slate-50/50">
                      {real ? real.cantidad_factkard : '—'}
                    </td>
                    <td className="py-3 px-4 text-right font-bold border-r border-slate-200 bg-slate-50/30">
                      {resultado ? (
                        <span className={isZeroDiff(resultado.diferencias.cantidad) ? 'text-emerald-600' : 'text-rose-600'}>
                          {resultado.diferencias.cantidad}
                        </span>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td className="py-3 px-4 text-center">
                      {resultado ? (
                        isZeroDiff(resultado.diferencias.cantidad) ? (
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-emerald-50 text-emerald-700 border border-emerald-300">
                            <Check className="h-3 w-3 text-emerald-600" />
                            0.000000 · Cuadre Exacto
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-rose-50 text-rose-700 border border-rose-300">
                            <AlertCircle className="h-3 w-3 text-rose-600" />
                            Discrepancia {resultado.diferencias.cantidad}
                          </span>
                        )
                      ) : (
                        <span className="text-slate-400 font-sans text-[11px]">Pendiente de comparar</span>
                      )}
                    </td>
                  </tr>

                  {/* Fila 2: Costo Promedio Ponderado (CPP) */}
                  <tr className="hover:bg-slate-50 transition-colors">
                    <td className="py-3 px-4 font-sans font-semibold text-slate-900">
                      Costo Unitario Promedio (CPP en PEN)
                    </td>
                    <td className="py-3 px-4 text-right text-slate-700 font-medium border-r border-slate-200 bg-slate-50/30">
                      {form.cpp_esperado || '—'}
                    </td>
                    <td className="py-3 px-4 text-right text-slate-950 font-bold border-r border-slate-200 bg-slate-50/50">
                      {real ? real.cpp_factkard : '—'}
                    </td>
                    <td className="py-3 px-4 text-right font-bold border-r border-slate-200 bg-slate-50/30">
                      {resultado ? (
                        <span className={isZeroDiff(resultado.diferencias.cpp) ? 'text-emerald-600' : 'text-rose-600'}>
                          {resultado.diferencias.cpp}
                        </span>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td className="py-3 px-4 text-center">
                      {resultado ? (
                        isZeroDiff(resultado.diferencias.cpp) ? (
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-emerald-50 text-emerald-700 border border-emerald-300">
                            <Check className="h-3 w-3 text-emerald-600" />
                            0.000000 · Cuadre Exacto
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-rose-50 text-rose-700 border border-rose-300">
                            <AlertCircle className="h-3 w-3 text-rose-600" />
                            Discrepancia {resultado.diferencias.cpp}
                          </span>
                        )
                      ) : (
                        <span className="text-slate-400 font-sans text-[11px]">Pendiente de comparar</span>
                      )}
                    </td>
                  </tr>

                  {/* Fila 3: Saldo Valor Total */}
                  <tr className="hover:bg-slate-50 transition-colors bg-slate-50/40">
                    <td className="py-3 px-4 font-sans font-bold text-slate-950">
                      Valor Total de Inventario (S/)
                    </td>
                    <td className="py-3 px-4 text-right text-slate-900 font-bold border-r border-slate-200 bg-slate-50/30">
                      {form.valor_esperado ? `S/ ${form.valor_esperado}` : '—'}
                    </td>
                    <td className="py-3 px-4 text-right text-emerald-700 font-black border-r border-slate-200 bg-slate-50/50">
                      {real ? `S/ ${real.valor_factkard}` : '—'}
                    </td>
                    <td className="py-3 px-4 text-right font-black border-r border-slate-200 bg-slate-50/30">
                      {resultado ? (
                        <span className={isZeroDiff(resultado.diferencias.valor) ? 'text-emerald-600' : 'text-rose-600'}>
                          S/ {resultado.diferencias.valor}
                        </span>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td className="py-3 px-4 text-center">
                      {resultado ? (
                        isZeroDiff(resultado.diferencias.valor) ? (
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-emerald-50 text-emerald-700 border border-emerald-300">
                            <Check className="h-3 w-3 text-emerald-600" />
                            0.000000 · Cuadre Exacto
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-rose-50 text-rose-700 border border-rose-300">
                            <AlertCircle className="h-3 w-3 text-rose-600" />
                            Discrepancia S/ {resultado.diferencias.valor}
                          </span>
                        )
                      ) : (
                        <span className="text-slate-400 font-sans text-[11px]">Pendiente de comparar</span>
                      )}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
};

export default Formato131Page;
