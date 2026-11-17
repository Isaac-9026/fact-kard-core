import apiClient from './http';
import type { Periodo } from './periodos';

export interface SustentoPdfCierreInfo {
  tiene_pdf: boolean;
  nombre_archivo: string;
  sha256: string;
  referencia?: string;
}

export interface CierreDetalle { id:number; producto:number; producto_codigo:string; producto_descripcion:string; establecimiento:number; establecimiento_nombre:string; saldo_cantidad:string; saldo_valor_pen:string; cpp_pen:string }
export interface CierrePeriodo { id:number; periodo:number; periodo_info:{anio:number;mes:number;estado:string}; version_calculo:number; cerrado_por:number; cerrado_por_username:string; cerrado_en:string; archivo_excel:string|null; sustento_pdf?:SustentoPdfCierreInfo|null; hash_resultado:string; snapshot_resumen:Record<string,string|number>; vigente:boolean; detalles:CierreDetalle[] }
export interface DiferenciaCierre { producto_id:number; establecimiento_id:number; version_anterior:{saldo_cantidad:string;saldo_valor_pen:string;cpp_pen:string}; version_nueva:{saldo_cantidad:string;saldo_valor_pen:string;cpp_pen:string}; diferencia:{cantidad:string;valor_pen:string;cpp_pen:string} }

export const obtenerCierres = async (): Promise<CierrePeriodo[]> => (await apiClient.get('/empresas/cierres/')).data;
export const ejecutarCierre = async (periodoId:number): Promise<{mensaje:string;periodo:Periodo;cierre:CierrePeriodo;advertencias:string[]}> => (await apiClient.post(`/empresas/periodos/${periodoId}/cerrar/`)).data;
export const compararCierres = async (periodoId:number, versionA?:number, versionB?:number): Promise<{periodo_id:number;version_a:number|null;version_b:number|null;versiones:CierrePeriodo[];comparacion_ultimas_versiones:DiferenciaCierre[]}> => (await apiClient.get(`/empresas/periodos/${periodoId}/comparar-cierres/`,{params:versionA&&versionB?{version_a:versionA,version_b:versionB}:undefined})).data;

export const subirSustentoPdfCierre = async (
  cierreId: number,
  archivo: File,
  referencia?: string,
): Promise<CierrePeriodo> => {
  const formData = new FormData();
  formData.append('archivo', archivo);
  if (referencia) {
    formData.append('referencia', referencia);
  }
  return (
    await apiClient.post<CierrePeriodo>(
      `/empresas/cierres/${cierreId}/sustento-pdf/`,
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } }
    )
  ).data;
};

export const descargarSustentoPdfCierre = async (
  cierreId: number,
  nombreArchivo = 'sustento_cierre.pdf',
): Promise<void> => {
  const response = await apiClient.get(
    `/empresas/cierres/${cierreId}/sustento-pdf/`,
    { responseType: 'blob' }
  );
  const blob = new Blob([response.data], { type: 'application/pdf' });
  const url = window.URL.createObjectURL(blob);
  const enlace = document.createElement('a');
  enlace.href = url;
  enlace.download = nombreArchivo;
  document.body.appendChild(enlace);
  enlace.click();
  enlace.remove();
  window.URL.revokeObjectURL(url);
};
