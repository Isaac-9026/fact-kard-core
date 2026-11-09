/**
 * Bloque 12 — operación de inventario de cada línea en el formulario de comprobantes.
 *
 * Antes la línea tomaba `tiposOperacion[0]`: el catálogo viene ordenado alfabéticamente y
 * el primero es AJUSTE_INGRESO, así que COMPRA y VENTA quedaban con un ajuste interno, el
 * selector ofrecía las 23 operaciones y al cambiar COMPRA ↔ VENTA la línea no se corregía.
 *
 * Reglas (solo filtran lo que la UI ofrece; el backend sigue siendo quien valida):
 * - Operación comercial = no interna y con origen DOCUMENTO o MOV_ORIGEN (propiedades del
 *   catálogo). Quedan fuera ajustes, mermas, transferencias, saldo inicial, motor y extornos.
 * - Movimiento físico en factura/boleta → origen DOCUMENTO; en una nota → MOV_ORIGEN
 *   (devoluciones: necesitan la línea del comprobante de origen).
 * - Compatibilidad clase × comprobante × naturaleza = matriz del backend
 *   (backend/apps/documentos/reglas.py, `_regla_linea`).
 * - Operación por defecto buscada por `codigo_interno`, nunca por posición en el catálogo.
 */
export type ClaseComprobante = 'COMPRA' | 'VENTA';
type Naturaleza = 'ENTRADA' | 'SALIDA' | 'AJUSTE_VALOR';
type Efecto = 'NINGUNO' | 'CREDITO' | 'DEBITO';

export interface OperacionCatalogo {
  id: number;
  codigo_interno: string;
  naturaleza: Naturaleza;
  es_interna: boolean;
  afecta_kardex: boolean;
  origen_requerido: string;
  activo: boolean;
}

export interface ComprobanteCatalogo {
  es_nota: boolean;
  efecto_nota: Efecto;
}

const ORIGENES_COMERCIALES = ['DOCUMENTO', 'MOV_ORIGEN'];

// Copia de backend/apps/documentos/reglas.py::_regla_linea ('sin_kardex' = solo si no afecta Kardex).
const REGLAS: Record<string, Partial<Record<Naturaleza, 'siempre' | 'sin_kardex'>>> = {
  'COMPRA:NINGUNO': { ENTRADA: 'siempre' },
  'VENTA:NINGUNO': { SALIDA: 'siempre' },
  'COMPRA:CREDITO': { SALIDA: 'siempre', AJUSTE_VALOR: 'siempre' },
  'COMPRA:DEBITO': { AJUSTE_VALOR: 'siempre' },
  'VENTA:CREDITO': { ENTRADA: 'siempre', AJUSTE_VALOR: 'sin_kardex' },
  'VENTA:DEBITO': { AJUSTE_VALOR: 'sin_kardex' },
};

// Operación que se propone primero en cada caso (si existe y es compatible).
const PREFERIDA: Record<string, string> = {
  'COMPRA:NINGUNO': 'COMPRA',
  'VENTA:NINGUNO': 'VENTA',
  'COMPRA:CREDITO': 'DEVOLUCION_COMPRA',
  'COMPRA:DEBITO': 'ND_CARGO_COMPRA',
  'VENTA:CREDITO': 'DEVOLUCION_VENTA',
  'VENTA:DEBITO': 'ND_CARGO_VENTA',
};

/** Sin comprobante elegido todavía se asume factura/boleta (no nota). */
function efectoDe(comprobante?: ComprobanteCatalogo | null): Efecto | null {
  if (!comprobante || !comprobante.es_nota) return 'NINGUNO';
  return comprobante.efecto_nota === 'CREDITO' || comprobante.efecto_nota === 'DEBITO' ? comprobante.efecto_nota : null;
}

export function esOperacionComercial(op: OperacionCatalogo): boolean {
  return op.activo !== false && !op.es_interna && ORIGENES_COMERCIALES.includes(op.origen_requerido);
}

export function esOperacionCompatible(
  op: OperacionCatalogo, clase: ClaseComprobante, comprobante?: ComprobanteCatalogo | null,
): boolean {
  if (!esOperacionComercial(op)) return false;
  const efecto = efectoDe(comprobante);
  if (efecto === null) return false;
  // Movimiento físico: en factura/boleta es la operación del documento (origen DOCUMENTO);
  // en una nota es siempre una devolución (origen MOV_ORIGEN, el backend exige detalle_origen).
  const fisica = op.naturaleza === 'ENTRADA' || op.naturaleza === 'SALIDA';
  if (fisica && (efecto === 'NINGUNO') !== (op.origen_requerido === 'DOCUMENTO')) return false;
  const condicion = REGLAS[`${clase}:${efecto}`]?.[op.naturaleza];
  return condicion === 'siempre' || (condicion === 'sin_kardex' && !op.afecta_kardex);
}

/** Opciones del selector: la operación preferida primero y el resto por código. */
export function operacionesPermitidas<T extends OperacionCatalogo>(
  tipos: readonly T[], clase: ClaseComprobante, comprobante?: ComprobanteCatalogo | null,
): T[] {
  const preferida = PREFERIDA[`${clase}:${efectoDe(comprobante)}`];
  return tipos
    .filter((op) => esOperacionCompatible(op, clase, comprobante))
    .sort((a, b) => {
      if (a.codigo_interno === preferida) return -1;
      if (b.codigo_interno === preferida) return 1;
      return a.codigo_interno.localeCompare(b.codigo_interno);
    });
}

export function operacionPorDefecto(
  tipos: readonly OperacionCatalogo[], clase: ClaseComprobante, comprobante?: ComprobanteCatalogo | null,
): number | '' {
  return operacionesPermitidas(tipos, clase, comprobante)[0]?.id ?? '';
}

type ConOperacion = { tipoOperacionId: number | '' };

function buscar(tipos: readonly OperacionCatalogo[], id: number | '' | string): OperacionCatalogo | undefined {
  return tipos.find((t) => String(t.id) === String(id));
}

/**
 * Al cambiar la clase o el comprobante: cada línea con una operación incompatible pasa a la
 * operación por defecto (COMPRA → VENTA y viceversa); las compatibles se conservan.
 */
export function reconciliarOperaciones<L extends ConOperacion>(
  lineas: readonly L[], tipos: readonly OperacionCatalogo[], clase: ClaseComprobante, comprobante?: ComprobanteCatalogo | null,
): L[] {
  const porDefecto = operacionPorDefecto(tipos, clase, comprobante);
  return lineas.map((l) => {
    const actual = buscar(tipos, l.tipoOperacionId);
    return actual && esOperacionCompatible(actual, clase, comprobante) ? l : { ...l, tipoOperacionId: porDefecto };
  });
}

/** Validación previa al envío (el backend vuelve a validar). Devuelve el primer error o null. */
export function errorDeOperaciones(
  lineas: readonly ConOperacion[], tipos: readonly OperacionCatalogo[], clase: ClaseComprobante, comprobante?: ComprobanteCatalogo | null,
): string | null {
  for (let i = 0; i < lineas.length; i++) {
    const op = buscar(tipos, lineas[i].tipoOperacionId);
    if (!op) return `Línea ${i + 1}: Debe seleccionar un tipo de operación.`;
    if (!esOperacionCompatible(op, clase, comprobante)) {
      const documento = comprobante?.es_nota ? `esta nota de ${clase.toLowerCase()}` : `un comprobante de ${clase.toLowerCase()}`;
      return `Línea ${i + 1}: la operación ${op.codigo_interno} no corresponde a ${documento}.`;
    }
  }
  return null;
}
