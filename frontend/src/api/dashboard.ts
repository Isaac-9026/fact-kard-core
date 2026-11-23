import apiClient from './http';

export interface PeriodoGrafico { id: number; anio: number; mes: number; estado: string; etiqueta: string }

export interface Kpi { actual: string; anterior: string | null; variacion_pct: string | null }

export interface PuntoMensual {
  periodo: PeriodoGrafico;
  ventas: string;
  costo_venta: string;
  margen: string;
  margen_pct: string | null;
  compras: string;
  comprobantes: number;
}

export interface ProductoVenta {
  producto: { id: number; codigo: string; descripcion: string };
  unidad: string | null;
  unidades: string | null;
  costo_unitario: string | null;
  ventas: string;
  costo_venta: string;
  margen: string;
  margen_pct: string | null;
}

export interface SectorParticipacion { nombre: string; ventas: string; porcentaje: string | null }

export interface ProductoInventario {
  producto: { id: number; codigo: string; descripcion: string };
  cantidad: string;
  valor: string;
  dias_stock: string | null;
}

export interface KpisDashboard {
  ventas: Kpi;
  costo_venta: Kpi;
  margen: Kpi;
  compras: Kpi;
  margen_pct: string | null;
  comprobantes: number;
}

export interface GraficosDashboardResponse {
  moneda: 'PEN';
  producto: { id: number; codigo: string; descripcion: string } | null;
  periodo: PeriodoGrafico | null;
  kpis: KpisDashboard | null;
  serie_mensual: PuntoMensual[];
  mejor_mes: { periodo: PeriodoGrafico; ventas: string } | null;
  productos: ProductoVenta[];
  participacion: SectorParticipacion[];
  inventario: { valor_total: string; productos_con_stock: number; top_productos: ProductoInventario[] };
}

export const obtenerGraficosDashboard = async (
  periodoId: number | null, meses = 6, productoId: number | null = null,
): Promise<GraficosDashboardResponse> =>
  (await apiClient.get<GraficosDashboardResponse>('/reportes/dashboard-graficos/', {
    params: { ...(periodoId ? { periodo_id: periodoId } : {}), meses, ...(productoId ? { producto_id: productoId } : {}) },
  })).data;
