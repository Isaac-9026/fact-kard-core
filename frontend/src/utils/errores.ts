/**
 * Bloque 7 — mensaje legible de un error de la API sin usar `any`.
 * Devuelve el primer campo con contenido de `response.data` (en el orden dado) o el texto
 * por defecto. Las listas de DRF (`{"archivo": ["..."]}`) se unen con espacios.
 */
export function mensajeDeError(err: unknown, campos: readonly string[], porDefecto: string): string {
  const data = (err as { response?: { data?: unknown } } | null | undefined)?.response?.data
  if (data && typeof data === 'object') {
    for (const campo of campos) {
      const valor = (data as Record<string, unknown>)[campo]
      if (Array.isArray(valor)) {
        if (valor.length > 0) return valor.map(String).join(' ')
      } else if (valor !== undefined && valor !== null && valor !== '' && valor !== false && valor !== 0) {
        return String(valor)
      }
    }
  }
  return porDefecto
}

/** Nombres legibles de los campos de la API de comprobantes (los demás se muestran tal cual). */
const ETIQUETAS_CAMPO: Record<string, string> = {
  clase: 'Clase',
  periodo: 'Período',
  tipo_comprobante: 'Tipo de comprobante',
  serie: 'Serie',
  numero: 'Número',
  fecha_emision: 'Fecha de emisión',
  tercero: 'Tercero',
  moneda_codigo: 'Moneda',
  documento_origen: 'Documento de origen',
  producto: 'Producto',
  producto_unidad: 'Unidad',
  almacen: 'Almacén',
  tipo_operacion: 'Operación',
  cantidad_original: 'Cantidad',
  precio_unitario: 'Precio unitario',
  igv: 'IGV',
  afectacion_igv: 'Afectación IGV',
  es_bonificacion: 'Bonificación',
  detalle_origen: 'Línea de origen',
  estado_revision: 'Estado de revisión',
  motivo: 'Motivo',
  stock: 'Stock',
  estado: 'Estado',
  // Captura XML / OCR y homologación (Bloque 14)
  archivo: 'Archivo',
  tipo: 'Tipo de captura',
  ruc_emisor: 'RUC emisor',
  ruc_cliente: 'RUC cliente',
  codigo_externo: 'Código externo',
  descripcion_externa: 'Descripción externa',
  unidad_externa_codigo: 'Unidad externa',
  factor_conversion: 'Factor de conversión',
  campo_id: 'Campo',
  valor_corregido: 'Valor corregido',
}

/** Claves de DRF que son mensajes generales: se muestran primero y sin prefijo. */
const CLAVES_GENERALES = ['detail', 'non_field_errors']

function aplanar(valor: unknown, prefijo: string, salida: string[]): void {
  if (valor === null || valor === undefined || valor === '') return
  if (typeof valor === 'string' || typeof valor === 'number' || typeof valor === 'boolean') {
    salida.push(prefijo ? `${prefijo}: ${String(valor)}` : String(valor))
    return
  }
  if (Array.isArray(valor)) {
    const sonLineas = valor.some((v) => v !== null && typeof v === 'object' && !Array.isArray(v))
    valor.forEach((v, i) => aplanar(v, sonLineas ? [prefijo, `Línea ${i + 1}`].filter(Boolean).join(' · ') : prefijo, salida))
    return
  }
  if (typeof valor === 'object') {
    const entradas = Object.entries(valor as Record<string, unknown>)
    entradas.sort(([a], [b]) => Number(CLAVES_GENERALES.includes(b)) - Number(CLAVES_GENERALES.includes(a)))
    for (const [clave, v] of entradas) {
      if (clave === 'detalles') {
        // Lista por línea ("Línea N · campo") o texto que ya nombra la línea: sin prefijo extra.
        aplanar(v, prefijo, salida)
      } else {
        const etiqueta = CLAVES_GENERALES.includes(clave) ? '' : (ETIQUETAS_CAMPO[clave] ?? clave)
        aplanar(v, [prefijo, etiqueta].filter(Boolean).join(' · '), salida)
      }
    }
  }
}

/**
 * Bloque 10 — TODOS los mensajes de un error de la API, uno por línea, para mostrarlos
 * dentro del formulario: primero los generales (`detail`, `non_field_errors`), luego los de
 * campos, y los del detalle con su número de línea ("Línea 2 · IGV: ..."). Sin duplicados.
 */
export function mensajesDeErrorApi(err: unknown, porDefecto: string): string[] {
  const data = (err as { response?: { data?: unknown } } | null | undefined)?.response?.data
  const salida: string[] = []
  if (data && typeof data === 'object') aplanar(data, '', salida)
  const unicos = [...new Set(salida)]
  return unicos.length > 0 ? unicos : [porDefecto]
}
