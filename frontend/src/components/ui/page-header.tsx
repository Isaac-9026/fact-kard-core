import * as React from 'react'
import { cn } from '../../lib/utils'

export interface PageHeaderProps {
  title: string
  description?: string
  icon?: React.ReactNode | React.ComponentType<{ className?: string }>
  badge?: React.ReactNode
  actions?: React.ReactNode
  className?: string
}

export function PageHeader({
  title,
  description,
  icon,
  badge,
  actions,
  className,
}: PageHeaderProps) {
  const renderIcon = () => {
    if (!icon) return null
    if (React.isValidElement(icon)) return icon
    const IconComponent = icon as React.ComponentType<{ className?: string }>
    return <IconComponent className="h-4 w-4" />
  }

  return (
    <div
      className={cn(
        'flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3.5 border-b border-slate-200/80 mb-4 sm:mb-5',
        className
      )}
    >
      <div className="flex items-start gap-2.5">
        {icon && (
          <div className="h-8 w-8 rounded-lg bg-indigo-50 border border-indigo-100/80 flex items-center justify-center text-indigo-600 shrink-0 shadow-2xs mt-0.5">
            {renderIcon()}
          </div>
        )}
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="text-lg font-bold tracking-tight text-slate-900 font-sans">{title}</h1>
            {badge}
          </div>
          {description && (
            <p className="text-xs text-slate-500 mt-0.5 max-w-3xl leading-relaxed">{description}</p>
          )}
        </div>
      </div>
      {actions && <div className="flex items-center gap-2 shrink-0 flex-wrap">{actions}</div>}
    </div>
  )
}
