/**
 * Bloque 17C — consulta de datos fiscales por RUC. Siempre pasa por el backend
 * (GET /api/consulta-ruc/<ruc>/): React nunca llama a proveedores externos ni envía credenciales.
 */
import apiClient from './http';

export interface DatosRuc {
  ruc: string;
  razon_social: string;
  nombre_comercial: string | null;
  direccion: string | null;
  ubigeo: string | null;
  departamento: string | null;
  provincia: string | null;
  distrito: string | null;
  estado: string | null;
  condicion: string | null;
}

export interface ResultadoConsultaRuc {
  datos: DatosRuc;
  advertencias: string[];
  proveedor: string;
  oficial: boolean;
  /** Bloque 17D: p. ej. "Padrón Reducido SUNAT" (copia local, no consulta en línea). */
  fuente: string | null;
  /** Fecha (YYYY-MM-DD) del padrón consultado, si se conoce. */
  actualizado_al: string | null;
  desde_cache: boolean;
  consultado_en: string;
}

/** Bloque 17D — estado de la fuente de consulta RUC (solo metadatos, solo ADMIN). */
export interface EstadoConsultaRuc {
  proveedor: string | null;
  configurado: boolean;
  oficial: boolean;
  fuente: string | null;
  disponible: boolean;
  registros: number | null;
  version: number | null;
  fecha_padron: string | null;
  fecha_importacion: string | null;
}

export const consultarRuc = async (ruc: string): Promise<ResultadoConsultaRuc> =>
  (await apiClient.get<ResultadoConsultaRuc>(`/consulta-ruc/${encodeURIComponent(ruc)}/`)).data;

export const obtenerEstadoConsultaRuc = async (): Promise<EstadoConsultaRuc> =>
  (await apiClient.get<EstadoConsultaRuc>('/configuracion/consulta-ruc/estado/')).data;
