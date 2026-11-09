import apiClient from './http';

export type EstadoMaestro = 'ACTIVO' | 'INACTIVO';
export type FiltroTercero = 'cliente' | 'proveedor';

export interface TipoExistencia {
  codigo: string;
  descripcion: string;
}

export interface UnidadMedida {
  codigo: string;
  descripcion: string;
}

export interface UnidadBaseResumen {
  id: number;
  codigo: string;
  descripcion: string;
  factor_a_base: string;
}

export interface Producto {
  id: number;
  empresa: number;
  codigo_interno: string;
  descripcion: string;
  tipo_existencia_codigo: string;
  tipo_existencia_descripcion: string;
  estado: EstadoMaestro;
  unidad_base: UnidadBaseResumen | null;
  /** Bloque 16: sugerencias comerciales (no intervienen en costo, CPP ni Kardex). */
  precio_venta_sugerido?: string | null;
  afectacion_igv_defecto?: 'GRAVADO' | 'EXONERADO' | 'INAFECTO' | 'EXPORTACION' | 'GRATUITO' | null;
}

export interface ProductoPayload {
  codigo_interno: string;
  descripcion: string;
  tipo_existencia_codigo: string;
  estado?: EstadoMaestro;
  unidad_base_codigo?: string;
  precio_venta_sugerido?: string | null;
  afectacion_igv_defecto?: string | null;
}

export interface ProductoUnidad {
  id: number;
  producto: number;
  unidad_codigo: string;
  unidad_descripcion: string;
  factor_a_base: string;
  es_base: boolean;
}

export interface ProductoUnidadPayload {
  unidad_codigo: string;
  factor_a_base: string;
  es_base: boolean;
}

export interface Tercero {
  id: number;
  empresa: number;
  tipo_documento: string;
  numero_documento: string;
  razon_social: string;
  nombre_comercial: string | null;
  direccion: string | null;
  telefono: string | null;
  correo: string | null;
  es_cliente: boolean;
  es_proveedor: boolean;
  estado: EstadoMaestro;
  creado_en: string;
  actualizado_en: string;
}

export interface TerceroPayload {
  tipo_documento: string;
  numero_documento: string;
  razon_social: string;
  nombre_comercial?: string;
  direccion?: string;
  telefono?: string;
  correo?: string;
  es_cliente: boolean;
  es_proveedor: boolean;
  estado?: EstadoMaestro;
}

export interface Almacen {
  id: number;
  empresa: number;
  establecimiento: number;
  establecimiento_codigo: string;
  establecimiento_nombre: string;
  codigo: string;
  nombre: string;
  activo: boolean;
}

export interface AlmacenPayload {
  establecimiento: number;
  codigo: string;
  nombre: string;
  activo: boolean;
}

export const getProductos = async (): Promise<Producto[]> =>
  (await apiClient.get<Producto[]>('/inventario/productos/')).data;

export const createProducto = async (payload: ProductoPayload): Promise<Producto> =>
  (await apiClient.post<Producto>('/inventario/productos/', payload)).data;

export const updateProducto = async (
  id: number,
  payload: Partial<ProductoPayload>,
): Promise<Producto> =>
  (await apiClient.patch<Producto>(`/inventario/productos/${id}/`, payload)).data;

export const getProductoUnidades = async (productoId: number): Promise<ProductoUnidad[]> =>
  (await apiClient.get<ProductoUnidad[]>(`/inventario/productos/${productoId}/unidades/`)).data;

export const createProductoUnidad = async (
  productoId: number,
  payload: ProductoUnidadPayload,
): Promise<ProductoUnidad> =>
  (await apiClient.post<ProductoUnidad>(`/inventario/productos/${productoId}/unidades/`, payload)).data;

export const updateProductoUnidad = async (
  productoId: number,
  unidadId: number,
  payload: Partial<ProductoUnidadPayload>,
): Promise<ProductoUnidad> =>
  (await apiClient.patch<ProductoUnidad>(
    `/inventario/productos/${productoId}/unidades/${unidadId}/`,
    payload,
  )).data;

export const getTerceros = async (filters?: {
  tipo?: FiltroTercero;
  search?: string;
}): Promise<Tercero[]> =>
  (await apiClient.get<Tercero[]>('/inventario/terceros/', { params: filters })).data;

export const createTercero = async (payload: TerceroPayload): Promise<Tercero> =>
  (await apiClient.post<Tercero>('/inventario/terceros/', payload)).data;

export const updateTercero = async (
  id: number,
  payload: Partial<TerceroPayload>,
): Promise<Tercero> =>
  (await apiClient.patch<Tercero>(`/inventario/terceros/${id}/`, payload)).data;

export const getAlmacenes = async (): Promise<Almacen[]> =>
  (await apiClient.get<Almacen[]>('/inventario/almacenes/')).data;

export const createAlmacen = async (payload: AlmacenPayload): Promise<Almacen> =>
  (await apiClient.post<Almacen>('/inventario/almacenes/', payload)).data;

export const updateAlmacen = async (
  id: number,
  payload: Partial<AlmacenPayload>,
): Promise<Almacen> =>
  (await apiClient.patch<Almacen>(`/inventario/almacenes/${id}/`, payload)).data;

export const getTiposExistencia = async (): Promise<TipoExistencia[]> =>
  (await apiClient.get<TipoExistencia[]>('/inventario/catalogos/tipos-existencia/')).data;

export const getUnidadesMedida = async (): Promise<UnidadMedida[]> =>
  (await apiClient.get<UnidadMedida[]>('/inventario/catalogos/unidades-medida/')).data;
