"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";

import { ProntoMark } from "@/components/brand/pronto-mark";
import { ProntoWordmark } from "@/components/brand/pronto-wordmark";
import { AuroraField } from "@/components/marketing/aurora-field";
import { CallPreview } from "@/components/marketing/call-preview";

const STATS = [
  { value: "12", label: "clinicians on the book" },
  { value: "Madrid", label: "clinic time, always" },
  { value: "A verb", label: "never a ghost slot" },
] as const;

export function LandingPage() {
  return (
    <div className="marketing-shell">
      <AuroraField />
      <header className="relative z-10 mx-auto flex w-full max-w-[1240px] items-center justify-between px-6 py-6 sm:px-10">
        <Link href="/" className="flex items-center gap-3 text-canvas-white" aria-label="Pronto">
          <span className="grid size-10 place-items-center rounded-[12px] bg-canvas-white text-graphite shadow-[0_8px_24px_rgb(255_254_251/0.12)]">
            <ProntoMark className="size-[22px]" />
          </span>
          <ProntoWordmark className="hidden h-7 w-[132px] sm:block" />
        </Link>
        <Link
          href="/login"
          className="rounded-full border border-white/12 bg-white/5 px-4 py-2 font-heading text-[13px] text-canvas-white/90 backdrop-blur-md transition-[background-color,transform] duration-200 hover:bg-white/10 active:scale-[0.98]"
        >
          Sign in
        </Link>
      </header>

      <main className="relative z-10 mx-auto grid w-full max-w-[1240px] flex-1 items-center gap-10 px-6 pt-4 pb-12 sm:px-10 md:grid-cols-[minmax(0,1fr)_minmax(260px,400px)] md:gap-10 lg:gap-12">
        <div>
          <p
            data-reveal=""
            className="mb-5 flex items-center gap-2.5 font-heading text-[11px] tracking-[0.14em] text-brass uppercase"
          >
            <span className="h-px w-7 bg-brass/80" />
            Voice at the desk
          </p>
          <h1
            data-reveal=""
            data-delay="1"
            className="max-w-[20ch] overflow-visible pb-[0.16em] font-heading text-[clamp(2.6rem,6.4vw,5.2rem)] leading-[1.04] tracking-[-0.06em] text-canvas-white"
          >
            Booked{" "}
            <span className="hero-gradient-word">before you hang up.</span>
          </h1>
          <p
            data-reveal=""
            data-delay="2"
            className="mt-6 max-w-[34rem] text-[17px] leading-relaxed text-white/62 sm:text-[18px]"
          >
            Pronto takes Clínica Arenal&apos;s line, names the case, and files
            the action. The model never invents a slot — it sends a verb.
          </p>
          <div data-reveal="" data-delay="3" className="mt-9 flex flex-wrap items-center gap-4">
            <Link href="/login" className="cta-glow group inline-flex items-center gap-2 rounded-full bg-canvas-white px-6 py-3.5 font-heading text-[15px] tracking-[-0.02em] text-graphite transition-transform duration-200 hover:-translate-y-0.5 active:translate-y-0 active:scale-[0.98]">
              Open the desk
              <ArrowRight className="size-4 transition-transform duration-200 group-hover:translate-x-0.5" />
            </Link>
            <p className="text-[13px] text-white/40">Clínica Arenal · HackSpain 2026</p>
          </div>
        </div>
        <div className="md:justify-self-end">
          <CallPreview />
        </div>
      </main>

      <footer className="relative z-10 mx-auto w-full max-w-[1240px] px-6 pb-10 sm:px-10">
        <ul className="grid gap-6 border-t border-white/10 pt-8 sm:grid-cols-3">
          {STATS.map((stat) => (
            <li key={stat.label} data-reveal="">
              <p className="font-heading text-[1.65rem] leading-none tracking-[-0.04em] text-canvas-white">
                {stat.value}
              </p>
              <p className="mt-2 text-[13px] text-white/45">{stat.label}</p>
            </li>
          ))}
        </ul>
      </footer>
    </div>
  );
}
