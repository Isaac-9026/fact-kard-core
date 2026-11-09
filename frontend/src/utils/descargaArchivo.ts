/**
 * Bloque 13 — descarga de archivos binarios (Excel del Formato 13.1).
 *
 * Problema: si la API respondía con error, axios entregaba el cuerpo como Blob (la petición
 * es `responseType: 'blob'`); el mensaje se armaba con Object.values(blob) → '' y la pantalla
 * no mostraba nada: el botón "no hacía nada". Además la URL del Blob se liberaba en el mismo
 * instante del click, lo que en algunos navegadores cancela la descarga.
 *
 * Aquí: nombre de archivo seguro, descarga con liberación diferida y mensajes de error
 * legibles leyendo el Blob de error (sin interpretar nunca el XLSX como JSON).
 */
export const TIPO_XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet';
export const MENSAJE_ERROR_FORMATO131 = 'No se pudo exportar el Formato 13.1.';

/** Tiempo antes de liberar la URL del Blob: el navegador ya tomó el archivo. */
export const ESPERA_LIBERAR_MS = 60_000;

/** Solo letras, números, guion, punto y guion bajo; sin rutas; longitud acotada. */
export const nombreSeguro = (texto: string, maximo = 80): string =>
  texto
    .normalize('NFD').replace(/[̀-ͯ]/g, '')
    .replace(/[^A-Za-z0-9._-]+/g, '_')
    .replace(/_+/g, '_')
    .replace(/^[_.]+|[_.]+$/g, '')
    .slice(0, maximo) || 'archivo';

/** `Formato_13_1_2026-01_20999000003.xlsx` (mismo nombre que envía el backend). */
export const nombreArchivoFormato131 = ({ periodo, ruc }: { periodo: string; ruc?: string | null }): string =>
  `${nombreSeguro(['Formato_13_1', periodo, ruc].filter(Boolean).join('_'))}.xlsx`;

/** Un XLSX es un ZIP: empieza con "PK". Evita descargar como .xlsx una página HTML o un JSON. */
export const esXlsx = async (blob: Blob): Promise<boolean> => {
  if (!blob || blob.size < 4) return false;
  const cabecera = new Uint8Array(await blob.slice(0, 2).arrayBuffer());
  return cabecera[0] === 0x50 && cabecera[1] === 0x4b;
};

export interface EntornoDescarga {
  document: Pick<Document, 'createElement' | 'body'>;
  URL: Pick<typeof URL, 'createObjectURL' | 'revokeObjectURL'>;
  setTimeout: (fn: () => void, ms: number) => unknown;
}

/** Inicia la descarga del Blob con el nombre dado. La URL se libera después, no en el mismo click. */
export const descargarBlob = (blob: Blob, nombre: string, entorno: EntornoDescarga = globalThis as unknown as EntornoDescarga): void => {
  const url = entorno.URL.createObjectURL(blob);
  const enlace = entorno.document.createElement('a');
  enlace.href = url;
  enlace.download = nombre;
  enlace.rel = 'noopener';
  enlace.style.display = 'none';
  entorno.document.body.appendChild(enlace);
  enlace.click();
  enlace.remove();
  entorno.setTimeout(() => entorno.URL.revokeObjectURL(url), ESPERA_LIBERAR_MS);
};

const textoDeDetalle = (data: unknown): string => {
  if (!data || typeof data !== 'object') return '';
  const valores = Object.values(data as Record<string, unknown>).flat();
  return valores.filter((v) => typeof v === 'string' || typeof v === 'number').map(String).join(' ').trim();
};

/**
 * Mensaje para el usuario cuando la exportación falla: "No se pudo exportar el Formato 13.1."
 * + el detalle que envía la API (si el cuerpo es JSON), o el código HTTP. Nunca trazas internas.
 */
export const mensajeErrorExportacion = async (error: unknown, base = MENSAJE_ERROR_FORMATO131): Promise<string> => {
  const respuesta = (error as { response?: { status?: number; data?: unknown } } | null)?.response;
  if (!respuesta) {
    const propio = error instanceof ErrorExportacion ? error.message : '';
    return propio ? `${base} ${propio}` : `${base} No se pudo contactar al servidor.`;
  }
  const data = respuesta.data;
  let detalle: string;
  if (data instanceof Blob) {
    // El error llega como Blob (la petición pidió binario): se lee como texto y solo se usa
    // si es JSON de la API; el HTML de un 502/500 no se muestra (puede traer trazas).
    const texto = await data.text().catch(() => '');
    try {
      detalle = textoDeDetalle(JSON.parse(texto));
    } catch {
      detalle = '';
    }
  } else {
    detalle = textoDeDetalle(data);
  }
  if (detalle) return `${base} ${detalle}`;
  return respuesta.status ? `${base} El servidor respondió con el código ${respuesta.status}.` : base;
};

/** Error de validación de la descarga (respuesta que no es un XLSX). */
export class ErrorExportacion extends Error {}

// ---- Formato 13.1 ------------------------------------------------------------------------

export const URL_EXCEL_FORMATO131 = '/reportes/formato-13-1/excel/';

export interface FiltrosExcelFormato131 { periodo_id: number | string; establecimiento_id?: number | string; producto_id?: number | string }

/** Parámetros que se envían (sin filtros vacíos). */
export const paramsFormato131 = (f: FiltrosExcelFormato131) => ({
  periodo_id: f.periodo_id,
  ...(f.establecimiento_id ? { establecimiento_id: f.establecimiento_id } : {}),
  ...(f.producto_id ? { producto_id: f.producto_id } : {}),
});

type GetBinario = (url: string, config: { params: Record<string, unknown>; responseType: 'blob' }) => Promise<{ data: Blob }>;

/**
 * Pide el Excel como binario (`responseType: 'blob'`, nunca como JSON), verifica que sea un
 * XLSX y lo descarga con el nombre dado. Los errores de la API los traduce `mensajeErrorExportacion`.
 */
export const exportarExcelFormato131 = async (
  get: GetBinario, filtros: FiltrosExcelFormato131, nombre: string, entorno?: EntornoDescarga,
): Promise<void> => {
  const { data } = await get(URL_EXCEL_FORMATO131, { params: paramsFormato131(filtros), responseType: 'blob' });
  if (!(data instanceof Blob) || !(await esXlsx(data))) {
    throw new ErrorExportacion('La respuesta del servidor no es un archivo Excel válido.');
  }
  descargarBlob(data.type === TIPO_XLSX ? data : new Blob([data], { type: TIPO_XLSX }), nombre, entorno);
};
