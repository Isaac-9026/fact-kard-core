import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  CONFIG_VISTAS, TABS_COMPROBANTES, claseDeTab, claseInicialNuevo, filtrosApiDocumentos, queryConTab, tabDesdeQuery,
  tiposComprobanteDeVista,
} from './vistaDocumentos.ts';

const usuario = { periodo: 3, estado: 'CONFIRMADO', search: 'F001' };

test('Comprobantes: título, descripción y un único botón "Nuevo Comprobante"', () => {
  assert.equal(CONFIG_VISTAS.COMPROBANTES.titulo, 'Comprobantes');
  assert.equal(CONFIG_VISTAS.COMPROBANTES.descripcion, 'Gestión de comprobantes comerciales de compra y venta.');
  assert.equal(CONFIG_VISTAS.COMPROBANTES.botonNuevo, 'Nuevo Comprobante');
  assert.deepEqual(Object.keys(CONFIG_VISTAS), ['COMPROBANTES', 'NOTAS']); // ya no hay vistas Compras / Ventas
});

test('pestañas Todos | Compras | Ventas desde la URL', () => {
  assert.deepEqual(TABS_COMPROBANTES.map((t) => t.etiqueta), ['Todos', 'Compras', 'Ventas']);
  assert.equal(tabDesdeQuery(null), 'TODOS'); // /comprobantes
  assert.equal(tabDesdeQuery('COMPRA'), 'COMPRA'); // /comprobantes?clase=COMPRA (y /compras redirigido)
  assert.equal(tabDesdeQuery('VENTA'), 'VENTA'); // /comprobantes?clase=VENTA (y /ventas redirigido)
  assert.equal(tabDesdeQuery('venta'), 'VENTA');
  assert.equal(tabDesdeQuery('NOTA'), 'TODOS'); // valor inválido: no filtra a ciegas
});

test('filtro de cada pestaña combinado con los filtros del usuario (sin notas)', () => {
  assert.deepEqual(filtrosApiDocumentos('COMPROBANTES', { ...usuario, clase: claseDeTab('TODOS') }), { ...usuario, clase: undefined, es_nota: false });
  assert.deepEqual(filtrosApiDocumentos('COMPROBANTES', { ...usuario, clase: claseDeTab('COMPRA') }), { ...usuario, clase: 'COMPRA', es_nota: false });
  assert.deepEqual(filtrosApiDocumentos('COMPROBANTES', { ...usuario, clase: claseDeTab('VENTA') }), { ...usuario, clase: 'VENTA', es_nota: false });
});

test('cambiar de pestaña solo cambia `clase` en la URL y conserva lo demás', () => {
  assert.equal(queryConTab('', 'COMPRA').toString(), 'clase=COMPRA');
  assert.equal(queryConTab('clase=COMPRA', 'VENTA').toString(), 'clase=VENTA');
  assert.equal(queryConTab('clase=VENTA&x=1', 'TODOS').toString(), 'x=1');
  assert.equal(queryConTab(new URLSearchParams('nuevo=1'), 'VENTA').toString(), 'nuevo=1&clase=VENTA');
});

test('el modal se abre con la clase de la pestaña y en Todos con la última usada', () => {
  assert.equal(claseInicialNuevo('COMPRA', 'VENTA'), 'COMPRA');
  assert.equal(claseInicialNuevo('VENTA', 'COMPRA'), 'VENTA');
  assert.equal(claseInicialNuevo('TODOS', 'VENTA'), 'VENTA');
  assert.equal(claseInicialNuevo('TODOS', 'COMPRA'), 'COMPRA');
});

test('Notas: módulo separado, solo notas', () => {
  assert.deepEqual(filtrosApiDocumentos('NOTAS', { clase: 'COMPRA' }), { clase: 'COMPRA', es_nota: true });
  assert.deepEqual(filtrosApiDocumentos('NOTAS', {}), { es_nota: true });
});

test('el formulario ofrece los tipos de comprobante de la vista', () => {
  const tipos = [{ id: 1, es_nota: false }, { id: 3, es_nota: false }, { id: 7, es_nota: true }, { id: 8, es_nota: true }];
  assert.deepEqual(tiposComprobanteDeVista('COMPROBANTES', tipos).map((t) => t.id), [1, 3]);
  assert.deepEqual(tiposComprobanteDeVista('NOTAS', tipos).map((t) => t.id), [7, 8]);
});

import { claveConsulta, irAPagina, paginaVigente } from './paginacion.ts';

test('paginación con pestañas: cambiar Todos → Compras → Ventas vuelve a la página 1; volver a la misma conserva', () => {
  const clave = (tab: 'TODOS' | 'COMPRA' | 'VENTA') => claveConsulta(1, 'COMPROBANTES', claseDeTab(tab) ?? '', 6, 'CONFIRMADO', '', '');
  const enTodos = irAPagina(clave('TODOS'), 3);
  assert.equal(paginaVigente(enTodos, clave('TODOS')), 3);
  assert.equal(paginaVigente(enTodos, clave('COMPRA')), 1);
  const enCompras = irAPagina(clave('COMPRA'), 2);
  assert.equal(paginaVigente(enCompras, clave('VENTA')), 1);
  assert.equal(paginaVigente(enCompras, clave('COMPRA')), 2);
});
