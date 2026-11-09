/**
 * Bloque 14 — reglas de archivo de la captura (mismas que valida el backend en
 * `apps/documentos/uploads.py`). Se muestran en pantalla y se verifican antes de subir para
 * dar un mensaje claro; el backend sigue siendo quien decide (extensión, MIME y contenido).
 */
export type TipoCaptura = 'XML' | 'PDF' | 'IMAGEN' | 'ESCANER';

export const TIPOS_CAPTURA: readonly TipoCaptura[] = ['XML', 'PDF', 'IMAGEN', 'ESCANER'];

/** Igual que `CAPTURA_MAX_BYTES` del backend (Nginx corta en 12 MB). */
export const CAPTURA_MAX_MB = 10;
export const CAPTURA_MAX_BYTES = CAPTURA_MAX_MB * 1024 * 1024;

export const EXTENSIONES_CAPTURA: Record<TipoCaptura, readonly string[]> = {
  XML: ['.xml'],
  PDF: ['.pdf'],
  IMAGEN: ['.jpg', '.jpeg', '.png'],
  ESCANER: ['.pdf', '.jpg', '.jpeg', '.png', '.tif', '.tiff'],
};

export const DESCRIPCION_TIPO_CAPTURA: Record<TipoCaptura, { titulo: string; texto: string }> = {
  XML: {
    titulo: 'XML UBL 2.1',
    texto: 'Comprobante electrónico en XML UBL 2.1 (factura, boleta, nota de crédito o débito). Los datos se leen directamente del XML.',
  },
  PDF: {
    titulo: 'PDF',
    texto: 'PDF del comprobante. Si no tiene texto seleccionable, pegue abajo el texto obtenido con un programa de OCR y revise cada campo.',
  },
  IMAGEN: {
    titulo: 'Imagen',
    texto: 'Foto o captura del comprobante (JPG o PNG). Pegue abajo el texto reconocido por OCR y revise cada campo.',
  },
  ESCANER: {
    titulo: 'Escáner',
    texto: 'Comprobante en papel digitalizado con su escáner. Escanéelo con el programa del escáner, guárdelo como PDF, JPG, PNG o TIFF y súbalo aquí. El sistema no controla el escáner.',
  },
};

const extension = (nombre: string): string => {
  const base = nombre.split(/[\\/]/).pop() ?? '';
  const i = base.lastIndexOf('.');
  return i > 0 ? base.slice(i).toLowerCase() : '';
};

/** Lista para el atributo `accept` del input de archivo. */
export const acceptCaptura = (tipo: TipoCaptura): string => EXTENSIONES_CAPTURA[tipo].join(',');

/** Texto visible: ".pdf, .jpg, .jpeg, .png, .tif, .tiff · máx. 10 MB". */
export const formatosVisibles = (tipo: TipoCaptura): string =>
  `${EXTENSIONES_CAPTURA[tipo].join(', ')} · máx. ${CAPTURA_MAX_MB} MB`;

/**
 * Tipo sugerido según la extensión. Si el tipo actual ya admite el archivo se mantiene
 * (un PDF elegido con ESCANER sigue siendo ESCANER).
 */
export const tipoSugerido = (nombre: string, actual: TipoCaptura): TipoCaptura => {
  const ext = extension(nombre);
  if (EXTENSIONES_CAPTURA[actual].includes(ext)) return actual;
  if (ext === '.xml') return 'XML';
  if (ext === '.pdf') return 'PDF';
  if (['.jpg', '.jpeg', '.png'].includes(ext)) return 'IMAGEN';
  if (['.tif', '.tiff'].includes(ext)) return 'ESCANER';
  return actual;
};

/** Mensaje de error si el archivo no cumple las reglas visibles; `null` si puede enviarse. */
export const validarArchivoCaptura = (archivo: { name: string; size: number }, tipo: TipoCaptura): string | null => {
  const ext = extension(archivo.name);
  const permitidas = EXTENSIONES_CAPTURA[tipo];
  if (!ext || !permitidas.includes(ext)) {
    return `El archivo "${archivo.name}" no es válido para ${DESCRIPCION_TIPO_CAPTURA[tipo].titulo}. Formatos permitidos: ${permitidas.join(', ')}.`;
  }
  if (archivo.size <= 0) return 'El archivo está vacío.';
  if (archivo.size > CAPTURA_MAX_BYTES) {
    return `El archivo supera el tamaño máximo permitido (${CAPTURA_MAX_MB} MB).`;
  }
  return null;
};

/** Pasos del flujo, en el orden en que se recorren en pantalla. */
export const PASOS_CAPTURA = [
  'Archivo',
  'Extracción',
  'Vista previa',
  'Validación',
  'Homologación',
  'Crear comprobante',
] as const;

/**
 * Paso en el que está la captura seleccionada (índice de PASOS_CAPTURA): sin captura → Archivo;
 * subida y sin comprobante → Validación (revisar, corregir y homologar); con borrador → Crear
 * comprobante (falta confirmarlo en Comprobantes: nada se registra solo).
 */
export const pasoActualCaptura = (c: { documento_id?: number | null } | null): number => {
  if (!c) return 0;
  return c.documento_id ? 5 : 3;
};
