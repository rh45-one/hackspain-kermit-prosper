/**
 * El contrato de `GET /ops/api/live/cover`, tal y como lo define
 * `agent/ops/cover.py`. Sólo lo que el panel dibuja.
 */
export type CoverPerson = {
  slug: string;
  name: string;
  role: string;
  detail: string;
  phone: string;
  covers_for: string;
  /** "jev" cuando lo ha elegido el sidecar; "route" cuando es la ruta configurada. */
  source: "jev" | "route";
};

export type CoverSuggestion = {
  situation: string;
  reason: string;
  /** Falso cuando no había situación que preguntar: entonces nadie ha llamado a Jev. */
  asked: boolean;
  suggested: CoverPerson | null;
  fallback: CoverPerson | null;
  urgency: string;
  /** Por encima del umbral. Es la diferencia entre una decisión y un encogimiento de hombros. */
  sure: boolean;
  confidence: number;
  threshold: number;
  /** chosen | not_confident | unclear | unreachable | http_error | malformed | not_asked */
  why: string;
  considered: { slug: string; name: string; role: string }[];
  latency_ms: number;
};
