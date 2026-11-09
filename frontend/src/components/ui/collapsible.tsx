import * as React from 'react'
import { cn } from '../../lib/utils'

interface CollapsibleContextValue {
  open: boolean
  toggle: () => void
}

const CollapsibleContext = React.createContext<CollapsibleContextValue | null>(null)

// Hook del mismo componente (patrón shadcn); no afecta al fast refresh en la práctica.
// eslint-disable-next-line react-refresh/only-export-components
export function useCollapsible() {
  const context = React.useContext(CollapsibleContext)
  if (!context) {
    throw new Error('useCollapsible must be used within a Collapsible')
  }
  return context
}

export interface CollapsibleProps extends React.HTMLAttributes<HTMLDivElement> {
  open?: boolean
  defaultOpen?: boolean
  onOpenChange?: (open: boolean) => void
  asChild?: boolean
}

export const Collapsible = React.forwardRef<HTMLDivElement, CollapsibleProps>(
  ({ open: controlledOpen, defaultOpen = true, onOpenChange, className, children, ...props }, ref) => {
    const [uncontrolledOpen, setUncontrolledOpen] = React.useState(defaultOpen)
    const isControlled = controlledOpen !== undefined
    const open = isControlled ? controlledOpen : uncontrolledOpen

    const toggle = React.useCallback(() => {
      const nextOpen = !open
      if (!isControlled) {
        setUncontrolledOpen(nextOpen)
      }
      onOpenChange?.(nextOpen)
    }, [open, isControlled, onOpenChange])

    return (
      <CollapsibleContext.Provider value={{ open, toggle }}>
        <div
          ref={ref}
          data-state={open ? 'open' : 'closed'}
          className={cn('group/collapsible w-full', className)}
          {...props}
        >
          {children}
        </div>
      </CollapsibleContext.Provider>
    )
  }
)
Collapsible.displayName = 'Collapsible'

export interface CollapsibleTriggerProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  asChild?: boolean
}

export const CollapsibleTrigger = React.forwardRef<HTMLButtonElement, CollapsibleTriggerProps>(
  ({ className, onClick, children, ...props }, ref) => {
    const { open, toggle } = useCollapsible()

    return (
      <button
        ref={ref}
        type="button"
        data-state={open ? 'open' : 'closed'}
        onClick={(e) => {
          onClick?.(e)
          toggle()
        }}
        className={cn('cursor-pointer select-none', className)}
        {...props}
      >
        {children}
      </button>
    )
  }
)
CollapsibleTrigger.displayName = 'CollapsibleTrigger'

export type CollapsibleContentProps = React.HTMLAttributes<HTMLDivElement>

export const CollapsibleContent = React.forwardRef<HTMLDivElement, CollapsibleContentProps>(
  ({ className, children, ...props }, ref) => {
    const { open } = useCollapsible()

    return (
      <div
        ref={ref}
        data-state={open ? 'open' : 'closed'}
        aria-hidden={!open}
        className={cn(
          'grid w-full transition-[grid-template-rows,opacity] duration-200 ease-out motion-reduce:transition-none',
          open ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0 pointer-events-none',
          className
        )}
        {...props}
      >
        <div className="overflow-hidden min-h-0">
          {children}
        </div>
      </div>
    )
  }
)
CollapsibleContent.displayName = 'CollapsibleContent'
