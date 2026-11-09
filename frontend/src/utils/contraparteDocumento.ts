/**
 * QA-004 — contraparte de un comprobante: el proveedor en una compra y el cliente en una venta.
 *
 * `ruc_emisor` es el emisor del comprobante: en una COMPRA coincide con el proveedor, pero en
 * una VENTA es la propia empresa. Antes la lista mostraba "RUC: {ruc_emisor}" debajo del cliente,
 * con lo que en FV01-1 aparecía el RUC de la empresa en vez del del cliente.
 */
export interface DocumentoConTercero {
  clase: string;
  ruc_emisor?: string | null;
  tercero?: number | null;
  tercero_razon_social?: string | null;
  tercero_tipo_documento?: string | null;
  tercero_numero_documento?: string | null;
}

export interface Contraparte {
  rol: 'Proveedor' | 'Cliente';
  /** Etiqueta del documento de identidad (RUC, DNI, …). */
  etiquetaDocumento: string;
  documento: string;
  nombre: string;
}

const ETIQUETA_TIPO_DOCUMENTO: Record<string, string> = {
  '6': 'RUC', '1': 'DNI', '4': 'C.E.', '7': 'Pasaporte', '0': 'Doc.', 'A': 'Céd. dipl.',
};

export const etiquetaTipoDocumento = (tipo?: string | null): string =>
  (tipo && ETIQUETA_TIPO_DOCUMENTO[tipo]) || 'Doc.';

export function contraparteDocumento(doc: DocumentoConTercero): Contraparte {
  const esVenta = doc.clase === 'VENTA';
  const numero = (doc.tercero_numero_documento ?? '').trim();
  if (numero) {
    return {
      rol: esVenta ? 'Cliente' : 'Proveedor',
      etiquetaDocumento: etiquetaTipoDocumento(doc.tercero_tipo_documento),
      documento: numero,
      nombre: doc.tercero_razon_social || '—',
    };
  }
  if (esVenta) {
    // Venta sin cliente identificado: nunca se muestra el RUC de la empresa como si fuera el del cliente.
    return { rol: 'Cliente', etiquetaDocumento: 'Doc.', documento: '—', nombre: doc.tercero_razon_social || 'CLIENTES VARIOS' };
  }
  // Compra: el emisor del comprobante es el proveedor.
  return { rol: 'Proveedor', etiquetaDocumento: 'RUC', documento: doc.ruc_emisor || '—', nombre: doc.tercero_razon_social || doc.ruc_emisor || '—' };
}
