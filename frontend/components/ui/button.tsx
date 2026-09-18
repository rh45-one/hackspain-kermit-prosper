import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "cn"
import { Slot } from "radix-ui"

const buttonVariants = cva(
  "group/button inline-flex shrink-0 items-center justify-center rounded-[10px] border border-transparent font-heading text-[14px] leading-none tracking-[-0.01em] whitespace-nowrap shadow-sm transition-[transform,background-color,border-color,color,box-shadow] duration-200 outline-none select-none hover:-translate-y-px focus-visible:ring-2 focus-visible:ring-brass/35 disabled:pointer-events-none disabled:translate-y-0 disabled:cursor-not-allowed disabled:opacity-40 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: "bg-graphite text-canvas-white hover:bg-[#313733] hover:shadow-md",
        outline: "border-mist bg-canvas-white text-graphite hover:border-[#c6cac3] hover:bg-fog",
        secondary: "bg-ash text-graphite hover:bg-mist",
        ghost: "shadow-none text-graphite hover:bg-ash/70",
        destructive: "shadow-none text-ember-orange hover:bg-ivory",
        link: "ember-underline text-graphite",
      },
      size: {
        default: "h-10 gap-2 px-4",
        xs: "h-7 gap-1 px-2.5 text-[12px]",
        sm: "h-9 gap-1.5 px-3.5 text-[13px]",
        lg: "h-11 gap-2 px-5 text-[15px]",
        icon: "size-10",
        "icon-xs": "size-8",
        "icon-sm": "size-9",
        "icon-lg": "size-11",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Button({
  className,
  variant = "default",
  size = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
  }) {
  const Comp = asChild ? Slot.Root : "button"

  return (
    <Comp
      data-slot="button"
      data-variant={variant}
      data-size={size}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
