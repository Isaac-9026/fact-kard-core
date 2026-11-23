import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Check, ChevronDown, Package, Search, X } from 'lucide-react';
import { filtrarProductos, type OpcionProducto } from '../../utils/graficosDashboard';

interface Props {
  productos: OpcionProducto[];
  valor: number | null;
  onCambio: (id: number | null) => void;
}

export const SelectorProducto: React.FC<Props> = ({ productos, valor, onCambio }) => {
  const [abierto, setAbierto] = useState(false);
  const [texto, setTexto] = useState('');
  const caja = useRef<HTMLDivElement>(null);
  const actual = productos.find((p) => p.id === valor) ?? null;
  const opciones = useMemo(() => filtrarProductos(productos, texto), [productos, texto]);

  useEffect(() => {
    if (!abierto) return;
    const cerrar = (e: MouseEvent) => {
      if (caja.current && !caja.current.contains(e.target as Node)) setAbierto(false);
    };
    document.addEventListener('mousedown', cerrar);
    return () => document.removeEventListener('mousedown', cerrar);
  }, [abierto]);

  const elegir = (id: number | null) => {
    onCambio(id);
    setAbierto(false);
    setTexto('');
  };

  return (
    <div ref={caja} className="relative" data-testid="dashboard-filtro-producto">
      <button
        type="button"
        onClick={() => setAbierto((a) => !a)}
        className="inline-flex h-9 min-w-64 max-w-sm items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 text-xs text-slate-700 shadow-xs transition-colors hover:border-slate-300"
      >
        <Package className="h-3.5 w-3.5 shrink-0 text-slate-400" />
        <span className="text-slate-400">Producto:</span>
        <span className="truncate font-semibold text-slate-900">{actual ? actual.descripcion : 'Todos'}</span>
        <ChevronDown className="ml-auto h-3.5 w-3.5 shrink-0 text-slate-400" />
      </button>
      {abierto && (
        <div className="absolute left-0 z-30 mt-1 w-96 max-w-[90vw] overflow-hidden rounded-lg border border-slate-200 bg-white shadow-lg">
          <div className="flex items-center gap-2 border-b border-slate-100 px-3 py-2">
            <Search className="h-3.5 w-3.5 text-slate-400" />
            <input
              autoFocus
              value={texto}
              onChange={(e) => setTexto(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Escape') setAbierto(false);
                if (e.key === 'Enter' && opciones[0]) elegir(opciones[0].id);
              }}
              placeholder="Buscar por código o nombre"
              className="w-full bg-transparent text-xs outline-none placeholder:text-slate-400"
            />
          </div>
          <ul className="max-h-72 overflow-y-auto py-1 text-xs">
            <li>
              <button type="button" onClick={() => elegir(null)}
                className="flex w-full items-center justify-between px-3 py-2 text-left font-medium text-slate-700 hover:bg-slate-50">
                Todos los productos {valor === null && <Check className="h-3.5 w-3.5 text-blue-600" />}
              </button>
            </li>
            {opciones.map((p) => (
              <li key={p.id}>
                <button type="button" onClick={() => elegir(p.id)}
                  className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left hover:bg-slate-50">
                  <span className="min-w-0">
                    <span className="block truncate text-slate-800">{p.descripcion}</span>
                    <span className="font-mono text-[10px] text-slate-400">{p.codigo_interno}</span>
                  </span>
                  {valor === p.id && <Check className="h-3.5 w-3.5 shrink-0 text-blue-600" />}
                </button>
              </li>
            ))}
            {!opciones.length && <li className="px-3 py-3 text-slate-400">Sin coincidencias.</li>}
          </ul>
        </div>
      )}
      {actual && (
        <button type="button" onClick={() => elegir(null)} title="Ver todos"
          className="absolute -right-2 -top-2 rounded-full bg-slate-700 p-0.5 text-white shadow hover:bg-slate-900">
          <X className="h-3 w-3" />
        </button>
      )}
    </div>
  );
};

export default SelectorProducto;
