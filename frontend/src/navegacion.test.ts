import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  ACCESOS_RAPIDOS, NAV_SECCIONES, RUTA_INICIAL, RUTAS_ANTERIORES, destinoInicial, destinoRedireccion, itemActivo,
  todasLasRutasDelMenu,
} from './navegacion.ts';
import { tabDesdeQuery } from './utils/vistaDocumentos.ts';
import { resolverAccesoRuta } from './utils/sesion.ts';

const app = readFileSync(new URL('./App.tsx', import.meta.url), 'utf8');
const login = readFileSync(new URL('./pages/auth/LoginPage.tsx', import.meta.url), 'utf8');
const documentos = readFileSync(new URL('./pages/documentos/DocumentosPage.tsx', import.meta.url), 'utf8');
const rutasDeApp = new Set([...app.matchAll(/<Route path="([^"*]+)"/g)].map((m) => `/${m[1].replace(/^\//, '')}`));

test('Dashboard es la ruta inicial: raíz, rutas desconocidas y después del login', () => {
  assert.equal(RUTA_INICIAL, '/dashboard');
  assert.match(app, /<Route index element={<Navigate to={RUTA_INICIAL} replace \/>} \/>/);
  assert.match(app, /<Route path="\*" element={<Navigate to={RUTA_INICIAL} replace \/>} \/>/);
  assert.match(login, /navigate\(RUTA_INICIAL\)/);
  assert.ok(rutasDeApp.has('/dashboard'));
});

test('usuario autenticado entra al Dashboard', () => {
  assert.equal(destinoInicial({ token: 'tk' }), '/dashboard');
  assert.equal(resolverAccesoRuta({ token: 'tk', verificandoSesion: false }), 'permitido');
});

test('usuario no autenticado sigue yendo a login', () => {
  assert.equal(destinoInicial({ token: null }), '/login');
  assert.equal(resolverAccesoRuta({ token: null, verificandoSesion: false }), 'redirigir_login');
  // El Dashboard está dentro de las rutas protegidas (RutaProtegida).
  assert.ok(app.indexOf('<Route element={<RutaProtegida />}>') < app.indexOf('path="dashboard"'));
});

test('menú con las secciones y opciones en el orden del flujo', () => {
  assert.deepEqual(
    NAV_SECCIONES.map((s) => [s.title, s.items.map((i) => i.label)]),
    [
      ['INICIO', ['Dashboard']],
      ['CONFIGURACIÓN', ['Empresas y Anexos', 'Períodos e IGV', 'Catálogos y TC SBS']],
      ['MAESTROS', ['Productos y Unidades', 'Almacenes', 'Terceros']],
      ['INVENTARIO INICIAL', ['Saldo Inicial', 'Inventario']],
      ['OPERACIONES', ['Comprobantes', 'Notas de Crédito / Débito', 'Transferencias', 'Captura XML / OCR']],
      ['FINANZAS', ['Cuentas por cobrar', 'Cuentas por pagar']],
      ['KARDEX', ['Kardex Valorizado', 'Incidencias y Recálculo']],
      ['CIERRE Y REPORTES', ['Cierres y Snapshots', 'Formato 13.1 SUNAT', 'Registro de ventas y compras']],
      ['SEGURIDAD', ['Auditoría Inmutable']],
    ],
  );
});

test('cada opción del menú tiene ruta, sin duplicados, y resalta la opción activa', () => {
  const rutas = todasLasRutasDelMenu();
  assert.equal(new Set(rutas).size, rutas.length);
  for (const ruta of rutas) assert.ok(rutasDeApp.has(ruta), `falta la ruta ${ruta} en App.tsx`);
  assert.equal(itemActivo('/comprobantes')?.item.label, 'Comprobantes');
  assert.equal(itemActivo('/comprobantes')?.seccion.title, 'OPERACIONES'); // breadcrumb OPERACIONES > Comprobantes
  assert.equal(itemActivo('/notas')?.seccion.title, 'OPERACIONES');
  assert.equal(itemActivo('/inventario')?.seccion.title, 'INVENTARIO INICIAL');
  assert.equal(itemActivo('/cuentas-por-cobrar')?.seccion.title, 'FINANZAS'); // Bloque 16
  assert.equal(itemActivo('/cuentas-por-pagar')?.item.label, 'Cuentas por pagar');
  assert.equal(itemActivo('/no-existe'), null);
  // Coincidencia exacta o por segmento.
  assert.equal(itemActivo('/comprobantesx'), null);
});

test('accesos rápidos navegan a rutas existentes', () => {
  assert.deepEqual(ACCESOS_RAPIDOS.map((a) => [a.label, a.to]), [
    ['Nueva compra', '/comprobantes?clase=COMPRA&nuevo=1'],
    ['Nueva venta', '/comprobantes?clase=VENTA&nuevo=1'],
    ['Ver Kardex', '/kardex'],
    ['Ver incidencias', '/incidencias'],
  ]);
  for (const a of ACCESOS_RAPIDOS) assert.ok(rutasDeApp.has(a.to.split('?')[0]), a.to);
});

test('rutas anteriores redirigen a su nueva ubicación', () => {
  assert.equal(RUTAS_ANTERIORES['/operaciones-internas'], '/saldo-inicial');
  assert.ok(rutasDeApp.has('/saldo-inicial'));
});

test('Bloque 13: el sidebar ya no muestra Compras ni Ventas (son pestañas de Comprobantes)', () => {
  const labels = NAV_SECCIONES.flatMap((sec) => sec.items.map((i) => i.label));
  assert.ok(!labels.includes('Compras'));
  assert.ok(!labels.includes('Ventas'));
  const rutas = todasLasRutasDelMenu();
  for (const r of ['/compras', '/ventas', '/documentos']) assert.ok(!rutas.includes(r), r);
  assert.equal(itemActivo('/compras'), null); // tras redirigir, el breadcrumb es OPERACIONES > Comprobantes
});

test('Bloque 13: /compras y /ventas siguen funcionando: redirigen a Comprobantes con su pestaña', () => {
  assert.equal(RUTAS_ANTERIORES['/compras'], '/comprobantes?clase=COMPRA');
  assert.equal(RUTAS_ANTERIORES['/ventas'], '/comprobantes?clase=VENTA');
  assert.equal(RUTAS_ANTERIORES['/documentos'], '/comprobantes');
  assert.ok(rutasDeApp.has('/comprobantes'));
  for (const desde of ['/compras', '/ventas', '/documentos']) assert.ok(!rutasDeApp.has(desde), `${desde} ya no es una pantalla propia`);
  assert.match(app, /RUTAS_ANTERIORES\)\.map\(\(\[desde, hacia\]\) =>/);
  assert.match(app, /<RedireccionAnterior hacia={hacia} \/>/);
  // Pestaña resultante de cada ruta
  const pestaña = (url: string) => tabDesdeQuery(new URLSearchParams(url.split('?')[1] ?? '').get('clase'));
  assert.equal(pestaña(destinoRedireccion(RUTAS_ANTERIORES['/compras'], '')), 'COMPRA');
  assert.equal(pestaña(destinoRedireccion(RUTAS_ANTERIORES['/ventas'], '')), 'VENTA');
  assert.equal(pestaña('/comprobantes'), 'TODOS');
});

test('Bloque 13: la redirección conserva los parámetros del enlace antiguo', () => {
  assert.equal(destinoRedireccion('/comprobantes?clase=COMPRA', '?nuevo=1'), '/comprobantes?nuevo=1&clase=COMPRA');
  assert.equal(destinoRedireccion('/comprobantes?clase=VENTA', '?clase=COMPRA'), '/comprobantes?clase=VENTA');
  assert.equal(destinoRedireccion('/comprobantes', ''), '/comprobantes');
  assert.equal(destinoRedireccion('/saldo-inicial', ''), '/saldo-inicial');
});

test('Bloque 13: Comprobantes tiene un único botón "Nuevo Comprobante" y el modal conserva Compra / Venta', () => {
  assert.equal((documentos.match(/configVista\.botonNuevo/g) ?? []).length, 1);
  assert.doesNotMatch(documentos, /Nueva Compra|Nueva Venta|claseFija/);
  assert.match(documentos, /<option value="COMPRA">COMPRA \(Entrada\)<\/option>/);
  assert.match(documentos, /<option value="VENTA">VENTA \(Salida\)<\/option>/);
  assert.match(documentos, /onChange={\(e\) => cambiarClase\(e\.target\.value as ClaseDocumento\)}/);
});
