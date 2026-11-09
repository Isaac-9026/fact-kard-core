import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  errorDeOperaciones, esOperacionComercial, operacionesPermitidas, operacionPorDefecto, reconciliarOperaciones,
  type OperacionCatalogo,
} from './operacionesComerciales.ts';

// Catálogo de seed_catalogos_sunat, en el orden alfabético en que lo entrega la API
// (AJUSTE_INGRESO primero: era la operación que quedaba por defecto).
const SEED: [string, OperacionCatalogo['naturaleza'], boolean, boolean, string][] = [
  ['AJUSTE_INGRESO', 'ENTRADA', true, true, 'NOTA_INTERNA'], ['AJUSTE_SALIDA', 'SALIDA', true, true, 'NOTA_INTERNA'],
  ['AJUSTE_VALOR_MANUAL', 'AJUSTE_VALOR', true, true, 'NOTA_INTERNA'], ['BONIFICACION', 'ENTRADA', false, true, 'DOCUMENTO'],
  ['COMPRA', 'ENTRADA', false, true, 'DOCUMENTO'], ['CONSUMO_INTERNO', 'SALIDA', true, true, 'NOTA_INTERNA'],
  ['DESMEDRO', 'SALIDA', true, true, 'NOTA_INTERNA'], ['DEVOLUCION_COMPRA', 'SALIDA', false, true, 'MOV_ORIGEN'],
  ['DEVOLUCION_VENTA', 'ENTRADA', false, true, 'MOV_ORIGEN'], ['EXTORNO_AJUSTE_VALOR', 'AJUSTE_VALOR', true, true, 'MOV_EXTORNADO'],
  ['EXTORNO_ENTRADA', 'ENTRADA', true, true, 'MOV_EXTORNADO'], ['EXTORNO_SALIDA', 'SALIDA', true, true, 'MOV_EXTORNADO'],
  ['MERMA', 'SALIDA', true, true, 'NOTA_INTERNA'], ['NC_DESCUENTO_COMPRA', 'AJUSTE_VALOR', false, true, 'DOCUMENTO'],
  ['NC_VENTA_SIN_DEVOLUCION', 'AJUSTE_VALOR', false, false, 'DOCUMENTO'], ['ND_CARGO_COMPRA', 'AJUSTE_VALOR', false, true, 'DOCUMENTO'],
  ['ND_CARGO_VENTA', 'AJUSTE_VALOR', false, false, 'DOCUMENTO'], ['RESIDUO_AUTOMATICO', 'AJUSTE_VALOR', true, true, 'MOTOR'],
  ['RETIRO', 'SALIDA', true, true, 'NOTA_INTERNA'], ['SALDO_INICIAL', 'ENTRADA', false, true, 'SALDO_INICIAL'],
  ['TRANSFERENCIA_ENTRADA', 'ENTRADA', true, true, 'TRANSFERENCIA'], ['TRANSFERENCIA_SALIDA', 'SALIDA', true, true, 'TRANSFERENCIA'],
  ['VENTA', 'SALIDA', false, true, 'DOCUMENTO'],
];
const TIPOS: OperacionCatalogo[] = SEED.map(([codigo_interno, naturaleza, es_interna, afecta_kardex, origen_requerido], i) => ({
  id: 15 + i, codigo_interno, naturaleza, es_interna, afecta_kardex, origen_requerido, activo: true,
}));
const id = (codigo: string) => TIPOS.find((t) => t.codigo_interno === codigo)!.id;
const codigos = (ops: OperacionCatalogo[]) => ops.map((o) => o.codigo_interno);
const FACTURA = { es_nota: false, efecto_nota: 'NINGUNO' as const };
const NC = { es_nota: true, efecto_nota: 'CREDITO' as const };
const ND = { es_nota: true, efecto_nota: 'DEBITO' as const };
const INTERNAS = ['AJUSTE_INGRESO', 'AJUSTE_SALIDA', 'AJUSTE_VALOR_MANUAL', 'SALDO_INICIAL', 'TRANSFERENCIA_ENTRADA', 'TRANSFERENCIA_SALIDA',
  'RESIDUO_AUTOMATICO', 'MERMA', 'DESMEDRO', 'CONSUMO_INTERNO', 'RETIRO', 'EXTORNO_ENTRADA', 'EXTORNO_SALIDA', 'EXTORNO_AJUSTE_VALOR'];

test('compra usa COMPRA y venta usa VENTA aunque AJUSTE_INGRESO sea el primero del catálogo', () => {
  assert.equal(TIPOS[0].codigo_interno, 'AJUSTE_INGRESO');
  assert.equal(operacionPorDefecto(TIPOS, 'COMPRA', FACTURA), id('COMPRA'));
  assert.equal(operacionPorDefecto(TIPOS, 'VENTA', FACTURA), id('VENTA'));
  assert.equal(operacionPorDefecto(TIPOS, 'COMPRA', null), id('COMPRA')); // aún sin comprobante elegido
  assert.equal(operacionPorDefecto(TIPOS, 'VENTA', undefined), id('VENTA'));
});

test('operaciones internas, de motor, transferencia y saldo inicial no aparecen en el selector comercial', () => {
  for (const c of INTERNAS) assert.equal(esOperacionComercial(TIPOS.find((t) => t.codigo_interno === c)!), false, c);
  for (const [clase, comp] of [['COMPRA', FACTURA], ['VENTA', FACTURA], ['COMPRA', NC], ['COMPRA', ND], ['VENTA', NC], ['VENTA', ND]] as const) {
    const visibles = codigos(operacionesPermitidas(TIPOS, clase, comp));
    for (const c of INTERNAS) assert.ok(!visibles.includes(c), `${clase} ${comp.efecto_nota}: ${c}`);
  }
});

test('opciones visibles por documento (matriz de backend/apps/documentos/reglas.py)', () => {
  assert.deepEqual(codigos(operacionesPermitidas(TIPOS, 'COMPRA', FACTURA)), ['COMPRA', 'BONIFICACION']);
  assert.deepEqual(codigos(operacionesPermitidas(TIPOS, 'VENTA', FACTURA)), ['VENTA']);
  assert.deepEqual(codigos(operacionesPermitidas(TIPOS, 'COMPRA', NC)), ['DEVOLUCION_COMPRA', 'NC_DESCUENTO_COMPRA', 'NC_VENTA_SIN_DEVOLUCION', 'ND_CARGO_COMPRA', 'ND_CARGO_VENTA']);
  assert.deepEqual(codigos(operacionesPermitidas(TIPOS, 'COMPRA', ND)), ['ND_CARGO_COMPRA', 'NC_DESCUENTO_COMPRA', 'NC_VENTA_SIN_DEVOLUCION', 'ND_CARGO_VENTA']);
  // En ventas el ajuste de valor solo si NO afecta Kardex.
  assert.deepEqual(codigos(operacionesPermitidas(TIPOS, 'VENTA', NC)), ['DEVOLUCION_VENTA', 'NC_VENTA_SIN_DEVOLUCION', 'ND_CARGO_VENTA']);
  assert.deepEqual(codigos(operacionesPermitidas(TIPOS, 'VENTA', ND)), ['ND_CARGO_VENTA', 'NC_VENTA_SIN_DEVOLUCION']);
  // Las devoluciones (MOV_ORIGEN) no se ofrecen en una factura.
  assert.ok(!codigos(operacionesPermitidas(TIPOS, 'COMPRA', FACTURA)).includes('DEVOLUCION_VENTA'));
});

test('compra → venta y venta → compra recalculan la operación de cada línea', () => {
  const lineas = [{ n: 1, tipoOperacionId: id('COMPRA') as number | '' }, { n: 2, tipoOperacionId: id('BONIFICACION') as number | '' }];
  const enVenta = reconciliarOperaciones(lineas, TIPOS, 'VENTA', FACTURA);
  assert.deepEqual(enVenta.map((l) => l.tipoOperacionId), [id('VENTA'), id('VENTA')]);
  assert.deepEqual(enVenta.map((l) => l.n), [1, 2]); // el resto de la línea se conserva
  const deVuelta = reconciliarOperaciones(enVenta, TIPOS, 'COMPRA', FACTURA);
  assert.deepEqual(deVuelta.map((l) => l.tipoOperacionId), [id('COMPRA'), id('COMPRA')]);
});

test('una operación compatible se conserva y un id de texto del <select> se reconoce', () => {
  const lineas = [{ tipoOperacionId: id('BONIFICACION') as number | '' }];
  assert.equal(reconciliarOperaciones(lineas, TIPOS, 'COMPRA', FACTURA)[0], lineas[0]);
  const texto = [{ tipoOperacionId: String(id('VENTA')) as unknown as number }];
  assert.equal(reconciliarOperaciones(texto, TIPOS, 'VENTA', FACTURA)[0], texto[0]);
});

test('una línea interna heredada (AJUSTE_INGRESO) se corrige y la validación previa la rechaza', () => {
  const heredada = [{ tipoOperacionId: id('AJUSTE_INGRESO') as number | '' }];
  assert.equal(reconciliarOperaciones(heredada, TIPOS, 'COMPRA', FACTURA)[0].tipoOperacionId, id('COMPRA'));
  assert.equal(errorDeOperaciones(heredada, TIPOS, 'COMPRA', FACTURA), 'Línea 1: la operación AJUSTE_INGRESO no corresponde a un comprobante de compra.');
});

test('el frontend no permite enviar una combinación incompatible', () => {
  assert.equal(errorDeOperaciones([{ tipoOperacionId: id('COMPRA') }, { tipoOperacionId: id('VENTA') }], TIPOS, 'COMPRA', FACTURA),
    'Línea 2: la operación VENTA no corresponde a un comprobante de compra.');
  assert.equal(errorDeOperaciones([{ tipoOperacionId: id('COMPRA') }], TIPOS, 'VENTA', FACTURA),
    'Línea 1: la operación COMPRA no corresponde a un comprobante de venta.');
  assert.equal(errorDeOperaciones([{ tipoOperacionId: id('NC_DESCUENTO_COMPRA') }], TIPOS, 'VENTA', NC),
    'Línea 1: la operación NC_DESCUENTO_COMPRA no corresponde a esta nota de venta.');
  assert.equal(errorDeOperaciones([{ tipoOperacionId: '' }], TIPOS, 'VENTA', FACTURA), 'Línea 1: Debe seleccionar un tipo de operación.');
  assert.equal(errorDeOperaciones([{ tipoOperacionId: id('COMPRA') }, { tipoOperacionId: id('BONIFICACION') }], TIPOS, 'COMPRA', FACTURA), null);
  assert.equal(errorDeOperaciones([{ tipoOperacionId: id('VENTA') }], TIPOS, 'VENTA', FACTURA), null);
});

test('catálogo vacío o sin la operación preferida: nada inventado', () => {
  assert.equal(operacionPorDefecto([], 'COMPRA', FACTURA), '');
  const sinCompra = TIPOS.filter((t) => t.codigo_interno !== 'COMPRA');
  assert.equal(operacionPorDefecto(sinCompra, 'COMPRA', FACTURA), id('BONIFICACION'));
  assert.equal(operacionPorDefecto(TIPOS.map((t) => ({ ...t, activo: t.codigo_interno !== 'VENTA' })), 'VENTA', FACTURA), '');
});
