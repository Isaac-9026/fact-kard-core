import apiClient from './http';
import {
  paramsCostoVenta, paramsCostoVentaAnual, type FiltrosCostoVenta, type FiltrosCostoVentaAnual,
} from '../utils/costoVenta';

/** Unidades / costo unitario / total de un concepto (cantidad y P.U. son null en los totales de la empresa). */
export interface BloqueCosto { cantidad: string | null; costo_unitario: string | null; valor: string }

export type ClaveCompra = 'compras' | 'bonificaciones' | 'devoluciones' | 'notas_credito_debito';
export type ClaveDesglose =
  | 'ventas' | 'devoluciones_venta' | 'mermas_desmedros' | 'consumo_retiros' | 'ajustes' | 'transferencias' | 'otros';

export interface FilaCostoVenta {
  producto: { id: number; codigo: string; descripcion: string; unidad: string | null; tipo_existencia: string | null };
  saldo_inicial: BloqueCosto;
  compras: BloqueCosto;
  /** Subtotal (S.I. + Compras) con el P.U. promedio del período. */
  disponible: BloqueCosto;
  saldo_final: BloqueCosto;
  /** Mermas y desmedros al P.U. promedio: no son costo de venta, se restan aparte (solo si hubo). */
  mermas: BloqueCosto;
  costo_venta: BloqueCosto;
  costo_promedio: string | null;
  compras_detalle: Record<ClaveCompra, BloqueCosto>;
  desglose: Record<ClaveDesglose, BloqueCosto>;
  diferencia: string;
  /** Referencia: lo que da el Kardex (promedio móvil). */
  kardex: { saldo_final: BloqueCosto; costo_venta: BloqueCosto };
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
  totales: {
    saldo_inicial: BloqueCosto;
    compras: BloqueCosto;
    disponible: BloqueCosto;
    saldo_final: BloqueCosto;
    mermas: BloqueCosto;
    costo_venta: BloqueCosto;
    compras_detalle: Record<ClaveCompra, string>;
    desglose: Record<ClaveDesglose, string>;
    diferencia: string;
    kardex: { saldo_final: BloqueCosto; costo_venta: BloqueCosto };
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
  disponible: string;
  saldo_final: string;
  mermas: string;
  costo_venta: string;
  costo_venta_kardex: string;
  diferencia_metodo: string;
}

export interface CostoVentaAnualResponse {
  empresa: { ruc: string; razon_social: string };
  anio: number;
  producto_id: number | null;
  moneda: 'PEN';
  formula: string;
  metodo: string;
  meses: MesCostoVenta[];
  total: Omit<MesCostoVenta, 'periodo' | 'disponible'> & { disponible?: string };
}

export const URL_COSTO_VENTA_ANUAL = '/reportes/costo-ventas/anual/';

export const obtenerCostoVentaAnual = async (filtros: FiltrosCostoVentaAnual): Promise<CostoVentaAnualResponse> =>
  (await apiClient.get<CostoVentaAnualResponse>(URL_COSTO_VENTA_ANUAL, { params: paramsCostoVentaAnual(filtros) })).data;
