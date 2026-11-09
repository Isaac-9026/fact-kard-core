export interface PeriodoReapertura {
  id: number;
  anio: number;
  mes: number;
}

export interface EstadoReapertura {
  abierto: boolean;
  periodo: PeriodoReapertura | null;
  motivo: string;
  error: string | null;
  enviando: boolean;
}

export const estadoReaperturaInicial: EstadoReapertura = {
  abierto: false,
  periodo: null,
  motivo: '',
  error: null,
  enviando: false,
};

export const abrirReapertura = (periodo: PeriodoReapertura): EstadoReapertura => ({
  abierto: true,
  periodo,
  motivo: '',
  error: null,
  enviando: false,
});

export const cancelarReapertura = (): EstadoReapertura => ({ ...estadoReaperturaInicial });

export const etiquetaEstadoCierre = (vigente: boolean, estadoPeriodo: string): 'Vigente' | 'Histórico' => (
  vigente && estadoPeriodo === 'CERRADO' ? 'Vigente' : 'Histórico'
);

export const validarMotivoReapertura = (motivo: string): string | null => {
  const longitud = motivo.trim().length;
  if (longitud < 3) return 'Ingrese un motivo de al menos 3 caracteres.';
  if (longitud > 500) return 'El motivo no puede superar los 500 caracteres.';
  return null;
};

export const ejecutarReapertura = async <T>(
  estado: EstadoReapertura,
  enviar: (periodoId: number, payload: { motivo_reapertura: string }) => Promise<T>,
): Promise<{ estado: EstadoReapertura; respuesta?: T }> => {
  if (!estado.periodo) return { estado };
  const motivo = estado.motivo.trim();
  const errorValidacion = validarMotivoReapertura(motivo);
  if (errorValidacion) {
    return { estado: { ...estado, error: errorValidacion, enviando: false } };
  }

  try {
    const respuesta = await enviar(estado.periodo.id, { motivo_reapertura: motivo });
    return { estado: cancelarReapertura(), respuesta };
  } catch (error: unknown) {
    const detalle = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
    return {
      estado: {
        ...estado,
        motivo,
        error: detalle || 'La reapertura no pudo completarse.',
        enviando: false,
      },
    };
  }
};
