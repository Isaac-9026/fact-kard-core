import apiClient from './http';

export interface CapturaCampo {
  id: number;
  seccion: 'CABECERA' | 'DETALLE';
  numero_linea: number | null;
  nombre_campo: string;
  valor_extraido: string | null;
  confianza: string | null;
  valor_corregido: string | null;
  corregido_por: number | null;
  corregido_por_username: string | null;
}

export interface DocumentoCaptura {
  id: number;
  tipo: 'XML' | 'PDF' | 'IMAGEN' | 'ESCANER';
  ruta_archivo: string;
  hash_sha256: string;
  estado_proceso: string;
  documento_id: number | null;
  documento_serie_numero?: string | null;
  subido_por: number | null;
  subido_por_username: string | null;
  creado_en: string;
  total_campos?: number;
  campos?: CapturaCampo[];
  /** QA2-001: homologación de cada línea con la misma regla que el borrador. */
  homologacion?: HomologacionCaptura;
  fue_creado_nuevo?: boolean;
  mensaje?: string;
}

export interface LineaHomologacion {
  linea: number;
  codigo_externo: string;
  codigo_normalizado: string;
  descripcion: string;
  unidad: string;
  unidad_normalizada: string;
  criterio: 'codigo' | 'descripcion' | null;
  estado: 'HOMOLOGADA' | 'PENDIENTE';
  motivo: string;
  equivalencia_id: number | null;
  producto_id: number | null;
  producto_codigo: string | null;
  producto_unidad_id: number | null;
  factor_conversion: string;
}

export interface HomologacionCaptura {
  clase: 'COMPRA' | 'VENTA' | null;
  proveedor: { documento: string; nombre: string; tercero_id: number | null; razon_social: string | null } | null;
  lineas: LineaHomologacion[];
  pendientes_homologacion: number | null;
  error?: string;
}

export interface ProductoEquivalencia {
  id: number;
  empresa: number;
  tercero: number | null;
  /** QA2-001: captura de origen; el backend usa su proveedor (y lo registra si aún no existe). */
  captura?: number | null;
  tercero_info?: {
    id: number;
    numero_documento: string;
    razon_social: string;
  };
  codigo_externo: string | null;
  descripcion_externa: string | null;
  unidad_externa_codigo: string | null;
  unidad_externa_nombre?: string | null;
  producto_unidad: number;
  producto_info?: {
    producto_id: number;
    producto_codigo: string;
    producto_descripcion: string;
    unidad_codigo: string;
    factor_a_base: string;
    es_base: boolean;
  };
  factor_conversion: string;
  confirmado_por: number | null;
  confirmado_por_username?: string | null;
  confirmado_en: string | null;
  activa: boolean;
}

export interface GenerarBorradorResponse {
  documento_id: number;
  serie_numero: string;
  estado: string;
  estado_revision: string;
  total_lineas: number;
  lineas_sin_homologar: number;
  incidencias: Array<{
    incidencia_id: number;
    linea: number;
    codigo_externo: string;
    descripcion: string;
  }>;
  mensaje: string;
}

export interface SugerirEquivalenciaResponse {
  encontrado: boolean;
  sugerencia: ProductoEquivalencia | null;
  estado?: string;
  mensaje: string;
}

/**
 * Sube un archivo XML o documento para OCR a la bandeja de captura.
 */
export const subirCaptura = async (
  archivo: File,
  tipo: 'XML' | 'PDF' | 'IMAGEN' | 'ESCANER',
  textoOcr?: string
): Promise<DocumentoCaptura> => {
  const formData = new FormData();
  formData.append('archivo', archivo);
  formData.append('tipo', tipo);
  if (textoOcr) {
    formData.append('texto_ocr', textoOcr);
  }

  const response = await apiClient.post<DocumentoCaptura>('/documentos/capturas/subir/', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });
  return response.data;
};

/**
 * Obtiene la lista de capturas realizadas.
 */
export const obtenerCapturas = async (tipo?: string, estado?: string): Promise<DocumentoCaptura[]> => {
  const params: Record<string, string> = {};
  if (tipo) params.tipo = tipo;
  if (estado) params.estado = estado;

  const response = await apiClient.get<DocumentoCaptura[]>('/documentos/capturas/', { params });
  return response.data;
};

/**
 * Obtiene el detalle de una captura con sus campos y confianza.
 */
export const obtenerCapturaDetalle = async (id: number): Promise<DocumentoCaptura> => {
  const response = await apiClient.get<DocumentoCaptura>(`/documentos/capturas/${id}/`);
  return response.data;
};

/**
 * Corrige un valor extraído en la revisión humana de la captura.
 */
export const corregirCampoCaptura = async (
  capturaId: number,
  campoId: number,
  valorCorregido: string
): Promise<CapturaCampo> => {
  const response = await apiClient.patch<CapturaCampo>(`/documentos/capturas/${capturaId}/corregir-campo/`, {
    campo_id: campoId,
    valor_corregido: valorCorregido,
  });
  return response.data;
};

/**
 * Genera un comprobante comercial estrictamente en BORRADOR desde la captura.
 */
export const generarBorradorDesdeCaptura = async (
  capturaId: number,
  almacenId?: number
): Promise<GenerarBorradorResponse> => {
  const response = await apiClient.post<GenerarBorradorResponse>(
    `/documentos/capturas/${capturaId}/generar-borrador/`,
    { almacen_id: almacenId }
  );
  return response.data;
};

/**
 * Lista las equivalencias de productos del catálogo de homologación.
 */
export const obtenerEquivalencias = async (
  terceroId?: number,
  codigoExterno?: string,
  activa?: boolean
): Promise<ProductoEquivalencia[]> => {
  const params: Record<string, string> = {};
  if (terceroId) params.tercero_id = String(terceroId);
  if (codigoExterno) params.codigo_externo = codigoExterno;
  if (activa !== undefined) params.activa = String(activa);

  const response = await apiClient.get<ProductoEquivalencia[]>('/inventario/equivalencias/', { params });
  return response.data;
};

/**
 * Registra y confirma una nueva equivalencia de producto.
 */
export const crearEquivalencia = async (
  data: Partial<ProductoEquivalencia>
): Promise<ProductoEquivalencia> => {
  const response = await apiClient.post<ProductoEquivalencia>('/inventario/equivalencias/', data);
  return response.data;
};

/**
 * Actualiza una equivalencia existente.
 */
export const actualizarEquivalencia = async (
  id: number,
  data: Partial<ProductoEquivalencia>
): Promise<ProductoEquivalencia> => {
  const response = await apiClient.patch<ProductoEquivalencia>(`/inventario/equivalencias/${id}/`, data);
  return response.data;
};

/**
 * Sugiere una equivalencia automática para un proveedor y código/descripción externa.
 */
export const sugerirEquivalencia = async (
  terceroId: number,
  codigoExterno?: string,
  descripcion?: string
): Promise<SugerirEquivalenciaResponse> => {
  const params: Record<string, string> = { tercero_id: String(terceroId) };
  if (codigoExterno) params.codigo_externo = codigoExterno;
  if (descripcion) params.descripcion = descripcion;

  const response = await apiClient.get<SugerirEquivalenciaResponse>('/inventario/equivalencias/sugerir/', {
    params,
  });
  return response.data;
};
