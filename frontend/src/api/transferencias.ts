import apiClient from './http';

export type EstadoTransferencia = 'BORRADOR' | 'CONFIRMADO' | 'ANULADO';

export interface TransferenciaDetalle {
  id: number;
  producto: number;
  producto_codigo: string;
  producto_descripcion: string;
  cantidad_base: string;
}

export interface Transferencia {
  id: number;
  empresa: number;
  almacen_origen: number;
  almacen_origen_nombre: string;
  almacen_destino: number;
  almacen_destino_nombre: string;
  fecha: string;
  estado: EstadoTransferencia;
  creado_por: number | null;
  numero_lineas: number;
  detalles: TransferenciaDetalle[];
}

export interface TransferenciaPayload {
  almacen_origen: number;
  almacen_destino: number;
  fecha: string;
  detalles: Array<{ producto: number; cantidad_base: string }>;
}

export const getTransferencias = async (): Promise<Transferencia[]> =>
  (await apiClient.get<Transferencia[]>('/inventario/transferencias/')).data;

export const createTransferencia = async (payload: TransferenciaPayload): Promise<Transferencia> =>
  (await apiClient.post<Transferencia>('/inventario/transferencias/', payload)).data;

export const confirmarTransferencia = async (id: number): Promise<Transferencia> =>
  (await apiClient.post<Transferencia>(`/inventario/transferencias/${id}/confirmar/`)).data;
