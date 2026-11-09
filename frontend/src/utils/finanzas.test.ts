import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  numeroComprobante,
  distribuirCuotas, errorCondicionPago, errorDocumentoIdentidad, errorMontoPago, esRucValido, fechasMensuales, sumaCuotas,
} from './finanzas.ts';

test('RUC: 11 dígitos, prefijo y dígito verificador (módulo 11 SUNAT)', () => {
  assert.equal(esRucValido('20100070970'), true);
  assert.equal(esRucValido('20100070971'), false);
  assert.equal(errorDocumentoIdentidad('6', '20100070970'), null);
  assert.match(errorDocumentoIdentidad('6', '20100070971') ?? '', /dígito verificador/);
  assert.match(errorDocumentoIdentidad('6', '2010007097') ?? '', /11 dígitos/);
  assert.match(errorDocumentoIdentidad('6', '30100070970') ?? '', /empezar con/);
});

test('DNI 8 dígitos y otros documentos', () => {
  assert.equal(errorDocumentoIdentidad('1', '45678912'), null);
  assert.match(errorDocumentoIdentidad('1', '4567891') ?? '', /8 dígitos/);
  assert.match(errorDocumentoIdentidad('1', '4567891A') ?? '', /8 dígitos/);
  assert.equal(errorDocumentoIdentidad('7', 'ab123456'), null);
  assert.match(errorDocumentoIdentidad('RUC', '20100070970') ?? '', /tipo de documento/);
});

test('cuotas: reparto exacto (la última absorbe el redondeo) y suma = total', () => {
  const tres = distribuirCuotas('100.00', ['2026-02-10', '2026-03-10', '2026-04-10']);
  assert.deepEqual(tres.map((c) => c.monto), ['33.33', '33.33', '33.34']);
  assert.equal(sumaCuotas(tres), '100.00000000');
  const raro = distribuirCuotas('10.12345678', ['2026-02-10', '2026-03-10']);
  assert.equal(sumaCuotas(raro), '10.12345678');
  assert.deepEqual(distribuirCuotas('118', ['2026-02-10']).map((c) => c.monto), ['118.00']);
});

test('fechas mensuales desde la emisión (fin de mes si el día no existe)', () => {
  assert.deepEqual(fechasMensuales('2026-01-31', 3), ['2026-02-28', '2026-03-31', '2026-04-30']);
  assert.deepEqual(fechasMensuales('2026-01-10', 2), ['2026-02-10', '2026-03-10']);
});

test('condición de pago: contado, crédito, vencimiento y cuotas', () => {
  const base = { fechaEmision: '2026-01-10', total: '118', cuotas: [] as { fecha_vencimiento: string; monto: string }[] };
  assert.equal(errorCondicionPago({ ...base, condicion: 'CONTADO', fechaVencimiento: '' }), null);
  assert.match(errorCondicionPago({ ...base, condicion: 'CREDITO', fechaVencimiento: '' }) ?? '', /vencimiento/);
  assert.match(errorCondicionPago({ ...base, condicion: 'CREDITO', fechaVencimiento: '2026-01-01' }) ?? '', /anterior/);
  assert.equal(errorCondicionPago({ ...base, condicion: 'CREDITO', fechaVencimiento: '2026-03-10' }), null);
  const cuotas = [{ fecha_vencimiento: '2026-02-10', monto: '59' }, { fecha_vencimiento: '2026-03-10', monto: '59' }];
  assert.equal(errorCondicionPago({ ...base, condicion: 'CREDITO', fechaVencimiento: '2026-03-10', cuotas }), null);
  assert.match(errorCondicionPago({ ...base, condicion: 'CREDITO', fechaVencimiento: '2026-03-10',
    cuotas: [cuotas[0], { ...cuotas[1], monto: '50' }] }) ?? '', /suma de las cuotas/);
  assert.match(errorCondicionPago({ ...base, condicion: 'CREDITO', fechaVencimiento: '2026-04-10', cuotas }) ?? '', /última cuota/);
});

test('monto del pago frente al saldo', () => {
  assert.equal(errorMontoPago('18', '118'), null);
  assert.equal(errorMontoPago('118', '118.00000000'), null);
  assert.match(errorMontoPago('118.01', '118') ?? '', /supera el saldo/);
  assert.match(errorMontoPago('0', '118') ?? '', /mayor a 0/);
});

test('numeroComprobante: correlativo oficial de 8 dígitos solo con serie automática', () => {
  assert.equal(numeroComprobante({ serie_normalizada: 'F001', numero_normalizado: '26', serie_comprobante: 3 }), 'F001-00000026');
  assert.equal(numeroComprobante({ serie_normalizada: 'F001', numero_normalizado: '26', serie_comprobante: null }), 'F001-26');
});
