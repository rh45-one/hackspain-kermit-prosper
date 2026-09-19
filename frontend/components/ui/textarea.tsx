import * as React from "react"
import { cn } from "cn"

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        "flex min-h-24 w-full resize-y rounded-[10px] border border-input bg-canvas-white px-3.5 py-3 text-[15px] leading-relaxed text-graphite shadow-[0_1px_1px_rgb(29_33_31/0.03)] transition-[border-color,box-shadow] duration-200 outline-none placeholder:text-quiet/70 hover:border-[#bdc2ba] focus-visible:border-brass focus-visible:ring-3 focus-visible:ring-brass/12 disabled:cursor-not-allowed disabled:bg-ash/60 disabled:opacity-60 aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/10",
        className
      )}
      {...props}
    />
  )
}

export { Textarea }
