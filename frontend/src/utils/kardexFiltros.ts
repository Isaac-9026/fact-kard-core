export interface KardexFiltrosFormulario {
  producto_id?: number;
  periodo_id?: number;
  almacen_id?: number;
  tipo_operacion_id?: number;
  fecha_desde?: string;
  fecha_hasta?: string;
}

const numeroOpcional = (valor: FormDataEntryValue | null): number | undefined => {
  if (typeof valor !== 'string' || valor === '') return undefined;
  return Number(valor);
};

const textoOpcional = (valor: FormDataEntryValue | null): string | undefined => (
  typeof valor === 'string' && valor !== '' ? valor : undefined
);

export const filtrosKardexDesdeFormulario = (datos: FormData): KardexFiltrosFormulario => ({
  producto_id: numeroOpcional(datos.get('producto_id')),
  periodo_id: numeroOpcional(datos.get('periodo_id')),
  almacen_id: numeroOpcional(datos.get('almacen_id')),
  tipo_operacion_id: numeroOpcional(datos.get('tipo_operacion_id')),
  fecha_desde: textoOpcional(datos.get('fecha_desde')),
  fecha_hasta: textoOpcional(datos.get('fecha_hasta')),
});

export const parametrosKardex = (
  filtros?: object,
): Record<string, string | number> => {
  const parametros: Record<string, string | number> = {};
  Object.entries(filtros ?? {}).forEach(([clave, valor]) => {
    if ((typeof valor === 'string' && valor !== '') || typeof valor === 'number') {
      parametros[clave] = valor;
    }
  });
  return parametros;
};
