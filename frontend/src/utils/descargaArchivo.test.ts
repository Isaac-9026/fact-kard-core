import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  ESPERA_LIBERAR_MS, ErrorExportacion, TIPO_XLSX, URL_EXCEL_FORMATO131, descargarBlob, esXlsx, exportarExcelFormato131,
  mensajeErrorExportacion, nombreArchivoFormato131, nombreSeguro, type EntornoDescarga,
} from './descargaArchivo.ts';

// Contenido mínimo con la firma ZIP ("PK") de un .xlsx.
const xlsx = () => new Blob([new Uint8Array([0x50, 0x4b, 0x03, 0x04, 1, 2, 3])], { type: TIPO_XLSX });

/** Navegador simulado: solo lo que usa la descarga (enlace, URL de objetos y temporizador). */
function navegador() {
  const ev: string[] = [];
  const pendientes: Array<() => void> = [];
  const enlace = {
    href: '', download: '', rel: '', style: {} as Record<string, string>,
    click: () => ev.push(`click:${enlace.download}:${enlace.href}`),
    remove: () => ev.push('remove'),
  };
  const entorno: EntornoDescarga = {
    document: {
      createElement: () => enlace as unknown as HTMLAnchorElement,
      body: { appendChild: () => ev.push('append') } as unknown as HTMLElement,
    } as unknown as EntornoDescarga['document'],
    URL: {
      createObjectURL: (b: Blob) => { ev.push(`create:${b.type}:${b.size}`); return 'blob:qa/1'; },
      revokeObjectURL: (u: string) => ev.push(`revoke:${u}`),
    } as unknown as EntornoDescarga['URL'],
    setTimeout: (fn: () => void, ms: number) => { ev.push(`timer:${ms}`); pendientes.push(fn); return 0; },
  };
  return { ev, entorno, liberar: () => pendientes.forEach((f) => f()) };
}

test('nombre de archivo descriptivo y seguro', () => {
  assert.equal(nombreArchivoFormato131({ periodo: '2026-01', ruc: '20999000003' }), 'Formato_13_1_2026-01_20999000003.xlsx');
  assert.equal(nombreArchivoFormato131({ periodo: '2026-10' }), 'Formato_13_1_2026-10.xlsx');
  assert.equal(nombreSeguro('../a\\b:c/d EMPRESA S.A.C.'), 'a_b_c_d_EMPRESA_S.A.C');
  assert.equal(nombreSeguro('Ñandú Comercial'), 'Nandu_Comercial');
  assert.ok(nombreSeguro('x'.repeat(500)).length <= 80);
  assert.equal(nombreSeguro('///'), 'archivo');
});

test('la descarga crea la URL del Blob, hace click con el nombre y la libera DESPUÉS (no en el mismo click)', () => {
  const { ev, entorno, liberar } = navegador();
  descargarBlob(xlsx(), 'Formato_13_1_2026-01_20999000003.xlsx', entorno);
  assert.deepEqual(ev, [
    `create:${TIPO_XLSX}:7`, 'append', 'click:Formato_13_1_2026-01_20999000003.xlsx:blob:qa/1', 'remove', `timer:${ESPERA_LIBERAR_MS}`,
  ]);
  assert.ok(!ev.some((e) => e.startsWith('revoke')), 'antes se liberaba en el mismo instante del click');
  liberar();
  assert.equal(ev.at(-1), 'revoke:blob:qa/1');
});

test('el botón llama al endpoint del Excel pidiendo binario y dispara la descarga', async () => {
  const { ev, entorno } = navegador();
  const llamadas: unknown[] = [];
  const get = async (url: string, config: unknown) => { llamadas.push([url, config]); return { data: xlsx() }; };
  await exportarExcelFormato131(get, { periodo_id: 5, producto_id: 9, establecimiento_id: '' }, 'Formato_13_1_2026-01_1.xlsx', entorno);
  assert.deepEqual(llamadas, [[URL_EXCEL_FORMATO131, { params: { periodo_id: 5, producto_id: 9 }, responseType: 'blob' }]]);
  assert.equal(URL_EXCEL_FORMATO131, '/reportes/formato-13-1/excel/');
  assert.ok(ev.includes('click:Formato_13_1_2026-01_1.xlsx:blob:qa/1'));
});

test('no descarga como .xlsx algo que no es un Excel (HTML o JSON con código 200)', async () => {
  const { ev, entorno } = navegador();
  const html = async () => ({ data: new Blob(['<!doctype html><html>'], { type: 'text/html' }) });
  await assert.rejects(exportarExcelFormato131(html, { periodo_id: 5 }, 'x.xlsx', entorno), ErrorExportacion);
  assert.equal(ev.length, 0);
  assert.equal(await esXlsx(new Blob([])), false);
  assert.equal(await esXlsx(xlsx()), true);
});

test('error de la API: el Blob se lee y se muestra "No se pudo exportar el Formato 13.1." con el detalle', async () => {
  const blobJson = new Blob([JSON.stringify({ periodo_id: ['El período no existe o no pertenece a la empresa activa.'] })], { type: 'application/json' });
  assert.equal(
    await mensajeErrorExportacion({ response: { status: 400, data: blobJson } }),
    'No se pudo exportar el Formato 13.1. El período no existe o no pertenece a la empresa activa.',
  );
  const blobDetalle = new Blob([JSON.stringify({ detail: 'No tiene acceso a esta empresa.' })]);
  assert.equal(await mensajeErrorExportacion({ response: { status: 403, data: blobDetalle } }), 'No se pudo exportar el Formato 13.1. No tiene acceso a esta empresa.');
});

test('error sin JSON (502 de Nginx, 500 con HTML): mensaje visible, sin mostrar el HTML ni trazas', async () => {
  const html = new Blob(['<html><body>Traceback (most recent call last): secreto</body></html>'], { type: 'text/html' });
  const m = await mensajeErrorExportacion({ response: { status: 502, data: html } });
  assert.equal(m, 'No se pudo exportar el Formato 13.1. El servidor respondió con el código 502.');
  assert.ok(!m.includes('Traceback'));
  assert.equal(await mensajeErrorExportacion(new Error('Network Error')), 'No se pudo exportar el Formato 13.1. No se pudo contactar al servidor.');
  assert.equal(await mensajeErrorExportacion(new ErrorExportacion('La respuesta del servidor no es un archivo Excel válido.')),
    'No se pudo exportar el Formato 13.1. La respuesta del servidor no es un archivo Excel válido.');
});

test('el mensaje nunca queda vacío (antes Object.values(blob) daba "" y no se veía nada)', async () => {
  assert.deepEqual(Object.values(new Blob(['x'])), []); // la causa original
  for (const error of [{ response: { status: 500, data: new Blob(['']) } }, { response: {} }, null]) {
    assert.ok((await mensajeErrorExportacion(error)).startsWith('No se pudo exportar el Formato 13.1.'));
  }
});
