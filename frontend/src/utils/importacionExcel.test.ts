import { test } from 'node:test';
import assert from 'node:assert/strict';
import type { ComprobanteImportado, PrevisualizacionImportacion, TrabajoImportacion } from '../api/importacion.ts';
import {
  FILTRO_A_SERVIDOR, aplicarProveedorAClaves, aplicarProveedorATodas, archivosXlsx, asignarProveedor,
  contadoresDesdePrevia, contarPorFiltro, debeContinuarPolling, etiquetaFaseTrabajo, fechaCorta,
  filtrarComprobantes, hayErroresParaDescargar, montoConSigno, motivoNoConfirmable, nombreArchivoDiferencias,
  rangoPagina, resultadoDesdeTrabajo, resumenAnulacionDesdeTrabajo, rucValido, signoMonto, sinProveedor,
  textoPorGrabar, textoProgresoTrabajo,
} from './importacionExcel.ts';

const comp = (serie: string, extra: Partial<ComprobanteImportado> = {}): ComprobanteImportado => ({
  clave: `01-${serie}-1`, clase: 'VENTA', operacion: '01', tipo: '01', serie, numero: '1', fecha: '2026-01-05',
  ruc: null, naturaleza: 'SALIDA', lineas: 1, productos: ['P1'], origen: null, requiere_proveedor: false,
  clave_proveedor: null, estado: 'NUEVO', mensaje: '', observaciones: [], completa_lote: null, agregar: [], ...extra,
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
    nuevos: comprobantes.filter((c) => c.estado === 'NUEVO').length,
    completar: comprobantes.filter((c) => c.estado === 'COMPLETAR').length,
    lineas_a_agregar: comprobantes.reduce((n, c) => n + c.agregar.length, 0), ya_existen: 0, conflictos: 0,
    con_error: comprobantes.filter((c) => c.estado === 'ERROR').length, requieren_proveedor: 0, productos: 1,
    desde: null, hasta: null, limite_lote: 1500, excede_limite: false, puede_confirmar: true, ...resumen,
  },
});

const trabajo = (extra: Partial<TrabajoImportacion> = {}): TrabajoImportacion => ({
  id: 10,
  trabajo_id: 10,
  tipo: 'CONFIRMAR',
  estado: 'EN_COLA',
  lote_id: null,
  lote: null,
  almacen: { id: 1, codigo: 'ALM', nombre: 'Principal' },
  archivos: ['anual.xlsx'],
  intentos: 0,
  resumen: {},
  error_detalle: '',
  progreso: { trabajo_id: 10, fase: 'EN_COLA', actual: 0, total: 1, porcentaje: 0, mensaje: 'En cola' },
  creado_en: '2026-01-01T00:00:00Z',
  iniciado_en: null,
  finalizado_en: null,
  ...extra,
});

test('filtros y contadores para ir directo a los errores', () => {
  const lista = [comp('F1'), comp('F2', { estado: 'ERROR' }), comp('F3', { observaciones: ['x'] }), compraSinRuc('C1')];
  const conteo = contarPorFiltro(lista, {});
  assert.deepEqual(conteo, { TODOS: 4, NUEVO: 2, COMPLETAR: 0, YA_EXISTE: 0, CONFLICTO: 0, ERROR: 2, OBSERVADOS: 1, SIN_PROVEEDOR: 1 });
  assert.deepEqual(filtrarComprobantes(lista, 'ERROR', {}).map((c) => c.serie), ['F2', 'C1']);
  assert.deepEqual(filtrarComprobantes(lista, 'SIN_PROVEEDOR', {}).map((c) => c.serie), ['C1']);
  assert.equal(filtrarComprobantes(lista, 'TODOS', {}).length, 4);
});

test('paginación, contadores globales del servidor y asignación masiva multipágina', () => {
  const p = {
    ...previa([comp('F1')], { con_error: 5, conflictos: 2, requieren_proveedor: 140 }),
    previsualizacion_id: 'abc123',
    contadores: {
      todos: 500, nuevos: 300, a_completar: 20, ya_existen: 33, errores: 5, conflictos: 2, sin_proveedor: 140, observaciones: 10,
    },
  };
  assert.deepEqual(contadoresDesdePrevia(p, {}), {
    TODOS: 500, NUEVO: 300, COMPLETAR: 20, YA_EXISTE: 33, ERROR: 5, CONFLICTO: 2, SIN_PROVEEDOR: 140, OBSERVADOS: 10,
  });
  assert.equal(FILTRO_A_SERVIDOR.COMPLETAR, 'a_completar');
  assert.equal(FILTRO_A_SERVIDOR.SIN_PROVEEDOR, 'sin_proveedor');
  assert.equal(hayErroresParaDescargar(p), true);
  assert.equal(hayErroresParaDescargar(previa([comp('F1')])), false);

  assert.deepEqual(rangoPagina(1, 100, 340), { desde: 1, hasta: 100 });
  assert.deepEqual(rangoPagina(4, 100, 340), { desde: 301, hasta: 340 });
  assert.deepEqual(rangoPagina(1, 100, 0), { desde: 0, hasta: 0 });

  // Asignación masiva sobre claves de varias páginas respetando asignaciones previas
  const iniciales = { '01-C1-1-2026-01-05': '20555000111' };
  const todas = ['01-C1-1-2026-01-05', '01-C150-1-2026-01-05', '01-C220-1-2026-01-05'];
  const actualizados = aplicarProveedorAClaves(todas, iniciales, '20666000222');
  assert.equal(actualizados['01-C1-1-2026-01-05'], '20555000111');
  assert.equal(actualizados['01-C150-1-2026-01-05'], '20666000222');
  assert.equal(actualizados['01-C220-1-2026-01-05'], '20666000222');
});

test('estados de polling para trabajos EN_COLA, PROCESANDO, COMPLETADO y ERROR', () => {
  const enCola = trabajo({ estado: 'EN_COLA' });
  assert.equal(debeContinuarPolling(enCola), true);
  assert.equal(etiquetaFaseTrabajo('EN_COLA'), 'En cola');

  const procesando = trabajo({
    estado: 'PROCESANDO',
    progreso: { trabajo_id: 10, fase: 'GRABANDO_COMPROBANTES', actual: 150, total: 300, porcentaje: 50, mensaje: 'Grabando' },
  });
  assert.equal(debeContinuarPolling(procesando), true);
  assert.equal(textoProgresoTrabajo(procesando), 'Grabando comprobantes · 150 / 300 (50%)');

  const completado = trabajo({
    estado: 'COMPLETADO',
    lote_id: 42,
    lote: 42,
    resumen: { lote: 42, comprobantes: 300, completados: 4, lineas_agregadas: 6, omitidos: 1, segundos: 12 },
  });
  assert.equal(debeContinuarPolling(completado), false);
  assert.deepEqual(resultadoDesdeTrabajo(completado), {
    lote: 42, comprobantes: 300, completados: 4, lineas_agregadas: 6, omitidos: 1, segundos: 12,
  });

  const anularCompletado = trabajo({
    tipo: 'ANULAR',
    estado: 'COMPLETADO',
    lote_id: 42,
    resumen: { lote: 42, estado: 'ANULADO', comprobantes_anulados: 300, lineas_revertidas: 6, comprobantes_revertidos: ['BS01-1'] },
  });
  assert.deepEqual(resumenAnulacionDesdeTrabajo(anularCompletado), {
    lote: 42, estado: 'ANULADO', comprobantes_anulados: 300, lineas_revertidas: 6, comprobantes_revertidos: ['BS01-1'],
  });

  const conError = trabajo({ estado: 'ERROR', error_detalle: 'Fallo controlado' });
  assert.equal(debeContinuarPolling(conError), false);
  assert.equal(resultadoDesdeTrabajo(conError), null);
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
  assert.match(motivoNoConfirmable({ ...base, previa: previa([comp('F1', { estado: 'YA_EXISTE' })]) }) ?? '', /No hay comprobantes nuevos ni líneas/);
  assert.match(motivoNoConfirmable({ ...base, previa: previa([comp('F1')]), almacenId: null }) ?? '', /almacén/);
  assert.equal(motivoNoConfirmable({ ...base, previa: previa([comp('F1')]) }), null);
});

test('completar comprobante: cuenta, filtra y permite confirmar aunque no haya nuevos', () => {
  const linea = { archivo: 'SUERO.xlsx', fila: 40, codigo: '011035', cantidad: '5', costo_unitario: '3.98429', costo_total: '19.92145', precio_unitario: null };
  const lista = [
    comp('BS01', { estado: 'COMPLETAR', completa_lote: 7, agregar: [linea] }),
    comp('BS02', { estado: 'COMPLETAR', completa_lote: 7, agregar: [linea] }),
    comp('BS03', { estado: 'YA_EXISTE' }),
  ];
  assert.equal(contarPorFiltro(lista, {}).COMPLETAR, 2);
  assert.deepEqual(filtrarComprobantes(lista, 'COMPLETAR', {}).map((c) => c.serie), ['BS01', 'BS02']);
  const base = { desactualizada: false, almacenId: 1, proveedores: {} };
  assert.equal(motivoNoConfirmable({ ...base, previa: previa(lista) }), null);
  assert.match(motivoNoConfirmable({ ...base, previa: previa([...lista, comp('BS04', { estado: 'CONFLICTO' })], { conflictos: 1 }) }) ?? '', /Corrija 1/);
  assert.equal(textoPorGrabar({ nuevos: 56, completar: 2, lineas_a_agregar: 2 }), '56 nuevos y 2 por completar (2 líneas)');
  assert.equal(textoPorGrabar({ nuevos: 1, completar: 0, lineas_a_agregar: 0 }), '1 nuevo');
  assert.equal(textoPorGrabar({ nuevos: 0, completar: 1, lineas_a_agregar: 1 }), '1 por completar (1 línea)');
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
