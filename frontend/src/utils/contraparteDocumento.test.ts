import { test } from 'node:test';
import assert from 'node:assert/strict';
import { contraparteDocumento, etiquetaTipoDocumento } from './contraparteDocumento.ts';

const EMPRESA = '20999000003';

test('venta: se muestra el RUC y el nombre del CLIENTE, no el de la empresa emisora (FV01-1)', () => {
  const c = contraparteDocumento({ clase: 'VENTA', ruc_emisor: EMPRESA, tercero: 9, tercero_razon_social: 'CLIENTE QA C', tercero_tipo_documento: '6', tercero_numero_documento: '20666000222' });
  assert.deepEqual(c, { rol: 'Cliente', etiquetaDocumento: 'RUC', documento: '20666000222', nombre: 'CLIENTE QA C' });
  assert.notEqual(c.documento, EMPRESA);
});

test('venta a persona con DNI', () => {
  const c = contraparteDocumento({ clase: 'VENTA', ruc_emisor: EMPRESA, tercero_razon_social: 'JUAN PEREZ', tercero_tipo_documento: '1', tercero_numero_documento: '45678912' });
  assert.equal(`${c.etiquetaDocumento}: ${c.documento}`, 'DNI: 45678912');
});

test('venta sin cliente: CLIENTES VARIOS y sin RUC de la empresa', () => {
  const c = contraparteDocumento({ clase: 'VENTA', ruc_emisor: EMPRESA, tercero: null });
  assert.equal(c.nombre, 'CLIENTES VARIOS');
  assert.equal(c.documento, '—');
});

test('compra: el proveedor (tercero) y, sin tercero, el RUC emisor del comprobante', () => {
  assert.deepEqual(
    contraparteDocumento({ clase: 'COMPRA', ruc_emisor: '20555000111', tercero_razon_social: 'PROVEEDOR QA C', tercero_tipo_documento: '6', tercero_numero_documento: '20555000111' }),
    { rol: 'Proveedor', etiquetaDocumento: 'RUC', documento: '20555000111', nombre: 'PROVEEDOR QA C' },
  );
  assert.equal(contraparteDocumento({ clase: 'COMPRA', ruc_emisor: '20555000111' }).documento, '20555000111');
  assert.equal(etiquetaTipoDocumento(null), 'Doc.');
});
