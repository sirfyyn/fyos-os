/**
 * Button — Knopf mit Variante und Größe (Muster wie shadcn/ui), ohne zusätzliche Abhängigkeit.
 */
import { splitProps, type Component, type ComponentProps, type JSX } from 'solid-js';
import { cn } from '~/lib/cn';

const BASIS =
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium ring-offset-(--color-bg) transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--color-accent) focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50';

const VARIANTEN = {
  default: 'bg-(--color-accent) text-(--color-accent-text) hover:bg-(--color-accent-glow)',
  soft: 'bg-(--color-accent-soft) text-(--color-accent) hover:opacity-80',
  secondary:
    'bg-(--color-card) text-(--color-fg) border border-(--color-border) hover:bg-(--color-card-hover) hover:border-(--color-border-strong)',
  ghost: 'text-(--color-fg-muted) hover:bg-(--color-card-hover) hover:text-(--color-fg)',
  outline: 'border border-(--color-border-strong) bg-transparent text-(--color-fg) hover:bg-(--color-card-hover)',
  destructive: 'bg-(--color-error) text-(--color-accent-text) hover:opacity-90',
  link: 'text-(--color-accent) underline-offset-4 hover:underline',
} as const;

const GROESSEN = {
  default: 'h-9 px-4 py-2',
  sm: 'h-8 rounded-md px-3 text-xs',
  xs: 'h-7 rounded-md px-2.5 text-xs',
  lg: 'h-10 rounded-md px-6',
  icon: 'h-9 w-9',
} as const;

export type ButtonVariante = keyof typeof VARIANTEN;
export type ButtonGroesse = keyof typeof GROESSEN;

export const buttonVariants = (o: { variant?: ButtonVariante | null; size?: ButtonGroesse | null } = {}): string =>
  cn(BASIS, VARIANTEN[o.variant ?? 'default'], GROESSEN[o.size ?? 'default']);

export interface ButtonProps extends ComponentProps<'button'> {
  variant?: ButtonVariante | null;
  size?: ButtonGroesse | null;
  /** Rendert ein `<a>` statt `<button>` (für Navigation) */
  href?: string;
}

export const Button: Component<ButtonProps> = (props) => {
  const [local, rest] = splitProps(props, ['variant', 'size', 'class', 'href', 'children']);
  const classes = () => cn(buttonVariants({ variant: local.variant, size: local.size }), local.class);

  if (local.href) {
    return (
      <a href={local.href} class={classes()} {...(rest as unknown as JSX.AnchorHTMLAttributes<HTMLAnchorElement>)}>
        {local.children}
      </a>
    );
  }

  return (
    <button class={classes()} {...rest}>
      {local.children}
    </button>
  );
};
