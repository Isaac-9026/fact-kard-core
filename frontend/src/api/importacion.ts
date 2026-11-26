import apiClient from './http';

export type EstadoComprobanteImportado = 'NUEVO' | 'COMPLETAR' | 'YA_EXISTE' | 'CONFLICTO' | 'ERROR';

/** Línea del Excel que se agregará a un comprobante ya importado («Completar comprobante»). */
export interface LineaPorAgregar {
  archivo: string;
  fila: number;
  codigo: string;
  cantidad: string;
  costo_unitario: string;
  costo_total: string;
  precio_unitario: string | null;
}

export interface ComprobanteImportado {
  clave: string;
  clase: 'COMPRA' | 'VENTA';
  operacion: string;
  tipo: string;
  serie: string;
  numero: string;
  fecha: string | null;
  ruc: string | null;
  naturaleza: 'ENTRADA' | 'SALIDA';
  lineas: number;
  productos: string[];
  origen: { fuente: 'EXCEL' | 'SISTEMA'; comprobante: string; tipo: string; aproximado: boolean } | null;
  requiere_proveedor: boolean;
  clave_proveedor: string | null;
  estado: EstadoComprobanteImportado;
  mensaje: string;
  observaciones: string[];
  /** Lote que importó el comprobante que se completará (solo en COMPLETAR). */
  completa_lote: number | null;
  agregar: LineaPorAgregar[];
}

export interface FilaImportada {
  archivo: string;
  fila: number;
  codigo: string;
  fecha: string | null;
  comprobante: string | null;
  estado: EstadoComprobanteImportado;
  errores: string[];
  observaciones: string[];
}

export interface ResumenImportacion {
  archivos: number;
  filas: number;
  filas_con_error: number;
  filas_con_observacion: number;
  comprobantes: number;
  nuevos: number;
  completar: number;
  lineas_a_agregar: number;
  ya_existen: number;
  conflictos: number;
  con_error: number;
  requieren_proveedor: number;
  productos: number;
  desde: string | null;
  hasta: string | null;
  limite_lote: number;
  excede_limite: boolean;
  puede_confirmar: boolean;
}

export interface PrevisualizacionImportacion {
  formato: 'ENTRADAS_SALIDAS';
  resumen: ResumenImportacion;
  comprobantes: ComprobanteImportado[];
  filas: FilaImportada[];
}

export interface ResultadoImportacion {
  lote: number;
  comprobantes: number;
  completados: number;
  lineas_agregadas: number;
  omitidos: number;
  segundos: number;
}

export interface LoteImportacion {
  id: number;
  formato: string;
  estado: 'CONFIRMADO' | 'ANULADO';
  almacen: { id: number; codigo: string; nombre: string };
  archivos: string[];
  comprobantes: number;
  completados: number;
  lineas_agregadas: number;
  comprobantes_completados: string[];
  desde: string | null;
  hasta: string | null;
  segundos: number | null;
  creado_por: string | null;
  creado_en: string;
  anulado_por: string | null;
  anulado_en: string | null;
  motivo_anulacion: string | null;
}

const BASE = '/documentos/importacion';
const MULTIPART = { headers: { 'Content-Type': 'multipart/form-data' } };

const formulario = (archivos: File[], extra: Record<string, string> = {}) => {
  const datos = new FormData();
  archivos.forEach((a) => datos.append('archivos', a));
  Object.entries(extra).forEach(([k, v]) => datos.append(k, v));
  return datos;
};

export const descargarPlantillaEntradasSalidas = async (): Promise<Blob> =>
  (await apiClient.get(`${BASE}/entradas-salidas/plantilla/`, { responseType: 'blob' })).data;

export const previsualizarImportacion = async (
  archivos: File[], proveedores: Record<string, string>,
): Promise<PrevisualizacionImportacion> =>
  (await apiClient.post<PrevisualizacionImportacion>(
    `${BASE}/entradas-salidas/previsualizar/`,
    formulario(archivos, Object.keys(proveedores).length ? { proveedores: JSON.stringify(proveedores) } : {}),
    MULTIPART,
  )).data;

export const confirmarImportacion = async (
  archivos: File[], almacenId: number | null, proveedores: Record<string, string>,
): Promise<ResultadoImportacion> =>
  (await apiClient.post<ResultadoImportacion>(
    `${BASE}/entradas-salidas/confirmar/`,
    formulario(archivos, {
      ...(almacenId ? { almacen: String(almacenId) } : {}),
      ...(Object.keys(proveedores).length ? { proveedores: JSON.stringify(proveedores) } : {}),
    }),
    { ...MULTIPART, timeout: 180_000 },
  )).data;

export const listarLotesImportacion = async (): Promise<LoteImportacion[]> =>
  (await apiClient.get<LoteImportacion[]>(`${BASE}/lotes/`)).data;

export interface ResultadoAnulacionLote {
  lote: number;
  estado: 'ANULADO';
  comprobantes_anulados: number;
  lineas_revertidas: number;
  comprobantes_revertidos: string[];
}

export const anularLoteImportacion = async (id: number, motivo: string): Promise<ResultadoAnulacionLote> =>
  (await apiClient.post<ResultadoAnulacionLote>(`${BASE}/lotes/${id}/anular/`, { motivo }, { timeout: 180_000 })).data;

export type NivelDiferencia = 'VERDE' | 'AMBAR' | 'ROJO';

export interface FiltrosDiferencias { producto?: number | null; nivel?: NivelDiferencia | null }

export interface LineaDiferencia {
  detalle_id: number;
  documento_id: number;
  fecha: string;
  comprobante: string;
  operacion: string;
  producto_id: number;
  producto_codigo: string;
  producto: string;
  cantidad: string;
  costo_unitario_excel: string | null;
  costo_unitario_sistema: string | null;
  diferencia_unitaria: string | null;
  porcentaje: string | null;
  costo_total_excel: string | null;
  costo_total_sistema: string | null;
  diferencia_total: string | null;
  nivel: NivelDiferencia;
  motivo: string;
}

export interface DiferenciasLote {
  lote: { id: number; estado: string };
  umbrales: { tolerancia: string; ambar_pct: string };
  productos: { id: number; codigo: string; descripcion: string }[];
  resumen: {
    lineas: number; verde: number; ambar: number; rojo: number;
    valor_excel: string; valor_sistema: string; diferencia_neta: string; diferencia_absoluta: string;
  };
  lineas: LineaDiferencia[];
}

const paramsDiferencias = (f: FiltrosDiferencias) => ({
  ...(f.producto ? { producto: String(f.producto) } : {}),
  ...(f.nivel ? { nivel: f.nivel } : {}),
});

export const obtenerDiferenciasLote = async (id: number, filtros: FiltrosDiferencias): Promise<DiferenciasLote> =>
  (await apiClient.get<DiferenciasLote>(`${BASE}/lotes/${id}/diferencias/`, { params: paramsDiferencias(filtros), timeout: 120_000 })).data;

export const descargarDiferenciasLote = async (id: number, filtros: FiltrosDiferencias): Promise<Blob> =>
  (await apiClient.get(`${BASE}/lotes/${id}/diferencias/excel/`, {
    params: paramsDiferencias(filtros), responseType: 'blob', timeout: 120_000,
  })).data;
