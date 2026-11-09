import type { EmpresaActiva, EmpresaAsociada } from '../types/auth';

export interface EstadoEmpresas {
  empresas: EmpresaAsociada[];
  empresaActiva: EmpresaActiva | null;
}

const comoEmpresaActiva = (empresa: EmpresaAsociada): EmpresaActiva => ({
  id: empresa.id,
  ruc: empresa.ruc,
  razon_social: empresa.razon_social,
  nombre_comercial: empresa.nombre_comercial,
  rol: empresa.rol,
  logo: empresa.logo ?? null,
  color_tema: empresa.color_tema ?? null,
});

export const reconciliarEstadoEmpresas = (
  empresas: EmpresaAsociada[],
  empresaActiva: EmpresaActiva | null,
): EstadoEmpresas => {
  const activaValida = empresaActiva
    ? empresas.find((empresa) => empresa.id === empresaActiva.id)
    : undefined;
  const siguienteActiva = activaValida ?? empresas[0] ?? null;

  return {
    empresas,
    empresaActiva: siguienteActiva ? comoEmpresaActiva(siguienteActiva) : null,
  };
};
