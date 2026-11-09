import apiClient from './http';
import { leerPaginado, type Paginado, type ParamsPaginacion } from '../utils/paginacion';

export interface Incidencia { id: number; tipo: string; severidad: string; descripcion: string; bloquea_cierre: boolean; estado: 'PENDIENTE' | 'RESUELTA' | 'DESCARTADA'; detectado_en: string }
export interface RecalculoDetalle { movimiento_id: number; cpp_anterior: string | null; cpp_nuevo: string | null; valor_anterior: string | null; valor_nuevo: string | null; saldo_anterior: string | null; saldo_nuevo: string | null }
export interface Recalculo { id: number; producto: number; fecha_desde: string; fecha_hasta: string | null; version: number; estado: string; ejecutado_en: string; detalles: RecalculoDetalle[] }

export const obtenerIncidencias = async (): Promise<Incidencia[]> => (await apiClient.get('/kardex/incidencias/')).data;
export const resolverIncidencia = async (id: number, estado: 'RESUELTA' | 'DESCARTADA'): Promise<Incidencia> => (await apiClient.patch(`/kardex/incidencias/${id}/`, { estado })).data;
export const obtenerRecalculos = async (): Promise<Recalculo[]> => (await apiClient.get('/kardex/recalculos/')).data;

// Bloque 7 — listados paginados en el servidor (`?page=&page_size=`).
export const obtenerIncidenciasPaginadas = async (paginacion: ParamsPaginacion): Promise<Paginado<Incidencia>> =>
  leerPaginado((await apiClient.get<Paginado<Incidencia> | Incidencia[]>('/kardex/incidencias/', { params: paginacion })).data);
export const obtenerRecalculosPaginados = async (paginacion: ParamsPaginacion): Promise<Paginado<Recalculo>> =>
  leerPaginado((await apiClient.get<Paginado<Recalculo> | Recalculo[]>('/kardex/recalculos/', { params: paginacion })).data);
export const ejecutarRecalculo = async (producto: number, fecha_desde: string): Promise<Recalculo> => (await apiClient.post('/kardex/recalculos/', { producto, fecha_desde })).data;

// Navegación por flujo — vista "Inventario": saldos vigentes que mantiene el motor Kardex
// (SaldoCppActual por producto y StockAlmacen por almacén). Solo lectura.
export interface SaldoCppActualApi { producto_id: number; cantidad_total: number | string; valor_total_pen: number | string; cpp_pen: number | string | null; actualizado_en: string }
export interface StockAlmacenApi { producto_id: number; almacen_id: number; cantidad_actual: number | string }
export interface SaldosActualesResponse { saldos_cpp: SaldoCppActualApi[]; stocks_almacen: StockAlmacenApi[] }
export const obtenerSaldosActuales = async (): Promise<SaldosActualesResponse> => (await apiClient.get('/kardex/saldos-actuales/')).data;
