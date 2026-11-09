import apiClient from './http';
import { leerPaginado, type Paginado, type ParamsPaginacion } from '../utils/paginacion';

export type ClaseDocumento = 'COMPRA' | 'VENTA';
export type EstadoDocumental = 'BORRADOR' | 'CONFIRMADO' | 'ANULADO';
export type EstadoRevision = 'PENDIENTE' | 'EN_REVISION' | 'REVISADO' | 'OBSERVADO';

export interface DocumentoDetalle {
  id: number;
  linea: number;
  producto: number | null;
  producto_codigo?: string;
  producto_descripcion?: string;
  producto_unidad: number | null;
  unidad_codigo?: string;
  almacen: number;
  almacen_codigo?: string;
  almacen_nombre?: string;
  tipo_operacion: number;
  tipo_operacion_codigo?: string;
  tipo_operacion_descripcion?: string;
  afecta_kardex_aplicado: boolean;
  equivalencia: number | null;
  descripcion_original?: string | null;
  cantidad_original: string;
  factor_conversion: string;
  cantidad_base: string;
  precio_unitario: string;
  igv: string;
  afectacion_igv?: string | null;
  codigo_afectacion_igv?: string | null;
  porcentaje_credito_fiscal_aplicado: string;
  costo_unitario_pen: string | null;
  es_bonificacion: boolean;
  detalle_origen: number | null;
  tipo_operacion_naturaleza?: string | null;
  /** QA-001: cantidad base ya devuelta por notas confirmadas y la que queda por devolver. */
  cantidad_devuelta?: string;
  cantidad_disponible_devolucion?: string;
}

export interface Documento {
  id: number;
  empresa_id: number;
  clase: ClaseDocumento;
  periodo: number;
  periodo_orden?: number;
  tercero: number | null;
  tercero_razon_social?: string;
  tercero_tipo_documento?: string | null;
  tercero_numero_documento?: string | null;
  ruc_emisor: string;
  tipo_comprobante: number;
  tipo_comprobante_codigo?: string;
  tipo_comprobante_descripcion?: string;
  es_nota?: boolean;
  serie: string | null;
  serie_normalizada: string;
  numero: string | null;
  numero_normalizado: string;
  fecha_emision: string;
  moneda_codigo: string;
  tipo_cambio: number | null;
  fecha_tc: string | null;
  monto_tc: string | null;
  fuente_tc: string | null;
  subtotal: string;
  igv: string;
  total: string;
  documento_origen: number | null;
  documento_origen_comprobante?: string | null;
  origen_captura: string;
  estado: EstadoDocumental;
  estado_revision: EstadoRevision;
  revisado_por?: number | null;
  revisado_por_username?: string | null;
  revisado_en?: string | null;
  creado_por?: number | null;
  creado_por_username?: string | null;
  confirmado_por?: number | null;
  confirmado_por_username?: string | null;
  confirmado_en?: string | null;
  detalles_count?: number;
  detalles?: DocumentoDetalle[];
  /** Bloque 16 */
  condicion_pago?: CondicionPago;
  fecha_vencimiento?: string | null;
  serie_comprobante?: number | null;
  cuotas?: Cuota[];
  pagos?: Pago[];
  finanzas?: ResumenFinanciero | null;
  /** Bloque 17A: motivo tributario de la nota (catálogo 09/10). */
  motivo_nota_codigo?: string | null;
  motivo_nota_descripcion?: string | null;
  emision_electronica_resumen?: {
    estado: CodigoEstadoElectronico;
    ambiente: 'BETA' | 'PRODUCCION';
    codigo_sunat: string | null;
    pdf_disponible: boolean;
  } | null;
}

export type CondicionPago = 'CONTADO' | 'CREDITO';
export type EstadoFinanciero = 'PENDIENTE' | 'PARCIAL' | 'PAGADO' | 'VENCIDO';

export interface Cuota { id?: number; numero?: number; fecha_vencimiento: string; monto: string }

export interface Pago {
  id: number;
  documento: number;
  fecha: string;
  monto: string;
  moneda_codigo: string;
  metodo_pago: string;
  metodo_pago_descripcion?: string;
  referencia: string | null;
  estado: 'VIGENTE' | 'ANULADO';
  motivo_anulacion: string | null;
  registrado_por_username?: string | null;
  registrado_en: string;
  anulado_por_username?: string | null;
  anulado_en?: string | null;
}

export interface ResumenFinanciero {
  total: string;
  total_notas_credito: string;
  total_notas_debito: string;
  total_ajustado: string;
  pagado: string;
  saldo_pendiente: string;
  monto_vencido: string;
  estado_financiero: EstadoFinanciero | null;
}

export interface CrearDocumentoDetallePayload {
  producto?: number | null;
  producto_unidad?: number | null;
  almacen: number;
  tipo_operacion: number;
  cantidad_original: string | number;
  precio_unitario?: string | number;
  igv?: string | number;
  afectacion_igv?: 'GRAVADO' | 'EXONERADO' | 'INAFECTO' | 'EXPORTACION' | 'GRATUITO';
  /** B17A-QA-001: código del Catálogo 07 (en líneas gratuitas: 11-16, 21, 31-36). */
  codigo_afectacion_igv?: string | null;
  es_bonificacion?: boolean;
  descripcion_original?: string;
  detalle_origen?: number | null;
  equivalencia?: number | null;
}

export interface CrearDocumentoPayload {
  clase: ClaseDocumento;
  periodo: number;
  tercero?: number | null;
  ruc_emisor?: string;
  tipo_comprobante: number;
  /** Sin serie_comprobante: serie y número del comprobante (compras, ventas sin serie configurada). */
  serie?: string;
  numero?: string;
  /** Bloque 16: con serie_comprobante el número lo asigna el backend. */
  serie_comprobante?: number | null;
  condicion_pago?: CondicionPago;
  fecha_vencimiento?: string | null;
  cuotas?: { fecha_vencimiento: string; monto: string }[];
  /** Bloque 17A: código del motivo de la nota (catálogo 09 en NC, 10 en ND). */
  motivo_nota?: string | null;
  fecha_emision: string;
  moneda_codigo: string;
  documento_origen?: number | null;
  origen_captura?: string;
  detalles: CrearDocumentoDetallePayload[];
}

export interface DocumentoFiltros {
  clase?: ClaseDocumento;
  periodo?: number;
  estado?: EstadoDocumental;
  estado_revision?: EstadoRevision;
  search?: string;
  /** true = solo notas de crédito/débito; false = sin notas. */
  es_nota?: boolean;
}

export const obtenerDocumentos = async (filtros?: DocumentoFiltros): Promise<Documento[]> => {
  const { data } = await apiClient.get<Documento[]>('/documentos/', { params: filtros });
  return data;
};

/** Bloque 7 — una página de documentos con los filtros aplicados en el servidor. */
export const obtenerDocumentosPaginados = async (
  filtros: DocumentoFiltros,
  paginacion: ParamsPaginacion,
): Promise<Paginado<Documento>> => {
  const params: Record<string, string | number> = { ...paginacion };
  Object.entries(filtros).forEach(([clave, valor]) => {
    if (valor !== undefined && valor !== null && String(valor).trim() !== '') params[clave] = typeof valor === 'string' ? valor.trim() : valor;
  });
  const { data } = await apiClient.get<Paginado<Documento> | Documento[]>('/documentos/', { params });
  return leerPaginado(data);
};

export const obtenerDocumento = async (id: number): Promise<Documento> => {
  const { data } = await apiClient.get<Documento>(`/documentos/${id}/`);
  return data;
};

export const crearDocumento = async (payload: CrearDocumentoPayload): Promise<Documento> => {
  const { data } = await apiClient.post<Documento>('/documentos/', payload);
  return data;
};

export const eliminarDocumento = async (id: number): Promise<void> => {
  await apiClient.delete(`/documentos/${id}/`);
};

export const revisarDocumento = async (
  id: number,
  estado_revision: EstadoRevision,
  motivo?: string
): Promise<Documento> => {
  const { data } = await apiClient.post<Documento>(`/documentos/${id}/revisar/`, {
    estado_revision,
    motivo,
  });
  return data;
};

export const confirmarDocumento = async (id: number): Promise<Documento> => {
  const { data } = await apiClient.post<Documento>(`/documentos/${id}/confirmar/`);
  return data;
};

export const anularDocumento = async (id: number, motivo: string): Promise<Documento> => {
  const { data } = await apiClient.post<Documento>(`/documentos/${id}/anular/`, { motivo });
  return data;
};

// ---- Bloque 17A: preparación tributaria (sin XML, firma ni envío) ----------------------------

export type EstadoPreparacion = 'LISTO_PARA_EMISION' | 'NO_PREPARADO';
export interface ValidacionElectronica {
  documento_id: number;
  tipo_comprobante: string;
  listo: boolean;
  estado: EstadoPreparacion;
  errores: string[];
  advertencias: string[];
  // Bloque 18 (estado electrónico separado del contable; nada se envía todavía)
  identidad_sunat?: string | null;
  identidad_error?: string | null;
  estado_electronico?: EstadoElectronico;
  preparacion?: {
    ambiente?: 'BETA' | 'PRODUCCION' | null;  // Bloque 21: ambiente del servidor (solo lectura)
    servidor: NivelPreparacion;
    empresa: NivelPreparacion;
    documento: { listo: boolean };
  };
}
export type CodigoEstadoElectronico =
  | 'NO_PREPARADO' | 'PREPARADO' | 'XML_GENERADO' | 'FIRMADO' | 'PENDIENTE_ENVIO' | 'ENVIADO'
  | 'ACEPTADO' | 'ACEPTADO_CON_OBSERVACIONES' | 'RECHAZADO' | 'DADO_DE_BAJA' | 'ERROR';
export interface EstadoElectronico {
  estado: CodigoEstadoElectronico;
  etiqueta: string;
  registrado: boolean;
  preparado_en: string | null;
  ambiente: 'BETA' | 'PRODUCCION' | null;
  // Bloque 19: XML UBL 2.1 SIN firma. firmado / enviado_sunat siempre false hasta los bloques 20+.
  xml_generado?: boolean;
  nombre_xml?: string | null;
  hash_xml?: string | null;
  firmado?: boolean;
  enviado_sunat?: boolean;
  // Bloque 20: XML firmado (XMLDSig) — nunca rutas ni datos del certificado privado.
  nombre_xml_firmado?: string | null;
  firmado_en?: string | null;
  // Bloque 21: envío sendBill y CDR (nunca credenciales, sobre SOAP ni rutas).
  envio_incierto?: boolean;
  envio_en_curso?: boolean;
  ultimo_error_envio?: string | null;
  respuesta_sunat?: {
    codigo: string | null; descripcion: string | null; observaciones: { codigo: string; descripcion: string }[];
    fecha_envio: string | null; fecha_respuesta: string | null;
  } | null;
  cdr_disponible?: boolean;
  nombre_cdr?: string | null;
  zip_disponible?: boolean;
  nombre_zip?: string | null;
  pdf_disponible?: boolean;
  nombre_pdf?: string | null;
  pdf_generado_en?: string | null;
}
export interface NivelPreparacion { listo: boolean; errores?: string[]; advertencias?: string[] }

export const obtenerValidacionElectronica = async (id: number): Promise<ValidacionElectronica> =>
  (await apiClient.get<ValidacionElectronica>(`/documentos/${id}/validacion-electronica/`)).data;

/** Bloque 18: registra el estado electrónico PREPARADO (solo ADMIN). No genera XML ni envía a SUNAT. */
export const prepararEmisionElectronica = async (id: number): Promise<{ documento_id: number; identidad_sunat: string; estado_electronico: EstadoElectronico; ya_estaba_preparado: boolean }> =>
  (await apiClient.post(`/documentos/${id}/emision-electronica/preparar/`)).data;

/** Bloque 19: resultado de generar el XML (nunca incluye rutas del servidor). */
export interface ResultadoGeneracionXml {
  documento_id: number;
  estado: CodigoEstadoElectronico;
  identidad_sunat: string;
  nombre_xml: string;
  hash_xml: string;
  algoritmo_hash: string;
  firmado: false;
  enviado_sunat: false;
  validaciones: string[];
  generado_ahora: boolean;
}

/** Bloque 19: genera el XML UBL 2.1 SIN firma (solo ADMIN, estado PREPARADO). No firma ni envía a SUNAT. */
export const generarXmlElectronico = async (id: number): Promise<ResultadoGeneracionXml> =>
  (await apiClient.post<ResultadoGeneracionXml>(`/documentos/${id}/emision-electronica/generar-xml/`)).data;

/** Bloque 19: descarga el XML SIN firma ya generado (binario; el nombre lo da el estado electrónico). */
export const descargarXmlElectronico = async (id: number): Promise<Blob> =>
  (await apiClient.get<Blob>(`/documentos/${id}/emision-electronica/xml/`, { responseType: 'blob' })).data;

/** Bloque 20: resultado de firmar el XML (sin rutas, contraseña, clave privada ni certificado completo). */
export interface ResultadoFirmaXml {
  documento_id: number;
  estado: CodigoEstadoElectronico;
  identidad_sunat: string;
  nombre_xml_sin_firma: string;
  nombre_xml_firmado: string | null;
  hash_xml: string;
  hash_xml_firmado: string | null;
  firmado: boolean;
  firmado_en: string | null;
  enviado_sunat: false;
  firmado_ahora: boolean;
  certificado: { huella_sha256: string | null; vigente?: boolean; valido_hasta?: string; titular?: string };
  advertencias: string[];
}

/** Bloque 20: firma el XML ya generado (solo ADMIN, estado XML_GENERADO). No envía a SUNAT. */
export const firmarXmlElectronico = async (id: number): Promise<ResultadoFirmaXml> =>
  (await apiClient.post<ResultadoFirmaXml>(`/documentos/${id}/emision-electronica/firmar/`)).data;

/** Bloque 20: descarga el XML FIRMADO (binario). */
export const descargarXmlFirmado = async (id: number): Promise<Blob> =>
  (await apiClient.get<Blob>(`/documentos/${id}/emision-electronica/xml-firmado/`, { responseType: 'blob' })).data;

/** Bloque 21: pide al backend enviar el comprobante FIRMADO a SUNAT. Solo el id: el backend arma ZIP, SOAP y receptor. */
export const enviarSunat = async (id: number, reintentarIncierto = false): Promise<Record<string, unknown>> =>
  (await apiClient.post(`/documentos/${id}/emision-electronica/enviar-sunat/`,
    reintentarIncierto ? { reintentar_incierto: true } : {})).data;

/** Bloque 21: descarga el CDR (ZIP de SUNAT). */
export const descargarCdr = async (id: number): Promise<Blob> =>
  (await apiClient.get<Blob>(`/documentos/${id}/emision-electronica/cdr/`, { responseType: 'blob' })).data;

export const generarPdfElectronico = async (id: number): Promise<Record<string, unknown>> =>
  (await apiClient.post(`/documentos/${id}/emision-electronica/generar-pdf/`)).data;

export const descargarPdfElectronico = async (id: number): Promise<Blob> =>
  (await apiClient.get<Blob>(`/documentos/${id}/emision-electronica/pdf/`, { responseType: 'blob' })).data;

export const descargarZipElectronico = async (id: number): Promise<Blob> =>
  (await apiClient.get<Blob>(`/documentos/${id}/emision-electronica/zip/`, { responseType: 'blob' })).data;

export const cambiarMotivoNota = async (id: number, motivo_nota: string): Promise<Documento> =>
  (await apiClient.put<Documento>(`/documentos/${id}/motivo-nota/`, { motivo_nota })).data;

/** B17A-QA-001: registra el código del Catálogo 07 de una línea gratuita ya guardada. */
export const cambiarCodigoAfectacion = async (documentoId: number, detalleId: number, codigo: string): Promise<Documento> =>
  (await apiClient.put<Documento>(`/documentos/${documentoId}/detalles/${detalleId}/codigo-afectacion/`, {
    codigo_afectacion_igv: codigo,
  })).data;
