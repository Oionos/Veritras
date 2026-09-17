import { cn } from '@/utils/cn'

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost'
  children: React.ReactNode
}

const variants = {
  primary:
    'bg-accent text-bg font-semibold hover:bg-accent/90 active:bg-accent/80 shadow-glow',
  secondary:
    'border border-border bg-transparent text-text hover:border-accent/50 hover:bg-surface2 active:bg-surface2/80',
  ghost:
    'bg-transparent text-muted hover:text-text hover:bg-surface2 active:bg-surface2/80',
}

export default function Button({
  children,
  variant = 'primary',
  className,
  disabled,
  ...props
}: ButtonProps) {
  return (
    <button
      className={cn(
        'inline-flex items-center justify-center gap-2 rounded-button px-5 py-2.5 text-sm transition-[transform,background-color,border-color,color,box-shadow] duration-200 ease-out active:scale-[0.97] focus:outline-hidden focus:ring-2 focus:ring-accent/30 disabled:cursor-not-allowed disabled:opacity-50',
        variants[variant],
        className
      )}
      disabled={disabled}
      {...props}
    >
      {children}
    </button>
  )
}
