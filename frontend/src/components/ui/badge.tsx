import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '../../lib/utils'

const badgeVariants = cva(
  'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors select-none font-sans',
  {
    variants: {
      variant: {
        default: 'border-slate-900 bg-slate-900 text-white',
        success: 'border-emerald-200 bg-emerald-50 text-emerald-700',
        warning: 'border-amber-200 bg-amber-50 text-amber-700',
        destructive: 'border-rose-200 bg-rose-50 text-rose-700',
        info: 'border-indigo-200 bg-indigo-50 text-indigo-700',
        neutral: 'border-slate-200 bg-slate-100 text-slate-700',
        outline: 'border-slate-200 bg-white text-slate-700',
      },
      size: {
        default: 'text-xs px-2.5 py-0.5',
        xs: 'text-[9px] px-1.5 py-0 font-semibold',
        sm: 'text-[10px] px-2 py-0.2',
        lg: 'text-sm px-3 py-1',
      },
    },
    defaultVariants: {
      variant: 'neutral',
      size: 'default',
    },
  }
)

const dotColorMap: Record<string, string> = {
  default: 'bg-white',
  success: 'bg-emerald-500',
  warning: 'bg-amber-500',
  destructive: 'bg-rose-500',
  info: 'bg-indigo-500',
  neutral: 'bg-slate-400',
  outline: 'bg-slate-400',
}

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {
  dot?: boolean
}

export function Badge({ className, variant = 'neutral', size, dot, children, ...props }: BadgeProps) {
  const dotColor = dotColorMap[variant || 'neutral'] || 'bg-slate-400'
  return (
    <div className={cn(badgeVariants({ variant, size }), className)} {...props}>
      {dot && <span className={cn('h-1.5 w-1.5 rounded-full shrink-0 motion-safe:animate-pulse', dotColor)} />}
      {children}
    </div>
  )
}
