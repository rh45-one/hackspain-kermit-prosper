/**
 * "¿Quién cubre esto?" — resuelto al refrescar la página, no al llamar.
 *
 * Un formulario GET y nada más: escribes lo que ha pasado, pulsas enter, y el
 * navegador recarga `/grafo?situacion=...`. Esa recarga es la que pregunta a
 * Jev, en el servidor, con el token que nunca baja al cliente. No hay estado,
 * no hay `useEffect`, no hay spinner — y el resultado es enlazable: puedes
 * mandar la URL a un compañero y verá exactamente lo mismo.
 *
 * Esa es la razón de que esté aquí y no en la llamada. El agente, hablando por
 * teléfono, ya tiene la ruta configurada y la resuelve en microsegundos; meterle
 * una consulta de ~800 ms a mitad de turno es pagar silencio por un consejo. El
 * panel, en cambio, no tiene a nadie esperando.
 *
 * La sugerencia se dibuja siempre junto a la ruta configurada, y dice de cuál
 * de las dos viene. Cuando Jev se abstiene —que pasa, y debe pasar— lo que se
 * ve es la ruta de siempre, sin un hueco ni un error.
 */
import type { CoverSuggestion } from "@/lib/cover";

const EXAMPLES = [
  "El jefe de ginecología está de baja el lunes",
  "Marina no puede venir y hay una urgencia de salud mental",
  "Hugo está de vacaciones y hay pacientes de otorrino",
];

export function CoverSuggestionPanel({
  situation,
  cover,
}: {
  situation: string;
  cover: CoverSuggestion | null;
}) {
  const suggested = cover?.suggested ?? null;
  const fromJev = suggested?.source === "jev";

  return (
    <section
      data-reveal=""
      className="mb-10 rounded-2xl border border-mist bg-white/70 p-5 sm:p-6"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-heading text-[17px] tracking-[-0.02em] text-graphite">
          ¿Quién cubre esto?
        </h2>
        <p className="text-[12px] text-steel">
          Lo decide Jev al recargar la página. Nunca durante una llamada.
        </p>
      </div>

      <form method="get" action="/grafo" className="mt-4 flex flex-wrap gap-2">
        <input
          type="text"
          name="situacion"
          defaultValue={situation}
          placeholder="Qué ha pasado, con tus palabras"
          aria-label="Qué ha pasado"
          className="min-w-[16rem] flex-1 rounded-xl border border-mist bg-white px-3.5 py-2.5 text-[14px] text-graphite outline-none placeholder:text-steel/70 focus:border-graphite"
        />
        <input type="hidden" name="motivo" value="provider_on_leave" />
        <button
          type="submit"
          className="rounded-xl bg-graphite px-4 py-2.5 text-[14px] font-medium text-white transition-opacity hover:opacity-90"
        >
          Preguntar
        </button>
      </form>

      {!situation ? (
        <ul className="mt-3 flex flex-wrap gap-2">
          {EXAMPLES.map((example) => (
            <li key={example}>
              <a
                href={`/grafo?situacion=${encodeURIComponent(example)}&motivo=provider_on_leave`}
                className="inline-block rounded-full border border-mist px-3 py-1 text-[12px] text-steel transition-colors hover:border-graphite hover:text-graphite"
              >
                {example}
              </a>
            </li>
          ))}
        </ul>
      ) : null}

      {situation && suggested ? (
        <div className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-mist pt-4">
          <span
            className={`rounded-full px-2.5 py-1 text-[11px] font-medium uppercase tracking-wide ${
              fromJev ? "bg-graphite text-white" : "border border-mist text-steel"
            }`}
          >
            {fromJev ? "Jev sugiere" : "Ruta configurada"}
          </span>
          <span className="font-heading text-[19px] tracking-[-0.02em] text-graphite">
            {suggested.name}
          </span>
          <span className="text-[13px] text-steel">{suggested.role}</span>
          {suggested.phone ? (
            <a
              href={`tel:${suggested.phone}`}
              className="text-[13px] text-graphite underline decoration-mist underline-offset-4"
            >
              {suggested.phone}
            </a>
          ) : null}
          {fromJev && cover?.fallback && cover.fallback.slug !== suggested.slug ? (
            <span className="text-[12px] text-steel">
              sin preguntar habría ido a {cover.fallback.name}
            </span>
          ) : null}
          {cover?.latency_ms ? (
            <span className="ml-auto text-[12px] tabular-nums text-steel/80">
              {Math.round(cover.latency_ms)} ms
            </span>
          ) : null}
        </div>
      ) : null}

      {situation && !fromJev && cover?.asked ? (
        <p className="mt-2 text-[12px] leading-[1.6] text-steel">
          Jev no ha visto a nadie claramente mejor que la ruta, así que no ha elegido. Abstenerse
          es una respuesta: la clínica sigue teniendo a quien llamar.
        </p>
      ) : null}
    </section>
  );
}
