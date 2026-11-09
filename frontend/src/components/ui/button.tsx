import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '../../lib/utils'

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900 focus-visible:ring-offset-1 disabled:pointer-events-none disabled:opacity-50 select-none cursor-pointer enabled:active:scale-[0.97] duration-150',
  {
    variants: {
      variant: {
        default: 'bg-slate-900 text-white shadow-xs hover:bg-slate-800 active:bg-slate-950',
        primary: 'bg-indigo-600 text-white shadow-xs hover:bg-indigo-500 active:bg-indigo-700',
        secondary: 'bg-slate-100 text-slate-900 shadow-xs hover:bg-slate-200/80 active:bg-slate-200 border border-slate-200/60',
        outline: 'border border-slate-200 bg-white shadow-xs hover:bg-slate-50 hover:text-slate-900 text-slate-700',
        ghost: 'text-slate-700 hover:bg-slate-100 hover:text-slate-900',
        destructive: 'bg-rose-600 text-white shadow-xs hover:bg-rose-500 active:bg-rose-700',
        success: 'bg-emerald-600 text-white shadow-xs hover:bg-emerald-500 active:bg-emerald-700',
      },
      size: {
        default: 'h-9 px-4 py-2',
        xs: 'h-7 rounded px-2.5 text-xs',
        sm: 'h-8 rounded-md px-3 text-xs',
        icon: 'h-9 w-9 p-0',
        'icon-sm': 'h-7 w-7 p-0 rounded',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  }
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  isLoading?: boolean
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, isLoading, children, disabled, ...props }, ref) => {
    return (
      <button
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        disabled={disabled || isLoading}
        {...props}
      >
        {isLoading && (
          <svg className="animate-spin -ml-1 mr-1.5 h-4 w-4" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
          </svg>
        )}
        {children}
      </button>
    )
  }
)
Button.displayName = 'Button'
