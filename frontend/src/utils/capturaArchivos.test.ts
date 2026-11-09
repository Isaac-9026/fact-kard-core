import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  CAPTURA_MAX_BYTES, DESCRIPCION_TIPO_CAPTURA, PASOS_CAPTURA, acceptCaptura, formatosVisibles, pasoActualCaptura,
  tipoSugerido, validarArchivoCaptura,
} from './capturaArchivos.ts';

test('formatos visibles y accept iguales a los del backend (uploads.PERMITIDOS)', () => {
  assert.equal(acceptCaptura('XML'), '.xml');
  assert.equal(acceptCaptura('IMAGEN'), '.jpg,.jpeg,.png');
  assert.equal(acceptCaptura('ESCANER'), '.pdf,.jpg,.jpeg,.png,.tif,.tiff');
  assert.equal(formatosVisibles('PDF'), '.pdf · máx. 10 MB');
  assert.equal(CAPTURA_MAX_BYTES, 10 * 1024 * 1024);
});

test('ESCÁNER explica que es un comprobante físico digitalizado y que el sistema no controla el escáner', () => {
  const t = DESCRIPCION_TIPO_CAPTURA.ESCANER.texto;
  assert.match(t, /papel/);
  assert.match(t, /no controla el escáner/);
  assert.match(t, /PDF, JPG, PNG o TIFF/);
});

test('tipo sugerido por extensión, sin cambiar un tipo que ya admite el archivo', () => {
  assert.equal(tipoSugerido('F001-1.XML', 'PDF'), 'XML');
  assert.equal(tipoSugerido('factura.pdf', 'XML'), 'PDF');
  assert.equal(tipoSugerido('factura.pdf', 'ESCANER'), 'ESCANER');
  assert.equal(tipoSugerido('foto.jpeg', 'XML'), 'IMAGEN');
  assert.equal(tipoSugerido('scan.tiff', 'PDF'), 'ESCANER');
  assert.equal(tipoSugerido('raro.exe', 'PDF'), 'PDF');
});

test('validación previa: extensión, vacío y tamaño (el backend vuelve a validar el contenido)', () => {
  assert.equal(validarArchivoCaptura({ name: 'f.xml', size: 10 }, 'XML'), null);
  assert.equal(validarArchivoCaptura({ name: 'scan.tif', size: 10 }, 'ESCANER'), null);
  assert.match(validarArchivoCaptura({ name: 'scan.tif', size: 10 }, 'IMAGEN') ?? '', /Formatos permitidos: \.jpg, \.jpeg, \.png/);
  assert.match(validarArchivoCaptura({ name: 'virus.exe', size: 10 }, 'PDF') ?? '', /no es válido/);
  assert.match(validarArchivoCaptura({ name: 'sinextension', size: 10 }, 'PDF') ?? '', /no es válido/);
  assert.match(validarArchivoCaptura({ name: '../../etc/passwd', size: 10 }, 'XML') ?? '', /no es válido/);
  assert.equal(validarArchivoCaptura({ name: 'v.xml', size: 0 }, 'XML'), 'El archivo está vacío.');
  assert.equal(validarArchivoCaptura({ name: 'g.pdf', size: CAPTURA_MAX_BYTES }, 'PDF'), null);
  assert.match(validarArchivoCaptura({ name: 'g.pdf', size: CAPTURA_MAX_BYTES + 1 }, 'PDF') ?? '', /tamaño máximo permitido \(10 MB\)/);
});

test('flujo: Archivo → … → Crear comprobante; con borrador queda en el último paso', () => {
  assert.deepEqual([...PASOS_CAPTURA], ['Archivo', 'Extracción', 'Vista previa', 'Validación', 'Homologación', 'Crear comprobante']);
  assert.equal(pasoActualCaptura(null), 0);
  assert.equal(pasoActualCaptura({ documento_id: null }), 3);
  assert.equal(pasoActualCaptura({ documento_id: 157 }), 5);
});

test('errores de captura/homologación en lista (DRF) se muestran completos y con etiqueta legible', async () => {
  const { mensajesDeErrorApi } = await import('./errores.ts');
  const err = (data: unknown) => ({ response: { data } });
  // Duplicado: el backend responde una lista sin clave; antes mensajeDeError(['detail','periodo']) lo perdía.
  assert.deepEqual(mensajesDeErrorApi(err(["Ya existe un comprobante registrado con RUC emisor '20555000111', serie 'F001' y número '7001'."]), 'x'),
    ["Ya existe un comprobante registrado con RUC emisor '20555000111', serie 'F001' y número '7001'."]);
  assert.deepEqual(mensajesDeErrorApi(err({ codigo_externo: ['Ya existe una equivalencia activa para este proveedor'] }), 'x'),
    ['Código externo: Ya existe una equivalencia activa para este proveedor']);
  assert.deepEqual(mensajesDeErrorApi(err({ archivo: ['El contenido no corresponde a un archivo .pdf válido.'] }), 'x'),
    ['Archivo: El contenido no corresponde a un archivo .pdf válido.']);
  assert.deepEqual(mensajesDeErrorApi(err({ ruc_cliente: 'El comprobante no corresponde a la empresa activa' }), 'x'),
    ['RUC cliente: El comprobante no corresponde a la empresa activa']);
});
