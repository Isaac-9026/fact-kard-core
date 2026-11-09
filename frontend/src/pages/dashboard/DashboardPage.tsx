import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  LayoutDashboard,
  CalendarRange,
  Coins,
  Boxes,
  ArrowDownLeft,
  ArrowUpRight,
  ShoppingCart,
  Receipt,
  AlertTriangle,
  Lock,
  BookOpenCheck,
  RefreshCw,
  ShieldCheck,
  CheckCircle2,
  ArrowRight,
  ScanText,
  AlertCircle,
  FileCheck2,
} from 'lucide-react';
import { useAuth } from '../../context/useAuth';
import { obtenerPeriodos } from '../../api/periodos';
import { obtenerKardexValorizado } from '../../api/reportes';
import { obtenerDocumentosPaginados } from '../../api/documentos';
import { obtenerIncidencias, type Incidencia } from '../../api/kardex';
import { obtenerCierres } from '../../api/cierres';
import { diferirCarga } from '../../utils/efectos';
import { leerPeriodoGuardado } from '../../utils/kardexVista';
import { filtrosApiDocumentos } from '../../utils/vistaDocumentos';
import {
  SIN_DATO,
  contarPendientes,
  etiquetaPeriodo,
  periodoActivo,
  resumenUltimoCierre,
  textoODato,
  type PeriodoDashboard,
  type ResumenCierre,
} from '../../utils/dashboard';
import { PageHeader } from '../../components/ui/page-header';
import { Card, CardHeader, CardTitle, CardDescription, CardContent, KpiCard } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { Badge } from '../../components/ui/badge';
import { formatearDecimal } from '../../utils/decimal';

// Redondeo decimal ROUND_HALF_UP (sin pasar por float).
const formatQty = (v: string | number) => formatearDecimal(v, { min: 2, max: 6 });
const formatMoney = (v: string | number) => `S/ ${formatearDecimal(v)}`;

interface DatosDashboard {
  periodo: PeriodoDashboard | null;
  stockTotal: string | null;
  valorTotal: string | null;
  compras: number | null;
  ventas: number | null;
  incidenciasPendientes: number | null;
  incidenciasLista: Incidencia[];
  ultimoCierre: ResumenCierre | null;
  sinCierres: boolean;
}

const VACIO: DatosDashboard = {
  periodo: null,
  stockTotal: null,
  valorTotal: null,
  compras: null,
  ventas: null,
  incidenciasPendientes: null,
  incidenciasLista: [],
  ultimoCierre: null,
  sinCierres: false,
};

/** Cuenta los comprobantes confirmados de una clase en el período (conteo paginado, sin notas). */
const contarConfirmados = async (clase: 'COMPRA' | 'VENTA', periodoId: number) => {
  const pagina = await obtenerDocumentosPaginados(
    filtrosApiDocumentos('COMPROBANTES', { clase, periodo: periodoId, estado: 'CONFIRMADO' as const }),
    { page: 1, page_size: 1 },
  );
  return pagina.count;
};

/**
 * Centro de Comando Contable (Dashboard):
 * Supervisión del período activo, valuación de inventarios, pipeline contable y alertas de pre-cierre.
 */
export const DashboardPage: React.FC = () => {
  const { empresaActiva } = useAuth();
  const navigate = useNavigate();
  const [datos, setDatos] = useState<DatosDashboard>(VACIO);
  const [cargando, setCargando] = useState(true);
  const [errores, setErrores] = useState<string[]>([]);

  const empresaId = empresaActiva?.id;
  const cargar = useCallback(async () => {
    if (!empresaId) return;
    setCargando(true);
    const fallas: string[] = [];
    const valor = async <T,>(nombre: string, promesa: Promise<T>): Promise<T | null> => {
      try {
        return await promesa;
      } catch {
        fallas.push(nombre);
        return null;
      }
    };

    const [periodos, kardex, incidencias, cierres] = await Promise.all([
      valor('períodos', obtenerPeriodos()),
      valor('stock y valor', obtenerKardexValorizado({}, { page: 1, page_size: 1 })),
      valor('incidencias', obtenerIncidencias()),
      valor('cierres', obtenerCierres()),
    ]);
    const periodo = periodos ? periodoActivo(periodos, leerPeriodoGuardado(empresaId)) : null;
    const [compras, ventas] = periodo
      ? await Promise.all([
          valor('compras', contarConfirmados('COMPRA', periodo.id)),
          valor('ventas', contarConfirmados('VENTA', periodo.id)),
        ])
      : [null, null];

    setDatos({
      periodo,
      stockTotal: kardex?.resumen?.saldo_final_cantidad ?? null,
      valorTotal: kardex?.resumen?.saldo_final_valor ?? null,
      compras,
      ventas,
      incidenciasPendientes: incidencias ? contarPendientes(incidencias) : null,
      incidenciasLista: incidencias ?? [],
      ultimoCierre: cierres ? resumenUltimoCierre(cierres) : null,
      sinCierres: Boolean(cierres && cierres.length === 0),
    });
    setErrores(fallas);
    setCargando(false);
  }, [empresaId]);

  useEffect(() => {
    diferirCarga(cargar);
  }, [cargar]);

  const v = (texto: string) => (cargando ? '...' : texto);
  const etiqueta = etiquetaPeriodo(datos.periodo);

  const bloqueanCierre = datos.incidenciasLista.filter(
    (i) => i.estado === 'PENDIENTE' && i.bloquea_cierre,
  );

  return (
    <div className="space-y-4">
      {/* =========================================================================
          NIVEL 1 — HEADER EJECUTIVO + CINTA DE CONTEXTO FISCAL
          ========================================================================= */}
      <PageHeader
        title="Centro de Comando Contable"
        description={
          empresaActiva
            ? `${empresaActiva.razon_social} · RUC ${empresaActiva.ruc} · Rol: ${empresaActiva.rol}`
            : 'Supervisión del período contable, motor Kardex y auditoría inmutable'
        }
        icon={<LayoutDashboard className="h-5 w-5 text-indigo-600" />}
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="success"
              size="sm"
              onClick={() => navigate('/comprobantes?clase=COMPRA&nuevo=1')}
              data-acceso="/comprobantes?clase=COMPRA&nuevo=1"
              className="shadow-xs h-9 text-xs font-semibold"
            >
              <ShoppingCart className="h-3.5 w-3.5 mr-1.5" /> Nueva Compra
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={() => navigate('/comprobantes?clase=VENTA&nuevo=1')}
              data-acceso="/comprobantes?clase=VENTA&nuevo=1"
              className="shadow-xs h-9 text-xs font-semibold"
            >
              <Receipt className="h-3.5 w-3.5 mr-1.5" /> Nueva Venta
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => void cargar()}
              disabled={cargando}
              className="shadow-xs h-9 text-xs text-slate-700 hover:bg-slate-50 transition-colors"
            >
              <RefreshCw className={`h-3.5 w-3.5 mr-1.5 text-slate-500 ${cargando ? 'animate-spin' : ''}`} /> Actualizar
            </Button>
          </div>
        }
      />

      {/* Cinta de Contexto Fiscal Integrada (Barra Unificada de Alta Densidad con Divisiones Elegantes) */}
      <div className="rounded-xl border border-slate-200/90 bg-white shadow-2xs overflow-hidden">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 divide-y sm:divide-y-0 sm:divide-x divide-slate-100">
          {/* Segmento 1: Período Operativo Activo */}
          <div className="p-3.5 flex items-start gap-3 hover:bg-slate-50/50 transition-colors">
            <div className="h-9 w-9 rounded-lg bg-indigo-50 border border-indigo-100/80 flex items-center justify-center text-indigo-600 shrink-0 mt-0.5 shadow-2xs">
              <CalendarRange className="h-4 w-4" />
            </div>
            <div className="min-w-0 flex-1">
              <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 block">
                Período Operativo
              </span>
              <div className="flex items-center gap-2 mt-0.5">
                <span className="font-mono tabular-nums font-bold text-sm text-slate-900">
                  {v(etiqueta)}
                </span>
                {datos.periodo ? (
                  <Badge variant={datos.periodo.estado === 'ABIERTO' ? 'success' : 'neutral'} size="xs" dot>
                    {datos.periodo.estado}
                  </Badge>
                ) : !cargando ? (
                  <Badge variant="warning" size="xs">
                    SIN PERÍODO
                  </Badge>
                ) : null}
              </div>
              <p className="text-[11px] text-slate-500 mt-0.5 truncate">
                {datos.periodo ? 'Período contable en curso' : 'Sin período seleccionado'}
              </p>
            </div>
          </div>

          {/* Segmento 2: Norma de Valuación & IGV */}
          <div className="p-3.5 flex items-start gap-3 hover:bg-slate-50/50 transition-colors">
            <div className="h-9 w-9 rounded-lg bg-emerald-50 border border-emerald-100/80 flex items-center justify-center text-emerald-600 shrink-0 mt-0.5 shadow-2xs">
              <ShieldCheck className="h-4 w-4" />
            </div>
            <div className="min-w-0 flex-1">
              <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 block">
                Valuación & Régimen
              </span>
              <div className="flex items-center gap-1.5 mt-0.5">
                <span className="font-mono tabular-nums text-xs font-bold text-slate-900">
                  CPP · 6 Dec. PEN
                </span>
                <span className="text-slate-300">·</span>
                <span className="text-xs text-slate-700 font-medium">IGV 18%</span>
              </div>
              <p className="text-[11px] text-slate-500 mt-0.5 truncate">
                Costo Promedio Ponderado
              </p>
            </div>
          </div>

          {/* Segmento 3: Semáforo Pre-Cierre */}
          <div className="p-3.5 flex items-start gap-3 hover:bg-slate-50/50 transition-colors">
            <div
              className={`h-9 w-9 rounded-lg border flex items-center justify-center shrink-0 mt-0.5 shadow-2xs ${
                bloqueanCierre.length > 0
                  ? 'bg-rose-50 border-rose-200 text-rose-600'
                  : 'bg-emerald-50 border-emerald-200 text-emerald-600'
              }`}
            >
              {bloqueanCierre.length > 0 ? (
                <AlertCircle className="h-4 w-4" />
              ) : (
                <CheckCircle2 className="h-4 w-4" />
              )}
            </div>
            <div className="min-w-0 flex-1">
              <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 block">
                Control Pre-Cierre
              </span>
              <div className="mt-0.5">
                {cargando ? (
                  <span className="text-xs text-slate-400">Consultando...</span>
                ) : bloqueanCierre.length > 0 ? (
                  <span className="font-mono tabular-nums font-bold text-xs text-rose-700 flex items-center gap-1 truncate">
                    {bloqueanCierre.length} Incidencia(s) Crítica(s)
                  </span>
                ) : (
                  <span className="font-bold text-xs text-emerald-700 flex items-center gap-1">
                    Listo para Cierre
                  </span>
                )}
              </div>
              <p className="text-[11px] text-slate-500 mt-0.5 truncate">
                {bloqueanCierre.length > 0 ? 'Bloquean congelamiento' : 'Sin quiebres ni inconsistencias'}
              </p>
            </div>
          </div>

          {/* Segmento 4: Último Cierre Oficial */}
          <div className="p-3.5 flex items-start gap-3 hover:bg-slate-50/50 transition-colors">
            <div className="h-9 w-9 rounded-lg bg-slate-50 border border-slate-200/80 flex items-center justify-center text-slate-600 shrink-0 mt-0.5 shadow-2xs">
              <Lock className="h-4 w-4" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between gap-1">
                <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 block truncate">
                  Último Cierre Oficial
                </span>
                <Badge variant="neutral" size="xs" className="font-mono text-[9px] px-1 py-0 gap-1">
                  <ShieldCheck className="h-2.5 w-2.5 text-slate-500" /> SHA-256
                </Badge>
              </div>
              <div className="mt-0.5">
                {cargando ? (
                  <span className="text-xs text-slate-400">...</span>
                ) : datos.ultimoCierre ? (
                  <span className="font-mono tabular-nums text-xs font-semibold text-slate-900 block truncate">
                    {datos.ultimoCierre.titulo}
                  </span>
                ) : datos.sinCierres ? (
                  <span className="text-xs text-slate-500">Sin cierres previos</span>
                ) : (
                  <span className="text-xs text-slate-400">{SIN_DATO}</span>
                )}
              </div>
              <p className="text-[11px] text-slate-500 mt-0.5 truncate">
                {datos.ultimoCierre?.detalle ?? 'Snapshot inmutable'}
              </p>
            </div>
          </div>
        </div>
      </div>

      {errores.length > 0 && !cargando && (
        <div role="status" className="rounded-lg border border-amber-200 bg-amber-50/90 p-3 text-xs text-amber-800">
          No se pudo consultar: {errores.join(', ')}. Esos datos se muestran como “{SIN_DATO}”.
        </div>
      )}

      {/* =========================================================================
          NIVEL 2 — FILA ÚNICA DE 4 KPIs FINANCIEROS PUROS (Conserva data-testid="dashboard-kpis")
          ========================================================================= */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5" data-testid="dashboard-kpis">
        <KpiCard
          title="Valor del Inventario (PEN)"
          value={v(textoODato(datos.valorTotal, formatMoney))}
          subtitle="Saldo total valorizado CPP · PEN"
          icon={<Coins className="h-3.5 w-3.5 text-slate-700" />}
          className="border-slate-200/90 bg-white shadow-2xs hover:border-slate-300 transition-colors"
        />
        <KpiCard
          title="Stock Físico Total"
          value={v(textoODato(datos.stockTotal, formatQty))}
          subtitle="Unidades acumuladas en almacén"
          icon={<Boxes className="h-3.5 w-3.5 text-slate-700" />}
          className="border-slate-200/90 bg-white shadow-2xs hover:border-slate-300 transition-colors"
        />
        <KpiCard
          title="Compras Confirmadas"
          value={v(textoODato(datos.compras))}
          subtitle={datos.periodo ? `Mes ${etiqueta} · Afectas a Kardex` : 'Mes en curso'}
          icon={<ArrowDownLeft className="h-3.5 w-3.5 text-emerald-600" />}
          className="border-slate-200/90 bg-white shadow-2xs hover:border-slate-300 transition-colors"
        />
        <KpiCard
          title="Ventas Confirmadas"
          value={v(textoODato(datos.ventas))}
          subtitle={datos.periodo ? `Mes ${etiqueta} · Salidas valorizadas` : 'Mes en curso'}
          icon={<ArrowUpRight className="h-3.5 w-3.5 text-indigo-600" />}
          className="border-slate-200/90 bg-white shadow-2xs hover:border-slate-300 transition-colors"
        />
      </div>

      {/* =========================================================================
          NIVEL 3 — PIPELINE DEL CICLO CONTABLE MENSUAL (4 ETAPAS SECUENCIALES)
          ========================================================================= */}
      <Card className="border-slate-200/90 shadow-2xs overflow-hidden">
        <CardHeader className="py-3 px-4 border-b border-slate-100 bg-slate-50/50">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1">
            <div>
              <CardTitle className="text-sm font-semibold text-slate-900 flex items-center gap-2">
                <FileCheck2 className="h-4 w-4 text-indigo-600" />
                Pipeline del Ciclo Contable Mensual
              </CardTitle>
              <CardDescription className="text-xs">
                Secuencia operativa para el registro, costeo Kardex, resolución de incidencias y cierre oficial
              </CardDescription>
            </div>
            <span className="text-[11px] font-mono font-semibold text-slate-600 bg-slate-100 px-2.5 py-1 rounded-md self-start sm:self-auto border border-slate-200/70">
              Período: {v(etiqueta)}
            </span>
          </div>
        </CardHeader>
        <CardContent className="p-4">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3 relative">
            {/* Etapa 01: Captura & Registro */}
            <div className="p-3.5 rounded-xl border border-slate-200 bg-white shadow-2xs flex flex-col justify-between space-y-3 relative group hover:border-indigo-300 transition-colors">
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-bold font-mono uppercase tracking-wider text-indigo-700 bg-indigo-50 px-2 py-0.5 rounded border border-indigo-200/60">
                    01 CAPTURA
                  </span>
                  <Receipt className="h-4 w-4 text-slate-400 group-hover:text-indigo-600 transition-colors" />
                </div>
                <h4 className="font-semibold text-xs text-slate-900 pt-0.5">Captura & Registro</h4>
                <p className="text-[11px] text-slate-500 leading-relaxed">
                  Registro de comprobantes, facturas, boletas, notas y extracción automatizada XML / OCR.
                </p>
              </div>
              <div className="flex items-center gap-1.5 pt-1">
                <Button
                  size="xs"
                  variant="outline"
                  onClick={() => navigate('/documentos')}
                  className="flex-1 text-[11px] h-7 font-medium hover:border-indigo-300 hover:text-indigo-700"
                >
                  Comprobantes
                </Button>
                <Button
                  size="xs"
                  variant="outline"
                  onClick={() => navigate('/captura-homologacion')}
                  className="flex-1 text-[11px] h-7 font-medium hover:border-indigo-300 hover:text-indigo-700"
                  title="Captura XML / OCR y homologación"
                >
                  <ScanText className="h-3 w-3 mr-1" /> Captura
                </Button>
              </div>
            </div>

            {/* Etapa 02: Kardex Permanente */}
            <div className="p-3.5 rounded-xl border border-slate-200 bg-white shadow-2xs flex flex-col justify-between space-y-3 relative group hover:border-indigo-300 transition-colors">
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-bold font-mono uppercase tracking-wider text-indigo-700 bg-indigo-50 px-2 py-0.5 rounded border border-indigo-200/60">
                    02 KARDEX
                  </span>
                  <BookOpenCheck className="h-4 w-4 text-slate-400 group-hover:text-indigo-600 transition-colors" />
                </div>
                <h4 className="font-semibold text-xs text-slate-900 pt-0.5">Kardex Permanente</h4>
                <p className="text-[11px] text-slate-500 leading-relaxed">
                  Cálculo automático de CPP, saldo físico continuo y valorización cronológica en PEN.
                </p>
              </div>
              <div className="flex items-center gap-1.5 pt-1">
                <Button
                  size="xs"
                  variant="outline"
                  onClick={() => navigate('/kardex')}
                  data-acceso="/kardex"
                  className="flex-1 text-[11px] h-7 font-medium hover:border-indigo-300 hover:text-indigo-700"
                >
                  Ver Kardex
                </Button>
                <Button
                  size="xs"
                  variant="outline"
                  onClick={() => navigate('/inventario')}
                  className="flex-1 text-[11px] h-7 font-medium hover:border-indigo-300 hover:text-indigo-700"
                >
                  Stock Actual
                </Button>
              </div>
            </div>

            {/* Etapa 03: Control de Incidencias */}
            <div
              className={`p-3.5 rounded-xl border shadow-2xs flex flex-col justify-between space-y-3 relative transition-all ${
                bloqueanCierre.length > 0
                  ? 'border-rose-300 bg-rose-50/30'
                  : (datos.incidenciasPendientes ?? 0) > 0
                  ? 'border-amber-300 bg-amber-50/20'
                  : 'border-slate-200 bg-white hover:border-indigo-300'
              }`}
            >
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <span
                    className={`text-[10px] font-bold font-mono uppercase tracking-wider px-2 py-0.5 rounded border ${
                      bloqueanCierre.length > 0
                        ? 'text-rose-700 bg-rose-100/90 border-rose-200'
                        : (datos.incidenciasPendientes ?? 0) > 0
                        ? 'text-amber-700 bg-amber-100/90 border-amber-200'
                        : 'text-indigo-700 bg-indigo-50 border-indigo-200/60'
                    }`}
                  >
                    03 INCIDENCIAS
                  </span>
                  <AlertTriangle
                    className={`h-4 w-4 ${
                      bloqueanCierre.length > 0
                        ? 'text-rose-600'
                        : (datos.incidenciasPendientes ?? 0) > 0
                        ? 'text-amber-600'
                        : 'text-slate-400'
                    }`}
                  />
                </div>
                <h4 className="font-semibold text-xs text-slate-900 pt-0.5">Control de Incidencias</h4>
                <p className="text-[11px] text-slate-500 leading-relaxed">
                  Detección y recálculo de quiebres de stock negativo o inconsistencias cronológicas.
                </p>
              </div>
              <div className="pt-1">
                <Button
                  size="xs"
                  variant={bloqueanCierre.length > 0 ? 'destructive' : 'outline'}
                  onClick={() => navigate('/incidencias')}
                  data-acceso="/incidencias"
                  className="w-full text-[11px] h-7 font-medium"
                >
                  Incidencias ({datos.incidenciasPendientes ?? 0})
                  {bloqueanCierre.length > 0 && <span className="ml-1 text-[10px]">· {bloqueanCierre.length} bloquean</span>}
                </Button>
              </div>
            </div>

            {/* Etapa 04: Cierre & Formato 13.1 */}
            <div className="p-3.5 rounded-xl border border-slate-200 bg-white shadow-2xs flex flex-col justify-between space-y-3 relative group hover:border-indigo-300 transition-colors">
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-bold font-mono uppercase tracking-wider text-indigo-700 bg-indigo-50 px-2 py-0.5 rounded border border-indigo-200/60">
                    04 CIERRE & SUNAT
                  </span>
                  <Lock className="h-4 w-4 text-slate-400 group-hover:text-indigo-600 transition-colors" />
                </div>
                <h4 className="font-semibold text-xs text-slate-900 pt-0.5">Cierre & Formato 13.1</h4>
                <p className="text-[11px] text-slate-500 leading-relaxed">
                  Congelamiento inmutable con snapshot criptográfico SHA-256 y reporte oficial SUNAT.
                </p>
              </div>
              <div className="flex items-center gap-1.5 pt-1">
                <Button
                  size="xs"
                  variant="outline"
                  onClick={() => navigate('/cierres')}
                  className="flex-1 text-[11px] h-7 font-medium hover:border-indigo-300 hover:text-indigo-700"
                >
                  Cierres
                </Button>
                <Button
                  size="xs"
                  variant="outline"
                  onClick={() => navigate('/formato-13-1')}
                  className="flex-1 text-[11px] h-7 font-medium hover:border-indigo-300 hover:text-indigo-700"
                >
                  Formato 13.1
                </Button>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* =========================================================================
          NIVEL 4 — MESA DE CONTROL PRE-CIERRE (2 COLUMNAS lg:grid-cols-12)
          ========================================================================= */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* Columna Izquierda (lg:col-span-7) — Bandeja de Alertas Contables Bloqueantes */}
        <Card className="lg:col-span-7 border-slate-200/90 shadow-2xs overflow-hidden">
          <CardHeader className="py-3 px-4 border-b border-slate-100 bg-slate-50/50 flex flex-row items-center justify-between">
            <div className="flex items-center gap-2">
              <AlertCircle className={`h-4 w-4 shrink-0 ${bloqueanCierre.length > 0 ? 'text-rose-600' : 'text-indigo-600'}`} />
              <CardTitle className="text-sm font-semibold text-slate-900">
                Bandeja de Alertas Contables Bloqueantes
              </CardTitle>
            </div>
            <Badge variant={bloqueanCierre.length > 0 ? 'destructive' : 'success'} size="xs" dot>
              {bloqueanCierre.length > 0 ? `${bloqueanCierre.length} crítica(s)` : '0 Bloqueos'}
            </Badge>
          </CardHeader>
          <CardContent className="p-4">
            {bloqueanCierre.length === 0 ? (
              <div className="p-4 rounded-xl border border-emerald-200/90 bg-emerald-50/40 flex items-start gap-3.5 shadow-2xs">
                <div className="p-2 rounded-lg bg-emerald-100 text-emerald-800 shrink-0">
                  <CheckCircle2 className="h-5 w-5 text-emerald-700" />
                </div>
                <div className="space-y-1">
                  <h4 className="text-xs font-bold text-emerald-900">Período Operativo Verificado sin Bloqueos</h4>
                  <p className="text-xs text-emerald-800 leading-relaxed">
                    Todas las entradas, salidas y valuaciones CPP cumplen estrictamente las reglas contables del motor Kardex. No existen quiebres de stock negativo ni alteraciones cronológicas que impidan el cierre oficial.
                  </p>
                  {(datos.incidenciasPendientes ?? 0) > 0 && (
                    <p className="text-[11px] text-emerald-700 pt-1 font-medium">
                      Nota de auditoría: Hay {datos.incidenciasPendientes} incidencia(s) informativas de recálculo no bloqueantes registradas en el sistema.
                    </p>
                  )}
                </div>
              </div>
            ) : (
              <div className="space-y-2.5">
                <div className="text-xs text-rose-800 bg-rose-50 border border-rose-200 rounded-lg p-2.5 font-medium flex items-center justify-between">
                  <span>Se detectaron {bloqueanCierre.length} incidencia(s) crítica(s) que impiden el cierre del período:</span>
                  <span className="font-mono text-[10px] bg-rose-200 text-rose-900 px-2 py-0.5 rounded font-bold">
                    ACCIÓN REQUERIDA
                  </span>
                </div>
                {bloqueanCierre.slice(0, 4).map((inc) => (
                  <div
                    key={inc.id}
                    className="p-3 rounded-lg border border-rose-200 bg-white hover:bg-rose-50/30 transition-colors shadow-2xs flex items-start justify-between gap-3"
                  >
                    <div className="space-y-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <Badge variant="destructive" size="xs">
                          {inc.tipo}
                        </Badge>
                        <span className="font-mono tabular-nums text-[11px] text-slate-500">
                          {new Date(inc.detectado_en).toLocaleDateString('es-PE')}
                        </span>
                        <span className="font-mono text-[10px] text-slate-400">· ID #{inc.id}</span>
                      </div>
                      <p className="text-xs text-slate-800 font-medium leading-snug">{inc.descripcion}</p>
                    </div>
                    <Button
                      size="xs"
                      variant="outline"
                      onClick={() => navigate('/incidencias')}
                      className="shrink-0 h-7 text-xs text-rose-700 border-rose-200 hover:bg-rose-50 font-medium"
                    >
                      Resolver <ArrowRight className="h-3 w-3 ml-1" />
                    </Button>
                  </div>
                ))}
                {bloqueanCierre.length > 4 && (
                  <div className="pt-1 text-center">
                    <Button
                      size="xs"
                      variant="ghost"
                      onClick={() => navigate('/incidencias')}
                      className="text-xs text-rose-700 hover:text-rose-800"
                    >
                      Ver {bloqueanCierre.length - 4} incidencia(s) crítica(s) adicional(es) en Incidencias →
                    </Button>
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Columna Derecha (lg:col-span-5) — Checklist de Verificación para Cierre y Formato 13.1 */}
        <Card className="lg:col-span-5 border-slate-200/90 shadow-2xs overflow-hidden">
          <CardHeader className="py-3 px-4 border-b border-slate-100 bg-slate-50/50 flex flex-row items-center justify-between">
            <div>
              <CardTitle className="text-sm font-semibold text-slate-900">
                Checklist Pre-Cierre Mensual
              </CardTitle>
              <CardDescription className="text-xs">
                Condiciones normativas previas al Formato 13.1
              </CardDescription>
            </div>
            <span className="font-mono text-[10px] bg-slate-100 text-slate-600 border border-slate-200 px-2 py-0.5 rounded font-semibold">
              PRE-FLIGHT
            </span>
          </CardHeader>
          <CardContent className="p-4 space-y-3">
            {/* 1. Empresa activa y período contable identificado */}
            <div className="flex items-start gap-2.5 p-2 rounded-lg border border-slate-100 bg-slate-50/70">
              {empresaActiva && datos.periodo ? (
                <CheckCircle2 className="h-4 w-4 text-emerald-600 shrink-0 mt-0.5" />
              ) : (
                <AlertCircle className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />
              )}
              <div className="min-w-0">
                <h5 className="text-xs font-semibold text-slate-900">Empresa y Período Operativo</h5>
                <p className="text-[11px] text-slate-500 leading-tight">
                  {empresaActiva && datos.periodo
                    ? `Período ${etiqueta} (${datos.periodo.estado}) asignado a ${empresaActiva.razon_social}`
                    : 'Falta seleccionar una empresa o período contable activo'}
                </p>
              </div>
            </div>

            {/* 2. Movimientos valorizados bajo CPP en Soles */}
            <div className="flex items-start gap-2.5 p-2 rounded-lg border border-slate-100 bg-slate-50/70">
              {datos.valorTotal !== null && !cargando ? (
                <CheckCircle2 className="h-4 w-4 text-emerald-600 shrink-0 mt-0.5" />
              ) : (
                <AlertCircle className="h-4 w-4 text-amber-500 shrink-0 mt-0.5" />
              )}
              <div className="min-w-0">
                <h5 className="text-xs font-semibold text-slate-900">Valuación CPP en Moneda Nacional</h5>
                <p className="text-[11px] text-slate-500 leading-tight">
                  {datos.valorTotal !== null && !cargando
                    ? `Saldo valorizado en ${formatMoney(datos.valorTotal)} (PEN) con 6 decimales operativos`
                    : 'Sin saldo valorizado o cálculo en proceso'}
                </p>
              </div>
            </div>

            {/* 3. Ausencia de quiebres de stock o incidencias bloqueantes */}
            <div className="flex items-start gap-2.5 p-2 rounded-lg border border-slate-100 bg-slate-50/70">
              {bloqueanCierre.length === 0 ? (
                <CheckCircle2 className="h-4 w-4 text-emerald-600 shrink-0 mt-0.5" />
              ) : (
                <AlertCircle className="h-4 w-4 text-rose-500 shrink-0 mt-0.5" />
              )}
              <div className="min-w-0">
                <h5 className="text-xs font-semibold text-slate-900">Consistencia & Stock Físico</h5>
                <p className="text-[11px] text-slate-500 leading-tight">
                  {bloqueanCierre.length === 0
                    ? '0 incidencias críticas · Sin quiebres negativos ni alteraciones'
                    : `${bloqueanCierre.length} incidencia(s) crítica(s) bloquean el cierre oficial`}
                </p>
              </div>
            </div>

            {/* 4. Trazabilidad lista para Formato 13.1 SUNAT y Snapshot SHA-256 */}
            <div className="flex items-start gap-2.5 p-2 rounded-lg border border-slate-100 bg-slate-50/70">
              {bloqueanCierre.length === 0 && datos.periodo ? (
                <CheckCircle2 className="h-4 w-4 text-emerald-600 shrink-0 mt-0.5" />
              ) : (
                <AlertCircle className="h-4 w-4 text-slate-400 shrink-0 mt-0.5" />
              )}
              <div className="min-w-0">
                <h5 className="text-xs font-semibold text-slate-900">Trazabilidad SUNAT & Hash SHA-256</h5>
                <p className="text-[11px] text-slate-500 leading-tight">
                  {bloqueanCierre.length === 0 && datos.periodo
                    ? 'Libro Formato 13.1 listo para congelamiento y firma inmutable'
                    : 'Requiere subsanar advertencias para habilitar el cierre definitivo'}
                </p>
              </div>
            </div>

            {/* Enlace directo a gestión de cierres */}
            <div className="pt-2 flex items-center justify-between border-t border-slate-100 mt-2">
              <span className="text-[11px] text-slate-400">¿Listo para cerrar el período?</span>
              <Button
                size="xs"
                variant="outline"
                onClick={() => navigate('/cierres')}
                className="text-xs h-7 font-medium text-slate-700 hover:text-slate-900 hover:bg-slate-50 border-slate-200"
              >
                Ir a Cierres <ArrowRight className="h-3 w-3 ml-1" />
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
};

export default DashboardPage;
