import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  ETIQUETA_FASE, MAPA_DATOS_FISCALES, MAPA_EMPRESA_NUEVA, MAPA_TERCERO, MENSAJES_CONSULTA_RUC, aplicarCambios,
  cambiosPropuestos, codigoErrorConsulta, cuantosSobrescriben, descripcionFuente, errorRucLocal, etiquetasContribuyente,
  fechaCorta, filasEstadoConsultaRuc, puedeAplicarResultado, puedeConsultarRuc,
  reducirConsulta, resultadoAplicable,
  type EstadoConsulta, type ResultadoRuc,
} from './consultaRuc.ts';

// Datos FICTICIOS (RUC con dígito verificador válido).
const RESULTADO: ResultadoRuc = {
  proveedor: 'MOCK_DESARROLLO', oficial: false, advertencias: [],
  datos: {
    ruc: '20999999019', razon_social: 'EMPRESA FICTICIA DEMO S.A.C.', nombre_comercial: 'DEMO FICTICIA',
    direccion: 'AV. FICTICIA 123', ubigeo: '150101', departamento: 'LIMA', provincia: 'LIMA', distrito: 'LIMA',
    estado: 'ACTIVO', condicion: 'HABIDO',
  },
};
const INICIAL: EstadoConsulta = { fase: 'inactivo' };
const fuente = (ruta: string) => readFileSync(new URL(ruta, import.meta.url), 'utf8');

test('botón Consultar RUC presente en Empresa (nueva y datos fiscales) y en Tercero (solo con RUC)', () => {
  assert.match(fuente('../pages/empresas/EmpresasPage.tsx'), /<ConsultaRucBoton ruc=\{empresaForm\.ruc\}[^>]*MAPA_EMPRESA_NUEVA/);
  assert.match(fuente('../components/tributario/DatosFiscalesPanel.tsx'), /<ConsultaRucBoton ruc=\{datos\.ruc\}[^>]*MAPA_DATOS_FISCALES/);
  assert.match(fuente('../pages/inventario/MaestrosInventarioPage.tsx'),
    /terceroForm\.tipo_documento === '6' && \(\s*<ConsultaRucBoton ruc=\{terceroForm\.numero_documento\}[^>]*MAPA_TERCERO/);
  assert.match(fuente('../components/consultaRuc/ConsultaRucBoton.tsx'), /Consultar RUC/);
});

test('loading: "Consultando..." mientras espera; luego "Datos encontrados"', () => {
  const consultando = reducirConsulta(INICIAL, { tipo: 'CONSULTAR', ruc: '20999999019' });
  assert.equal(consultando.fase, 'consultando');
  assert.equal(ETIQUETA_FASE.consultando, 'Consultando...');
  const encontrado = reducirConsulta(consultando, { tipo: 'EXITO', ruc: '20999999019', resultado: RESULTADO });
  assert.equal(encontrado.fase, 'encontrado');
  assert.equal(ETIQUETA_FASE.encontrado, 'Datos encontrados');
});

test('respuesta exitosa sobre formulario vacío: propone los campos disponibles', () => {
  const cambios = cambiosPropuestos({ ruc: '20999999019', razon_social: '', nombre_comercial: '', direccion: '' }, RESULTADO.datos, MAPA_EMPRESA_NUEVA);
  assert.deepEqual(cambios.map((c) => [c.campoFormulario, c.nuevo, c.sobrescribe]), [
    ['razon_social', 'EMPRESA FICTICIA DEMO S.A.C.', false], ['nombre_comercial', 'DEMO FICTICIA', false], ['direccion', 'AV. FICTICIA 123', false],
  ]);
});

test('aplicar datos: solo cambia los campos propuestos y el estado vuelve a inactivo', () => {
  const form = { ruc: '20999999019', razon_social: '', nombre_comercial: '', direccion: '', moneda_base_codigo: 'PEN' };
  const nuevo = aplicarCambios(form, cambiosPropuestos(form, RESULTADO.datos, MAPA_EMPRESA_NUEVA));
  assert.deepEqual(nuevo, { ruc: '20999999019', razon_social: 'EMPRESA FICTICIA DEMO S.A.C.', nombre_comercial: 'DEMO FICTICIA',
    direccion: 'AV. FICTICIA 123', moneda_base_codigo: 'PEN' });
  assert.deepEqual(form.razon_social, '');  // el original no se muta
  assert.equal(reducirConsulta({ fase: 'encontrado', ruc: '20999999019', resultado: RESULTADO }, { tipo: 'APLICAR' }).fase, 'inactivo');
});

test('cancelar: no cambia nada', () => {
  assert.deepEqual(reducirConsulta({ fase: 'encontrado', ruc: '20999999019', resultado: RESULTADO }, { tipo: 'CANCELAR' }), { fase: 'inactivo' });
});

test('no sobrescribir sin confirmación: lo ya escrito se marca como reemplazo', () => {
  const form = { razon_social: 'MI NOMBRE ESCRITO', nombre_comercial: 'DEMO FICTICIA', direccion: '', ubigeo: '', departamento: '',
    provincia: '', distrito: '', codigo_pais: 'PE' };
  const cambios = cambiosPropuestos(form, RESULTADO.datos, MAPA_DATOS_FISCALES);
  assert.equal(cuantosSobrescriben(cambios), 1);
  assert.deepEqual(cambios.find((c) => c.sobrescribe), { campoFormulario: 'razon_social', etiqueta: 'Razón social',
    actual: 'MI NOMBRE ESCRITO', nuevo: 'EMPRESA FICTICIA DEMO S.A.C.', sobrescribe: true });
  assert.ok(!cambios.some((c) => c.campoFormulario === 'nombre_comercial'));  // igual: no se propone
  assert.match(fuente('../components/consultaRuc/ConsultaRucBoton.tsx'), /reemplaza \$\{reemplazos\} campo/);
});

test('campos nulos de la fuente no borran ni inventan datos', () => {
  const parcial = { ...RESULTADO.datos, nombre_comercial: null, direccion: null, ubigeo: null };
  const cambios = cambiosPropuestos({ razon_social: '', nombre_comercial: 'ESCRITO', direccion: 'CALLE 9' }, parcial, MAPA_TERCERO);
  assert.deepEqual(cambios.map((c) => c.campoFormulario), ['razon_social']);
});

test('RUC inválido: se detecta antes de llamar al backend', () => {
  assert.match(errorRucLocal('123') ?? '', /11 dígitos/);
  assert.match(errorRucLocal('20999999012') ?? '', /dígito verificador/);
  assert.equal(errorRucLocal('20999999019'), null);
  assert.equal(codigoErrorConsulta({ response: { status: 400, data: { codigo: 'RUC_INVALIDO' } } }), 'RUC_INVALIDO');
});

test('no encontrado y error de servicio muestran mensajes claros', () => {
  assert.equal(codigoErrorConsulta({ response: { status: 404, data: { codigo: 'RUC_NO_ENCONTRADO' } } }), 'RUC_NO_ENCONTRADO');
  assert.equal(codigoErrorConsulta({ response: { status: 503, data: { codigo: 'PROVEEDOR_RUC_NO_CONFIGURADO' } } }), 'PROVEEDOR_RUC_NO_CONFIGURADO');
  assert.equal(codigoErrorConsulta({ response: { status: 429 } }), 'LIMITE_CONSULTAS');
  assert.equal(codigoErrorConsulta(new Error('Network Error')), 'SERVICIO_NO_DISPONIBLE');
  assert.equal(codigoErrorConsulta({ response: { status: 500, data: '<html>traza</html>' } }), 'SERVICIO_NO_DISPONIBLE');
  const error = reducirConsulta({ fase: 'consultando', ruc: '20999999019' }, { tipo: 'ERROR', codigo: 'SERVICIO_NO_DISPONIBLE' });
  assert.deepEqual(error, { fase: 'error', codigo: 'SERVICIO_NO_DISPONIBLE', mensaje: MENSAJES_CONSULTA_RUC.SERVICIO_NO_DISPONIBLE });
  assert.equal(MENSAJES_CONSULTA_RUC.RUC_NO_ENCONTRADO.startsWith('RUC no encontrado'), true);
  assert.equal(MENSAJES_CONSULTA_RUC.SERVICIO_NO_DISPONIBLE.startsWith('Servicio temporalmente no disponible'), true);
});

test('el formulario manual sigue funcionando: los errores no tocan el formulario ni lo bloquean', () => {
  for (const codigo of ['RUC_NO_ENCONTRADO', 'SERVICIO_NO_DISPONIBLE', 'PROVEEDOR_RUC_NO_CONFIGURADO', 'RESPUESTA_INCOMPLETA']) {
    assert.match(MENSAJES_CONSULTA_RUC[codigo], /manualmente/);
  }
  // Un nuevo intento siempre es posible desde el estado de error.
  assert.equal(reducirConsulta({ fase: 'error', codigo: 'X', mensaje: 'x' }, { tipo: 'CONSULTAR', ruc: '20999999019' }).fase, 'consultando');
  // El botón solo se deshabilita mientras consulta; los campos del formulario no dependen de la consulta.
  assert.match(fuente('../components/consultaRuc/ConsultaRucBoton.tsx'), /disabled=\{deshabilitado \|\| estado\.fase === 'consultando'\}/);
});

test('seguridad: la consulta pasa por el backend y no envía credenciales', () => {
  const api = fuente('../api/consultaRuc.ts');
  assert.match(api, /apiClient\.get<ResultadoConsultaRuc>\(`\/consulta-ruc\//);
  assert.doesNotMatch(api, /https?:\/\/|sunat\.gob|clave|password|usuario_sol|token/i);
});

// ---- Auditoría 17C, MEDIO-1: un resultado solo vale para el RUC con el que se consultó --------
const RUC_A = '20999999019';
const RUC_B = '20999999027';  // otro RUC válido (ficticio)
const A = (ruc = RUC_A): ResultadoRuc => ({ ...RESULTADO, datos: { ...RESULTADO.datos, ruc } });
const FORM_B = { ruc: RUC_B, razon_social: '', nombre_comercial: '', direccion: '' };

test('RUC cambiado: el resultado de A no se puede aplicar sobre B y hay que consultar de nuevo', () => {
  // 1-2. consultar A y obtener el resultado de A
  let estado = reducirConsulta(INICIAL, { tipo: 'CONSULTAR', ruc: RUC_A });
  estado = reducirConsulta(estado, { tipo: 'EXITO', ruc: RUC_A, resultado: A() });
  assert.equal(estado.fase, 'encontrado');
  assert.equal(resultadoAplicable(estado, RUC_A)?.datos.ruc, RUC_A);
  // 3-4. el usuario cambia el input a B: el resultado de A ya no es aplicable (ni antes ni después de invalidar)
  assert.equal(resultadoAplicable(estado, RUC_B), null);
  assert.equal(puedeAplicarResultado(A(), RUC_B), false);
  estado = reducirConsulta(estado, { tipo: 'RUC_CAMBIADO', ruc: RUC_B });
  assert.deepEqual(estado, { fase: 'inactivo' });
  // 5. volver a escribir A tampoco resucita la vista previa: hay que consultar otra vez
  assert.equal(resultadoAplicable(estado, RUC_A), null);
  // 6. una consulta nueva de B sí puede aplicarse, y solo con el RUC actual
  estado = reducirConsulta(estado, { tipo: 'CONSULTAR', ruc: RUC_B });
  estado = reducirConsulta(estado, { tipo: 'EXITO', ruc: RUC_B, resultado: A(RUC_B) });
  const vigente = resultadoAplicable(estado, ` ${RUC_B} `);
  assert.equal(vigente?.datos.ruc, RUC_B);
  assert.equal(aplicarCambios(FORM_B, cambiosPropuestos(FORM_B, vigente!.datos, MAPA_EMPRESA_NUEVA)).ruc, RUC_B);
});

test('respuesta tardía: si el RUC cambió mientras se consultaba, el resultado de A se descarta', () => {
  let estado = reducirConsulta(INICIAL, { tipo: 'CONSULTAR', ruc: RUC_A });
  estado = reducirConsulta(estado, { tipo: 'RUC_CAMBIADO', ruc: RUC_B });
  assert.deepEqual(estado, { fase: 'inactivo' });
  assert.deepEqual(reducirConsulta(estado, { tipo: 'EXITO', ruc: RUC_A, resultado: A() }), { fase: 'inactivo' });
  assert.deepEqual(reducirConsulta(estado, { tipo: 'ERROR', ruc: RUC_A, codigo: 'RUC_NO_ENCONTRADO' }), { fase: 'inactivo' });
  // Con otra consulta en curso (B), la respuesta de A tampoco la pisa.
  const enCursoB = reducirConsulta(estado, { tipo: 'CONSULTAR', ruc: RUC_B });
  assert.deepEqual(reducirConsulta(enCursoB, { tipo: 'EXITO', ruc: RUC_A, resultado: A() }), enCursoB);
});

test('la fuente devuelve otro RUC del consultado: no se muestra ni se aplica', () => {
  const enCurso = reducirConsulta(INICIAL, { tipo: 'CONSULTAR', ruc: RUC_A });
  const estado = reducirConsulta(enCurso, { tipo: 'EXITO', ruc: RUC_A, resultado: A(RUC_B) });
  assert.equal(estado.fase, 'error');
  assert.equal(resultadoAplicable(estado, RUC_A), null);
  assert.equal(resultadoAplicable(estado, RUC_B), null);
});

test('mismo RUC (con espacios alrededor): el resultado sigue vigente y el error anterior se limpia al cambiar', () => {
  const encontrado: EstadoConsulta = { fase: 'encontrado', ruc: RUC_A, resultado: A() };
  assert.equal(reducirConsulta(encontrado, { tipo: 'RUC_CAMBIADO', ruc: ` ${RUC_A} ` }), encontrado);
  assert.equal(puedeAplicarResultado(A(), ` ${RUC_A}`), true);
  assert.equal(puedeAplicarResultado(A(), ''), false);
  assert.equal(puedeAplicarResultado(null, RUC_A), false);
  const error: EstadoConsulta = { fase: 'error', codigo: 'RUC_NO_ENCONTRADO', mensaje: 'x' };
  assert.deepEqual(reducirConsulta(error, { tipo: 'RUC_CAMBIADO', ruc: RUC_B }), { fase: 'inactivo' });
});

// ---- Auditoría 17C, MEDIO-2: el botón solo se muestra a quien el endpoint atenderá -------------
test('Consultar RUC solo con empresa activa y rol ADMIN (o admin global); el resto sigue manual', () => {
  assert.equal(puedeConsultarRuc(null), false);                      // sin empresa activa (p. ej. primera empresa)
  assert.equal(puedeConsultarRuc(undefined, true), false);           // admin global sin empresa activa: el endpoint exige X-Empresa-Id
  assert.equal(puedeConsultarRuc({ rol: 'USUARIO' }), false);
  assert.equal(puedeConsultarRuc({ rol: 'CONTADOR' }, false), false);
  assert.equal(puedeConsultarRuc({ rol: 'ADMIN' }), true);
  assert.equal(puedeConsultarRuc({ rol: 'USUARIO' }, true), true);   // EsAdminEmpresa acepta admin global
});

// ---- Bloque 17D: padrón reducido SUNAT (oficial, copia local) -----------------------------------
const PADRON: ResultadoRuc = {
  proveedor: 'padron_reducido', oficial: true, fuente: 'Padrón Reducido SUNAT', actualizado_al: '2026-10-31', advertencias: [],
  datos: {
    ruc: '20999999019', razon_social: 'EMPRESA FICTICIA DEMO S.A.C.', nombre_comercial: null, direccion: 'AV. FICTICIA NRO. 123',
    ubigeo: '150101', departamento: null, provincia: null, distrito: null, estado: 'ACTIVO', condicion: 'HABIDO',
  },
};

test('fuente oficial: "Padrón Reducido SUNAT" con su fecha (nunca "consulta en línea"); el mock sigue marcado', () => {
  assert.equal(descripcionFuente(PADRON), 'Fuente oficial: Padrón Reducido SUNAT (actualizado al 31/10/2026)');
  assert.equal(descripcionFuente({ ...PADRON, actualizado_al: null }), 'Fuente oficial: Padrón Reducido SUNAT');
  assert.equal(descripcionFuente(RESULTADO), 'Datos de prueba (no oficiales)');
  assert.doesNotMatch(descripcionFuente(PADRON), /en línea|directa/i);
  assert.equal(fechaCorta('2026-10-31'), '31/10/2026');
  assert.equal(fechaCorta('2026-11-01T03:20:00-05:00'), '01/11/2026');
  assert.equal(fechaCorta(null), null);
  assert.match(fuente('../components/consultaRuc/ConsultaRucBoton.tsx'), /descripcionFuente\(resultado\)/);
});

test('estado y condición SUNAT: se muestran y lo distinto de ACTIVO/HABIDO se marca sin bloquear', () => {
  assert.deepEqual(etiquetasContribuyente(PADRON), [
    { etiqueta: 'Estado SUNAT', valor: 'ACTIVO', ok: true }, { etiqueta: 'Condición SUNAT', valor: 'HABIDO', ok: true }]);
  const baja = { ...PADRON, datos: { ...PADRON.datos, estado: 'BAJA DE OFICIO', condicion: 'NO HALLADO' } };
  assert.deepEqual(etiquetasContribuyente(baja).map((e) => e.ok), [false, false]);
  assert.deepEqual(etiquetasContribuyente(RESULTADO).map((e) => e.etiqueta), ['Estado', 'Condición']);  // el mock no dice "SUNAT"
  assert.deepEqual(etiquetasContribuyente({ ...PADRON, datos: { ...PADRON.datos, estado: null, condicion: null } }), []);
  // No bloquea: un contribuyente en baja igual propone sus datos para aplicar.
  assert.equal(cambiosPropuestos({ razon_social: '' }, baja.datos, MAPA_TERCERO).length, 2);
});

test('padrón: solo llena campos disponibles; departamento/provincia/distrito nulos no se inventan', () => {
  const form = { razon_social: '', nombre_comercial: 'MI COMERCIAL', direccion: '', ubigeo: '', departamento: 'LIMA', provincia: '', distrito: '' };
  const cambios = cambiosPropuestos(form, PADRON.datos, MAPA_DATOS_FISCALES);
  assert.deepEqual(cambios.map((c) => c.campoFormulario), ['razon_social', 'direccion', 'ubigeo']);
  const aplicado = aplicarCambios(form, cambios);
  assert.equal(aplicado.nombre_comercial, 'MI COMERCIAL');  // null en el padrón: no se borra
  assert.equal(aplicado.departamento, 'LIMA');
});

test('padrón no cargado: mensaje propio, distinto de "RUC no encontrado", y el registro manual sigue', () => {
  const codigo = codigoErrorConsulta({ response: { status: 503, data: { codigo: 'PADRON_RUC_NO_CARGADO' } } });
  assert.equal(codigo, 'PADRON_RUC_NO_CARGADO');
  assert.match(MENSAJES_CONSULTA_RUC[codigo], /padrón SUNAT todavía no ha sido importado/);
  assert.match(MENSAJES_CONSULTA_RUC[codigo], /manualmente/);
  assert.notEqual(MENSAJES_CONSULTA_RUC[codigo], MENSAJES_CONSULTA_RUC.RUC_NO_ENCONTRADO);
  const error = reducirConsulta({ fase: 'consultando', ruc: RUC_A }, { tipo: 'ERROR', ruc: RUC_A, codigo });
  assert.equal(error.fase, 'error');
});

test('recuadro administrativo: metadatos del padrón (fuente, estado, fecha, registros)', () => {
  const base = { proveedor: 'padron_reducido', configurado: true, oficial: true, fuente: 'Padrón Reducido SUNAT' };
  assert.deepEqual(filasEstadoConsultaRuc({ ...base, disponible: true, registros: 18501026, fecha_padron: '2026-10-31',
    fecha_importacion: '2026-11-01T03:40:00-05:00' }).map((f) => [f.etiqueta, f.valor]), [
    ['Fuente', 'Padrón Reducido SUNAT'], ['Estado', 'Disponible'], ['Padrón actualizado al', '31/10/2026'],
    ['Última importación', '01/11/2026'], ['Registros', (18501026).toLocaleString('es-PE')]]);
  assert.deepEqual(filasEstadoConsultaRuc({ ...base, disponible: false, registros: 0, fecha_padron: null, fecha_importacion: null })
    .map((f) => [f.etiqueta, f.valor, f.ok]), [['Fuente', 'Padrón Reducido SUNAT', true], ['Estado', 'No cargado', false]]);
  assert.deepEqual(filasEstadoConsultaRuc({ proveedor: null, configurado: false, oficial: false, fuente: null, disponible: false,
    registros: null, fecha_padron: null, fecha_importacion: null }).map((f) => f.valor), ['No configurada (registro manual)']);
  assert.match(fuente('../components/tributario/DatosFiscalesPanel.tsx'), /esAdmin && <ConsultaRucEstadoCard \/>/);
  assert.doesNotMatch(fuente('../components/consultaRuc/ConsultaRucEstadoCard.tsx'), /type="file"|upload|subir/i);
});

test('protección 17C intacta con resultados del padrón: un resultado oficial de A no se aplica sobre B', () => {
  let estado = reducirConsulta(INICIAL, { tipo: 'CONSULTAR', ruc: '20999999019' });
  estado = reducirConsulta(estado, { tipo: 'EXITO', ruc: '20999999019', resultado: PADRON });
  assert.equal(resultadoAplicable(estado, '20999999019')?.oficial, true);
  assert.equal(resultadoAplicable(estado, RUC_B), null);
  assert.deepEqual(reducirConsulta(estado, { tipo: 'RUC_CAMBIADO', ruc: RUC_B }), { fase: 'inactivo' });
});
