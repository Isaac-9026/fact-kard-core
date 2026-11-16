import apiClient from './http';
import { paramsCostoVenta, type FiltrosCostoVenta } from '../utils/costoVenta';

/** Unidades / costo unitario / total de un concepto (cantidad y P.U. son null en los totales de la empresa). */
export interface BloqueCosto { cantidad: string | null; costo_unitario: string | null; valor: string }

export type ClaveCompra = 'compras' | 'bonificaciones' | 'devoluciones' | 'notas_credito_debito';
export type ClaveDesglose =
  | 'ventas' | 'devoluciones_venta' | 'mermas_desmedros' | 'consumo_retiros' | 'ajustes' | 'transferencias' | 'otros';

export interface FilaCostoVenta {
  producto: { id: number; codigo: string; descripcion: string; unidad: string | null; tipo_existencia: string | null };
  saldo_inicial: BloqueCosto;
  compras: BloqueCosto;
  saldo_final: BloqueCosto;
  costo_venta: BloqueCosto;
  compras_detalle: Record<ClaveCompra, BloqueCosto>;
  desglose: Record<ClaveDesglose, BloqueCosto>;
  diferencia: string;
}

export interface PeriodoCostoVenta { id: number; anio: number; mes: number; estado: string; etiqueta: string }

export interface CostoVentaResponse {
  empresa: { ruc: string; razon_social: string };
  periodo_desde: PeriodoCostoVenta;
  periodo_hasta: PeriodoCostoVenta;
  fecha_inicio: string;
  fecha_fin: string;
  moneda: 'PEN';
  formula: string;
  totales: {
    saldo_inicial: BloqueCosto;
    compras: BloqueCosto;
    saldo_final: BloqueCosto;
    costo_venta: BloqueCosto;
    compras_detalle: Record<ClaveCompra, string>;
    desglose: Record<ClaveDesglose, string>;
    diferencia: string;
  };
  productos: FilaCostoVenta[];
}

export const URL_COSTO_VENTA = '/reportes/costo-ventas/';

export const obtenerCostoVenta = async (filtros: FiltrosCostoVenta): Promise<CostoVentaResponse> =>
  (await apiClient.get<CostoVentaResponse>(URL_COSTO_VENTA, { params: paramsCostoVenta(filtros) })).data;

export const descargarCostoVentaExcel = async (filtros: FiltrosCostoVenta): Promise<Blob> =>
  (await apiClient.get<Blob>(`${URL_COSTO_VENTA}excel/`, { params: paramsCostoVenta(filtros), responseType: 'blob' })).data;
