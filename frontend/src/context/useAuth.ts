import { createContext, useContext } from 'react';
import type { AuthContextType } from '../types/auth';

/**
 * Contexto y hook de autenticación. Viven separados de `AuthProvider` (AuthContext.tsx)
 * para que ese archivo exporte solo componentes (requisito de React Fast Refresh).
 */
export const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const useAuth = (): AuthContextType => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth debe ser utilizado dentro de un AuthProvider');
  }
  return context;
};
