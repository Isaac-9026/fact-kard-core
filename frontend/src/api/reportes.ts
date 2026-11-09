import apiClient from './http';
import { parametrosKardex } from '../utils/kardexFiltros';
import type { MetaPaginacion, ParamsPaginacion } from '../utils/paginacion';

export interface KardexFila {
  id: number;
  fecha: string;
  documento_referencia: string;
  tipo_operacion_codigo: string;
  tipo_operacion_descripcion: string;
  naturaleza: 'ENTRADA' | 'SALIDA' | 'AJUSTE_VALOR';
  almacen_codigo: string;
  almacen_nombre: string;
  producto_id: number;
  producto_codigo: string;
  producto_descripcion: string;
  entrada_cantidad: string | null;
  entrada_costo_unitario: string | null;
  entrada_valor: string | null;
  salida_cantidad: string | null;
  salida_costo_unitario: string | null;
  salida_valor: string | null;
  saldo_cantidad: string | null;
  cpp: string | null;
  saldo_valor: string | null;
  prioridad_dia: number;
  secuencia: number;
  es_extorno: boolean;
  generado_por_motor: boolean;
  creado_en: string;
}

export interface KardexResumen {
  total_entradas_cantidad: string;
  total_entradas_valor: string;
  total_salidas_cantidad: string;
  total_salidas_valor: string;
  saldo_inicial_cantidad?: string;
  saldo_inicial_valor?: string;
  saldo_final_cantidad: string;
  cpp_final: string | null;
  saldo_final_valor: string;
  total_registros: number;
  // CON-014: EMPRESA = saldo contable real; ALMACEN = stock del almacén × CPP global.
  ambito_saldo?: 'EMPRESA' | 'ALMACEN';
}

export interface KardexFiltros {
  producto_id?: number | string;
  periodo_id?: number | string;
  almacen_id?: number | string;
  tipo_operacion_id?: number | string;
  fecha_desde?: string;
  fecha_hasta?: string;
}

export interface KardexReporteResponse {
  empresa_id: number;
  filtros: KardexFiltros;
  resumen: KardexResumen;
  saldos_iniciales?: { producto_id: number; producto_codigo: string; cantidad: string; cpp: string | null; valor: string }[];
  movimientos: KardexFila[];
  /** Bloque 7: presente cuando se pide una página; `resumen` sigue siendo del rango completo. */
  paginacion?: MetaPaginacion;
}

/**
 * Consulta oficial del Kardex Valorizado bajo el orden cronológico del motor.
 */
export const obtenerKardexValorizado = async (
  filtros?: KardexFiltros,
  paginacion?: ParamsPaginacion
): Promise<KardexReporteResponse> => {
  const cleanParams = { ...parametrosKardex(filtros), ...(paginacion ?? {}) };
  const response = await apiClient.get<KardexReporteResponse>('/reportes/kardex/', {
    params: cleanParams,
  });
  return response.data;
};

/**
 * Descarga del libro de Kardex en formato Excel (.xlsx) con 4 hojas oficiales.
 */
export const exportarKardexExcel = async (
  filtros?: KardexFiltros
): Promise<void> => {
  const cleanParams = parametrosKardex(filtros);

  const response = await apiClient.get('/reportes/kardex/excel/', {
    params: cleanParams,
    responseType: 'blob',
  });

  const blob = new Blob([response.data], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  });
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  const timestamp = new Date().toISOString().replace(/[-:T.]/g, '').slice(0, 14);
  a.download = `kardex_valorizado_${timestamp}.xlsx`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  window.URL.revokeObjectURL(url);
};
