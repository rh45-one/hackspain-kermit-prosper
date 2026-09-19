import { ProntoMark } from "@/components/brand/pronto-mark";

const LINES = [
  { who: "Elena", text: "Buenos días, quiero cita con pediatría." },
  { who: "Pronto", text: "Claro. ¿Me dice su documento, por favor?" },
  { who: "Elena", text: "12345678Z. Para el jueves, si hay hueco." },
  { who: "Pronto", text: "Jueves 10:30, Dra. Peral, Arenal Norte." },
] as const;

export function CallPreview() {
  return (
    <div className="call-preview relative mx-auto w-full max-w-[420px]">
      <div className="hero-rings" aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
      <div className="relative overflow-hidden rounded-[28px] border border-white/10 bg-[#171b19]/80 p-6 shadow-[0_40px_80px_rgb(0_0_0/0.45)] backdrop-blur-xl sm:p-7">
        <div className="mb-6 flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <span className="grid size-10 place-items-center rounded-[12px] bg-canvas-white text-graphite">
              <ProntoMark className="size-6" />
            </span>
            <div>
              <p className="font-heading text-[13px] leading-none tracking-[-0.03em] text-canvas-white">
                Línea 01
              </p>
              <p className="mt-1.5 text-[11px] leading-none text-white/45">Clínica Arenal · en curso</p>
            </div>
          </div>
          <p className="flex items-center gap-2 font-heading text-[11px] text-[#8fd19a]">
            <span className="status-dot-online size-1.5 rounded-full" />
            En vivo
          </p>
        </div>
        <ul className="space-y-3">
          {LINES.map((line, index) => (
            <li
              key={line.text}
              className="preview-line rounded-[14px] px-3.5 py-2.5"
              style={{ animationDelay: `${900 + index * 420}ms` }}
            >
              <p className="font-heading text-[10px] tracking-[0.08em] text-white/40 uppercase">
                {line.who}
              </p>
              <p className="mt-1 text-[13px] leading-snug text-canvas-white/90">{line.text}</p>
            </li>
          ))}
        </ul>
        <div className="mt-6 flex items-center justify-between border-t border-white/8 pt-4 text-[11px] text-white/40">
          <span>BOOKED · pediatría</span>
          <span>0,8 s al saludo</span>
        </div>
      </div>
    </div>
  );
}
