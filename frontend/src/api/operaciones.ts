import apiClient from './http';

export type EstadoSaldoInicial = 'BORRADOR' | 'CONFIRMADO';
export type EstadoNotaInterna = 'BORRADOR' | 'CONFIRMADO' | 'ANULADO';

export interface SaldoInicial {
  id: number;
  empresa: number;
  periodo: number;
  periodo_descripcion: string;
  almacen: number;
  almacen_codigo: string;
  almacen_nombre: string;
  producto: number;
  producto_codigo: string;
  producto_descripcion: string;
  unidad_base_codigo: string | null;
  cantidad: string;
  valor_pen: string;
  cpp_inicial: string;
  estado: EstadoSaldoInicial;
  creado_por: number | null;
}

export interface SaldoInicialPayload {
  periodo: number;
  almacen: number;
  producto: number;
  cantidad: string;
  valor_pen: string;
}

export interface SaldoInicialFiltros {
  periodo_id?: number;
  almacen_id?: number;
  producto_id?: number;
  estado?: EstadoSaldoInicial | 'ACTIVOS' | 'TODOS';
}

export interface NotaInternaDetalle {
  id: number;
  producto: number;
  producto_codigo: string;
  producto_descripcion: string;
  unidad_base_codigo: string | null;
  cantidad_base: string;
  costo_unitario_pen: string | null;
  valor_ajuste_pen: string | null;
}

export interface NotaInternaDetallePayload {
  producto: number;
  cantidad_base: string;
  costo_unitario_pen?: string | null;
  valor_ajuste_pen?: string | null;
}

export interface NotaInterna {
  id: number;
  empresa: number;
  almacen: number;
  almacen_codigo: string;
  almacen_nombre: string;
  periodo: number;
  periodo_descripcion: string;
  tipo_operacion: number;
  tipo_operacion_codigo: string;
  tipo_operacion_descripcion: string;
  fecha: string;
  motivo: string;
  responsable: string | null;
  observacion: string | null;
  archivo_sustento: string | null;
  estado: EstadoNotaInterna;
  creado_por: number | null;
  numero_lineas: number;
  detalles: NotaInternaDetalle[];
}

export interface NotaInternaPayload {
  almacen: number;
  periodo: number;
  tipo_operacion: number;
  fecha: string;
  motivo: string;
  responsable?: string | null;
  observacion?: string | null;
  archivo_sustento?: string | null;
  detalles: NotaInternaDetallePayload[];
}

export interface NotaInternaFiltros {
  periodo_id?: number;
  almacen_id?: number;
  tipo_operacion?: string;
  estado?: EstadoNotaInterna | 'ACTIVOS' | 'TODOS';
  search?: string;
}

export const getSaldosIniciales = async (
  filtros?: SaldoInicialFiltros,
): Promise<SaldoInicial[]> =>
  (await apiClient.get<SaldoInicial[]>('/inventario/saldos-iniciales/', { params: filtros })).data;

export const getSaldoInicial = async (id: number): Promise<SaldoInicial> =>
  (await apiClient.get<SaldoInicial>(`/inventario/saldos-iniciales/${id}/`)).data;

export const createSaldoInicial = async (
  payload: SaldoInicialPayload,
): Promise<SaldoInicial> =>
  (await apiClient.post<SaldoInicial>('/inventario/saldos-iniciales/', payload)).data;

export const updateSaldoInicial = async (
  id: number,
  payload: Partial<SaldoInicialPayload>,
): Promise<SaldoInicial> =>
  (await apiClient.patch<SaldoInicial>(`/inventario/saldos-iniciales/${id}/`, payload)).data;

export const confirmarSaldoInicial = async (id: number): Promise<SaldoInicial> =>
  (await apiClient.post<SaldoInicial>(`/inventario/saldos-iniciales/${id}/confirmar/`)).data;

export const eliminarSaldoInicialBorrador = async (id: number): Promise<void> => {
  await apiClient.delete(`/inventario/saldos-iniciales/${id}/`);
};

export const getNotasInternas = async (
  filtros?: NotaInternaFiltros,
): Promise<NotaInterna[]> =>
  (await apiClient.get<NotaInterna[]>('/inventario/notas-internas/', { params: filtros })).data;

export const getNotaInterna = async (id: number): Promise<NotaInterna> =>
  (await apiClient.get<NotaInterna>(`/inventario/notas-internas/${id}/`)).data;

export const createNotaInterna = async (
  payload: NotaInternaPayload,
): Promise<NotaInterna> =>
  (await apiClient.post<NotaInterna>('/inventario/notas-internas/', payload)).data;

export const updateNotaInterna = async (
  id: number,
  payload: Partial<NotaInternaPayload>,
): Promise<NotaInterna> =>
  (await apiClient.patch<NotaInterna>(`/inventario/notas-internas/${id}/`, payload)).data;

export const anularNotaInterna = async (
  id: number,
  payload?: { motivo?: string } | string,
): Promise<NotaInterna> => {
  const data = typeof payload === 'string' ? { motivo: payload } : (payload ?? {});
  return (await apiClient.post<NotaInterna>(`/inventario/notas-internas/${id}/anular/`, data)).data;
};

export const confirmarNotaInterna = async (id: number): Promise<NotaInterna> =>
  (await apiClient.post<NotaInterna>(`/inventario/notas-internas/${id}/confirmar/`)).data;

export const eliminarNotaInternaBorrador = async (id: number): Promise<void> => {
  await apiClient.delete(`/inventario/notas-internas/${id}/`);
};

export interface FilaDiagnosticoSaldoInicial {
  numero_fila: number;
  codigo_interno: string;
  descripcion_producto: string;
  cantidad: string;
  cpp_inicial: string;
  valor_pen: string;
  estado_fila: 'NUEVO' | 'ACTUALIZAR' | 'ERROR';
  observacion: string;
  producto_id?: number | null;
  saldo_existente_id?: number | null;
}

export interface ResumenImportacionSaldoInicial {
  total_filas: number;
  validas?: number;
  nuevos?: number;
  actualizables?: number;
  con_error?: number;
  creados?: number;
  actualizados?: number;
  confirmados_kardex?: number;
  omitidos_por_error?: number;
}

export interface ResultadoImportacionSaldosIniciales {
  modo: 'PREVISUALIZAR' | 'CONFIRMAR';
  periodo_id: number;
  periodo_codigo: string;
  almacen_id: number;
  almacen_nombre: string;
  resumen: ResumenImportacionSaldoInicial;
  filas: FilaDiagnosticoSaldoInicial[];
}

export const descargarPlantillaSaldosInicialesExcel = async (): Promise<Blob> => {
  const response = await apiClient.get('/inventario/saldos-iniciales/plantilla-excel/', {
    responseType: 'blob',
  });
  return response.data;
};

export const importarSaldosInicialesExcel = async (
  formData: FormData,
): Promise<ResultadoImportacionSaldosIniciales> => {
  const response = await apiClient.post<ResultadoImportacionSaldosIniciales>(
    '/inventario/saldos-iniciales/importar-excel/',
    formData,
    {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    },
  );
  return response.data;
};
