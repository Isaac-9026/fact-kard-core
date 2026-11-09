import * as React from 'react'
import { cn } from '../../lib/utils'

export interface TableProps extends React.HTMLAttributes<HTMLTableElement> {
  containerClassName?: string
}

export const Table = React.forwardRef<HTMLTableElement, TableProps>(
  ({ className, containerClassName, ...props }, ref) => (
    <div
      className={cn(
        'relative w-full overflow-auto rounded-lg border border-slate-200/90 bg-white shadow-2xs overscroll-contain',
        containerClassName
      )}
    >
      <table ref={ref} className={cn('w-full caption-bottom text-xs text-left border-collapse', className)} {...props} />
    </div>
  )
)
Table.displayName = 'Table'

export const TableHeader = React.forwardRef<HTMLTableSectionElement, React.HTMLAttributes<HTMLTableSectionElement>>(
  ({ className, ...props }, ref) => (
    <thead
      ref={ref}
      className={cn(
        'sticky top-0 z-10 bg-slate-100/95 backdrop-blur-xs border-b border-slate-200 text-[11px] font-semibold uppercase tracking-wider text-slate-600 select-none',
        className
      )}
      {...props}
    />
  )
)
TableHeader.displayName = 'TableHeader'

export const TableBody = React.forwardRef<HTMLTableSectionElement, React.HTMLAttributes<HTMLTableSectionElement>>(
  ({ className, ...props }, ref) => (
    <tbody ref={ref} className={cn('divide-y divide-slate-200/70 text-slate-700', className)} {...props} />
  )
)
TableBody.displayName = 'TableBody'

export const TableFooter = React.forwardRef<HTMLTableSectionElement, React.HTMLAttributes<HTMLTableSectionElement>>(
  ({ className, ...props }, ref) => (
    <tfoot ref={ref} className={cn('border-t-2 border-slate-300 bg-slate-50/90 font-medium text-slate-900', className)} {...props} />
  )
)
TableFooter.displayName = 'TableFooter'

export const TableRow = React.forwardRef<HTMLTableRowElement, React.HTMLAttributes<HTMLTableRowElement>>(
  ({ className, ...props }, ref) => (
    <tr
      ref={ref}
      className={cn(
        'hover:bg-slate-50/90 transition-colors duration-100 border-b border-slate-200/60 last:border-0',
        className
      )}
      {...props}
    />
  )
)
TableRow.displayName = 'TableRow'

export const TableHead = React.forwardRef<HTMLTableCellElement, React.ThHTMLAttributes<HTMLTableCellElement> & { numeric?: boolean }>(
  ({ className, numeric, ...props }, ref) => (
    <th
      ref={ref}
      className={cn(
        'h-8 px-2.5 py-1.5 align-middle font-semibold text-slate-600 whitespace-nowrap',
        numeric && 'text-right font-mono tabular-nums',
        className
      )}
      {...props}
    />
  )
)
TableHead.displayName = 'TableHead'

export const TableCell = React.forwardRef<HTMLTableCellElement, React.TdHTMLAttributes<HTMLTableCellElement> & { numeric?: boolean }>(
  ({ className, numeric, ...props }, ref) => (
    <td
      ref={ref}
      className={cn(
        'px-2.5 py-1.5 align-middle text-slate-700',
        numeric && 'text-right font-mono tabular-nums',
        className
      )}
      {...props}
    />
  )
)
TableCell.displayName = 'TableCell'
