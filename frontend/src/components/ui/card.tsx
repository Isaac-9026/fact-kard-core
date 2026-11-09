import * as React from 'react'
import { cn } from '../../lib/utils'

export const Card = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      // min-w-0: dentro de un grid/flex, una tabla ancha no estira la tarjeta (la tabla se desplaza dentro).
      className={cn('min-w-0 rounded-lg border border-slate-200/90 bg-white text-slate-900 shadow-2xs transition-shadow', className)}
      {...props}
    />
  )
)
Card.displayName = 'Card'

export const CardHeader = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn('flex flex-col space-y-1 p-3.5 sm:p-4 border-b border-slate-100/90', className)} {...props} />
  )
)
CardHeader.displayName = 'CardHeader'

export const CardTitle = React.forwardRef<HTMLParagraphElement, React.HTMLAttributes<HTMLHeadingElement>>(
  ({ className, ...props }, ref) => (
    <h3 ref={ref} className={cn('font-semibold text-sm leading-snug tracking-tight text-slate-900', className)} {...props} />
  )
)
CardTitle.displayName = 'CardTitle'

export const CardDescription = React.forwardRef<HTMLParagraphElement, React.HTMLAttributes<HTMLParagraphElement>>(
  ({ className, ...props }, ref) => (
    <p ref={ref} className={cn('text-[11px] text-slate-500 mt-0.5', className)} {...props} />
  )
)
CardDescription.displayName = 'CardDescription'

export const CardContent = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => <div ref={ref} className={cn('p-3.5 sm:p-4', className)} {...props} />
)
CardContent.displayName = 'CardContent'

export const CardFooter = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn('flex items-center p-3.5 sm:p-4 pt-0 border-t border-slate-100/90 mt-1', className)} {...props} />
  )
)
CardFooter.displayName = 'CardFooter'

export interface KpiCardProps {
  title: string
  value: React.ReactNode
  subtitle?: React.ReactNode
  icon?: React.ReactNode | React.ComponentType<{ className?: string }>
  badge?: React.ReactNode
  className?: string
  trend?: {
    value: string
    positive?: boolean
  }
}

export function KpiCard({ title, value, subtitle, icon, badge, className, trend }: KpiCardProps) {
  const renderIcon = () => {
    if (!icon) return null
    if (React.isValidElement(icon)) return icon
    const IconComponent = icon as React.ComponentType<{ className?: string }>
    return <IconComponent className="h-3.5 w-3.5" />
  }

  return (
    <Card className={cn('overflow-hidden relative border-slate-200/90 bg-white shadow-2xs hover:border-slate-300 transition-colors', className)}>
      <div className="p-3 sm:p-3.5">
        <div className="flex items-center justify-between gap-1.5">
          <span className="text-[11px] font-semibold text-slate-500 tracking-wider uppercase truncate">{title}</span>
          <div className="flex items-center gap-1.5 shrink-0">
            {badge}
            {icon && (
              <div className="h-6 w-6 rounded-md bg-slate-50 border border-slate-200/80 flex items-center justify-center text-slate-600">
                {renderIcon()}
              </div>
            )}
          </div>
        </div>
        <div className="mt-2 flex items-baseline gap-2">
          <div className="text-xl sm:text-2xl font-bold font-mono tabular-nums tracking-tight text-slate-900 truncate">
            {value}
          </div>
          {trend && (
            <span className={cn('text-xs font-semibold font-mono tabular-nums', trend.positive ? 'text-emerald-600' : 'text-rose-600')}>
              {trend.positive ? '+' : ''}{trend.value}
            </span>
          )}
        </div>
        {subtitle && <p className="mt-0.5 text-[11px] text-slate-500 truncate">{subtitle}</p>}
      </div>
    </Card>
  )
}
