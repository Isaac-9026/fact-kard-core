import React, { Suspense, lazy, useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Receipt,
  AlertTriangle,
  Lock,
  BookOpenCheck,
  CheckCircle2,
  ArrowRight,
  ScanText,
  AlertCircle,
  FileCheck2,
} from 'lucide-react';
import { useAuth } from '../../context/useAuth';
import { obtenerPeriodos } from '../../api/periodos';
import { obtenerKardexValorizado } from '../../api/reportes';
import { obtenerIncidencias, type Incidencia } from '../../api/kardex';
import { obtenerCierres } from '../../api/cierres';
import { diferirCarga } from '../../utils/efectos';
import { leerPeriodoGuardado } from '../../utils/kardexVista';
import {
  SIN_DATO,
  contarPendientes,
  etiquetaPeriodo,
  pasosCierre,
  periodoActivo,
  resumenUltimoCierre,
  type PeriodoDashboard,
  type ResumenCierre,
} from '../../utils/dashboard';
import { BannerBienvenida } from '../../components/dashboard/BannerBienvenida';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../../components/ui/card';
import { Button } from '../../components/ui/button';

const GraficosDashboard = lazy(() => import('../../components/dashboard/GraficosDashboard'));

interface DatosDashboard {
  periodo: PeriodoDashboard | null;
  valorTotal: string | null;
  incidenciasPendientes: number | null;
  incidenciasLista: Incidencia[];
  ultimoCierre: ResumenCierre | null;
  sinCierres: boolean;
}

const VACIO: DatosDashboard = {
  periodo: null,
  valorTotal: null,
  incidenciasPendientes: null,
  incidenciasLista: [],
  ultimoCierre: null,
  sinCierres: false,
};

/**
 * Dashboard:
 * Bienvenida, alertas que bloquean el cierre, indicadores del mes y avance del cierre.
 */
export const DashboardPage: React.FC = () => {
  const { empresaActiva, usuario } = useAuth();
  const navigate = useNavigate();
  const [datos, setDatos] = useState<DatosDashboard>(VACIO);
  const [cargando, setCargando] = useState(true);
  const [errores, setErrores] = useState<string[]>([]);
  const [recarga, setRecarga] = useState(0);

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

    setDatos({
      periodo,
      valorTotal: kardex?.resumen?.saldo_final_valor ?? null,
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

  const pasos = pasosCierre({
    empresa: empresaActiva?.razon_social ?? null,
    periodo: datos.periodo,
    valorTotal: datos.valorTotal,
    pendientes: datos.incidenciasPendientes,
    bloqueantes: bloqueanCierre.length,
  });
  const listos = pasos.filter((p) => p.listo).length;
  const accesos: { texto: string; ruta: string; icono: React.ReactNode }[] = [
    { texto: 'Comprobantes', ruta: '/comprobantes', icono: <Receipt className="h-3.5 w-3.5" /> },
    { texto: 'Captura XML/OCR', ruta: '/captura-homologacion', icono: <ScanText className="h-3.5 w-3.5" /> },
    { texto: 'Kardex', ruta: '/kardex', icono: <BookOpenCheck className="h-3.5 w-3.5" /> },
    { texto: `Incidencias (${datos.incidenciasPendientes ?? 0})`, ruta: '/incidencias', icono: <AlertTriangle className="h-3.5 w-3.5" /> },
    { texto: 'Cierres', ruta: '/cierres', icono: <Lock className="h-3.5 w-3.5" /> },
    { texto: 'Formato 13.1', ruta: '/formato-13-1', icono: <FileCheck2 className="h-3.5 w-3.5" /> },
  ];

  return (
    <div className="space-y-4">
      <BannerBienvenida
        usuario={usuario?.username ?? null}
        empresa={empresaActiva ?? null}
        periodo={datos.periodo ? etiqueta : null}
        estadoPeriodo={datos.periodo?.estado ?? null}
        ultimoCierre={datos.ultimoCierre?.titulo ?? (datos.sinCierres ? 'Sin cierres previos' : null)}
        cargando={cargando}
        onNuevaCompra={() => navigate('/comprobantes?clase=COMPRA&nuevo=1')}
        onNuevaVenta={() => navigate('/comprobantes?clase=VENTA&nuevo=1')}
        onVerOperaciones={() => navigate('/comprobantes')}
        onActualizar={() => { setRecarga((n) => n + 1); void cargar(); }}
      />

      {!cargando && bloqueanCierre.length > 0 && (
        <div role="alert" className="flex flex-col gap-2 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 items-start gap-2.5">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-rose-600" />
            <div className="min-w-0 text-xs">
              <p className="font-semibold text-rose-900">
                {bloqueanCierre.length === 1 ? '1 incidencia bloquea' : `${bloqueanCierre.length} incidencias bloquean`} el cierre de {etiqueta}
              </p>
              <p className="truncate text-rose-700">
                {bloqueanCierre[0].tipo} · {bloqueanCierre[0].descripcion}
                {bloqueanCierre.length > 1 && ` y ${bloqueanCierre.length - 1} más`}
              </p>
            </div>
          </div>
          <Button size="xs" variant="destructive" onClick={() => navigate('/incidencias')} data-acceso="/incidencias"
            className="h-8 shrink-0 text-xs font-semibold">
            Resolver <ArrowRight className="ml-1 h-3 w-3" />
          </Button>
        </div>
      )}

      {errores.length > 0 && !cargando && (
        <div role="status" className="rounded-lg border border-amber-200 bg-amber-50/90 p-3 text-xs text-amber-800">
          No se pudo consultar: {errores.join(', ')}. Esos datos se muestran como “{SIN_DATO}”.
        </div>
      )}

      {empresaId && !(cargando && datos === VACIO) && (
        <Suspense fallback={<div className="h-72 animate-pulse rounded-lg border border-slate-200 bg-slate-50" />}>
          <GraficosDashboard periodoId={datos.periodo?.id ?? null} empresaId={empresaId} recarga={recarga} />
        </Suspense>
      )}

      <Card className="overflow-hidden border-slate-200/90 shadow-2xs" data-testid="dashboard-cierre">
        <CardHeader className="flex flex-col gap-3 space-y-0 border-b border-slate-100 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <CardTitle className="flex items-center gap-2 text-sm font-semibold text-slate-900">
              <FileCheck2 className="h-4 w-4 text-blue-600" /> Cierre del mes {datos.periodo ? etiqueta : ''}
            </CardTitle>
            <CardDescription className="mt-0.5 text-xs">
              Registro → Kardex → Incidencias → Cierre y Formato 13.1
            </CardDescription>
          </div>
          <div className="flex items-center gap-3">
            <div className="w-40">
              <div className="h-2 overflow-hidden rounded-full bg-slate-100">
                <div className={`h-full rounded-full transition-all ${listos === pasos.length ? 'bg-emerald-500' : 'bg-blue-600'}`}
                  style={{ width: `${(listos / pasos.length) * 100}%` }} />
              </div>
              <p className="mt-1 text-[11px] text-slate-500">{v(`${listos} de ${pasos.length} listos`)}</p>
            </div>
            <Button size="xs" variant="primary" onClick={() => navigate('/cierres')} data-acceso="/cierres"
              className="h-8 bg-blue-600 text-xs font-semibold hover:bg-blue-500 active:bg-blue-700">
              Ir a Cierres <ArrowRight className="ml-1 h-3 w-3" />
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-4 p-4">
          <ol className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {pasos.map((paso, i) => {
              const bloquea = paso.clave === 'incidencias' && bloqueanCierre.length > 0;
              return (
                <li key={paso.clave} className={`flex items-start gap-2.5 rounded-lg border p-3 ${
                  bloquea ? 'border-rose-200 bg-rose-50/60' : paso.listo ? 'border-emerald-200 bg-emerald-50/40' : 'border-slate-200 bg-white'}`}>
                  {paso.listo ? (
                    <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
                  ) : bloquea ? (
                    <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-rose-600" />
                  ) : (
                    <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-slate-300 text-[9px] font-bold text-slate-500">{i + 1}</span>
                  )}
                  <div className="min-w-0">
                    <p className="text-xs font-semibold text-slate-900">{paso.titulo}</p>
                    <p className={`truncate text-[11px] ${bloquea ? 'text-rose-700' : 'text-slate-500'}`}>{cargando ? '...' : paso.detalle}</p>
                  </div>
                </li>
              );
            })}
          </ol>
          <div className="flex flex-wrap gap-2 border-t border-slate-100 pt-3">
            {accesos.map((a) => (
              <Button key={a.ruta} size="xs" variant="outline" onClick={() => navigate(a.ruta)} data-acceso={a.ruta}
                className="h-8 gap-1.5 text-xs font-medium">
                {a.icono} {a.texto}
              </Button>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export default DashboardPage;
