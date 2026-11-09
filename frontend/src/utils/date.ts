const completarDosDigitos = (valor: number) => String(valor).padStart(2, '0');
const FECHA_CALENDARIO = /^\d{4}-\d{2}-\d{2}$/;

export const fechaCalendarioLocal = (fecha = new Date()): string => (
  `${fecha.getFullYear()}-${completarDosDigitos(fecha.getMonth() + 1)}-${completarDosDigitos(fecha.getDate())}`
);

export const fechaCalendarioFormulario = (valor: FormDataEntryValue | null): string => (
  typeof valor === 'string' && FECHA_CALENDARIO.test(valor) ? valor : ''
);
