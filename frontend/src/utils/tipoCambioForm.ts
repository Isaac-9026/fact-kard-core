import { fechaCalendarioFormulario, fechaCalendarioLocal } from './date.ts';

/**
 * FE-001: el formulario de Tipo de Cambio maneja `fecha_publicacion` como fecha
 * calendario literal (YYYY-MM-DD). Nunca se convierte a UTC ni se recalcula al enviar.
 */
export interface NuevoTipoCambioForm {
  moneda_codigo: string;
  fecha_publicacion: string;
  compra: string;
  venta: string;
  fuente: string;
}

export interface PayloadTipoCambio {
  moneda_codigo: string;
  fecha_publicacion: string;
  compra: string;
  venta: string;
  fuente: string;
}

export const nuevoTipoCambioInicial = (hoy: Date = new Date()): NuevoTipoCambioForm => ({
  moneda_codigo: 'USD',
  fecha_publicacion: fechaCalendarioLocal(hoy),
  compra: '',
  venta: '',
  fuente: 'SBS',
});

export class FechaTipoCambioInvalidaError extends Error {
  constructor() {
    super('Ingrese una fecha de publicación válida (AAAA-MM-DD).');
    this.name = 'FechaTipoCambioInvalidaError';
  }
}

/** Arma el payload enviando la fecha exactamente como la eligió el usuario. */
export const payloadTipoCambio = (form: NuevoTipoCambioForm): PayloadTipoCambio => {
  const fecha = fechaCalendarioFormulario(form.fecha_publicacion);
  if (!fecha) {
    throw new FechaTipoCambioInvalidaError();
  }
  return {
    moneda_codigo: form.moneda_codigo,
    fecha_publicacion: fecha,
    compra: form.compra,
    venta: form.venta,
    fuente: form.fuente.trim() || 'SBS',
  };
};
