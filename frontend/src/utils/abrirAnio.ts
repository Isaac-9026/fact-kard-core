/**
 * «Abrir año» (Configuración → Períodos e IGV): lógica de la pantalla sin React.
 * Los meses los crea y valida el backend; aquí solo se arma la selección y los textos.
 */
import type { MesAnio, ResultadoAbrirAnio, VistaPreviaAnio } from '../api/periodos.ts';

export const ANIO_MINIMO = 2000;

export const anioMaximo = (hoy: Date = new Date()): number => hoy.getFullYear() + 1;

export const anioValido = (anio: number, hoy: Date = new Date()): boolean =>
  Number.isInteger(anio) && anio >= ANIO_MINIMO && anio <= anioMaximo(hoy);

/** Por defecto se marcan todos los meses que faltan. */
export const seleccionInicial = (previa: VistaPreviaAnio): number[] => [...previa.faltantes];

/** Marca o desmarca un mes; los que ya existen no se pueden elegir. */
export const alternarMes = (previa: VistaPreviaAnio, seleccion: number[], mes: number): number[] => {
  if (!previa.faltantes.includes(mes)) return seleccion;
  return seleccion.includes(mes) ? seleccion.filter((m) => m !== mes) : [...seleccion, mes].sort((a, b) => a - b);
};

/** Solo los meses que faltan desde `desde` hasta diciembre (p. ej. una empresa que empezó en julio). */
export const seleccionDesde = (previa: VistaPreviaAnio, desde: number): number[] =>
  previa.faltantes.filter((m) => m >= desde);

export const mesesElegidos = (previa: VistaPreviaAnio, seleccion: number[]): MesAnio[] =>
  previa.meses.filter((m) => !m.existe && seleccion.includes(m.mes));

/** Meses elegidos con días sin vigencia de IGV (advertencia: no impide abrir). */
export const elegidosSinIgv = (previa: VistaPreviaAnio, seleccion: number[]): MesAnio[] =>
  mesesElegidos(previa, seleccion).filter((m) => !m.igv.cubierto);

export const textoResumen = (previa: VistaPreviaAnio, seleccion: number[]): string => {
  const elegidos = mesesElegidos(previa, seleccion);
  if (!elegidos.length) return 'No hay meses seleccionados.';
  const lista = elegidos.map((m) => m.nombre.toLowerCase()).join(', ');
  return `Se ${elegidos.length === 1 ? 'creará 1 mes' : `crearán ${elegidos.length} meses`} de ${previa.anio}: ${lista}.`;
};

export const textoResultado = (r: ResultadoAbrirAnio): string => {
  const creados = r.total_creados === 1 ? 'se creó 1 mes' : `se crearon ${r.total_creados} meses`;
  const existentes = r.total_existentes === 1 ? '1 ya existía' : `${r.total_existentes} ya existían`;
  return `Año ${r.anio}: ${creados}; ${existentes}.`;
};
