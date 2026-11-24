import apiClient from './http';

export type EstadoComprobanteImportado = 'NUEVO' | 'YA_EXISTE' | 'CONFLICTO' | 'ERROR';

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

export interface ResultadoAnulacionLote { lote: number; estado: 'ANULADO'; comprobantes_anulados: number }

export const anularLoteImportacion = async (id: number, motivo: string): Promise<ResultadoAnulacionLote> =>
  (await apiClient.post<ResultadoAnulacionLote>(`${BASE}/lotes/${id}/anular/`, { motivo }, { timeout: 180_000 })).data;
