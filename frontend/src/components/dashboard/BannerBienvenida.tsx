import React from 'react';
import { ArrowRight, CalendarRange, Lock, Receipt, RefreshCw, ShoppingCart } from 'lucide-react';

interface Props {
  usuario: string | null;
  empresa: { razon_social: string; ruc: string; rol: string } | null;
  periodo: string | null;
  estadoPeriodo: string | null;
  ultimoCierre: string | null;
  cargando: boolean;
  onNuevaCompra: () => void;
  onNuevaVenta: () => void;
  onVerOperaciones: () => void;
  onActualizar: () => void;
}

const ROLES: Record<string, string> = { ADMIN: 'Administrador', USUARIO: 'Usuario', CONSULTA: 'Consulta' };

const nombreRol = (rol: string | null | undefined): string =>
  rol ? ROLES[rol.toUpperCase()] ?? rol.charAt(0).toUpperCase() + rol.slice(1).toLowerCase() : '';

const ANIMACION = `
.bb-flota { animation: bb-flota 4s ease-in-out infinite; }
.bb-barra { transform-box: fill-box; transform-origin: bottom; animation: bb-barra 2.8s ease-in-out infinite; }
.bb-b2 { animation-delay: .35s; } .bb-b3 { animation-delay: .7s; } .bb-b4 { animation-delay: 1.05s; }
.bb-linea { stroke-dasharray: 160; animation: bb-linea 3.5s ease-in-out infinite; }
.bb-punto { animation: bb-punto 3.5s ease-in-out infinite; }
.bb-pulso { transform-box: fill-box; transform-origin: center; animation: bb-pulso 2.4s ease-out infinite; }
.bb-caja { animation: bb-flota 4s ease-in-out infinite; animation-delay: -2s; }
.bb-brillo { animation: bb-brillo 3s ease-in-out infinite; }
@keyframes bb-flota { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-6px); } }
@keyframes bb-barra { 0%,100% { transform: scaleY(1); } 50% { transform: scaleY(.55); } }
@keyframes bb-linea { 0% { stroke-dashoffset: 160; } 45%,75% { stroke-dashoffset: 0; } 100% { stroke-dashoffset: -160; } }
@keyframes bb-punto { 0%,40% { opacity: 0; } 50%,75% { opacity: 1; } 90%,100% { opacity: 0; } }
@keyframes bb-pulso { 0% { transform: scale(1); opacity: .6; } 100% { transform: scale(1.9); opacity: 0; } }
@keyframes bb-brillo { 0%,100% { opacity: .25; } 50% { opacity: 1; } }
@media (prefers-reduced-motion: reduce) {
  .bb-flota, .bb-barra, .bb-linea, .bb-punto, .bb-pulso, .bb-caja, .bb-brillo { animation: none; }
}
`;

const Ilustracion: React.FC = () => (
  <svg viewBox="0 0 240 150" className="h-40 w-auto" aria-hidden="true" fill="none" stroke="#fff" strokeLinecap="round" strokeLinejoin="round">
    <style>{ANIMACION}</style>
    <g className="bb-flota">
      <rect x="20" y="16" width="120" height="104" rx="12" strokeOpacity=".9" strokeWidth="2" fill="#fff" fillOpacity=".06" />
      <path d="M20 36 H140" strokeOpacity=".35" strokeWidth="1.5" />
      <circle cx="31" cy="26" r="2.5" fill="#fff" stroke="none" fillOpacity=".7" />
      <circle cx="40" cy="26" r="2.5" fill="#fff" stroke="none" fillOpacity=".45" />
      <circle cx="49" cy="26" r="2.5" fill="#fff" stroke="none" fillOpacity=".25" />
      <rect className="bb-barra" x="34" y="78" width="12" height="30" rx="3" fill="#fff" fillOpacity=".35" stroke="none" />
      <rect className="bb-barra bb-b2" x="54" y="66" width="12" height="42" rx="3" fill="#fff" fillOpacity=".5" stroke="none" />
      <rect className="bb-barra bb-b3" x="74" y="56" width="12" height="52" rx="3" fill="#fff" fillOpacity=".7" stroke="none" />
      <rect className="bb-barra bb-b4" x="94" y="70" width="12" height="38" rx="3" fill="#fff" fillOpacity=".9" stroke="none" />
      <path className="bb-linea" d="M32 70 L54 58 L74 48 L96 56 L124 42" strokeWidth="2.5" />
      <circle className="bb-punto" cx="124" cy="42" r="4" fill="#fff" stroke="none" />
      <path d="M30 112 H130" strokeOpacity=".35" strokeWidth="1.5" />
    </g>
    <g transform="translate(142 22)">
      <circle className="bb-pulso" cx="14" cy="14" r="14" strokeWidth="2" />
      <circle cx="14" cy="14" r="14" strokeWidth="2" fill="#fff" fillOpacity=".12" />
      <path d="M8 14.5 L12.5 19 L20.5 10" strokeWidth="2.5" />
    </g>
    <g className="bb-caja" transform="translate(0 0)">
      <g transform="translate(160 70)">
        <path d="M0 16 L28 4 L56 16 L28 28 Z" strokeWidth="2" fill="#fff" fillOpacity=".18" />
        <path d="M0 16 L0 50 L28 62 L28 28 Z" strokeWidth="2" fill="#fff" fillOpacity=".08" />
        <path d="M56 16 L56 50 L28 62 L28 28 Z" strokeWidth="2" fill="#fff" fillOpacity=".14" />
        <path d="M14 10 L42 22 L42 32" strokeWidth="2" strokeOpacity=".7" />
      </g>
    </g>
    <path className="bb-brillo" d="M210 30 v10 M205 35 h10" strokeWidth="2" />
    <path className="bb-brillo bb-b3" d="M226 58 v6 M223 61 h6" strokeWidth="1.5" />
    <path className="bb-brillo bb-b2" d="M150 128 v6 M147 131 h6" strokeWidth="1.5" />
  </svg>
);

export const BannerBienvenida: React.FC<Props> = ({
  usuario, empresa, periodo, estadoPeriodo, ultimoCierre, cargando, onNuevaCompra, onNuevaVenta, onVerOperaciones, onActualizar,
}) => (
  <section
    className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-[#0b1b3a] via-[#11285a] to-[#1e3a8a] px-6 py-5 text-white shadow-md"
    data-testid="dashboard-bienvenida"
  >
    <div className="pointer-events-none absolute -right-16 -top-20 h-64 w-64 rounded-full bg-blue-500/20 blur-3xl" />
    <div className="pointer-events-none absolute -bottom-24 left-1/3 h-56 w-56 rounded-full bg-indigo-400/10 blur-3xl" />
    <div className="relative flex flex-col gap-5 md:flex-row md:items-center md:justify-between">
      <div className="min-w-0 space-y-3">
        <div className="flex flex-wrap items-center gap-2 text-[11px] font-medium">
          {empresa?.rol && (
            <span className="rounded-full bg-white/10 px-2.5 py-0.5 text-white/90 ring-1 ring-white/15">{nombreRol(empresa.rol)}</span>
          )}
          {periodo && (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-white/10 px-2.5 py-0.5 text-white/90 ring-1 ring-white/15">
              <CalendarRange className="h-3 w-3" /> Período {periodo}
              {estadoPeriodo && (
                <span className="inline-flex items-center gap-1 font-semibold">
                  · <span className={`h-1.5 w-1.5 rounded-full ${estadoPeriodo === 'ABIERTO' ? 'bg-emerald-400' : 'bg-white/60'}`} />
                  {estadoPeriodo.charAt(0) + estadoPeriodo.slice(1).toLowerCase()}
                </span>
              )}
            </span>
          )}
          <span className="rounded-full bg-white/10 px-2.5 py-0.5 text-white/90 ring-1 ring-white/15">CPP · PEN · IGV 18 %</span>
          {ultimoCierre && (
            <span className="inline-flex items-center gap-1 rounded-full bg-white/10 px-2.5 py-0.5 text-white/90 ring-1 ring-white/15">
              <Lock className="h-3 w-3" /> Último cierre: {ultimoCierre}
            </span>
          )}
        </div>
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            Bienvenido nuevamente{usuario ? `, ${usuario}` : ''}
          </h1>
          {empresa ? (
            <p className="mt-1 text-sm text-white/90">
              <span className="font-semibold text-white">{empresa.razon_social}</span>
              <span className="text-white/70"> · RUC {empresa.ruc}</span>
            </p>
          ) : (
            <p className="mt-1 text-sm text-white/90">Seleccione una empresa para ver su información.</p>
          )}
          <p className="mt-1 max-w-xl text-xs text-white/70">
            Supervisa tu inventario, revisa alertas y cierra el período con información confiable.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <button
            type="button"
            onClick={onVerOperaciones}
            className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-blue-500 px-4 text-xs font-semibold text-white shadow-sm transition-colors hover:bg-blue-400"
          >
            <ArrowRight className="h-3.5 w-3.5" /> Ver operaciones
          </button>
          <button
            type="button"
            onClick={onNuevaCompra}
            data-acceso="/comprobantes?clase=COMPRA&nuevo=1"
            className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-white/10 px-3.5 text-xs font-semibold text-white ring-1 ring-white/20 transition-colors hover:bg-white/20"
          >
            <ShoppingCart className="h-3.5 w-3.5" /> Nueva Compra
          </button>
          <button
            type="button"
            onClick={onNuevaVenta}
            data-acceso="/comprobantes?clase=VENTA&nuevo=1"
            className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-white/10 px-3.5 text-xs font-semibold text-white ring-1 ring-white/20 transition-colors hover:bg-white/20"
          >
            <Receipt className="h-3.5 w-3.5" /> Nueva Venta
          </button>
          <button
            type="button"
            onClick={onActualizar}
            disabled={cargando}
            className="inline-flex h-9 items-center gap-1.5 rounded-lg px-3 text-xs font-medium text-white/90 transition-colors hover:bg-white/10 disabled:opacity-60"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${cargando ? 'animate-spin' : ''}`} /> Actualizar
          </button>
        </div>
      </div>
      <div className="hidden shrink-0 md:block"><Ilustracion /></div>
    </div>
  </section>
);

export default BannerBienvenida;
