import { test } from 'node:test';
import assert from 'node:assert/strict';
import type { ComprobanteImportado, PrevisualizacionImportacion } from '../api/importacion.ts';
import {
  aplicarProveedorATodas, archivosXlsx, asignarProveedor, contarPorFiltro, fechaCorta, filtrarComprobantes,
  montoConSigno, motivoNoConfirmable, nombreArchivoDiferencias, rucValido, signoMonto, sinProveedor,
} from './importacionExcel.ts';

const comp = (serie: string, extra: Partial<ComprobanteImportado> = {}): ComprobanteImportado => ({
  clave: `01-${serie}-1`, clase: 'VENTA', operacion: '01', tipo: '01', serie, numero: '1', fecha: '2026-01-05',
  ruc: null, naturaleza: 'SALIDA', lineas: 1, productos: ['P1'], origen: null, requiere_proveedor: false,
  clave_proveedor: null, estado: 'NUEVO', mensaje: '', observaciones: [], ...extra,
});

const compraSinRuc = (serie: string) => comp(serie, {
  clase: 'COMPRA', operacion: '02', estado: 'ERROR', requiere_proveedor: true, clave_proveedor: `01-${serie}-1-2026-01-05`,
});

const previa = (comprobantes: ComprobanteImportado[], resumen: Partial<PrevisualizacionImportacion['resumen']> = {}) => ({
  formato: 'ENTRADAS_SALIDAS' as const,
  comprobantes,
  filas: [],
  resumen: {
    archivos: 1, filas: comprobantes.length, filas_con_error: 0, filas_con_observacion: 0, comprobantes: comprobantes.length,
    nuevos: comprobantes.filter((c) => c.estado === 'NUEVO').length, ya_existen: 0, conflictos: 0,
    con_error: comprobantes.filter((c) => c.estado === 'ERROR').length, requieren_proveedor: 0, productos: 1,
    desde: null, hasta: null, limite_lote: 1500, excede_limite: false, puede_confirmar: true, ...resumen,
  },
});

test('filtros y contadores para ir directo a los errores', () => {
  const lista = [comp('F1'), comp('F2', { estado: 'ERROR' }), comp('F3', { observaciones: ['x'] }), compraSinRuc('C1')];
  const conteo = contarPorFiltro(lista, {});
  assert.deepEqual(conteo, { TODOS: 4, NUEVO: 2, YA_EXISTE: 0, CONFLICTO: 0, ERROR: 2, OBSERVADOS: 1, SIN_PROVEEDOR: 1 });
  assert.deepEqual(filtrarComprobantes(lista, 'ERROR', {}).map((c) => c.serie), ['F2', 'C1']);
  assert.deepEqual(filtrarComprobantes(lista, 'SIN_PROVEEDOR', {}).map((c) => c.serie), ['C1']);
  assert.equal(filtrarComprobantes(lista, 'TODOS', {}).length, 4);
});

test('proveedor elegido en pantalla, uno por uno o a todas las compras sin RUC', () => {
  const lista = [compraSinRuc('C1'), compraSinRuc('C2'), compraSinRuc('C3')];
  let proveedores = asignarProveedor({}, '01-C1-1-2026-01-05', '20555000111');
  assert.equal(sinProveedor(lista, proveedores).length, 2);
  proveedores = aplicarProveedorATodas(lista, proveedores, '20555000222');
  assert.equal(proveedores['01-C1-1-2026-01-05'], '20555000111');
  assert.equal(proveedores['01-C3-1-2026-01-05'], '20555000222');
  assert.equal(sinProveedor(lista, proveedores).length, 0);
  assert.deepEqual(asignarProveedor(proveedores, '01-C1-1-2026-01-05', '')['01-C1-1-2026-01-05'], undefined);
});

test('confirmar solo con previsualización vigente, sin errores, con proveedores y almacén', () => {
  const base = { desactualizada: false, almacenId: 1, proveedores: {} };
  assert.match(motivoNoConfirmable({ ...base, previa: null }) ?? '', /previsualice/);
  assert.match(motivoNoConfirmable({ ...base, previa: previa([comp('F1')]), desactualizada: true }) ?? '', /vuelva a previsualizar/);
  assert.match(motivoNoConfirmable({ ...base, previa: previa([compraSinRuc('C1')]) }) ?? '', /proveedor de 1 compra/);
  assert.match(motivoNoConfirmable({ ...base, previa: previa([comp('F1', { estado: 'ERROR' })]) }) ?? '', /Corrija 1/);
  assert.match(motivoNoConfirmable({ ...base, previa: previa([comp('F1')], { excede_limite: true }) }) ?? '', /supera 1500/);
  assert.match(motivoNoConfirmable({ ...base, previa: previa([comp('F1', { estado: 'YA_EXISTE' })]) }) ?? '', /No hay comprobantes nuevos/);
  assert.match(motivoNoConfirmable({ ...base, previa: previa([comp('F1')]), almacenId: null }) ?? '', /almacén/);
  assert.equal(motivoNoConfirmable({ ...base, previa: previa([comp('F1')]) }), null);
});

test('RUC, fechas y archivos', () => {
  assert.equal(rucValido('20555000111'), true);
  assert.equal(rucValido('2055500011'), false);
  assert.equal(rucValido('99555000111'), false);
  assert.equal(fechaCorta('2023-05-10'), '10/05/2023');
  assert.equal(fechaCorta(null), '—');
  const archivos = [new File(['x'], 'a.xlsx'), new File(['x'], 'b.csv'), new File(['x'], 'C.XLSX')];
  assert.deepEqual(archivosXlsx(archivos).rechazados, ['b.csv']);
  assert.equal(archivosXlsx(archivos).validos.length, 2);
});

test('diferencias: signo de montos en texto, sin pasar por número', () => {
  assert.equal(signoMonto('-4.00'), -1);
  assert.equal(signoMonto('2.50'), 1);
  assert.equal(signoMonto('0.00'), 0);
  assert.equal(signoMonto('-0.00'), 0);
  assert.equal(signoMonto(null), 0);
  assert.equal(montoConSigno('2.50'), '+2.50');
  assert.equal(montoConSigno('-4.00'), '-4.00');
  assert.equal(montoConSigno('0.00'), '0.00');
  assert.equal(montoConSigno(null), '—');
  assert.equal(montoConSigno('12345678901234567890.12'), '+12345678901234567890.12');
});

test('diferencias: nombre del Excel según filtros', () => {
  assert.equal(nombreArchivoDiferencias(46, {}), 'diferencias_lote_46.xlsx');
  assert.equal(nombreArchivoDiferencias(46, { producto: 3, nivel: 'ROJO' }, '011004'), 'diferencias_lote_46_011004_rojo.xlsx');
  assert.equal(nombreArchivoDiferencias(46, { producto: 3 }, '../x y'), 'diferencias_lote_46_xy.xlsx');
});
