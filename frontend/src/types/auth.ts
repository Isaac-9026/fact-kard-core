export interface Usuario {
  id: number;
  username: string;
  email: string;
  es_admin_global: boolean;
  activo?: boolean;
}

export interface EmpresaAsociada {
  id: number;
  ruc: string;
  razon_social: string;
  nombre_comercial?: string | null;
  rol: 'ADMIN' | 'USUARIO' | 'CONSULTA';
  activo?: boolean;
  logo?: string | null;
  color_tema?: string | null;
}

export interface EmpresaActiva {
  id: number;
  ruc: string;
  razon_social: string;
  nombre_comercial?: string | null;
  rol: 'ADMIN' | 'USUARIO' | 'CONSULTA';
  logo?: string | null;
  color_tema?: string | null;
}

export interface OpcionesSeleccionarEmpresa {
  silencioso?: boolean;
}

export interface AuthContextType {
  usuario: Usuario | null;
  empresaActiva: EmpresaActiva | null;
  empresasDisponibles: EmpresaAsociada[];
  token: string | null;
  isAuthenticated: boolean;
  verificandoSesion: boolean;
  empresaTransicion: EmpresaAsociada | null;
  confirmarCambioEmpresa: () => void;
  terminarTransicionEmpresa: () => void;
  /** token null/ausente = sesión por cookie HttpOnly. */
  login: (token: string | null, usuario: Usuario, empresas: EmpresaAsociada[]) => void;
  logout: () => void;
  registrarEmpresaDisponible: (empresa: EmpresaAsociada) => void;
  refrescarEmpresasDisponibles: () => Promise<EmpresaAsociada[]>;
  seleccionarEmpresa: (empresaId: number, opciones?: OpcionesSeleccionarEmpresa) => void;
  actualizarIdentidadEmpresa?: (empresaId: number, datos: { logo?: string | null; color_tema?: string | null }) => void;
}
