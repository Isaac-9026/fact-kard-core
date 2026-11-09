import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '../../lib/utils'

export interface SidebarProps extends React.HTMLAttributes<HTMLElement> {
  collapsed?: boolean
  mobileOpen?: boolean
  onCloseMobile?: () => void
}

export const Sidebar = React.forwardRef<HTMLElement, SidebarProps>(
  ({ className, collapsed = false, mobileOpen = false, onCloseMobile, children, ...props }, ref) => {
    return (
      <>
        {/* Backdrop en móvil */}
        {mobileOpen && (
          <div
            className="fixed inset-0 z-30 bg-slate-900/30 backdrop-blur-2xs md:hidden"
            aria-hidden="true"
            onClick={onCloseMobile}
          />
        )}

        {/* Sidebar Container */}
        <aside
          ref={ref}
          data-collapsed={collapsed}
          data-mobile-open={mobileOpen}
          className={cn(
            'fixed inset-y-0 left-0 z-40 flex flex-col border-r border-slate-200/80 bg-white transition-[width,transform] duration-200 ease-in-out shadow-xs md:translate-x-0',
            mobileOpen ? 'translate-x-0' : '-translate-x-full',
            collapsed ? 'w-64 md:w-18' : 'w-64',
            className
          )}
          {...props}
        >
          {children}
        </aside>
      </>
    )
  }
)
Sidebar.displayName = 'Sidebar'

export const SidebarHeader = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      data-sidebar="header"
      className={cn('flex h-16 shrink-0 items-center border-b border-slate-100 px-3', className)}
      {...props}
    />
  )
)
SidebarHeader.displayName = 'SidebarHeader'

export const SidebarContent = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      data-sidebar="content"
      className={cn('flex min-h-0 flex-1 flex-col overflow-y-auto overscroll-contain px-2 py-3 space-y-4', className)}
      {...props}
    />
  )
)
SidebarContent.displayName = 'SidebarContent'

export const SidebarGroup = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      data-sidebar="group"
      className={cn('relative flex w-full min-w-0 flex-col gap-1', className)}
      {...props}
    />
  )
)
SidebarGroup.displayName = 'SidebarGroup'

export const SidebarGroupLabel = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      data-sidebar="group-label"
      className={cn(
        'flex h-6 shrink-0 items-center px-2 text-[11px] font-bold tracking-wider text-slate-700 uppercase select-none',
        className
      )}
      {...props}
    />
  )
)
SidebarGroupLabel.displayName = 'SidebarGroupLabel'

export const SidebarGroupContent = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      data-sidebar="group-content"
      className={cn('w-full text-xs', className)}
      {...props}
    />
  )
)
SidebarGroupContent.displayName = 'SidebarGroupContent'

export const SidebarMenu = React.forwardRef<HTMLUListElement, React.HTMLAttributes<HTMLUListElement>>(
  ({ className, ...props }, ref) => (
    <ul
      ref={ref}
      data-sidebar="menu"
      className={cn('flex w-full min-w-0 flex-col gap-1 p-0 m-0 list-none', className)}
      {...props}
    />
  )
)
SidebarMenu.displayName = 'SidebarMenu'

export const SidebarMenuItem = React.forwardRef<HTMLLIElement, React.HTMLAttributes<HTMLLIElement>>(
  ({ className, ...props }, ref) => (
    <li
      ref={ref}
      data-sidebar="menu-item"
      className={cn('group/menu-item relative list-none', className)}
      {...props}
    />
  )
)
SidebarMenuItem.displayName = 'SidebarMenuItem'

// Variantes de estilo exportadas junto al componente (patrón shadcn).
// eslint-disable-next-line react-refresh/only-export-components
export const sidebarMenuButtonVariants = cva(
  'peer/menu-button flex w-full items-center gap-3 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors select-none outline-none focus-visible:ring-2 focus-visible:ring-slate-900 cursor-pointer',
  {
    variants: {
      variant: {
        default: 'text-slate-600 hover:bg-slate-100/80 hover:text-slate-900',
        active: 'bg-indigo-50 text-indigo-700 font-semibold shadow-2xs border border-indigo-100/60',
      },
      size: {
        default: 'h-8 text-xs',
        sm: 'h-7 text-xs',
        lg: 'h-10 text-sm',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  }
)

export interface SidebarMenuButtonProps
  extends React.AnchorHTMLAttributes<HTMLAnchorElement>,
    VariantProps<typeof sidebarMenuButtonVariants> {
  isActive?: boolean
  tooltip?: string
  compact?: boolean
}

export const SidebarMenuButton = React.forwardRef<HTMLAnchorElement, SidebarMenuButtonProps>(
  ({ className, variant, size, isActive = false, compact = false, tooltip, children, ...props }, ref) => {
    return (
      <a
        ref={ref}
        data-sidebar="menu-button"
        data-active={isActive}
        title={compact ? tooltip : undefined}
        className={cn(
          sidebarMenuButtonVariants({ variant: isActive ? 'active' : variant, size }),
          compact && 'justify-center px-0 gap-0',
          className
        )}
        {...props}
      >
        {children}
      </a>
    )
  }
)
SidebarMenuButton.displayName = 'SidebarMenuButton'

export const SidebarFooter = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      data-sidebar="footer"
      className={cn('shrink-0 border-t border-slate-100 p-3', className)}
      {...props}
    />
  )
)
SidebarFooter.displayName = 'SidebarFooter'

export const SidebarSeparator = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      data-sidebar="separator"
      className={cn('my-2 border-t border-slate-100', className)}
      {...props}
    />
  )
)
SidebarSeparator.displayName = 'SidebarSeparator'
