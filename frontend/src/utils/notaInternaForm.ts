const FECHA_CALENDARIO = /^\d{4}-\d{2}-\d{2}$/;

export const campoFechaNotaInterna = (valor: FormDataEntryValue | null) => ({
  fecha: typeof valor === 'string' && FECHA_CALENDARIO.test(valor) ? valor : '',
});

export const formularioNotaTrasRespuesta = <T>(
  formularioEnviado: T,
  guardado: boolean,
): T | null => (guardado ? null : formularioEnviado);
