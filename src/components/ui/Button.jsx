import { cn } from '../../lib/utils';

const variants = {
  default:
    'bg-zinc-900 text-zinc-50 hover:bg-zinc-800 shadow-sm dark:bg-zinc-100 dark:text-zinc-950 dark:hover:bg-white',
  secondary:
    'bg-white text-zinc-700 border border-zinc-200 hover:bg-zinc-50 hover:text-zinc-900 dark:bg-zinc-900 dark:text-zinc-200 dark:border-zinc-800 dark:hover:bg-zinc-800 dark:hover:text-zinc-50',
  ghost:
    'text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 dark:text-zinc-400 dark:hover:bg-zinc-800 dark:hover:text-zinc-100',
  destructive:
    'bg-white text-zinc-600 border border-zinc-200 hover:bg-rose-50 hover:text-rose-700 hover:border-rose-200 dark:bg-zinc-900 dark:text-zinc-300 dark:border-zinc-800 dark:hover:bg-rose-950/40 dark:hover:text-rose-300 dark:hover:border-rose-900/50',
  primary:
    'bg-emerald-600 text-white hover:bg-emerald-500 shadow-sm font-medium dark:bg-emerald-500 dark:text-zinc-950 dark:hover:bg-emerald-400',
};

const sizes = {
  default: 'h-9 px-3 text-xs',
  sm: 'h-8 px-2.5 text-xs',
  lg: 'h-10 px-4 text-sm',
  icon: 'h-8 w-8 p-0',
};

export function Button({
  className,
  variant = 'default',
  size = 'default',
  type = 'button',
  ...props
}) {
  return (
    <button
      type={type}
      className={cn(
        'inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors',
        'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-zinc-400 dark:focus-visible:ring-zinc-500',
        'disabled:pointer-events-none disabled:opacity-40',
        'active:scale-[0.98]',
        variants[variant] || variants.default,
        sizes[size] || sizes.default,
        className,
      )}
      {...props}
    />
  );
}
