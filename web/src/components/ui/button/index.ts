import type { VariantProps } from 'class-variance-authority'
import { cva } from 'class-variance-authority'

export { default as Button } from './Button.vue'

export const buttonVariants = cva(
  'btn',
  {
    variants: {
      variant: {
        default: 'btn-primary',
        destructive: 'btn-danger',
        outline: 'btn-secondary',
        secondary: 'btn-secondary',
        ghost: 'btn-ghost',
        link: 'text-primary underline-offset-4 hover:underline !shadow-none !p-0',
      },
      size: {
        'default': '',
        'sm': 'btn-sm',
        'lg': 'px-6 py-3 text-base',
        'icon': 'btn-icon',
        'icon-sm': 'btn-icon btn-sm',
        'icon-lg': 'btn-icon px-3 py-3',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  },
)

export type ButtonVariants = VariantProps<typeof buttonVariants>
