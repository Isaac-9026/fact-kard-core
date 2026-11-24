import React, { useCallback, useEffect, useState } from 'react';
import { Download, Loader2, Scale, X } from 'lucide-react';
import {
  descargarDiferenciasLote, obtenerDiferenciasLote, type DiferenciasLote as Datos, type FiltrosDiferencias,
  type NivelDiferencia,
} from '../../api/importacion';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { Badge } from '../../components/ui/badge';
import { descargarBlob, mensajeErrorExportacion } from '../../utils/descargaArchivo';
import { diferirCarga } from '../../utils/efectos';
import { mensajesDeErrorApi } from '../../utils/errores';
import {
  ETIQUETA_NIVEL, VARIANTE_NIVEL, fechaCorta, montoConSigno, nombreArchivoDiferencias, signoMonto,
} from '../../utils/importacionExcel';

const NIVELES: { valor: NivelDiferencia | null; etiqueta: string; clase: string }[] = [
  { valor: null, etiqueta: 'Todas', clase: '' },
  { valor: 'VERDE', etiqueta: 'Verde · OK', clase: 'text-emerald-700' },
  { valor: 'AMBAR', etiqueta: 'Ámbar · Error A', clase: 'text-amber-700' },
  { valor: 'ROJO', etiqueta: 'Rojo · Error B', clase: 'text-rose-700' },
];

const colorMonto = (valor: string | null) => {
  const s = signoMonto(valor);
  if (s === 0) return 'text-slate-500';
  return s === 1 ? 'text-amber-700' : 'text-sky-700';
};

const Dato: React.FC<{ etiqueta: string; valor: React.ReactNode; clase?: string }> = ({ etiqueta, valor, clase = '' }) => (
  <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
    <p className="text-[10px] font-medium uppercase tracking-wide text-slate-500">{etiqueta}</p>
    <p className={`mt-0.5 text-sm font-semibold tabular-nums ${clase}`}>{valor}</p>
  </div>
);

export const DiferenciasLote: React.FC<{ loteId: number; onCerrar: () => void }> = ({ loteId, onCerrar }) => {
  const [filtros, setFiltros] = useState<FiltrosDiferencias>({});
  const [datos, setDatos] = useState<Datos | null>(null);
  const [cargando, setCargando] = useState(true);
  const [exportando, setExportando] = useState(false);
  const [errores, setErrores] = useState<string[]>([]);

  const cargar = useCallback(async () => {
    setCargando(true);
    setErrores([]);
    try {
      setDatos(await obtenerDiferenciasLote(loteId, filtros));
    } catch (err) {
      setDatos(null);
      setErrores(mensajesDeErrorApi(err, 'No se pudo calcular el cuadro de diferencias.'));
    } finally {
      setCargando(false);
    }
  }, [loteId, filtros]);

  useEffect(() => { diferirCarga(cargar); }, [cargar]);

  const exportar = async () => {
    if (exportando) return;
    setExportando(true);
    try {
      const codigo = datos?.productos.find((p) => p.id === filtros.producto)?.codigo;
      descargarBlob(await descargarDiferenciasLote(loteId, filtros), nombreArchivoDiferencias(loteId, filtros, codigo));
    } catch (err) {
      setErrores([await mensajeErrorExportacion(err, 'No se pudo exportar el cuadro de diferencias.')]);
    } finally {
      setExportando(false);
    }
  };

  const r = datos?.resumen;

  return (
    <Card data-testid="diferencias-lote">
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle className="flex items-center gap-2 text-base">
            <Scale className="h-4 w-4 text-indigo-600" /> Diferencias de costo · Lote #{loteId}
          </CardTitle>
          <CardDescription>
            Costo unitario del Excel contra el costo que calculó el Kardex.
            {datos && ` Verde: hasta S/ ${datos.umbrales.tolerancia}. Ámbar: hasta ${datos.umbrales.ambar_pct} %. Rojo: más de ${datos.umbrales.ambar_pct} % o sin costo en el Excel.`}
          </CardDescription>
        </div>
        <div className="flex shrink-0 gap-2">
          <Button size="sm" variant="outline" onClick={exportar} disabled={exportando || cargando || !datos}>
            {exportando ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <Download className="mr-1.5 h-4 w-4" />}
            Exportar Excel
          </Button>
          <Button size="sm" variant="ghost" onClick={onCerrar} aria-label="Cerrar diferencias"><X className="h-4 w-4" /></Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filtrar por nivel">
            {NIVELES.map((n) => {
              const activo = (filtros.nivel ?? null) === n.valor;
              const cuenta = n.valor === null ? null : r?.[n.valor.toLowerCase() as 'verde' | 'ambar' | 'rojo'];
              return (
                <button
                  key={n.etiqueta} type="button" onClick={() => setFiltros((f) => ({ ...f, nivel: n.valor }))}
                  className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                    activo ? 'border-indigo-600 bg-indigo-600 text-white' : `border-slate-200 bg-white hover:bg-slate-50 ${n.clase}`}`}
                >
                  {n.etiqueta}{cuenta !== null && cuenta !== undefined && !filtros.nivel ? ` ${cuenta}` : ''}
                </button>
              );
            })}
          </div>
          <select
            className="ml-auto h-8 rounded-md border border-slate-200 bg-white px-2 text-xs" aria-label="Filtrar por producto"
            value={filtros.producto ?? ''} onChange={(e) => setFiltros((f) => ({ ...f, producto: e.target.value ? Number(e.target.value) : null }))}
          >
            <option value="">Todos los productos</option>
            {datos?.productos.map((p) => <option key={p.id} value={p.id}>{p.codigo} · {p.descripcion}</option>)}
          </select>
        </div>

        {errores.length > 0 && (
          <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs font-medium text-rose-700">
            {errores.map((e) => <p key={e}>{e}</p>)}
          </div>
        )}

        {r && (
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-7">
            <Dato etiqueta="Líneas" valor={r.lineas} />
            <Dato etiqueta="Verde · OK" valor={r.verde} clase="text-emerald-700" />
            <Dato etiqueta="Ámbar · Error A" valor={r.ambar} clase="text-amber-700" />
            <Dato etiqueta="Rojo · Error B" valor={r.rojo} clase="text-rose-700" />
            <Dato etiqueta="Valor Excel" valor={`S/ ${r.valor_excel}`} />
            <Dato etiqueta="Valor Kardex" valor={`S/ ${r.valor_sistema}`} />
            <Dato
              etiqueta="Diferencia neta" clase={colorMonto(r.diferencia_neta)}
              valor={<>S/ {montoConSigno(r.diferencia_neta)} <span className="text-[10px] font-normal text-slate-500">(abs. {r.diferencia_absoluta})</span></>}
            />
          </div>
        )}

        <div className="max-h-[32rem] overflow-auto rounded-lg border border-slate-200">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-3 py-2 text-left">Fecha</th>
                <th className="px-3 py-2 text-left">Comprobante</th>
                <th className="px-3 py-2 text-left">Producto</th>
                <th className="px-3 py-2 text-right">Cant.</th>
                <th className="px-3 py-2 text-right">C. unit. Excel</th>
                <th className="px-3 py-2 text-right">C. unit. Kardex</th>
                <th className="px-3 py-2 text-right">Dif. %</th>
                <th className="px-3 py-2 text-right">Dif. total S/</th>
                <th className="px-3 py-2 text-left">Nivel</th>
              </tr>
            </thead>
            <tbody>
              {datos?.lineas.map((l) => (
                <tr key={l.detalle_id} className="border-t border-slate-100 align-top">
                  <td className="whitespace-nowrap px-3 py-2">{fechaCorta(l.fecha)}</td>
                  <td className="px-3 py-2">
                    <span className="font-mono font-semibold">{l.comprobante}</span>
                    <span className="block text-[10px] text-slate-400">{l.operacion}</span>
                  </td>
                  <td className="px-3 py-2">
                    <span className="font-medium">{l.producto_codigo}</span>
                    <span className="block max-w-56 truncate text-[10px] text-slate-500" title={l.producto}>{l.producto}</span>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{l.cantidad}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{l.costo_unitario_excel ?? '—'}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{l.costo_unitario_sistema ?? '—'}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{l.porcentaje !== null ? `${l.porcentaje} %` : '—'}</td>
                  <td className={`px-3 py-2 text-right font-medium tabular-nums ${colorMonto(l.diferencia_total)}`}>{montoConSigno(l.diferencia_total)}</td>
                  <td className="px-3 py-2">
                    <Badge variant={VARIANTE_NIVEL[l.nivel]} size="xs">{ETIQUETA_NIVEL[l.nivel]}</Badge>
                    {l.motivo && <span className="mt-1 block text-[10px] text-slate-500">{l.motivo}</span>}
                  </td>
                </tr>
              ))}
              {!datos?.lineas.length && (
                <tr>
                  <td colSpan={9} className="px-3 py-8 text-center text-slate-400">
                    {cargando ? 'Calculando diferencias…' : 'No hay líneas con este filtro.'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
};
