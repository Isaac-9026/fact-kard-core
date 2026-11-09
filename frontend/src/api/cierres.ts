import apiClient from './http';
import type { Periodo } from './periodos';

export interface CierreDetalle { id:number; producto:number; producto_codigo:string; producto_descripcion:string; establecimiento:number; establecimiento_nombre:string; saldo_cantidad:string; saldo_valor_pen:string; cpp_pen:string }
export interface CierrePeriodo { id:number; periodo:number; periodo_info:{anio:number;mes:number;estado:string}; version_calculo:number; cerrado_por:number; cerrado_por_username:string; cerrado_en:string; archivo_excel:string|null; hash_resultado:string; snapshot_resumen:Record<string,string|number>; vigente:boolean; detalles:CierreDetalle[] }
export interface DiferenciaCierre { producto_id:number; establecimiento_id:number; version_anterior:{saldo_cantidad:string;saldo_valor_pen:string;cpp_pen:string}; version_nueva:{saldo_cantidad:string;saldo_valor_pen:string;cpp_pen:string}; diferencia:{cantidad:string;valor_pen:string;cpp_pen:string} }

export const obtenerCierres = async (): Promise<CierrePeriodo[]> => (await apiClient.get('/empresas/cierres/')).data;
export const ejecutarCierre = async (periodoId:number): Promise<{mensaje:string;periodo:Periodo;cierre:CierrePeriodo;advertencias:string[]}> => (await apiClient.post(`/empresas/periodos/${periodoId}/cerrar/`)).data;
export const compararCierres = async (periodoId:number, versionA?:number, versionB?:number): Promise<{periodo_id:number;version_a:number|null;version_b:number|null;versiones:CierrePeriodo[];comparacion_ultimas_versiones:DiferenciaCierre[]}> => (await apiClient.get(`/empresas/periodos/${periodoId}/comparar-cierres/`,{params:versionA&&versionB?{version_a:versionA,version_b:versionB}:undefined})).data;
