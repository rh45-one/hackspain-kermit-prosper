import * as React from "react"
import { cn } from "cn"

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "h-11 w-full min-w-0 rounded-[10px] border border-input bg-canvas-white px-3.5 py-2 text-[15px] text-graphite shadow-[0_1px_1px_rgb(29_33_31/0.03)] transition-[border-color,box-shadow,background-color] duration-200 outline-none file:mr-3 file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-[13px] file:font-medium file:text-foreground placeholder:text-quiet/70 hover:border-[#bdc2ba] focus-visible:border-brass focus-visible:ring-3 focus-visible:ring-brass/12 disabled:pointer-events-none disabled:cursor-not-allowed disabled:bg-ash/60 disabled:opacity-60 aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/10",
        className
      )}
      {...props}
    />
  )
}

export { Input }
