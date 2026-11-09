import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { diferirCarga } from '../../utils/efectos';
import { useAuth } from '../../context/useAuth';
import {
  compararCierres,
  ejecutarCierre,
  obtenerCierres,
  type CierrePeriodo,
  type DiferenciaCierre,
} from '../../api/cierres';
import { obtenerPeriodos, reabrirPeriodo, type Periodo } from '../../api/periodos';
import {
  abrirReapertura,
  cancelarReapertura,
  ejecutarReapertura,
  estadoReaperturaInicial,
  etiquetaEstadoCierre,
} from '../../utils/reaperturaPeriodo';
import {
  Lock,
  Unlock,
  RotateCcw,
  ShieldCheck,
  Fingerprint,
  GitCompare,
  AlertCircle,
  CheckCircle2,
  Check,
  X,
  FileCheck2,
  Loader2,
  Copy,
} from 'lucide-react';
import { PageHeader } from '../../components/ui/page-header';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../../components/ui/card';
import { Badge } from '../../components/ui/badge';
import { Button } from '../../components/ui/button';
import { Select } from '../../components/ui/select';
import { Label } from '../../components/ui/label';
import { formatearDecimal } from '../../utils/decimal';
import { ModalConfirmarCierre } from './ModalConfirmarCierre';

const etiqueta = (p: { anio: number; mes: number }) => `${p.anio}-${String(p.mes).padStart(2, '0')}`;
// Redondeo decimal ROUND_HALF_UP (sin pasar por float); vacío se muestra como 0.
const dinero = (v: string | number | undefined) => formatearDecimal(v || 0);
const cant = (v: string | number | undefined) => formatearDecimal(v || 0, { min: 2, max: 6 });
const cpp = (v: string | number | undefined) => formatearDecimal(v || 0, { min: 4, max: 6 });

const isNonZero = (val?: string | number | null) => {
  if (val === null || val === undefined) return false;
  const s = String(val).trim();
  return s !== '' && s !== '0' && !/^0(\.0+)?$/.test(s);
};

export const CierresPage: React.FC = () => {
  const { empresaActiva, usuario } = useAuth();
  const admin = Boolean(usuario?.es_admin_global || empresaActiva?.rol === 'ADMIN');
  const [periodos, setPeriodos] = useState<Periodo[]>([]);
  const [cierres, setCierres] = useState<CierrePeriodo[]>([]);
  const [periodoId, setPeriodoId] = useState('');
  const [seleccion, setSeleccion] = useState<CierrePeriodo | null>(null);
  const [diferencias, setDiferencias] = useState<DiferenciaCierre[]>([]);
  const [ocupado, setOcupado] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mensaje, setMensaje] = useState<string | null>(null);
  const [reapertura, setReapertura] = useState(estadoReaperturaInicial);
  const [modalCierreAbierto, setModalCierreAbierto] = useState(false);
  const [copiado, setCopiado] = useState(false);

  const periodo = useMemo(() => periodos.find((p) => p.id === Number(periodoId)), [periodos, periodoId]);

  const empresaId = empresaActiva?.id;
  const cargar = useCallback(async () => {
    if (!empresaId) return;
    setOcupado(true);
    setError(null);
    try {
      const [p, c] = await Promise.all([obtenerPeriodos(), obtenerCierres()]);
      setPeriodos(p);
      setCierres(c);
      setSeleccion(c[0] || null);
    } catch {
      setError('No fue posible cargar los períodos y snapshots.');
    } finally {
      setOcupado(false);
    }
  }, [empresaId]);

  useEffect(() => {
    diferirCarga(cargar);
  }, [cargar]);

  const ejecutarCierrePeriodo = async () => {
    if (!periodo) return;
    setOcupado(true);
    setError(null);
    try {
      const r = await ejecutarCierre(periodo.id);
      setMensaje([r.mensaje, ...r.advertencias].join(' '));
      setModalCierreAbierto(false);
      await cargar();
    } catch (e: unknown) {
      setError((e as { response?: { data?: { detail?: string } } }).response?.data?.detail || 'El cierre no pudo completarse.');
      setModalCierreAbierto(false);
      setOcupado(false);
    }
  };

  const abrirModalReapertura = () => {
    if (periodo) setReapertura(abrirReapertura(periodo));
  };

  const confirmarReapertura = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setReapertura((actual) => ({ ...actual, enviando: true, error: null }));
    const resultado = await ejecutarReapertura({ ...reapertura, enviando: true, error: null }, reabrirPeriodo);
    setReapertura(resultado.estado);
    if (resultado.respuesta) {
      setMensaje(
        `${resultado.respuesta.mensaje} ${resultado.respuesta.periodos_desactualizados} período(s) posterior(es) desactualizado(s).`
      );
      await cargar();
    }
  };

  const ver = async (c: CierrePeriodo) => {
    setSeleccion(c);
    setDiferencias([]);
    try {
      setDiferencias((await compararCierres(c.periodo)).comparacion_ultimas_versiones);
    } catch {
      setError('No fue posible comparar las versiones de cierre.');
    }
  };

  const copiarHash = (hash: string) => {
    navigator.clipboard
      .writeText(hash)
      .then(() => {
        setCopiado(true);
        setTimeout(() => setCopiado(false), 2000);
      })
      .catch(() => {});
  };

  return (
    <div className="space-y-4">
      {/* 1. Encabezado principal sobrio y de alta densidad */}
      <PageHeader
        title="Cierres Contables & Snapshots de Existencias"
        description="Gestión de inmutabilidad contable, snapshots de inventario valorizado y sellado SHA-256"
        icon={Lock}
        badge={
          <div className="flex items-center gap-1.5 flex-wrap">
            <Badge variant="neutral" className="font-mono text-xs">
              Algoritmo SHA-256
            </Badge>
          </div>
        }
        actions={
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={cargar}
            disabled={ocupado}
            className="shadow-xs h-9 text-xs"
          >
            {ocupado ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" /> : <RotateCcw className="h-3.5 w-3.5 mr-1.5" />}
            Actualizar
          </Button>
        }
      />

      {/* 2. Alertas de Feedback */}
      {error && (
        <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-3.5 text-xs text-rose-800 flex items-start gap-2.5">
          <AlertCircle className="h-4 w-4 text-rose-600 shrink-0 mt-0.5" />
          <div>
            <p className="font-semibold">Error en la operación</p>
            <p className="mt-0.5">{error}</p>
          </div>
        </div>
      )}

      {mensaje && (
        <div role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 p-3.5 text-xs text-emerald-800 flex items-start gap-2.5">
          <CheckCircle2 className="h-4 w-4 text-emerald-600 shrink-0 mt-0.5" />
          <div>
            <p className="font-semibold">Operación completada con éxito</p>
            <p className="mt-0.5">{mensaje}</p>
          </div>
        </div>
      )}

      {/* 3. Panel de Operación del Período con Pre-flight Checklist */}
      <Card className="shadow-2xs border-slate-200/90 overflow-hidden">
        <CardHeader className="pb-3 border-b border-slate-100 bg-slate-50/50">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div>
              <CardTitle className="text-sm font-semibold text-slate-900 flex items-center gap-2">
                <FileCheck2 className="h-4 w-4 text-indigo-600" />
                Operación de Cierre y Reapertura de Período
              </CardTitle>
              <CardDescription className="text-xs">
                El cierre calcula saldos contables, genera snapshots y congela los movimientos mediante un hash SHA-256.
              </CardDescription>
            </div>
            {periodo && (
              <Badge
                variant={
                  periodo.estado === 'ABIERTO'
                    ? 'success'
                    : periodo.estado === 'CERRADO'
                    ? 'neutral'
                    : 'destructive'
                }
                dot
                className="font-mono text-xs"
              >
                {etiqueta(periodo)} · {periodo.estado}
              </Badge>
            )}
          </div>
        </CardHeader>
        <CardContent className="pt-4 space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-12 gap-3 items-end">
            <div className="space-y-1 md:col-span-8">
              <Label htmlFor="periodo-cierre-select" className="text-xs font-semibold text-slate-700">
                Seleccionar Período Contable
              </Label>
              <Select
                id="periodo-cierre-select"
                value={periodoId}
                onChange={(e) => setPeriodoId(e.target.value)}
                className="h-9 text-xs"
              >
                <option value="">Seleccione un período para operar...</option>
                {periodos.map((p) => (
                  <option key={p.id} value={p.id}>
                    {etiqueta(p)} — Estado: {p.estado}
                  </option>
                ))}
              </Select>
            </div>

            <div className="flex items-center gap-2 md:col-span-4">
              <Button
                type="button"
                variant="primary"
                disabled={!admin || ocupado || !periodo || periodo.estado === 'CERRADO'}
                onClick={() => setModalCierreAbierto(true)}
                className="flex-1 h-9 text-xs font-semibold bg-emerald-600 hover:bg-emerald-700 text-white shadow-xs"
                title={!admin ? 'Requiere rol de Administrador' : 'Cerrar período y generar snapshot inmutable'}
              >
                <Lock className="h-3.5 w-3.5 mr-1.5" />
                Ejecutar Cierre
              </Button>
              <Button
                type="button"
                variant="destructive"
                disabled={!admin || ocupado || !periodo || periodo.estado !== 'CERRADO'}
                onClick={abrirModalReapertura}
                className="flex-1 h-9 text-xs font-semibold shadow-xs"
                title={!admin ? 'Requiere rol de Administrador' : 'Reabrir período contable'}
              >
                <Unlock className="h-3.5 w-3.5 mr-1.5" />
                Reabrir
              </Button>
            </div>
          </div>

          {/* Pre-flight Checklist visual de pre-requisitos de cierre */}
          <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-3.5 text-xs">
            <div className="flex items-center justify-between gap-2 mb-2.5">
              <span className="font-bold text-xs uppercase tracking-wider text-slate-700 flex items-center gap-1.5">
                <ShieldCheck className="h-3.5 w-3.5 text-slate-500" />
                Checklist de Reglas de Control para Cierre Oficial
              </span>
              <span className="text-[11px] text-slate-400">Verificación técnica de inmutabilidad</span>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2.5">
              {/* Item 1: Período Seleccionado */}
              <div className={`p-2.5 rounded-lg border flex items-center gap-2.5 ${
                periodo ? 'bg-white border-slate-200 shadow-2xs' : 'bg-slate-50/70 border-dashed border-slate-300'
              }`}>
                {periodo ? (
                  <Check className="h-4 w-4 text-emerald-600 shrink-0" />
                ) : (
                  <X className="h-4 w-4 text-slate-300 shrink-0" />
                )}
                <div className="min-w-0">
                  <span className="font-semibold text-slate-800 block truncate">Período seleccionado</span>
                  <span className="text-[11px] text-slate-500 block truncate font-mono">
                    {periodo ? etiqueta(periodo) : 'Pendiente de selección'}
                  </span>
                </div>
              </div>

              {/* Item 2: Estado ABIERTO */}
              <div className={`p-2.5 rounded-lg border flex items-center gap-2.5 ${
                periodo?.estado === 'ABIERTO' ? 'bg-white border-slate-200 shadow-2xs' : 'bg-slate-50/70 border-dashed border-slate-300'
              }`}>
                {periodo?.estado === 'ABIERTO' ? (
                  <Check className="h-4 w-4 text-emerald-600 shrink-0" />
                ) : periodo?.estado === 'CERRADO' ? (
                  <Lock className="h-4 w-4 text-slate-400 shrink-0" />
                ) : (
                  <X className="h-4 w-4 text-slate-300 shrink-0" />
                )}
                <div className="min-w-0">
                  <span className="font-semibold text-slate-800 block truncate">Estado vigente ABIERTO</span>
                  <span className="text-[11px] text-slate-500 block truncate">
                    {periodo ? `Estado: ${periodo.estado}` : 'Sin período'}
                  </span>
                </div>
              </div>

              {/* Item 3: Rol ADMIN Contable */}
              <div className={`p-2.5 rounded-lg border flex items-center gap-2.5 ${
                admin ? 'bg-white border-slate-200 shadow-2xs' : 'bg-rose-50/60 border-rose-200'
              }`}>
                {admin ? (
                  <Check className="h-4 w-4 text-emerald-600 shrink-0" />
                ) : (
                  <X className="h-4 w-4 text-rose-500 shrink-0" />
                )}
                <div className="min-w-0">
                  <span className="font-semibold text-slate-800 block truncate">
                    Rol ADMIN Contable ({admin ? 'Autorizado' : 'Requerido'})
                  </span>
                  <span className={`text-[11px] block truncate ${admin ? 'text-emerald-700' : 'text-rose-600'}`}>
                    {admin ? 'Permisos completos' : 'Requiere privilegios'}
                  </span>
                </div>
              </div>

              {/* Item 4: Snapshots SHA-256 Inmutables */}
              <div className="p-2.5 rounded-lg border bg-white border-slate-200 shadow-2xs flex items-center gap-2.5">
                <Check className="h-4 w-4 text-emerald-600 shrink-0" />
                <div className="min-w-0">
                  <span className="font-semibold text-slate-800 block truncate">Snapshots SHA-256 Inmutables</span>
                  <span className="text-[11px] text-slate-500 block truncate font-mono">Firma criptográfica</span>
                </div>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* 4. Historial de Snapshots */}
      <Card className="shadow-2xs border-slate-200/90 overflow-hidden">
        <CardHeader className="py-3 px-4 border-b border-slate-200 bg-slate-50/60 flex flex-row items-center justify-between">
          <div>
            <CardTitle className="text-sm font-semibold text-slate-900 flex items-center gap-2">
              <Fingerprint className="h-4 w-4 text-indigo-600" />
              Historial de Snapshots de Cierre
            </CardTitle>
            <CardDescription className="text-xs">
              Haga clic sobre un snapshot para inspeccionar el desglose de saldos o compararlo con su versión previa
            </CardDescription>
          </div>
          <Badge variant="neutral" className="text-xs font-mono">
            {cierres.length} snapshot(s)
          </Badge>
        </CardHeader>
        <CardContent className="p-0">
          {!cierres.length ? (
            <div className="py-12 text-center text-xs text-slate-500">
              {ocupado ? 'Cargando snapshots de cierre...' : 'Aún no existen cierres registrados para esta empresa.'}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs text-left border-collapse">
                <thead>
                  <tr className="bg-slate-100 text-[11px] font-semibold uppercase tracking-wider text-slate-600 border-b border-slate-200">
                    <th className="py-2.5 px-3">Período</th>
                    <th className="py-2.5 px-3 text-center">Versión</th>
                    <th className="py-2.5 px-3 text-center">Estado</th>
                    <th className="py-2.5 px-3">Fecha y Hora</th>
                    <th className="py-2.5 px-3">Usuario Cierre</th>
                    <th className="py-2.5 px-3 text-right">Valor Total Inventario</th>
                    <th className="py-2.5 px-3">Hash SHA-256 Inmutable</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 font-mono tabular-nums text-xs">
                  {cierres.map((c) => {
                    const isSelected = seleccion?.id === c.id;
                    const esVigente = etiquetaEstadoCierre(c.vigente, c.periodo_info.estado) === 'Vigente';
                    return (
                      <tr
                        key={c.id}
                        onClick={() => void ver(c)}
                        className={`cursor-pointer transition-colors ${
                          isSelected ? 'bg-indigo-50/70 border-l-2 border-indigo-600 font-medium' : 'hover:bg-slate-50'
                        }`}
                      >
                        <td className="py-2.5 px-3 font-mono font-bold text-slate-900">
                          {etiqueta(c.periodo_info)}
                        </td>
                        <td className="py-2.5 px-3 text-center">
                          <Badge variant="info" size="xs" className="font-mono">
                            v{c.version_calculo}
                          </Badge>
                        </td>
                        <td className="py-2.5 px-3 text-center font-sans">
                          <Badge
                            variant={esVigente ? 'success' : 'neutral'}
                            size="xs"
                            dot={esVigente}
                          >
                            {etiquetaEstadoCierre(c.vigente, c.periodo_info.estado)}
                          </Badge>
                        </td>
                        <td className="py-2.5 px-3 text-slate-600">
                          {new Date(c.cerrado_en).toLocaleString('es-PE')}
                        </td>
                        <td className="py-2.5 px-3 text-slate-700 font-sans">
                          {c.cerrado_por_username}
                        </td>
                        <td className="py-2.5 px-3 text-right font-bold text-slate-950">
                          S/ {dinero(c.snapshot_resumen.valor_total_inventario_pen)}
                        </td>
                        <td className="py-2.5 px-3">
                          <div className="flex items-center gap-1.5 text-[11px] text-slate-600" title={c.hash_resultado}>
                            <Fingerprint className="h-3.5 w-3.5 text-indigo-500 shrink-0" />
                            <code className="bg-slate-100 px-1.5 py-0.5 rounded border border-slate-200 font-mono text-slate-700">
                              {c.hash_resultado.slice(0, 16)}…
                            </code>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* 5. Detalle de Snapshot Seleccionado y Comparador */}
      {seleccion && (
        <Card className="shadow-2xs border-slate-200/90 overflow-hidden">
          <CardHeader className="py-3 px-4 border-b border-slate-200 bg-slate-50/60">
            <div className="flex items-center justify-between flex-wrap gap-2">
              <div className="flex items-center gap-2">
                <ShieldCheck className="h-4 w-4 text-indigo-600 shrink-0" />
                <CardTitle className="text-sm font-semibold text-slate-900">
                  Detalle de Cierre {etiqueta(seleccion.periodo_info)} · Versión v{seleccion.version_calculo}
                </CardTitle>
                <span className="text-slate-300">·</span>
                <span className="text-xs text-slate-500">
                  {seleccion.detalles.length} existencia(s) registradas
                </span>
              </div>

              <Badge
                variant={etiquetaEstadoCierre(seleccion.vigente, seleccion.periodo_info.estado) === 'Vigente' ? 'success' : 'neutral'}
                size="xs"
                dot={etiquetaEstadoCierre(seleccion.vigente, seleccion.periodo_info.estado) === 'Vigente'}
              >
                {etiquetaEstadoCierre(seleccion.vigente, seleccion.periodo_info.estado)}
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="p-0 space-y-0">
            {/* Caja Técnica del Sello Criptográfico SHA-256 */}
            <div className="p-3.5 bg-slate-50/70 border-b border-slate-200">
              <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-2xs">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-1.5">
                  <div className="flex items-center gap-1.5">
                    <Lock className="h-3.5 w-3.5 text-indigo-600 shrink-0" />
                    <span className="text-xs font-bold uppercase tracking-wider text-slate-700">
                      Hash SHA-256 Completo:
                    </span>
                    <span className="text-slate-300">·</span>
                    <span className="font-mono text-[11px] text-slate-400">Sello Digital Inmutable</span>
                  </div>

                  <Button
                    type="button"
                    variant="outline"
                    size="xs"
                    onClick={() => copiarHash(seleccion.hash_resultado)}
                    className="h-6 text-[11px] font-mono gap-1 text-slate-600 hover:text-slate-900"
                    title="Copiar hash SHA-256 al portapapeles"
                  >
                    {copiado ? <Check className="h-3 w-3 text-emerald-600" /> : <Copy className="h-3 w-3" />}
                    {copiado ? '¡Copiado!' : 'Copiar Hash'}
                  </Button>
                </div>

                <code className="block min-w-0 break-all font-mono text-xs bg-slate-50 px-2.5 py-1.5 rounded border border-slate-200 text-slate-800 select-all tracking-wider">
                  {seleccion.hash_resultado}
                </code>
              </div>
            </div>

            {/* Tabla de saldos por establecimiento y producto */}
            <div className="overflow-x-auto">
              <table className="w-full text-xs text-left border-collapse">
                <thead>
                  <tr className="bg-slate-100 text-[11px] font-semibold uppercase tracking-wider text-slate-600 border-b border-slate-200">
                    <th className="py-2.5 px-3">Producto</th>
                    <th className="py-2.5 px-3">Establecimiento</th>
                    <th className="py-2.5 px-3 text-right">Cantidad Final</th>
                    <th className="py-2.5 px-3 text-right">CPP Vigente</th>
                    <th className="py-2.5 px-3 text-right">Valor Total PEN</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 font-mono tabular-nums text-xs">
                  {seleccion.detalles.map((d) => (
                    <tr key={d.id} className="hover:bg-slate-50 transition-colors">
                      <td className="py-2 px-3 font-sans">
                        <span className="font-mono font-bold bg-slate-100 text-slate-800 px-1.5 py-0.5 rounded border border-slate-200 mr-1.5">
                          {d.producto_codigo}
                        </span>
                        <span className="text-slate-700 font-medium">{d.producto_descripcion}</span>
                      </td>
                      <td className="py-2 px-3 text-slate-600 font-sans">{d.establecimiento_nombre}</td>
                      <td className="py-2 px-3 text-right text-slate-800 font-medium">
                        {cant(d.saldo_cantidad)}
                      </td>
                      <td className="py-2 px-3 text-right text-slate-700">
                        {cpp(d.cpp_pen)}
                      </td>
                      <td className="py-2 px-3 text-right font-bold text-slate-950">
                        S/ {dinero(d.saldo_valor_pen)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Comparador de versiones de cierre */}
            {diferencias.length > 0 && (
              <div className="border-t border-slate-200 p-4 bg-slate-50/40">
                <div className="flex items-center gap-2 mb-3">
                  <GitCompare className="h-4 w-4 text-indigo-600 shrink-0" />
                  <div>
                    <h3 className="text-xs font-bold text-slate-900 uppercase tracking-wider">
                      Comparador de Diferencias Entre las Dos Últimas Versiones de Cierre
                    </h3>
                    <p className="text-[11px] text-slate-500">
                      Variaciones exactas de stock físico, costo promedio y valor total tras la reapertura del período
                    </p>
                  </div>
                </div>
                <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white shadow-2xs">
                  <table className="w-full text-xs text-left border-collapse">
                    <thead>
                      <tr className="bg-slate-100 text-[10px] font-semibold uppercase tracking-wider text-slate-600 border-b border-slate-200">
                        <th className="py-2 px-3">Producto / Código</th>
                        <th className="py-2 px-3">Establecimiento</th>
                        <th className="py-2 px-2.5 text-right">Cant. Ant.</th>
                        <th className="py-2 px-2.5 text-right">Cant. Nueva</th>
                        <th className="py-2 px-2.5 text-right font-bold bg-slate-50 border-r border-slate-200">Δ Cantidad</th>
                        <th className="py-2 px-2.5 text-right">CPP Ant.</th>
                        <th className="py-2 px-2.5 text-right">CPP Nuevo</th>
                        <th className="py-2 px-2.5 text-right font-bold bg-slate-50 border-r border-slate-200">Δ CPP</th>
                        <th className="py-2 px-2.5 text-right">Valor Ant.</th>
                        <th className="py-2 px-2.5 text-right">Valor Nuevo</th>
                        <th className="py-2 px-2.5 text-right font-bold bg-slate-50">Δ Valor PEN</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 font-mono tabular-nums text-xs">
                      {diferencias.map((d) => {
                        const det = seleccion.detalles.find(
                          (x) => x.producto === d.producto_id && x.establecimiento === d.establecimiento_id
                        );
                        const hasCantDiff = isNonZero(d.diferencia.cantidad);
                        const hasCppDiff = isNonZero(d.diferencia.cpp_pen);
                        const hasValorDiff = isNonZero(d.diferencia.valor_pen);

                        return (
                          <tr key={`${d.producto_id}-${d.establecimiento_id}`} className="hover:bg-slate-50 transition-colors">
                            <td className="py-2 px-3 font-sans font-medium text-slate-800">
                              {det ? (
                                <div className="flex items-center gap-1.5">
                                  <span className="font-mono font-bold bg-slate-100 px-1 py-0.2 rounded border border-slate-200 text-slate-700">
                                    {det.producto_codigo}
                                  </span>
                                  <span className="truncate max-w-[140px]" title={det.producto_descripcion}>
                                    {det.producto_descripcion}
                                  </span>
                                </div>
                              ) : (
                                `ID ${d.producto_id}`
                              )}
                            </td>
                            <td className="py-2 px-3 font-sans text-slate-600">
                              {det ? det.establecimiento_nombre : `Estab ${d.establecimiento_id}`}
                            </td>
                            <td className="py-2 px-2.5 text-right text-slate-500">{cant(d.version_anterior.saldo_cantidad)}</td>
                            <td className="py-2 px-2.5 text-right text-slate-800 font-medium">{cant(d.version_nueva.saldo_cantidad)}</td>
                            <td className={`py-2 px-2.5 text-right font-bold border-r border-slate-200 ${
                              hasCantDiff ? 'text-amber-700 bg-amber-50/60' : 'text-slate-400'
                            }`}>
                              {cant(d.diferencia.cantidad)}
                            </td>
                            <td className="py-2 px-2.5 text-right text-slate-500">{cpp(d.version_anterior.cpp_pen)}</td>
                            <td className="py-2 px-2.5 text-right text-slate-800 font-medium">{cpp(d.version_nueva.cpp_pen)}</td>
                            <td className={`py-2 px-2.5 text-right font-bold border-r border-slate-200 ${
                              hasCppDiff ? 'text-indigo-700 bg-indigo-50/60' : 'text-slate-400'
                            }`}>
                              {cpp(d.diferencia.cpp_pen)}
                            </td>
                            <td className="py-2 px-2.5 text-right text-slate-500">S/ {dinero(d.version_anterior.saldo_valor_pen)}</td>
                            <td className="py-2 px-2.5 text-right text-slate-800 font-medium">S/ {dinero(d.version_nueva.saldo_valor_pen)}</td>
                            <td className={`py-2 px-2.5 text-right font-bold ${
                              hasValorDiff ? 'text-emerald-800 bg-emerald-50/60' : 'text-slate-400'
                            }`}>
                              S/ {dinero(d.diferencia.valor_pen)}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Modal de Confirmación de Cierre Oficial */}
      <ModalConfirmarCierre
        abierto={modalCierreAbierto}
        periodo={periodo || null}
        enviando={ocupado}
        onConfirmar={ejecutarCierrePeriodo}
        onCancelar={() => setModalCierreAbierto(false)}
      />

      {/* 6. Modal de Reapertura de Período */}
      {reapertura.abierto && reapertura.periodo && (
        <div
          role="presentation"
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs animate-in fade-in duration-150"
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="reapertura-title"
            className="w-full max-w-lg rounded-xl border border-slate-200 bg-white p-6 shadow-xl animate-in zoom-in-95 duration-150"
          >
            <div className="flex items-start justify-between pb-4 border-b border-slate-100">
              <div className="flex items-center gap-2.5">
                <div className="p-2 rounded-lg bg-rose-50 text-rose-700">
                  <Unlock className="h-5 w-5" />
                </div>
                <div>
                  <h2 id="reapertura-title" className="text-base font-semibold text-slate-900">
                    Reabrir Período {etiqueta(reapertura.periodo)}
                  </h2>
                  <p className="text-xs text-slate-500">
                    El snapshot actual v{seleccion?.version_calculo || 1} permanecerá inmutable en el historial contable.
                  </p>
                </div>
              </div>
              <button
                type="button"
                aria-label="Cerrar modal"
                disabled={reapertura.enviando}
                onClick={() => setReapertura(cancelarReapertura())}
                className="text-slate-400 hover:text-slate-600 p-1"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <form noValidate onSubmit={confirmarReapertura} className="mt-4 space-y-4">
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800 flex items-start gap-2">
                <AlertCircle className="h-4 w-4 text-amber-600 shrink-0 mt-0.5" />
                <p>
                  <strong>Advertencia Contable:</strong> La reapertura de este período marcará como <em>DESACTUALIZADOS</em> todos los períodos posteriores, requiriendo un recálculo cronológico de CPP.
                </p>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="motivo-reapertura">
                  Motivo de Reapertura <span className="text-rose-500">*</span>
                </Label>
                <textarea
                  id="motivo-reapertura"
                  autoFocus
                  maxLength={500}
                  rows={4}
                  value={reapertura.motivo}
                  onChange={(e) =>
                    setReapertura((actual) => ({ ...actual, motivo: e.target.value, error: null }))
                  }
                  placeholder="Explique la justificación o corrección contable que requiere reabrir este período..."
                  className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-xs text-slate-900 placeholder:text-slate-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900 resize-y"
                />
                <span className="text-[11px] text-slate-400 text-right block">
                  {reapertura.motivo.length} / 500 caracteres
                </span>
              </div>

              {reapertura.error && (
                <div role="alert" className="rounded-md border border-rose-200 bg-rose-50 p-2.5 text-xs text-rose-700">
                  {reapertura.error}
                </div>
              )}

              <div className="flex items-center justify-end gap-2 pt-3 border-t border-slate-100">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={reapertura.enviando}
                  onClick={() => setReapertura(cancelarReapertura())}
                >
                  Cancelar
                </Button>
                <Button
                  type="submit"
                  variant="destructive"
                  size="sm"
                  disabled={reapertura.enviando}
                >
                  {reapertura.enviando ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" />
                  ) : (
                    <Unlock className="h-3.5 w-3.5 mr-1.5" />
                  )}
                  {reapertura.enviando ? 'Reabriendo período...' : 'Confirmar Reapertura'}
                </Button>
              </div>
            </form>
          </section>
        </div>
      )}
    </div>
  );
};

export default CierresPage;
