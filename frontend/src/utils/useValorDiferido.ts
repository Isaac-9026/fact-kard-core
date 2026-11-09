import { useEffect, useState } from 'react'

/**
 * Bloque 7 — devuelve `valor` después de `ms` milisegundos sin cambios. Se usa para no
 * consultar al servidor en cada tecla de un buscador.
 */
export function useValorDiferido<T>(valor: T, ms = 300): T {
  const [diferido, setDiferido] = useState(valor)
  useEffect(() => {
    const t = setTimeout(() => setDiferido(valor), ms)
    return () => clearTimeout(t)
  }, [valor, ms])
  return diferido
}
