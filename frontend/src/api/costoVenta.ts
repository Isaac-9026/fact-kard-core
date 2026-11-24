import apiClient from './http';
import {
  paramsCostoVenta, paramsCostoVentaAnual, type FiltrosCostoVenta, type FiltrosCostoVentaAnual,
} from '../utils/costoVenta';

/** Unidades / costo unitario / total de un concepto (cantidad y P.U. son null en los totales de la empresa). */
export interface BloqueCosto { cantidad: string | null; costo_unitario: string | null; valor: string }

export type ClaveCompra = 'compras' | 'bonificaciones' | 'devoluciones' | 'notas_credito_debito';
/** Salidas atribuibles a ventas. */
export type ClaveDesglose = 'ventas' | 'devoluciones_venta';
/** Salidas del inventario que no son ventas (se concilian aparte). */
export type ClaveConciliacion = 'mermas_desmedros' | 'consumo_retiros' | 'ajustes' | 'transferencias' | 'otros';

/** Comparación con el promedio ponderado (del mes o único del rango). */
export interface ComparacionCosto { saldo_final: BloqueCosto; mermas: BloqueCosto; costo_venta: BloqueCosto }

export interface FilaCostoVenta {
  producto: { id: number; codigo: string; descripcion: string; unidad: string | null; tipo_existencia: string | null };
  saldo_inicial: BloqueCosto;
  compras: BloqueCosto;
  disponible: BloqueCosto;
  /** Saldo final valorizado según el Kardex (promedio móvil). */
  saldo_final: BloqueCosto;
  /** Saldo inicial + Compras − Saldo final. */
  salidas: BloqueCosto;
  conciliacion: Record<ClaveConciliacion, BloqueCosto>;
  no_atribuibles: BloqueCosto;
  mermas: BloqueCosto;
  /** Resultado principal: salidas − salidas que no son ventas (según el Kardex). */
  costo_venta: BloqueCosto;
  costo_promedio: string | null;
  compras_detalle: Record<ClaveCompra, BloqueCosto>;
  desglose: Record<ClaveDesglose, BloqueCosto>;
  diferencia: string;
  comparacion: ComparacionCosto & { metodo: string; costo_unitario: string | null };
  /** Comparación − Kardex. */
  diferencia_metodo: string;
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
  metodo: string;
  metodo_comparacion: string;
  totales: {
    saldo_inicial: BloqueCosto;
    compras: BloqueCosto;
    disponible: BloqueCosto;
    saldo_final: BloqueCosto;
    salidas: BloqueCosto;
    conciliacion: Record<ClaveConciliacion, string>;
    no_atribuibles: BloqueCosto;
    mermas: BloqueCosto;
    costo_venta: BloqueCosto;
    compras_detalle: Record<ClaveCompra, string>;
    desglose: Record<ClaveDesglose, string>;
    diferencia: string;
    comparacion: ComparacionCosto;
    diferencia_metodo: string;
  };
  productos: FilaCostoVenta[];
}

export const URL_COSTO_VENTA = '/reportes/costo-ventas/';

export const obtenerCostoVenta = async (filtros: FiltrosCostoVenta): Promise<CostoVentaResponse> =>
  (await apiClient.get<CostoVentaResponse>(URL_COSTO_VENTA, { params: paramsCostoVenta(filtros) })).data;

/** Kardex → Costo de Venta «Por año»: una fila por mes (cada mes con su promedio) y la suma del año. */
export interface MesCostoVenta {
  periodo: PeriodoCostoVenta;
  saldo_inicial: string;
  compras: string;
  saldo_final: string;
  no_atribuibles: string;
  /** Costo de venta según el Kardex (resultado principal). */
  costo_venta: string;
  /** Comparación: promedio ponderado del mes. */
  costo_venta_promedio: string;
  /** Promedio − Kardex. */
  diferencia_metodo: string;
}

export interface CostoVentaAnualResponse {
  empresa: { ruc: string; razon_social: string };
  anio: number;
  producto_id: number | null;
  moneda: 'PEN';
  formula: string;
  metodo: string;
  metodo_comparacion: string;
  meses: MesCostoVenta[];
  total: Omit<MesCostoVenta, 'periodo'>;
}

export const URL_COSTO_VENTA_ANUAL = '/reportes/costo-ventas/anual/';

export const obtenerCostoVentaAnual = async (filtros: FiltrosCostoVentaAnual): Promise<CostoVentaAnualResponse> =>
  (await apiClient.get<CostoVentaAnualResponse>(URL_COSTO_VENTA_ANUAL, { params: paramsCostoVentaAnual(filtros) })).data;
