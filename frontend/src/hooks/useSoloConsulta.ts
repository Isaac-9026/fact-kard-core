import { useAuth } from '../context/useAuth'
import { esSoloConsulta } from '../utils/seguridad'

export function useSoloConsulta(): boolean {
  const { usuario, empresaActiva } = useAuth()
  return esSoloConsulta(empresaActiva?.rol, Boolean(usuario?.es_admin_global))
}
