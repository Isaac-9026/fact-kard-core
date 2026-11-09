/**
 * Bloque 7 — lanza una carga desde un efecto fuera de su cuerpo síncrono.
 *
 * La regla `react-hooks/set-state-in-effect` prohíbe llamar a setState de forma síncrona
 * dentro de un efecto (provoca un render en cascada). Las cargas de datos de las páginas
 * empiezan con `setLoading(true)`; al diferirlas a una microtarea el estado se actualiza
 * igual antes de que el navegador pinte, de modo que la pantalla no cambia.
 */
export function diferirCarga(carga: () => unknown): void {
  queueMicrotask(() => {
    void carga()
  })
}
