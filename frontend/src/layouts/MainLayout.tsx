import React, { useState } from 'react'
import { Outlet, NavLink, useNavigate, useLocation } from 'react-router-dom'
import {
  Boxes,
  LayoutDashboard,
  FileSpreadsheet,
  ClipboardList,
  ArrowLeftRight,
  ScanLine,
  BookOpenCheck,
  Lock,
  FileCheck2,
  AlertTriangle,
  Package,
  Warehouse,
  Users,
  Layers,
  CalendarRange,
  Globe,
  Building2,
  ShieldCheck,
  ShoppingCart,
  Receipt,
  FileMinus,
  PanelLeftClose,
  PanelLeftOpen,
  LogOut,
  ChevronRight,
  Menu,
  X,
  SlidersHorizontal,
  Database,
  HandCoins,
  Wallet,
  Maximize,
  Minimize,
  BookText,
  Banknote,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useAuth } from '../context/useAuth'
import {
  Sidebar,
  SidebarHeader,
  SidebarContent,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarGroupContent,
  SidebarMenu,
  SidebarMenuItem,
  SidebarFooter,
  SidebarSeparator,
} from '../components/ui/sidebar'
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
} from '../components/ui/collapsible'
import { NAV_SECCIONES, itemActivo, type IconoNav } from '../navegacion'
import {
  generarThemingSidebar,
  obtenerFiltroLogo,
  obtenerInicialesEmpresa,
  resolverUrlMedia,
  type TokensTemaSidebar,
} from '../utils/identidadEmpresa'

// El orden y las rutas del menú viven en src/navegacion.ts (probado con node --test).
const ICONOS: Record<IconoNav, LucideIcon> = {
  dashboard: LayoutDashboard,
  empresas: Building2,
  periodos: CalendarRange,
  catalogos: Globe,
  productos: Package,
  almacenes: Warehouse,
  terceros: Users,
  saldoInicial: ClipboardList,
  inventario: Layers,
  compras: ShoppingCart,
  ventas: Receipt,
  comprobantes: FileSpreadsheet,
  notas: FileMinus,
  transferencias: ArrowLeftRight,
  captura: ScanLine,
  kardex: BookOpenCheck,
  incidencias: AlertTriangle,
  cierres: Lock,
  formato131: FileCheck2,
  registroComercial: BookText,
  cuentasCobrar: HandCoins,
  cuentasPagar: Wallet,
  auditoria: ShieldCheck,
}

const ICONOS_SECCION: Record<string, LucideIcon> = {
  INICIO: LayoutDashboard,
  CONFIGURACIÓN: SlidersHorizontal,
  MAESTROS: Database,
  'INVENTARIO INICIAL': Layers,
  OPERACIONES: ArrowLeftRight,
  FINANZAS: Banknote,
  KARDEX: BookOpenCheck,
  'CIERRE Y REPORTES': FileCheck2,
  SEGURIDAD: ShieldCheck,
}

interface NavSectionGroupProps {
  section: (typeof NAV_SECCIONES)[number]
  compacto: boolean
  onItemClick: () => void
  currentPath: string
  themingTokens: TokensTemaSidebar | null
}

const NavSectionGroup: React.FC<NavSectionGroupProps> = ({
  section,
  compacto,
  onItemClick,
  currentPath,
  themingTokens,
}) => {
  const tieneActivo = section.items.some(
    (item) => currentPath === item.path || (item.path !== '/' && currentPath.startsWith(item.path))
  )
  // Acordeón Inteligente: la sección que contiene la ruta actual nace expandida; las demás nacen compactas.
  const [open, setOpen] = useState(tieneActivo)
  const SectionIcon = ICONOS_SECCION[section.title] || Boxes

  React.useEffect(() => {
    // Expande automáticamente la sección al visitarla y la mantiene abierta durante la sesión
    if (tieneActivo) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setOpen(true)
    }
  }, [tieneActivo])

  if (compacto) {
    return (
      <SidebarGroup key={section.title} className="py-1">
        <SidebarSeparator />
        <SidebarGroupContent>
          <SidebarMenu className="gap-1">
            {section.items.map((item) => {
              const ItemIcon = ICONOS[item.icono]
              return (
                <SidebarMenuItem key={item.path}>
                  <NavLink
                    to={item.path}
                    onClick={onItemClick}
                    title={item.label}
                    style={({ isActive }) =>
                      isActive && themingTokens
                        ? {
                            backgroundColor: 'rgba(255, 255, 255, 0.08)',
                            backdropFilter: 'blur(8px)',
                            WebkitBackdropFilter: 'blur(8px)',
                            borderColor: 'rgba(255, 255, 255, 0.14)',
                            boxShadow: 'inset 0 1px 0 0 rgba(255, 255, 255, 0.12)',
                            color: themingTokens['--tenant-sidebar-text'],
                          }
                        : themingTokens
                        ? { color: themingTokens['--tenant-sidebar-text-muted'] }
                        : undefined
                    }
                    className={({ isActive }) =>
                      `peer/menu-button flex w-full items-center justify-center rounded-lg py-1.5 text-xs font-medium select-none outline-none focus-visible:ring-2 focus-visible:ring-offset-1 focus-visible:ring-indigo-500 cursor-pointer relative border transition-colors duration-150 motion-safe:active:scale-[0.96] ${
                        isActive
                          ? themingTokens
                            ? 'shadow-2xs'
                            : 'bg-indigo-50 text-indigo-700 font-semibold shadow-2xs border border-indigo-100/60'
                          : themingTokens
                          ? 'border-transparent hover:bg-white/[0.07] hover:text-white'
                          : 'border-transparent text-slate-600 hover:bg-slate-100/80 hover:text-slate-900'
                      }`
                    }
                  >
                    {({ isActive }) => (
                      <>
                        {themingTokens && (
                          <span
                            className="absolute left-0 top-1.5 bottom-1.5 w-1 rounded-r transition-[opacity] duration-150"
                            style={{
                              backgroundColor: themingTokens['--tenant-sidebar-accent'],
                              opacity: isActive ? 1 : 0,
                            }}
                          />
                        )}
                        <ItemIcon className="h-4 w-4 shrink-0" strokeWidth={1.75} />
                      </>
                    )}
                  </NavLink>
                </SidebarMenuItem>
              )
            })}
          </SidebarMenu>
        </SidebarGroupContent>
      </SidebarGroup>
    )
  }

  return (
    <Collapsible
      key={section.title}
      open={open}
      onOpenChange={setOpen}
      className="group/collapsible"
    >
      <SidebarGroup className="py-1">
        <SidebarGroupLabel className="p-0 h-auto">
          <CollapsibleTrigger className={`flex h-7 w-full items-center justify-between rounded-md px-2 py-1 transition-colors duration-150 cursor-pointer select-none group/trigger outline-none focus-visible:ring-2 focus-visible:ring-offset-1 focus-visible:ring-indigo-500 ${
            themingTokens
              ? tieneActivo
                ? 'text-white font-bold bg-white/[0.10]'
                : 'text-[var(--tenant-sidebar-text-muted)] hover:text-white hover:bg-white/[0.07]'
              : tieneActivo
              ? 'text-indigo-600 bg-indigo-50/60 hover:bg-indigo-50 hover:text-indigo-700'
              : 'text-slate-700 hover:text-slate-900 hover:bg-slate-100/80'
          }`}>
            <div className="flex items-center gap-2 min-w-0">
              <SectionIcon
                className={`h-3.5 w-3.5 shrink-0 transition-colors ${
                  themingTokens
                    ? tieneActivo
                      ? 'text-white'
                      : 'text-[var(--tenant-sidebar-text-muted)] group-hover/trigger:text-white'
                    : tieneActivo
                    ? 'text-indigo-600'
                    : 'text-slate-600 group-hover/trigger:text-slate-900'
                }`}
                strokeWidth={tieneActivo ? 2 : 1.75}
              />
              <span className={`text-[10.5px] font-bold tracking-wider uppercase truncate ${
                themingTokens
                  ? tieneActivo
                    ? 'text-white font-extrabold'
                    : 'text-[var(--tenant-sidebar-text-muted)] group-hover/trigger:text-white'
                  : tieneActivo
                  ? 'text-indigo-900'
                  : 'text-slate-700 group-hover/trigger:text-slate-900'
              }`}>
                {section.title}
              </span>
            </div>
            <div className="flex items-center gap-1.5 shrink-0">
              {tieneActivo && !open && (
                <span
                  className="h-1.5 w-1.5 rounded-full"
                  style={{
                    backgroundColor: themingTokens ? 'var(--tenant-sidebar-accent)' : '#4F46E5',
                  }}
                  title="Contiene submódulo activo"
                />
              )}
              <ChevronRight className={`h-3.5 w-3.5 shrink-0 transition-transform duration-200 ease-out group-data-[state=open]/collapsible:rotate-90 ${
                themingTokens
                  ? tieneActivo
                    ? 'text-white'
                    : 'text-[var(--tenant-sidebar-text-muted)] group-hover/trigger:text-white'
                  : tieneActivo
                  ? 'text-indigo-600'
                  : 'text-slate-500 group-hover/trigger:text-slate-800'
              }`} />
            </div>
          </CollapsibleTrigger>
        </SidebarGroupLabel>

        <CollapsibleContent>
          <div
            style={themingTokens ? { borderColor: themingTokens['--tenant-sidebar-border'] } : undefined}
            className={`ml-3.5 pl-2 my-0.5 border-l ${
              themingTokens ? '' : 'border-slate-200/80'
            }`}
          >

            <SidebarGroupContent>
              <SidebarMenu className="gap-0.5">
                {section.items.map((item) => {
                  const ItemIcon = ICONOS[item.icono]
                  return (
                    <SidebarMenuItem key={item.path}>
                      <NavLink
                        to={item.path}
                        onClick={onItemClick}
                        style={({ isActive }) =>
                          isActive && themingTokens
                            ? {
                                backgroundColor: 'rgba(255, 255, 255, 0.08)',
                                backdropFilter: 'blur(8px)',
                                WebkitBackdropFilter: 'blur(8px)',
                                borderColor: 'rgba(255, 255, 255, 0.14)',
                                boxShadow: 'inset 0 1px 0 0 rgba(255, 255, 255, 0.12)',
                                color: themingTokens['--tenant-sidebar-text'],
                              }
                            : themingTokens
                            ? { color: themingTokens['--tenant-sidebar-text-muted'] }
                            : undefined
                        }
                        className={({ isActive }) =>
                          `peer/menu-button flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px] font-semibold select-none outline-none focus-visible:ring-2 focus-visible:ring-offset-1 focus-visible:ring-indigo-500 cursor-pointer relative border transition-colors duration-150 motion-safe:active:scale-[0.98] ${
                            isActive
                              ? themingTokens
                                ? 'shadow-2xs'
                                : 'bg-indigo-50 text-indigo-700 border-indigo-100/70 shadow-2xs'
                              : themingTokens
                              ? 'border-transparent font-medium hover:bg-white/[0.07] hover:text-white'
                              : 'border-transparent font-medium text-slate-600 hover:bg-slate-100/80 hover:text-slate-900'
                          }`
                        }
                      >
                        {({ isActive }) => (
                          <>
                            {themingTokens ? (
                              <span
                                className="absolute left-0 top-1.5 bottom-1.5 w-1 rounded-r transition-[opacity] duration-150"
                                style={{
                                  backgroundColor: themingTokens['--tenant-sidebar-accent'],
                                  opacity: isActive ? 1 : 0,
                                }}
                              />
                            ) : isActive ? (
                              <span className="absolute left-0 top-1.5 bottom-1.5 w-1 rounded-r bg-indigo-600 shadow-2xs" />
                            ) : null}
                            <ItemIcon className="h-4 w-4 shrink-0" strokeWidth={1.75} />
                            <span className="truncate">{item.label}</span>
                          </>
                        )}
                      </NavLink>
                    </SidebarMenuItem>
                  )
                })}
              </SidebarMenu>
            </SidebarGroupContent>
          </div>
        </CollapsibleContent>
      </SidebarGroup>
    </Collapsible>
  )
}

export const MainLayout: React.FC = () => {
  const { usuario, empresaActiva, empresasDisponibles, seleccionarEmpresa, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [collapsed, setCollapsed] = useState(false)
  // Bloque 9: en móvil (< md) la barra lateral es un panel que se abre sobre el contenido.
  const [menuMovilAbierto, setMenuMovilAbierto] = useState(false)
  // Con el panel móvil abierto siempre se muestran las etiquetas.
  const compacto = collapsed && !menuMovilAbierto

  // Estado de Pantalla Completa (Full Screen API) sincronizado con eventos del navegador (F11 / Esc)
  const [esPantallaCompleta, setEsPantallaCompleta] = useState(false)

  React.useEffect(() => {
    const handleFullscreenChange = () => {
      setEsPantallaCompleta(Boolean(document.fullscreenElement))
    }
    document.addEventListener('fullscreenchange', handleFullscreenChange)
    return () => {
      document.removeEventListener('fullscreenchange', handleFullscreenChange)
    }
  }, [])

  const togglePantallaCompleta = () => {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen().catch(() => {})
    } else if (document.exitFullscreen) {
      document.exitFullscreen().catch(() => {})
    }
  }

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  // Sección y opción activas para el encabezado
  const getActiveInfo = () => {
    const activo = itemActivo(location.pathname)
    if (activo) return { section: activo.seccion.title, item: activo.item.label, Icon: ICONOS[activo.item.icono] }
    return { section: 'INICIO', item: 'Dashboard', Icon: LayoutDashboard }
  }

  const activeInfo = getActiveInfo()
  const esAdmin = Boolean(usuario?.es_admin_global || empresaActiva?.rol === 'ADMIN')

  const themingTokens = React.useMemo(() => {
    return generarThemingSidebar(empresaActiva?.color_tema)
  }, [empresaActiva?.color_tema])

  const logoUrl = React.useMemo(() => resolverUrlMedia(empresaActiva?.logo), [empresaActiva?.logo])
  // Se recuerda QUÉ URL falló (no un booleano): al cambiar el logo, el error deja de aplicar sin
  // resetear estado en un efecto.
  const [logoFallido, setLogoFallido] = useState<string | null>(null)
  const logoError = logoUrl !== null && logoFallido === logoUrl

  return (
    <div className="flex min-h-screen bg-slate-50/60 font-sans text-slate-900 antialiased">
      {/* 1. SIDEBAR IZQUIERDO (shadcn sidebar con theming dinámico periférico) */}
      <Sidebar
        id="menu-principal"
        collapsed={compacto}
        mobileOpen={menuMovilAbierto}
        onCloseMobile={() => setMenuMovilAbierto(false)}
        style={themingTokens ? ({
          ...themingTokens,
          backgroundColor: themingTokens['--tenant-sidebar-bg'],
          backgroundImage: themingTokens['--tenant-sidebar-mesh-bg'],
          borderColor: themingTokens['--tenant-sidebar-border'],
          color: themingTokens['--tenant-sidebar-text'],
        } as React.CSSProperties) : undefined}
        className={themingTokens ? 'border-r shadow-md' : undefined}
      >
        {/* Branding (SidebarHeader) - Emblema Corporativo Compacto y Armónico */}
        <SidebarHeader
          style={themingTokens ? { borderColor: themingTokens['--tenant-sidebar-border'] } : undefined}
          className={`h-auto border-b bg-transparent transition-[padding] duration-200 ${
            compacto ? 'py-2.5 px-2 justify-center' : 'py-3 px-3'
          }`}
        >
          <div className={`flex w-full items-center ${compacto ? 'justify-center' : 'flex-col text-center gap-1.5'}`}>
            {/* Logo o Isotipo adaptativo (soporta transparente y alargado con resplandor perimetral inteligente) */}
            {logoUrl && !logoError ? (
              <div className={`flex items-center justify-center transition-[padding,max-height] duration-200 ${
                compacto ? 'h-8 w-8' : 'min-h-[36px] max-h-10 max-w-[190px] w-full px-1'
              }`}>
                <img
                  src={logoUrl}
                  alt={empresaActiva?.razon_social || 'Logo'}
                  onError={() => setLogoFallido(logoUrl)}
                  style={{
                    filter: obtenerFiltroLogo(Boolean(themingTokens)),
                  }}
                  className={`object-contain transition-opacity duration-150 ${
                    compacto
                      ? 'max-h-7 max-w-[36px] w-auto h-auto'
                      : 'max-h-9 max-w-full w-auto h-auto'
                  }`}
                />
              </div>
            ) : (
              <div
                className={`flex shrink-0 items-center justify-center rounded-lg text-white font-bold shadow-2xs select-none transition-[width,height] duration-200 ${
                  compacto ? 'h-8 w-8 text-xs' : 'h-9 w-9 text-xs'
                }`}
                style={{
                  backgroundColor: themingTokens ? themingTokens['--tenant-sidebar-accent'] : '#4F46E5',
                }}
              >
                {obtenerInicialesEmpresa(empresaActiva?.razon_social || 'FACT-KARD')}
              </div>
            )}

            {/* Razón Social y RUC centrado (solo visible en modo expandido) */}
            {!compacto && (
              <div className="flex flex-col items-center w-full min-w-0 space-y-0.5">
                <span
                  className="text-xs font-bold tracking-tight text-center leading-snug line-clamp-1 px-1 max-w-full"
                  style={{
                    color: themingTokens ? themingTokens['--tenant-sidebar-text'] : '#0F172A',
                  }}
                  title={empresaActiva?.razon_social || 'FACT-KARD'}
                >
                  {empresaActiva?.razon_social || 'FACT-KARD'}
                </span>
                <span
                  className="text-xs font-mono font-bold tabular-nums tracking-tight text-center leading-none mt-0.5"
                  style={{
                    color: themingTokens ? themingTokens['--tenant-sidebar-text'] : '#334155',
                  }}
                >
                  {empresaActiva?.ruc ? `RUC ${empresaActiva.ruc}` : 'ERP v1.0'}
                </span>
              </div>
            )}
          </div>
        </SidebarHeader>

        {/* Navigation list (SidebarContent) */}
        <SidebarContent>
          {NAV_SECCIONES.map((section) => (
            <NavSectionGroup
              key={section.title}
              section={section}
              compacto={compacto}
              onItemClick={() => setMenuMovilAbierto(false)}
              currentPath={location.pathname}
              themingTokens={themingTokens}
            />
          ))}
        </SidebarContent>

        {/* Sidebar Footer: Cápsula Unificada de Usuario + Logout */}
        <SidebarFooter
          style={themingTokens ? { borderColor: themingTokens['--tenant-sidebar-border'] } : undefined}
          className={`border-t p-2.5 ${
            themingTokens ? 'bg-transparent' : 'border-slate-100 bg-slate-50/50'
          }`}
        >
          {!compacto ? (
            <div
              style={themingTokens ? {
                backgroundColor: 'rgba(255, 255, 255, 0.06)',
                backdropFilter: 'blur(8px)',
                WebkitBackdropFilter: 'blur(8px)',
                borderColor: 'rgba(255, 255, 255, 0.10)',
              } : undefined}
              className={`flex items-center justify-between gap-2 rounded-lg p-2 border transition-all duration-150 ${
                themingTokens ? 'shadow-2xs' : 'bg-white border-slate-200/80 shadow-2xs'
              }`}
            >
              <div className="flex items-center gap-2.5 min-w-0">
                <div
                  className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-white font-bold text-xs shadow-2xs select-none"
                  style={{
                    backgroundColor: themingTokens ? themingTokens['--tenant-sidebar-accent'] : '#4F46E5',
                  }}
                >
                  {usuario?.username?.charAt(0).toUpperCase() || 'U'}
                </div>
                <div className="flex flex-col min-w-0 leading-tight">
                  <span
                    className={`text-xs font-semibold truncate ${
                      themingTokens ? 'text-[var(--tenant-sidebar-text)]' : 'text-slate-800'
                    }`}
                    title={usuario?.username || 'Usuario'}
                  >
                    {usuario?.username || 'Usuario'}
                  </span>
                  <span
                    className={`text-[10px] font-medium mt-0.5 ${
                      themingTokens ? 'text-[var(--tenant-sidebar-text-muted)]' : 'text-slate-500'
                    }`}
                  >
                    {esAdmin ? 'Administrador' : 'Operador'}
                  </span>
                </div>
              </div>

              {/* Botón Salir integrado ergonómicamente al pie del sidebar */}
              <button
                type="button"
                onClick={handleLogout}
                title="Cerrar sesión"
                aria-label="Cerrar sesión"
                className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-slate-400 hover:text-rose-600 hover:bg-rose-50 enabled:active:scale-[0.96] transition-all duration-150 cursor-pointer ${
                  themingTokens ? 'hover:bg-white/10 hover:text-rose-300' : ''
                }`}
              >
                <LogOut className="h-3.5 w-3.5" strokeWidth={1.75} />
              </button>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-2">
              <div
                className="flex h-8 w-8 items-center justify-center rounded-full text-white font-semibold text-xs shadow-2xs select-none"
                style={{
                  backgroundColor: themingTokens ? themingTokens['--tenant-sidebar-accent'] : '#4F46E5',
                }}
                title={`${usuario?.username || 'Usuario'} (${esAdmin ? 'ADMIN' : 'USUARIO'})`}
              >
                {usuario?.username?.charAt(0).toUpperCase() || 'U'}
              </div>
              <button
                type="button"
                onClick={handleLogout}
                title="Cerrar sesión"
                aria-label="Cerrar sesión"
                className="flex h-7 w-7 items-center justify-center rounded-md text-slate-400 hover:text-rose-600 hover:bg-rose-50 enabled:active:scale-[0.96] transition-all duration-150 cursor-pointer"
              >
                <LogOut className="h-3.5 w-3.5" strokeWidth={1.75} />
              </button>
            </div>
          )}
        </SidebarFooter>
      </Sidebar>

      {/* 2. ÁREA PRINCIPAL */}
      {/* min-w-0: sin esto una tabla ancha estira toda la columna y la página entera se desborda */}
      <div className={`flex min-w-0 flex-1 flex-col transition-[padding] duration-200 ease-in-out ${collapsed ? 'md:pl-18' : 'md:pl-64'}`}>
        {/* Topbar Superior Fijo (56px h-14, alta densidad y superficie limpia) */}
        <header className="sticky top-0 z-20 flex h-14 items-center justify-between gap-3 border-b border-slate-200/80 bg-white/90 px-3 sm:px-6 backdrop-blur-md">
          {/* Left: Collapse Button + Breadcrumb */}
          <div className="flex min-w-0 items-center gap-2 sm:gap-3">
            <button
              type="button"
              onClick={() => setMenuMovilAbierto(!menuMovilAbierto)}
              className="md:hidden rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-900 transition-colors enabled:active:scale-[0.96] cursor-pointer"
              aria-label={menuMovilAbierto ? 'Cerrar menú' : 'Abrir menú'}
              aria-expanded={menuMovilAbierto}
              aria-controls="menu-principal"
            >
              {menuMovilAbierto ? <X className="h-4 w-4" strokeWidth={1.75} /> : <Menu className="h-4 w-4" strokeWidth={1.75} />}
            </button>
            <button
              type="button"
              onClick={() => setCollapsed(!collapsed)}
              className="hidden md:inline-flex rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-900 transition-colors enabled:active:scale-[0.96] cursor-pointer"
              aria-label={collapsed ? 'Expandir barra lateral' : 'Colapsar barra lateral'}
            >
              {collapsed ? (
                <PanelLeftOpen className="h-4 w-4" strokeWidth={1.75} />
              ) : (
                <PanelLeftClose className="h-4 w-4" strokeWidth={1.75} />
              )}
            </button>

            <div className="hidden sm:block h-4 w-px bg-slate-200/80" />

            {/* Breadcrumb con jerarquía nítida */}
            <nav aria-label="Ruta de navegación" className="flex min-w-0 items-center gap-1.5 text-xs text-slate-500">
              <span className="hidden md:inline shrink-0 font-medium tracking-tight text-slate-400 select-none">
                {activeInfo.section}
              </span>
              <ChevronRight className="hidden md:inline h-3 w-3 shrink-0 text-slate-300" />
              <div className="flex min-w-0 items-center gap-1.5 font-semibold text-slate-800">
                <activeInfo.Icon className="h-3.5 w-3.5 shrink-0 text-indigo-600" strokeWidth={1.75} />
                <span className="truncate" title={`${activeInfo.section} › ${activeInfo.item}`}>
                  {activeInfo.item}
                </span>
              </div>
            </nav>
          </div>

          {/* Right: Workspace Switcher de Empresa + Pantalla Completa (F11) */}
          <div className="flex min-w-0 shrink-0 items-center gap-2">
            {empresasDisponibles && empresasDisponibles.length > 0 && (
              <div className="flex items-center gap-2 rounded-lg border border-slate-200/90 bg-slate-50/70 hover:bg-slate-100/80 px-2.5 py-1.5 shadow-2xs transition-colors duration-150 focus-within:ring-2 focus-within:ring-indigo-500/20 focus-within:border-indigo-400">
                <Building2 className="h-3.5 w-3.5 text-indigo-600 shrink-0" strokeWidth={1.75} />
                <select
                  aria-label="Seleccionar empresa activa"
                  value={empresaActiva?.id || ''}
                  onChange={(e) => seleccionarEmpresa(Number(e.target.value))}
                  className="bg-transparent text-xs font-semibold text-slate-800 focus:outline-none cursor-pointer max-w-[180px] sm:max-w-[260px] md:max-w-[340px] lg:max-w-[420px] truncate"
                >
                  {empresasDisponibles.map((emp) => (
                    <option key={emp.id} value={emp.id}>
                      {emp.razon_social}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {/* Botón de Pantalla Completa (tipo F11) */}
            <button
              type="button"
              onClick={togglePantallaCompleta}
              title={esPantallaCompleta ? 'Salir de pantalla completa (Esc)' : 'Pantalla completa (F11)'}
              aria-label={esPantallaCompleta ? 'Salir de pantalla completa' : 'Pantalla completa'}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-slate-200/90 bg-slate-50/70 hover:bg-slate-100 hover:text-slate-900 text-slate-500 shadow-2xs transition-colors duration-150 enabled:active:scale-[0.96] cursor-pointer"
            >
              {esPantallaCompleta ? (
                <Minimize className="h-3.5 w-3.5" strokeWidth={1.75} />
              ) : (
                <Maximize className="h-3.5 w-3.5" strokeWidth={1.75} />
              )}
            </button>
          </div>
        </header>

        {/* 3. CONTENIDO DE LA PÁGINA */}
        <main className="min-w-0 flex-1 p-4 md:p-8 max-w-7xl w-full mx-auto">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
