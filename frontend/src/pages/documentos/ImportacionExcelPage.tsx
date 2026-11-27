import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertCircle, ArrowLeft, CheckCircle2, ChevronLeft, ChevronRight, Download, FileSpreadsheet, History, Loader2, Lock, Scale, Upload, XCircle,
} from 'lucide-react';
import { useAuth } from '../../context/useAuth';
import { getAlmacenes, getTerceros, type Almacen, type Tercero } from '../../api/inventario';
import {
  anularLoteImportacion, confirmarImportacion, descargarErroresPrevisualizacion, descargarPlantillaEntradasSalidas,
  listarLotesImportacion, listarTrabajosImportacion, obtenerComprobantesPrevisualizacion, obtenerTrabajoImportacion,
  previsualizarImportacion, type ComprobanteImportado, type LoteImportacion, type PrevisualizacionImportacion,
  type PrevisualizacionPaginacion, type ResultadoImportacion, type TrabajoImportacion,
} from '../../api/importacion';
import { PageHeader } from '../../components/ui/page-header';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card';
import { Button } from '../../components/ui/button';
import { Badge } from '../../components/ui/badge';
import { Modal } from '../../components/ui/modal';
import { Tabs, TabsList, TabsTrigger } from '../../components/ui/tabs';
import { DiferenciasLote } from './DiferenciasLote';
import { descargarBlob } from '../../utils/descargaArchivo';
import { diferirCarga } from '../../utils/efectos';
import { mensajesDeErrorApi } from '../../utils/errores';
import {
  ETIQUETA_ESTADO, ETIQUETA_OPERACION, ETIQUETA_TIPO, FILTRO_A_SERVIDOR, aplicarProveedorAClaves,
  aplicarProveedorATodas, archivosXlsx, asignarProveedor, contadoresDesdePrevia, debeContinuarPolling,
  etiquetaFaseTrabajo, fechaCorta, filtrarComprobantes, hayErroresParaDescargar, motivoNoConfirmable, rangoPagina,
  resultadoDesdeTrabajo, resumenAnulacionDesdeTrabajo, textoPorGrabar, textoProgresoTrabajo, trabajoActivo,
  type FiltroImportacion,
} from '../../utils/importacionExcel';

const VARIANTE_ESTADO = {
  NUEVO: 'success', COMPLETAR: 'info', YA_EXISTE: 'neutral', CONFLICTO: 'warning', ERROR: 'destructive',
} as const;

const FILTROS: { valor: FiltroImportacion; etiqueta: string }[] = [
  { valor: 'TODOS', etiqueta: 'Todos' },
  { valor: 'NUEVO', etiqueta: 'Nuevos' },
  { valor: 'COMPLETAR', etiqueta: 'A completar' },
  { valor: 'YA_EXISTE', etiqueta: 'Ya existen' },
  { valor: 'ERROR', etiqueta: 'Errores' },
  { valor: 'CONFLICTO', etiqueta: 'Conflictos' },
  { valor: 'SIN_PROVEEDOR', etiqueta: 'Sin proveedor' },
  { valor: 'OBSERVADOS', etiqueta: 'Observaciones' },
];

const TAMANOS_PAGINA = [50, 100, 150, 200] as const;
const POLLING_MS = 2000;

const IndicadorTrabajo: React.FC<{ trabajo: TrabajoImportacion; titulo: string }> = ({ trabajo, titulo }) => {
  const progreso = trabajo.progreso;
  const pct = progreso?.porcentaje ?? 0;
  return (
    <div role="status" className="space-y-2 rounded-lg border border-indigo-200 bg-indigo-50 p-3.5 text-xs text-indigo-900">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 font-semibold">
          <Loader2 className="h-4 w-4 shrink-0 animate-spin text-indigo-600" />
          <span>{titulo} · #{trabajo.id}</span>
          <Badge variant="info" size="xs">{etiquetaFaseTrabajo(progreso?.fase ?? trabajo.estado)}</Badge>
        </div>
        <span className="tabular-nums font-medium">{textoProgresoTrabajo(trabajo)}</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-indigo-100">
        <div
          className="h-full rounded-full bg-indigo-600 transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="text-[11px] text-indigo-700">
        {progreso?.mensaje || 'Procesando en segundo plano…'} Puedes recargar o cambiar de pestaña; el proceso continúa en el servidor.
      </p>
    </div>
  );
};

const Aviso: React.FC<{ tipo: 'error' | 'ok'; children: React.ReactNode }> = ({ tipo, children }) => (
  <div
    role={tipo === 'error' ? 'alert' : 'status'}
    className={`flex items-start gap-2.5 rounded-lg border p-3.5 text-xs ${
      tipo === 'error' ? 'border-rose-200 bg-rose-50 text-rose-700' : 'border-emerald-200 bg-emerald-50 text-emerald-700'}`}
  >
    {tipo === 'error' ? <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" /> : <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />}
    <div className="space-y-1 font-medium leading-relaxed">{children}</div>
  </div>
);

const NuevaImportacion: React.FC<{ onImportado: () => void }> = ({ onImportado }) => {
  const [archivos, setArchivos] = useState<File[]>([]);
  const [almacenes, setAlmacenes] = useState<Almacen[]>([]);
  const [almacenId, setAlmacenId] = useState<number | null>(null);
  const [proveedoresLista, setProveedoresLista] = useState<Tercero[]>([]);
  const [proveedores, setProveedores] = useState<Record<string, string>>({});
  const [paraTodas, setParaTodas] = useState('');
  const [previa, setPrevia] = useState<PrevisualizacionImportacion | null>(null);
  const [comprobantesPagina, setComprobantesPagina] = useState<ComprobanteImportado[]>([]);
  const [paginacion, setPaginacion] = useState<PrevisualizacionPaginacion | null>(null);
  const [pageSize, setPageSize] = useState<number>(100);
  const [cargandoPagina, setCargandoPagina] = useState(false);
  const [desactualizada, setDesactualizada] = useState(false);
  const [filtro, setFiltro] = useState<FiltroImportacion>('TODOS');
  const [trabajando, setTrabajando] = useState<'' | 'previa' | 'confirmar' | 'plantilla' | 'errores' | 'proveedores'>('');
  const [trabajoConfirmar, setTrabajoConfirmar] = useState<TrabajoImportacion | null>(null);
  const [errores, setErrores] = useState<string[]>([]);
  const [resultado, setResultado] = useState<ResultadoImportacion | null>(null);

  useEffect(() => {
    getAlmacenes().then((lista) => {
      const activos = lista.filter((a) => a.activo);
      setAlmacenes(activos);
      if (activos.length) setAlmacenId(activos[0].id);
    }).catch(() => setAlmacenes([]));
    getTerceros({ tipo: 'proveedor' }).then((lista) => {
      setProveedoresLista(lista.filter((t) => t.estado === 'ACTIVO' && t.numero_documento.length === 11));
    }).catch(() => setProveedoresLista([]));

    // Recuperar trabajo activo si el usuario recargó o volvió a abrir la pestaña
    listarTrabajosImportacion({ tipo: 'CONFIRMAR' })
      .then((trabajos) => {
        const enCurso = trabajos.find((t) => trabajoActivo(t));
        if (enCurso) setTrabajoConfirmar(enCurso);
      })
      .catch(() => {});
  }, []);

  const trabajoConfirmarId = trabajoConfirmar && debeContinuarPolling(trabajoConfirmar) ? trabajoConfirmar.id : null;

  useEffect(() => {
    if (!trabajoConfirmarId) return;
    let cancelado = false;

    const consultar = async () => {
      try {
        const actualizado = await obtenerTrabajoImportacion(trabajoConfirmarId);
        if (cancelado) return;
        setTrabajoConfirmar(actualizado);
        if (actualizado.estado === 'COMPLETADO') {
          const res = resultadoDesdeTrabajo(actualizado);
          if (res) setResultado(res);
          setPrevia(null);
          setComprobantesPagina([]);
          setPaginacion(null);
          setArchivos([]);
          setProveedores({});
          setTrabajoConfirmar(null);
          onImportado();
        } else if (actualizado.estado === 'ERROR') {
          setErrores([actualizado.error_detalle || 'La importación falló en segundo plano. No se grabó nada.']);
          setTrabajoConfirmar(null);
        }
      } catch {
        // Si falla un tick de red, el siguiente intervalo reintenta sin perder el estado
      }
    };

    const timer = window.setInterval(consultar, POLLING_MS);
    return () => {
      cancelado = true;
      window.clearInterval(timer);
    };
  }, [trabajoConfirmarId, onImportado]);

  const elegirArchivos = (lista: FileList | null) => {
    const { validos, rechazados } = archivosXlsx(Array.from(lista ?? []));
    setArchivos(validos);
    setPrevia(null);
    setComprobantesPagina([]);
    setPaginacion(null);
    setProveedores({});
    setResultado(null);
    setErrores(rechazados.length ? [`Se ignoraron archivos que no son .xlsx: ${rechazados.join(', ')}.`] : []);
  };

  const previsualizar = async (conProveedores = proveedores, tamano = pageSize) => {
    if (!archivos.length) return;
    setTrabajando('previa');
    setErrores([]);
    setResultado(null);
    try {
      const data = await previsualizarImportacion(archivos, conProveedores, tamano);
      setPrevia(data);
      setComprobantesPagina(data.comprobantes);
      setPaginacion(data.paginacion ?? {
        page: 1,
        page_size: tamano,
        total: data.comprobantes.length,
        total_pages: 1,
        has_next: false,
        has_previous: false,
      });
      setDesactualizada(false);
      setFiltro('TODOS');
    } catch (err) {
      setPrevia(null);
      setComprobantesPagina([]);
      setPaginacion(null);
      setErrores(mensajesDeErrorApi(err, 'No se pudieron leer los archivos.'));
    } finally {
      setTrabajando('');
    }
  };

  const cargarPagina = async (nuevoFiltro: FiltroImportacion, nuevaPagina: number, nuevoTamano = pageSize) => {
    setFiltro(nuevoFiltro);
    if (!previa?.previsualizacion_id) {
      setComprobantesPagina(filtrarComprobantes(previa?.comprobantes ?? [], nuevoFiltro, proveedores));
      return;
    }
    setCargandoPagina(true);
    setErrores([]);
    try {
      const resp = await obtenerComprobantesPrevisualizacion(previa.previsualizacion_id, {
        page: nuevaPagina,
        page_size: nuevoTamano,
        filtro: FILTRO_A_SERVIDOR[nuevoFiltro],
      });
      setComprobantesPagina(resp.comprobantes);
      setPaginacion(resp.paginacion);
      setPageSize(nuevoTamano);
    } catch (err) {
      setErrores(mensajesDeErrorApi(err, 'No se pudo cargar la página de previsualización.'));
    } finally {
      setCargandoPagina(false);
    }
  };

  const cambiarProveedores = (nuevos: Record<string, string>) => {
    setProveedores(nuevos);
    setDesactualizada(true);
  };

  const aplicarATodasSinRuc = async () => {
    if (!paraTodas || !previa) return;
    if (!previa.previsualizacion_id) {
      cambiarProveedores(aplicarProveedorATodas(previa.comprobantes, proveedores, paraTodas));
      return;
    }
    setTrabajando('proveedores');
    try {
      const resp = await obtenerComprobantesPrevisualizacion(previa.previsualizacion_id, {
        filtro: 'sin_proveedor',
        page: 1,
        page_size: 50,
        incluir_claves: true,
      });
      const claves = resp.claves_sin_proveedor ?? [];
      cambiarProveedores(
        claves.length
          ? aplicarProveedorAClaves(claves, proveedores, paraTodas)
          : aplicarProveedorATodas(comprobantesPagina, proveedores, paraTodas),
      );
    } catch (err) {
      setErrores(mensajesDeErrorApi(err, 'No se pudieron obtener todas las compras sin RUC.'));
    } finally {
      setTrabajando('');
    }
  };

  const descargarErrores = async () => {
    if (!previa?.previsualizacion_id || trabajando) return;
    setTrabajando('errores');
    try {
      const blob = await descargarErroresPrevisualizacion(previa.previsualizacion_id);
      descargarBlob(blob, `errores_previsualizacion_${previa.previsualizacion_id.slice(0, 8)}.xlsx`);
    } catch (err) {
      setErrores(mensajesDeErrorApi(err, 'No se pudo descargar el Excel de errores.'));
    } finally {
      setTrabajando('');
    }
  };

  const confirmar = async () => {
    if (trabajando || trabajoActivo(trabajoConfirmar)) return;
    setTrabajando('confirmar');
    setErrores([]);
    setResultado(null);
    try {
      const trabajo = await confirmarImportacion(archivos, almacenId, proveedores);
      setTrabajoConfirmar(trabajo);
      if (trabajo.estado === 'COMPLETADO') {
        const res = resultadoDesdeTrabajo(trabajo);
        if (res) setResultado(res);
        setPrevia(null);
        setComprobantesPagina([]);
        setPaginacion(null);
        setArchivos([]);
        setProveedores({});
        setTrabajoConfirmar(null);
        onImportado();
      }
    } catch (err) {
      setErrores(mensajesDeErrorApi(err, 'No se pudo encolar la importación. No se grabó nada.'));
    } finally {
      setTrabajando('');
    }
  };

  const descargarPlantilla = async () => {
    setTrabajando('plantilla');
    try {
      descargarBlob(await descargarPlantillaEntradasSalidas(), 'plantilla_entradas_salidas.xlsx');
    } catch (err) {
      setErrores(mensajesDeErrorApi(err, 'No se pudo descargar la plantilla.'));
    } finally {
      setTrabajando('');
    }
  };

  const conteo = useMemo(() => contadoresDesdePrevia(previa, proveedores), [previa, proveedores]);
  const visibles = previa?.previsualizacion_id ? comprobantesPagina : filtrarComprobantes(comprobantesPagina, filtro, proveedores);
  const bloqueo = motivoNoConfirmable({ previa, desactualizada, almacenId, proveedores });
  const enProceso = trabajando !== '' || trabajoActivo(trabajoConfirmar);
  const pagActual = paginacion?.page ?? 1;
  const totalPaginas = paginacion?.total_pages ?? 1;
  const totalFiltrado = paginacion?.total ?? visibles.length;
  const rango = rangoPagina(pagActual, paginacion?.page_size ?? pageSize, totalFiltrado);

  return (
    <div className="space-y-4">
      <Card className="border-indigo-300 ring-1 ring-indigo-200" data-testid="importacion-formato">
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            <FileSpreadsheet className="h-4 w-4 text-indigo-600" /> Entradas y salidas
          </CardTitle>
          <CardDescription className="text-xs">
            Importa un Excel con solo compras, solo ventas o ambas. Puedes seleccionar varios archivos a la vez.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button variant="outline" size="sm" onClick={descargarPlantilla} disabled={enProceso}>
            <Download className="mr-1.5 h-3.5 w-3.5" /> Descargar plantilla
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="space-y-3 pt-5">
          <div className="grid gap-3 md:grid-cols-[1fr_260px_auto] md:items-end">
            <label className="block text-xs font-medium text-slate-700">
              Archivos Excel (.xlsx)
              <input
                type="file" accept=".xlsx" multiple disabled={enProceso}
                onChange={(e) => elegirArchivos(e.target.files)}
                className="mt-1 block w-full text-xs file:mr-3 file:rounded-md file:border-0 file:bg-slate-100 file:px-3 file:py-2 file:text-xs file:font-semibold"
                data-testid="importacion-archivos"
              />
            </label>
            <label className="block text-xs font-medium text-slate-700">
              Almacén de los movimientos
              <select
                className="mt-1 block h-9 w-full rounded-md border border-slate-200 bg-white px-2 text-sm"
                value={almacenId ?? ''} disabled={enProceso}
                onChange={(e) => { setAlmacenId(e.target.value ? Number(e.target.value) : null); }}
              >
                {almacenes.length === 0 && <option value="">Sin almacenes activos</option>}
                {almacenes.map((a) => <option key={a.id} value={a.id}>{a.codigo} · {a.nombre}</option>)}
              </select>
            </label>
            <Button variant="primary" onClick={() => previsualizar()} disabled={!archivos.length || enProceso}>
              {trabajando === 'previa' ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <Upload className="mr-1.5 h-4 w-4" />}
              Previsualizar
            </Button>
          </div>
          {archivos.length > 0 && (
            <p className="text-xs text-slate-500">{archivos.length} archivo(s): {archivos.map((a) => a.name).join(', ')}</p>
          )}
        </CardContent>
      </Card>

      {errores.length > 0 && <Aviso tipo="error">{errores.map((e) => <p key={e}>{e}</p>)}</Aviso>}
      {resultado && (
        <Aviso tipo="ok">
          <p>Lote {resultado.lote}: se grabaron {resultado.comprobantes} comprobantes
            {resultado.completados ? ` y se completaron ${resultado.completados} (${resultado.lineas_agregadas} línea(s) agregada(s))` : ''}
            {' '}en {resultado.segundos} s
            {resultado.omitidos ? ` (${resultado.omitidos} ya existían y se omitieron)` : ''}. El Kardex quedó actualizado.</p>
        </Aviso>
      )}
      {trabajoConfirmar && trabajoActivo(trabajoConfirmar) && (
        <IndicadorTrabajo trabajo={trabajoConfirmar} titulo="Importando comprobantes y recalculando Kardex" />
      )}

      {previa && (
        <Card data-testid="importacion-previa">
          <CardHeader className="pb-3">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <CardTitle className="text-sm">Previsualización · nada se ha grabado todavía</CardTitle>
                <CardDescription className="text-xs">
                  {previa.resumen.total_filas ?? previa.resumen.filas} filas de {previa.resumen.archivos} archivo(s) ·{' '}
                  {previa.resumen.total_comprobantes ?? previa.resumen.comprobantes} comprobantes ·{' '}
                  del {fechaCorta(previa.resumen.desde)} al {fechaCorta(previa.resumen.hasta)}
                  {previa.resumen.periodos_detectados?.length ? ` · Períodos: ${previa.resumen.periodos_detectados.join(', ')}` : ''}
                </CardDescription>
              </div>
              {hayErroresParaDescargar(previa) && previa.previsualizacion_id && (
                <Button
                  size="sm" variant="outline" onClick={descargarErrores} disabled={enProceso}
                  data-testid="importacion-descargar-errores"
                >
                  {trabajando === 'errores' ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Download className="mr-1.5 h-3.5 w-3.5" />}
                  Descargar errores (.xlsx)
                </Button>
              )}
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filtrar comprobantes">
              {FILTROS.map((f) => (
                <button
                  key={f.valor} type="button" disabled={cargandoPagina}
                  onClick={() => cargarPagina(f.valor, 1)}
                  className={`rounded-full border px-3 py-1 text-xs font-semibold transition-colors ${
                    filtro === f.valor ? 'border-indigo-600 bg-indigo-600 text-white' : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'}`}
                >
                  {f.etiqueta} <span className="tabular-nums opacity-80">{conteo[f.valor]}</span>
                </button>
              ))}
            </div>

            {conteo.SIN_PROVEEDOR > 0 && (
              <div className="flex flex-wrap items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
                <span className="font-semibold">{conteo.SIN_PROVEEDOR} compra(s) sin RUC del proveedor.</span>
                <select
                  className="h-8 rounded-md border border-amber-300 bg-white px-2 text-xs" value={paraTodas}
                  onChange={(e) => setParaTodas(e.target.value)} aria-label="Proveedor para todas las compras sin RUC"
                >
                  <option value="">Elegir proveedor…</option>
                  {proveedoresLista.map((t) => <option key={t.id} value={t.numero_documento}>{t.numero_documento} · {t.razon_social}</option>)}
                </select>
                <Button
                  size="sm" variant="outline" disabled={!paraTodas || enProceso}
                  onClick={aplicarATodasSinRuc}
                >
                  {trabajando === 'proveedores' && <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />}
                  Aplicar a todas las compras sin RUC
                </Button>
              </div>
            )}

            {desactualizada && (
              <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-indigo-200 bg-indigo-50 p-3 text-xs text-indigo-800">
                <span>Cambiaste proveedores: vuelve a previsualizar para validarlos.</span>
                <Button size="sm" variant="primary" onClick={() => previsualizar()} disabled={enProceso}>Volver a previsualizar</Button>
              </div>
            )}

            <div className="max-h-[480px] overflow-auto rounded-lg border border-slate-200">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
                  <tr>
                    <th className="px-2 py-2 text-left">Fecha</th>
                    <th className="px-2 py-2 text-left">Comprobante</th>
                    <th className="px-2 py-2 text-left">Operación</th>
                    <th className="px-2 py-2 text-left">Productos</th>
                    <th className="px-2 py-2 text-left">Estado</th>
                    <th className="px-2 py-2 text-left">Detalle</th>
                  </tr>
                </thead>
                <tbody>
                  {visibles.map((c) => (
                    <tr key={`${c.clave}-${c.fecha ?? ''}`} className="border-t border-slate-100 align-top">
                      <td className="whitespace-nowrap px-2 py-2 tabular-nums">{fechaCorta(c.fecha)}</td>
                      <td className="whitespace-nowrap px-2 py-2">
                        <span className="font-mono font-semibold text-slate-800">{c.serie}-{c.numero}</span>
                        <span className="block text-[10px] text-slate-400">{ETIQUETA_TIPO[c.tipo] ?? c.tipo}{c.ruc ? ` · ${c.ruc}` : ''}</span>
                      </td>
                      <td className="whitespace-nowrap px-2 py-2">{ETIQUETA_OPERACION[c.operacion] ?? c.operacion}</td>
                      <td className="px-2 py-2">{c.productos.join(', ')}{c.lineas > c.productos.length ? ` (${c.lineas} líneas)` : ''}</td>
                      <td className="px-2 py-2"><Badge variant={VARIANTE_ESTADO[c.estado]} size="xs">{ETIQUETA_ESTADO[c.estado]}</Badge></td>
                      <td className="min-w-72 px-2 py-2 text-slate-600">
                        {c.requiere_proveedor && c.clave_proveedor ? (
                          <select
                            className="h-8 w-full rounded-md border border-slate-200 bg-white px-2 text-xs"
                            value={proveedores[c.clave_proveedor] ?? ''} aria-label={`Proveedor de ${c.serie}-${c.numero}`}
                            onChange={(e) => cambiarProveedores(asignarProveedor(proveedores, c.clave_proveedor ?? '', e.target.value))}
                          >
                            <option value="">Elegir proveedor…</option>
                            {proveedoresLista.map((t) => <option key={t.id} value={t.numero_documento}>{t.numero_documento} · {t.razon_social}</option>)}
                          </select>
                        ) : c.estado === 'COMPLETAR' ? (
                          <div className="space-y-1" data-testid="importacion-completar">
                            <p className="text-indigo-800">
                              Ya está registrado (lote {c.completa_lote}). Se le agregará solo:
                            </p>
                            <ul className="list-disc pl-4 text-indigo-800">
                              {c.agregar.map((a) => (
                                <li key={`${a.archivo}-${a.fila}`}>
                                  <span className="font-mono font-semibold">{a.codigo}</span> · cantidad {a.cantidad} · costo {a.costo_unitario}
                                  {a.precio_unitario ? ` · precio ${a.precio_unitario}` : ''}
                                  <span className="text-slate-400"> (fila {a.fila} de {a.archivo})</span>
                                </li>
                              ))}
                            </ul>
                          </div>
                        ) : c.mensaje && <p className={c.estado === 'ERROR' ? 'text-rose-700' : ''}>{c.mensaje}</p>}
                        {c.origen && <p className="text-slate-500">Devuelve {c.origen.comprobante}{c.origen.aproximado ? ' (aproximado)' : ''}</p>}
                        {c.observaciones.map((o) => <p key={o} className="text-amber-700">{o}</p>)}
                      </td>
                    </tr>
                  ))}
                  {!visibles.length && (
                    <tr><td colSpan={6} className="px-2 py-6 text-center text-slate-400">{cargandoPagina ? 'Cargando página…' : 'Sin comprobantes en este filtro.'}</td></tr>
                  )}
                </tbody>
              </table>
            </div>

            {previa.previsualizacion_id && (
              <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-600" data-testid="importacion-paginacion">
                <span className="tabular-nums">
                  {totalFiltrado > 0 ? `Mostrando ${rango.desde}–${rango.hasta} de ${totalFiltrado} comprobante(s)` : '0 comprobantes'}
                </span>
                <div className="flex items-center gap-2">
                  <label className="flex items-center gap-1.5">
                    <span>Por página:</span>
                    <select
                      className="h-8 rounded-md border border-slate-200 bg-white px-2 text-xs"
                      value={pageSize}
                      disabled={cargandoPagina}
                      onChange={(e) => cargarPagina(filtro, 1, parseInt(e.target.value, 10))}
                    >
                      {TAMANOS_PAGINA.map((n) => <option key={n} value={n}>{n}</option>)}
                    </select>
                  </label>
                  <Button
                    size="xs" variant="outline" disabled={cargandoPagina || pagActual <= 1}
                    onClick={() => cargarPagina(filtro, pagActual - 1)}
                  >
                    <ChevronLeft className="h-3.5 w-3.5" /> Anterior
                  </Button>
                  <span className="tabular-nums font-medium">Pág. {pagActual} / {totalPaginas}</span>
                  <Button
                    size="xs" variant="outline" disabled={cargandoPagina || pagActual >= totalPaginas}
                    onClick={() => cargarPagina(filtro, pagActual + 1)}
                  >
                    Siguiente <ChevronRight className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            )}

            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-3">
              <p className="text-xs text-slate-500">{bloqueo ?? `Se grabarán ${textoPorGrabar(previa.resumen)}. Todo o nada.`}</p>
              <Button variant="success" onClick={confirmar} disabled={Boolean(bloqueo) || enProceso} data-testid="importacion-confirmar">
                {trabajando === 'confirmar' ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <CheckCircle2 className="mr-1.5 h-4 w-4" />}
                Confirmar importación
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
};

const LotesImportados: React.FC<{ recarga: number }> = ({ recarga }) => {
  const [lotes, setLotes] = useState<LoteImportacion[]>([]);
  const [cargando, setCargando] = useState(true);
  const [anulando, setAnulando] = useState<LoteImportacion | null>(null);
  const [viendo, setViendo] = useState<number | null>(null);
  const [motivo, setMotivo] = useState('');
  const [procesando, setProcesando] = useState(false);
  const [trabajoAnular, setTrabajoAnular] = useState<TrabajoImportacion | null>(null);
  const [errores, setErrores] = useState<string[]>([]);
  const [exito, setExito] = useState('');

  const cargar = useCallback(async () => {
    setCargando(true);
    try {
      const [lista, trabajos] = await Promise.all([
        listarLotesImportacion(),
        listarTrabajosImportacion({ tipo: 'ANULAR' }).catch(() => [] as TrabajoImportacion[]),
      ]);
      setLotes(lista);
      const activo = trabajos.find((t) => trabajoActivo(t)) ?? null;
      if (activo) setTrabajoAnular(activo);
    } catch (err) {
      setErrores(mensajesDeErrorApi(err, 'No se pudieron cargar los lotes.'));
    } finally {
      setCargando(false);
    }
  }, []);

  useEffect(() => { diferirCarga(cargar); }, [cargar, recarga]);

  const trabajoAnularId = trabajoAnular && debeContinuarPolling(trabajoAnular) ? trabajoAnular.id : null;

  useEffect(() => {
    if (!trabajoAnularId) return;
    let cancelado = false;

    const consultar = async () => {
      try {
        const actualizado = await obtenerTrabajoImportacion(trabajoAnularId);
        if (cancelado) return;
        setTrabajoAnular(actualizado);
        if (actualizado.estado === 'COMPLETADO') {
          const r = resumenAnulacionDesdeTrabajo(actualizado);
          if (r) {
            setExito(
              `Lote ${r.lote} anulado: ${r.comprobantes_anulados} comprobantes y su efecto en el Kardex revertidos.`
              + (r.lineas_revertidas
                ? ` Se revirtieron ${r.lineas_revertidas} línea(s) que el lote había agregado a ${r.comprobantes_revertidos.join(', ')}; las demás líneas de esos comprobantes siguen vigentes.`
                : ''),
            );
          }
          setTrabajoAnular(null);
          await cargar();
        } else if (actualizado.estado === 'ERROR') {
          setErrores([actualizado.error_detalle || 'No se pudo anular el lote. No se anuló nada.']);
          setTrabajoAnular(null);
          await cargar();
        }
      } catch {
        // Reintenta en el siguiente intervalo
      }
    };

    const timer = window.setInterval(consultar, POLLING_MS);
    return () => {
      cancelado = true;
      window.clearInterval(timer);
    };
  }, [trabajoAnularId, cargar]);

  const anular = async () => {
    if (!anulando || procesando) return;
    setProcesando(true);
    setErrores([]);
    setExito('');
    try {
      const trabajo = await anularLoteImportacion(anulando.id, motivo.trim());
      setAnulando(null);
      setMotivo('');
      if (trabajo.estado === 'COMPLETADO') {
        const r = resumenAnulacionDesdeTrabajo(trabajo);
        if (r) {
          setExito(`Lote ${r.lote} anulado: ${r.comprobantes_anulados} comprobantes revertidos.`);
        }
        await cargar();
      } else {
        setTrabajoAnular(trabajo);
      }
    } catch (err) {
      setErrores(mensajesDeErrorApi(err, 'No se pudo anular el lote. No se anuló nada.'));
    } finally {
      setProcesando(false);
    }
  };

  return (
    <div className="space-y-3">
      {errores.length > 0 && !anulando && <Aviso tipo="error">{errores.map((e) => <p key={e}>{e}</p>)}</Aviso>}
      {exito && <Aviso tipo="ok"><p>{exito}</p></Aviso>}
      {trabajoAnular && trabajoActivo(trabajoAnular) && (
        <IndicadorTrabajo
          trabajo={trabajoAnular}
          titulo={`Anulando lote #${trabajoAnular.lote_id ?? ''}`}
        />
      )}
      <Card>
        <CardContent className="overflow-x-auto p-0">
          <table className="w-full text-xs">
            <thead className="bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-3 py-2 text-left">Lote</th>
                <th className="px-3 py-2 text-left">Fecha</th>
                <th className="px-3 py-2 text-left">Estado</th>
                <th className="px-3 py-2 text-left">Archivos</th>
                <th className="px-3 py-2 text-right">Comprobantes</th>
                <th className="px-3 py-2 text-left">Período</th>
                <th className="px-3 py-2 text-left">Almacén</th>
                <th className="px-3 py-2 text-left">Usuario</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {lotes.map((l) => {
                const anularEnCurso = trabajoAnular && trabajoActivo(trabajoAnular) && trabajoAnular.lote_id === l.id;
                return (
                  <tr key={l.id} className="border-t border-slate-100 align-top">
                    <td className="px-3 py-2 font-mono font-semibold">#{l.id}</td>
                    <td className="whitespace-nowrap px-3 py-2">{fechaCorta(l.creado_en)}</td>
                    <td className="px-3 py-2">
                      <Badge variant={l.estado === 'CONFIRMADO' ? 'success' : 'neutral'} size="xs">
                        {l.estado === 'CONFIRMADO' ? 'Activo' : 'Anulado'}
                      </Badge>
                      {l.estado === 'ANULADO' && (
                        <span className="mt-1 block text-[10px] text-slate-400">{fechaCorta(l.anulado_en)} · {l.anulado_por} · {l.motivo_anulacion}</span>
                      )}
                    </td>
                    <td className="max-w-64 px-3 py-2 text-slate-600">{l.archivos.join(', ')}</td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {l.comprobantes}
                      {l.completados > 0 && (
                        <span className="block text-[10px] text-indigo-700" title={l.comprobantes_completados.join(', ')}>
                          + {l.lineas_agregadas} línea(s) en {l.completados} completado(s)
                        </span>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2">{fechaCorta(l.desde)} – {fechaCorta(l.hasta)}</td>
                    <td className="px-3 py-2">{l.almacen.codigo}</td>
                    <td className="px-3 py-2">{l.creado_por ?? '—'}</td>
                    <td className="px-3 py-2 text-right">
                      {l.estado === 'CONFIRMADO' && (
                        <div className="flex justify-end gap-1.5">
                          <Button size="xs" variant={viendo === l.id ? 'primary' : 'outline'} onClick={() => setViendo(viendo === l.id ? null : l.id)}>
                            <Scale className="mr-1 h-3.5 w-3.5" /> Diferencias
                          </Button>
                          <Button
                            size="xs" variant="outline" className="text-rose-700" disabled={Boolean(anularEnCurso)}
                            onClick={() => { setAnulando(l); setMotivo(''); setErrores([]); setExito(''); }}
                          >
                            {anularEnCurso ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <XCircle className="mr-1 h-3.5 w-3.5" />}
                            {anularEnCurso ? 'Anulando…' : 'Anular lote'}
                          </Button>
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
              {!lotes.length && (
                <tr><td colSpan={9} className="px-3 py-8 text-center text-slate-400">{cargando ? 'Cargando…' : 'Aún no hay lotes importados.'}</td></tr>
              )}
            </tbody>
          </table>
        </CardContent>
      </Card>

      {viendo !== null && lotes.some((l) => l.id === viendo && l.estado === 'CONFIRMADO') && (
        <DiferenciasLote key={viendo} loteId={viendo} onCerrar={() => setViendo(null)} />
      )}

      <Modal
        isOpen={Boolean(anulando)} onClose={() => { if (!procesando) setAnulando(null); }}
        title={`Anular lote #${anulando?.id ?? ''}`}
        description="Se anulan todos sus comprobantes (o ninguno) y se revierte su efecto en el Kardex. No se borra nada."
        icon={<Lock className="h-5 w-5 text-rose-600" />}
        footer={(
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setAnulando(null)} disabled={procesando}>Cancelar</Button>
            <Button variant="destructive" onClick={anular} disabled={procesando || motivo.trim().length < 5}>
              {procesando && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />} Anular lote
            </Button>
          </div>
        )}
      >
        <div className="space-y-3">
          <label className="block text-xs font-medium text-slate-700">
            Motivo (obligatorio)
            <textarea
              className="mt-1 block w-full rounded-md border border-slate-200 p-2 text-sm" rows={3} maxLength={500}
              value={motivo} onChange={(e) => setMotivo(e.target.value)} disabled={procesando}
              placeholder="Ej.: se importó con el almacén equivocado"
            />
          </label>
          <p className="text-xs text-slate-500">Al confirmar, el sistema te pedirá tu contraseña.</p>
          {errores.length > 0 && <Aviso tipo="error">{errores.map((e) => <p key={e}>{e}</p>)}</Aviso>}
        </div>
      </Modal>
    </div>
  );
};

export const ImportacionExcelPage: React.FC = () => {
  const { empresaActiva, usuario } = useAuth();
  const navigate = useNavigate();
  const [pestana, setPestana] = useState<'nueva' | 'lotes'>('nueva');
  const [recarga, setRecarga] = useState(0);
  const esAdmin = Boolean(usuario?.es_admin_global) || empresaActiva?.rol === 'ADMIN';

  return (
    <div className="space-y-5">
      <PageHeader
        title="Importar comprobantes desde Excel"
        description="Registro masivo que pasa por el flujo normal (crear → revisar → confirmar) y actualiza el Kardex. Todo o nada."
        icon={<FileSpreadsheet className="h-5 w-5" />}
        actions={(
          <Button variant="outline" size="sm" onClick={() => navigate('/comprobantes')}>
            <ArrowLeft className="mr-1.5 h-4 w-4" /> Volver a comprobantes
          </Button>
        )}
      />
      {!esAdmin ? (
        <Aviso tipo="error"><p>Solo un administrador de la empresa puede importar comprobantes.</p></Aviso>
      ) : (
        <>
          <Tabs value={pestana} onValueChange={(v) => setPestana(v as 'nueva' | 'lotes')}>
            <TabsList aria-label="Importación">
              <TabsTrigger value="nueva" role="tab" aria-selected={pestana === 'nueva'} icon={<Upload className="h-4 w-4" />}>Nueva importación</TabsTrigger>
              <TabsTrigger value="lotes" role="tab" aria-selected={pestana === 'lotes'} icon={<History className="h-4 w-4" />}>Lotes importados</TabsTrigger>
            </TabsList>
          </Tabs>
          <div hidden={pestana !== 'nueva'}><NuevaImportacion onImportado={() => setRecarga((n) => n + 1)} /></div>
          <div hidden={pestana !== 'lotes'}><LotesImportados recarga={recarga} /></div>
        </>
      )}
    </div>
  );
};

export default ImportacionExcelPage;
