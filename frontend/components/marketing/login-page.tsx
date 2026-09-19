"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { ArrowRight } from "lucide-react";

import { ProntoMark } from "@/components/brand/pronto-mark";
import { ProntoWordmark } from "@/components/brand/pronto-wordmark";
import { AuroraField } from "@/components/marketing/aurora-field";
import { cn } from "@/lib/utils";

/**
 * Entrar de verdad.
 *
 * Esto aceptaba cualquier cosa, escribía una bandera en `sessionStorage` que
 * no lee nadie y esperaba 700 ms para parecer que hacía algo. La pantalla
 * estaba bien y detrás no había nada, así que `/equipo` —que sí necesita una
 * sesión— seguía sin ver al equipo por mucho que "entraras".
 *
 * Ahora la contraseña la comprueba el agente, que es quien tiene el hash, a
 * través de `/api/login` en este mismo origen para que la cookie sea de
 * primera parte. Y lo que se enseña al fallar es lo que ha pasado de verdad:
 * la contraseña, la cuenta sin organización o el agente sin contestar son
 * tres problemas con tres arreglos distintos.
 */
export function LoginPage() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const email = String(data.get("email") ?? "").trim();
    const password = String(data.get("password") ?? "");
    if (!email || !password) {
      setError("Introduce correo y contraseña.");
      return;
    }
    setError("");
    setBusy(true);
    try {
      const response = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const answer = (await response.json().catch(() => ({}))) as {
        ok?: boolean;
        detail?: string;
      };
      if (!response.ok || !answer.ok) {
        setError(answer.detail ?? "No se ha podido iniciar sesión.");
        setBusy(false);
        return;
      }
      // `refresh()` antes de navegar: las pantallas que leen la sesión se
      // pintan en el servidor, y sin esto la primera visita se sirve desde la
      // caché de antes de la cookie — entras, y te sigue diciendo que no.
      router.refresh();
      router.push("/equipo");
    } catch {
      setError("No se puede hablar con el panel. Inténtalo otra vez.");
      setBusy(false);
    }
  };

  return (
    <div className="marketing-shell">
      <AuroraField />
      <header className="relative z-10 mx-auto flex w-full max-w-[1240px] items-center justify-between px-6 py-6 sm:px-10">
        <Link href="/" className="flex items-center gap-3 text-canvas-white" aria-label="Pronto, volver">
          <span className="grid size-10 place-items-center rounded-[12px] bg-canvas-white text-graphite">
            <ProntoMark className="size-[22px]" />
          </span>
          <ProntoWordmark className="hidden h-7 w-[132px] sm:block" />
        </Link>
      </header>

      <main className="relative z-10 flex flex-1 items-center justify-center px-6 pb-16">
        <form
          onSubmit={onSubmit}
          className="w-full max-w-[420px] rounded-[28px] border border-white/10 bg-[#171b19]/75 p-8 shadow-[0_40px_80px_rgb(0_0_0/0.4)] backdrop-blur-xl sm:p-10"
        >
          <p className="font-heading text-[11px] tracking-[0.14em] text-brass uppercase">
            Clínica Arenal
          </p>
          <h1 className="mt-3 font-heading text-[2.1rem] leading-none tracking-[-0.05em] text-canvas-white">
            Entrar al panel
          </h1>
          <p className="mt-3 text-[14px] leading-relaxed text-white/55">
            Recepción en vivo, llamadas y resultados. Con la cuenta de tu
            clínica.
          </p>

          <label className="mt-8 block font-heading text-[12px] text-white/70" htmlFor="email">
            Correo
          </label>
          <input
            id="email"
            name="email"
            type="text"
            autoComplete="username"
            required
            placeholder="recepcion@arenal.es"
            className="mt-2 h-12 w-full rounded-[12px] border border-white/12 bg-white/5 px-3.5 text-[15px] text-canvas-white outline-none placeholder:text-white/30 transition-[border-color,box-shadow] focus-visible:border-brass/70 focus-visible:ring-3 focus-visible:ring-brass/20"
          />

          <label className="mt-5 block font-heading text-[12px] text-white/70" htmlFor="password">
            Contraseña
          </label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            placeholder="••••••••"
            className="mt-2 h-12 w-full rounded-[12px] border border-white/12 bg-white/5 px-3.5 text-[15px] text-canvas-white outline-none placeholder:text-white/30 transition-[border-color,box-shadow] focus-visible:border-brass/70 focus-visible:ring-3 focus-visible:ring-brass/20"
          />

          {error ? (
            <p className="mt-4 text-[13px] text-[#f0a39a]" role="alert">
              {error}
            </p>
          ) : null}

          <button
            type="submit"
            disabled={busy}
            className={cn(
              "cta-glow group mt-8 inline-flex h-12 w-full items-center justify-center gap-2 rounded-full bg-canvas-white font-heading text-[15px] tracking-[-0.02em] text-graphite transition-transform duration-200 hover:-translate-y-0.5 active:scale-[0.98] disabled:translate-y-0 disabled:opacity-70",
            )}
          >
            {busy ? "Entrando…" : "Continuar"}
            <ArrowRight className="size-4 transition-transform duration-200 group-hover:translate-x-0.5" />
          </button>
        </form>
      </main>
    </div>
  );
}
