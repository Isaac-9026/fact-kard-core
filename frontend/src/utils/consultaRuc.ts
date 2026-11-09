/**
 * Bloque 17C — lógica pura de "Consultar RUC" (probada con node --test).
 * La consulta es una AYUDA: nunca guarda, nunca reemplaza datos escritos sin que el usuario
 * vea la vista previa y pulse "Aplicar", y si falla el formulario sigue siendo manual.
 */
import { errorDocumentoIdentidad } from './finanzas.ts';

export interface DatosRucMinimos {
  ruc: string;
  razon_social: string;
  nombre_comercial: string | null;
  direccion: string | null;
  ubigeo: string | null;
  departamento: string | null;
  provincia: string | null;
  distrito: string | null;
  estado: string | null;
  condicion: string | null;
}
export interface ResultadoRuc {
  datos: DatosRucMinimos;
  advertencias: string[];
  proveedor: string;
  oficial: boolean;
  fuente?: string | null;
  actualizado_al?: string | null;
}

/** Validación local previa (misma regla que el backend: catálogo 06 + dígito verificador). */
export function errorRucLocal(ruc: string): string | null {
  return errorDocumentoIdentidad('6', ruc);
}

export const MENSAJES_CONSULTA_RUC: Record<string, string> = {
  RUC_INVALIDO: 'RUC inválido.',
  RUC_NO_ENCONTRADO: 'RUC no encontrado. Puede registrar los datos manualmente.',
  SERVICIO_NO_DISPONIBLE: 'Servicio temporalmente no disponible. Puede registrar los datos manualmente.',
  RESPUESTA_INCOMPLETA: 'La consulta devolvió datos incompletos. Complete los datos manualmente.',
  PROVEEDOR_RUC_NO_CONFIGURADO: 'La consulta RUC no está configurada en el servidor. Registre los datos manualmente.',
  PADRON_RUC_NO_CARGADO: 'El padrón SUNAT todavía no ha sido importado. Registre los datos manualmente.',
  LIMITE_CONSULTAS: 'Demasiadas consultas seguidas. Espere un momento o registre los datos manualmente.',
  SIN_PERMISO: 'No tiene permiso para consultar RUC.',
};

/** Código de error a partir de la respuesta de la API (o de un fallo de red). */
export function codigoErrorConsulta(error: unknown): string {
  const r = (error as { response?: { status?: number; data?: { codigo?: string } } } | null)?.response;
  if (r?.data?.codigo && MENSAJES_CONSULTA_RUC[r.data.codigo]) return r.data.codigo;
  if (r?.status === 429) return 'LIMITE_CONSULTAS';
  if (r?.status === 403) return 'SIN_PERMISO';
  if (r?.status === 400) return 'RUC_INVALIDO';
  if (r?.status === 404) return 'RUC_NO_ENCONTRADO';
  return 'SERVICIO_NO_DISPONIBLE';
}

// ---- Estado del botón -------------------------------------------------------------------------
// Cada consulta y cada resultado guardan el RUC con el que se pidieron: un resultado solo vale
// para ESE número. Si el RUC del formulario cambia, el resultado anterior se descarta y hay que
// consultar de nuevo (auditoría 17C, MEDIO-1).
export type EstadoConsulta =
  | { fase: 'inactivo' }
  | { fase: 'consultando'; ruc: string }
  | { fase: 'encontrado'; ruc: string; resultado: ResultadoRuc }
  | { fase: 'error'; codigo: string; mensaje: string };

export type EventoConsulta =
  | { tipo: 'CONSULTAR'; ruc: string }
  | { tipo: 'EXITO'; ruc: string; resultado: ResultadoRuc }
  | { tipo: 'ERROR'; codigo: string; mensaje?: string; ruc?: string }
  | { tipo: 'RUC_CAMBIADO'; ruc: string }
  | { tipo: 'APLICAR' }
  | { tipo: 'CANCELAR' };

/** El RUC tal como se compara: sin espacios alrededor (el backend devuelve 11 dígitos). */
export const rucNormalizado = (ruc: string | null | undefined) => String(ruc ?? '').trim();

/** Un resultado solo puede aplicarse sobre el mismo RUC que tiene ahora el formulario. */
export function puedeAplicarResultado(resultado: ResultadoRuc | null | undefined, rucActual: string): boolean {
  const actual = rucNormalizado(rucActual);
  return Boolean(resultado && actual !== '' && rucNormalizado(resultado.datos.ruc) === actual);
}

/** Resultado vigente para el RUC actual del formulario, o null (consulta vieja o de otro número). */
export function resultadoAplicable(estado: EstadoConsulta, rucActual: string): ResultadoRuc | null {
  if (estado.fase !== 'encontrado') return null;
  if (estado.ruc !== rucNormalizado(rucActual)) return null;
  return puedeAplicarResultado(estado.resultado, rucActual) ? estado.resultado : null;
}

export function reducirConsulta(estado: EstadoConsulta, evento: EventoConsulta): EstadoConsulta {
  switch (evento.tipo) {
    case 'CONSULTAR': return { fase: 'consultando', ruc: rucNormalizado(evento.ruc) };
    case 'EXITO': {
      const ruc = rucNormalizado(evento.ruc);
      // Respuesta tardía de una consulta anterior (el RUC cambió o se canceló): se ignora.
      if (estado.fase !== 'consultando' || estado.ruc !== ruc) return estado;
      // La fuente respondió por otro número: no se muestra ni se puede aplicar.
      if (!puedeAplicarResultado(evento.resultado, ruc)) {
        return { fase: 'error', codigo: 'RESPUESTA_INCOMPLETA', mensaje: MENSAJES_CONSULTA_RUC.RESPUESTA_INCOMPLETA };
      }
      return { fase: 'encontrado', ruc, resultado: evento.resultado };
    }
    case 'ERROR':
      if (evento.ruc !== undefined && (estado.fase !== 'consultando' || estado.ruc !== rucNormalizado(evento.ruc))) return estado;
      return { fase: 'error', codigo: evento.codigo, mensaje: evento.mensaje || MENSAJES_CONSULTA_RUC[evento.codigo] || MENSAJES_CONSULTA_RUC.SERVICIO_NO_DISPONIBLE };
    case 'RUC_CAMBIADO':
      if (estado.fase === 'inactivo') return estado;
      if ((estado.fase === 'consultando' || estado.fase === 'encontrado') && estado.ruc === rucNormalizado(evento.ruc)) return estado;
      return { fase: 'inactivo' };
    case 'APLICAR':
    case 'CANCELAR': return { fase: 'inactivo' };
  }
}

/**
 * ¿Mostrar "Consultar RUC"? El endpoint exige empresa activa y rol ADMIN en ella (o admin
 * global); sin eso el botón terminaría siempre en 403, así que no se muestra (MEDIO-2).
 */
export function puedeConsultarRuc(empresaActiva: { rol?: string | null } | null | undefined, esAdminGlobal?: boolean | null): boolean {
  if (!empresaActiva) return false;
  return Boolean(esAdminGlobal) || empresaActiva.rol === 'ADMIN';
}

export const ETIQUETA_FASE: Record<EstadoConsulta['fase'], string> = {
  inactivo: '', consultando: 'Consultando...', encontrado: 'Datos encontrados', error: '',
};

// ---- Fuente y situación del contribuyente (Bloque 17D) ------------------------------------------
/** 'YYYY-MM-DD' → 'DD/MM/YYYY' sin pasar por Date (evita corrimientos de zona horaria). */
export function fechaCorta(iso: string | null | undefined): string | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? '');
  return m ? `${m[3]}/${m[2]}/${m[1]}` : null;
}

/** Texto de la fuente. El padrón es oficial pero es una copia local: se indica su fecha, nunca "en línea". */
export function descripcionFuente(r: Pick<ResultadoRuc, 'oficial' | 'fuente' | 'actualizado_al'>): string {
  if (!r.oficial) return 'Datos de prueba (no oficiales)';
  const fecha = fechaCorta(r.actualizado_al);
  return `Fuente oficial: ${r.fuente || 'Padrón Reducido SUNAT'}${fecha ? ` (actualizado al ${fecha})` : ''}`;
}

export interface EtiquetaContribuyente { etiqueta: string; valor: string; ok: boolean }

/** Estado y condición tal como vienen; no ACTIVO / no HABIDO se marcan (solo aviso, nunca bloquean). */
export function etiquetasContribuyente(r: Pick<ResultadoRuc, 'oficial' | 'datos'>): EtiquetaContribuyente[] {
  const sufijo = r.oficial ? ' SUNAT' : '';
  const filas: EtiquetaContribuyente[] = [];
  if (r.datos.estado) filas.push({ etiqueta: `Estado${sufijo}`, valor: r.datos.estado, ok: r.datos.estado === 'ACTIVO' });
  if (r.datos.condicion) filas.push({ etiqueta: `Condición${sufijo}`, valor: r.datos.condicion, ok: r.datos.condicion === 'HABIDO' });
  return filas;
}

export interface EstadoFuenteRuc {
  proveedor: string | null; configurado: boolean; oficial: boolean; fuente: string | null; disponible: boolean;
  registros: number | null; fecha_padron: string | null; fecha_importacion: string | null;
}
export interface FilaEstadoFuente { etiqueta: string; valor: string; ok: boolean }

/** Filas del recuadro administrativo "Consulta RUC" (solo metadatos). */
export function filasEstadoConsultaRuc(e: EstadoFuenteRuc): FilaEstadoFuente[] {
  if (!e.configurado) return [{ etiqueta: 'Estado', valor: 'No configurada (registro manual)', ok: false }];
  const filas: FilaEstadoFuente[] = [
    { etiqueta: 'Fuente', valor: e.oficial ? (e.fuente || 'Padrón Reducido SUNAT') : (e.fuente || 'Datos de prueba (no oficiales)'), ok: e.oficial },
    { etiqueta: 'Estado', valor: e.disponible ? 'Disponible' : 'No cargado', ok: e.disponible },
  ];
  if (e.oficial && e.disponible) {
    filas.push({ etiqueta: 'Padrón actualizado al', valor: fechaCorta(e.fecha_padron) ?? 'Desconocido', ok: true });
    filas.push({ etiqueta: 'Última importación', valor: fechaCorta(e.fecha_importacion) ?? '—', ok: true });
    filas.push({ etiqueta: 'Registros', valor: (e.registros ?? 0).toLocaleString('es-PE'), ok: true });
  }
  return filas;
}

// ---- Vista previa y aplicación ------------------------------------------------------------------
export type CampoRuc = keyof Omit<DatosRucMinimos, 'ruc' | 'estado' | 'condicion'>;
export interface CampoMapeado { campoFormulario: string; campoRuc: CampoRuc; etiqueta: string }

const ETIQUETAS: Record<CampoRuc, string> = {
  razon_social: 'Razón social', nombre_comercial: 'Nombre comercial', direccion: 'Dirección fiscal', ubigeo: 'Ubigeo',
  departamento: 'Departamento', provincia: 'Provincia', distrito: 'Distrito',
};
const mapa = (...campos: CampoRuc[]): CampoMapeado[] =>
  campos.map((c) => ({ campoFormulario: c, campoRuc: c, etiqueta: ETIQUETAS[c] }));

/** Campos que cada formulario existente puede recibir (los nombres ya coinciden con los del modelo). */
export const MAPA_EMPRESA_NUEVA = mapa('razon_social', 'nombre_comercial', 'direccion');
export const MAPA_DATOS_FISCALES = mapa('razon_social', 'nombre_comercial', 'direccion', 'ubigeo', 'departamento', 'provincia', 'distrito');
export const MAPA_TERCERO = mapa('razon_social', 'nombre_comercial', 'direccion');

export interface CambioPropuesto { campoFormulario: string; etiqueta: string; actual: string; nuevo: string; sobrescribe: boolean }

/** Solo campos con dato encontrado y distinto del actual. `sobrescribe` = reemplaza algo ya escrito. */
export function cambiosPropuestos(
  formulario: Record<string, unknown>, datos: DatosRucMinimos, campos: readonly CampoMapeado[],
): CambioPropuesto[] {
  return campos.flatMap(({ campoFormulario, campoRuc, etiqueta }) => {
    const nuevo = datos[campoRuc];
    if (nuevo === null || nuevo === undefined || String(nuevo).trim() === '') return [];
    const actual = String(formulario[campoFormulario] ?? '').trim();
    if (actual === nuevo) return [];
    return [{ campoFormulario, etiqueta, actual, nuevo, sobrescribe: actual !== '' }];
  });
}

export const cuantosSobrescriben = (cambios: readonly CambioPropuesto[]) => cambios.filter((c) => c.sobrescribe).length;

/** Formulario con los cambios aplicados (los demás campos quedan intactos). */
export function aplicarCambios<T extends Record<string, unknown>>(formulario: T, cambios: readonly CambioPropuesto[]): T {
  const copia: Record<string, unknown> = { ...formulario };
  for (const c of cambios) copia[c.campoFormulario] = c.nuevo;
  return copia as T;
}
