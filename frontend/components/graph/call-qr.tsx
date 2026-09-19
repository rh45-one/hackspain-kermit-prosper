"use client";

import { useEffect, useMemo, useRef } from "react";

import { encodeQr, qrPath } from "@/lib/qr";
import { URGENCY, type CallSubject } from "@/lib/graph";
import { cn } from "@/lib/utils";

/**
 * The end of the escalation, made demonstrable.
 *
 * The graph already says who has to be told and how fast. The honest gap is
 * that nobody's phone rings: dialling a real number is another product
 * (carrier, consent, an audit of who was woken at 3 a.m.). So this closes the
 * loop the only way that is true today — a QR that opens the agent's own
 * browser call page, so anyone in the room can pick up their phone and talk to
 * it.
 *
 * Three things this screen must never blur, and does not:
 *  - who is being called, by name, and why, in the clinic's words;
 *  - that it is a demonstration, said in full size and not in a footnote;
 *  - the URL itself, in plain text, so nobody has to trust a black square.
 *
 * Escape is owned by the board, not by this component: it has to close the
 * dialog before it unpins the node, and two listeners racing for one key is
 * how you end up closing both in front of a jury.
 */

/** The size of the code on screen. 29 modules across a 380 px box is 13 px a
 * module, which is what makes it scannable from the back of a room, off a
 * projector, at an angle. */
const QUIET_ZONE = 4;

function QrCodeSvg({ url }: { url: string }) {
  const drawn = useMemo(() => {
    try {
      const code = encodeQr(url);
      return { code, d: qrPath(code) };
    } catch {
      return null;
    }
  }, [url]);

  if (!drawn) {
    return (
      <p className="rounded-[10px] border border-dashed border-ember-orange/50 bg-canvas-white px-4 py-3 text-[13px] leading-[1.5] text-steel">
        Esa dirección es demasiado larga para dibujarla como QR. Ábrela a mano:{" "}
        <span className="font-mono break-all">{url}</span>
      </p>
    );
  }

  const span = drawn.code.size + QUIET_ZONE * 2;
  return (
    <svg
      viewBox={`0 0 ${span} ${span}`}
      role="img"
      aria-label={`Código QR que abre ${url}`}
      className="block h-auto w-full max-w-[400px] rounded-[10px]"
      shapeRendering="crispEdges"
    >
      {/* Pure black on pure white, not the brand greys: a scanner decides on
          luminance contrast, and a projector eats most of it before the code
          reaches anyone's camera. The quiet zone is the spec's four modules —
          without it the corners stop being findable. */}
      <rect width={span} height={span} fill="#ffffff" />
      <g transform={`translate(${QUIET_ZONE} ${QUIET_ZONE})`}>
        <path d={drawn.d} fill="#000000" />
      </g>
    </svg>
  );
}

function isLoopback(url: string): boolean {
  try {
    const host = new URL(url).hostname;
    return host === "localhost" || host === "127.0.0.1" || host === "0.0.0.0" || host === "::1";
  } catch {
    return false;
  }
}

/** The button that opens it. Lives in the inspector, next to the route it calls. */
export function CallButton({
  subject,
  onClick,
}: {
  subject: CallSubject;
  onClick: () => void;
}) {
  const urgency = URGENCY[subject.escalation.urgency];
  return (
    <button
      type="button"
      onClick={onClick}
      className="group mt-4 flex w-full cursor-pointer items-center gap-3 rounded-[12px] border px-4 py-3 text-left transition-[transform,box-shadow] duration-200 hover:-translate-y-px hover:shadow-[var(--shadow-md)] focus-visible:ring-2 focus-visible:ring-brass/40 focus-visible:outline-none"
      style={{ borderColor: urgency.ink, background: `${urgency.ink}0f` }}
    >
      <span
        aria-hidden
        className="flex size-9 shrink-0 items-center justify-center rounded-full"
        style={{ background: urgency.ink }}
      >
        <svg viewBox="0 0 24 24" width="17" height="17" fill="#fffefb">
          <path d="M6.6 10.8a15.5 15.5 0 0 0 6.6 6.6l2.2-2.2c.3-.3.7-.4 1.1-.2 1.2.4 2.5.6 3.8.6.5 0 .9.4.9.9v3.4c0 .5-.4.9-.9.9A17.1 17.1 0 0 1 3.2 3.7c0-.5.4-.9.9-.9h3.4c.5 0 .9.4.9.9 0 1.3.2 2.6.6 3.8.1.4 0 .8-.2 1.1l-2.2 2.2Z" />
        </svg>
      </span>
      <span className="min-w-0">
        <span
          className="block font-heading text-[15px] leading-tight"
          style={{ color: urgency.ink }}
        >
          Llamar a {subject.role.label}
        </span>
        <span className="block text-[12px] leading-[1.4] text-steel">
          Abre el QR y habla tú con el agente. Demostración: no se envía nada.
        </span>
      </span>
    </button>
  );
}

export function CallQrDialog({
  subject,
  url,
  urgencyNote,
  onClose,
}: {
  subject: CallSubject;
  /** Public address of the agent's browser call page. Resolved on the server. */
  url: string;
  /** The clinic's own words for this urgency, straight from the backend legend. */
  urgencyNote?: string;
  onClose: () => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const urgency = URGENCY[subject.escalation.urgency];
  const unreachable = isLoopback(url);

  useEffect(() => {
    closeRef.current?.focus();
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, []);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-[var(--page-gutter)] py-6"
      role="dialog"
      aria-modal="true"
      aria-labelledby="call-qr-title"
    >
      <div
        aria-hidden
        onClick={onClose}
        className="absolute inset-0 bg-graphite/70 backdrop-blur-[2px]"
      />

      <div className="relative max-h-[92vh] w-full max-w-[1000px] overflow-y-auto rounded-[20px] border border-mist bg-canvas-white shadow-[var(--shadow-md)]">
        <div className="flex items-start justify-between gap-4 border-b border-mist px-6 py-4 sm:px-8">
          <p className="flex items-center gap-2.5 font-heading text-[11px] leading-none tracking-[0.09em] text-brass uppercase">
            <span className="h-px w-5 bg-brass/70" />
            Escalado · demostración en directo
          </p>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            className="-mt-1 cursor-pointer rounded-full border border-mist px-3 py-1 font-heading text-[11px] tracking-[0.04em] text-quiet uppercase hover:text-graphite focus-visible:ring-2 focus-visible:ring-brass/40 focus-visible:outline-none"
          >
            Cerrar
          </button>
        </div>

        <div className="grid gap-8 px-6 py-6 sm:px-8 sm:py-7 lg:grid-cols-[minmax(0,1fr)_440px]">
          <div className="min-w-0">
            <p className="font-heading text-[12px] leading-none tracking-[0.08em] text-quiet uppercase">
              Hay que avisar a
            </p>
            <h2
              id="call-qr-title"
              className="mt-2.5 font-heading text-[clamp(1.7rem,3.6vw,2.5rem)] leading-[1.05] tracking-[-0.04em] text-graphite"
            >
              {subject.role.label}
            </h2>
            <p className="mt-2 text-[14px] leading-[1.5] text-steel">{subject.role.detail}</p>

            <div className="mt-6 rounded-[14px] border border-mist bg-fog/70 px-5 py-4">
              <p className="flex flex-wrap items-center gap-2.5">
                <span className="font-heading text-[12px] leading-none tracking-[0.08em] text-quiet uppercase">
                  Porque
                </span>
                <span
                  className="rounded-full px-2.5 py-0.5 font-heading text-[11px] tracking-[0.06em] uppercase"
                  style={{ background: `${urgency.ink}18`, color: urgency.ink }}
                >
                  {urgency.word}
                </span>
              </p>
              <p className="mt-2 font-heading text-[19px] leading-tight text-graphite">
                {subject.reasonLabel}
              </p>
              <p className="mt-1.5 text-[14px] leading-[1.5] text-steel">
                {subject.escalation.detail}
              </p>
              {urgencyNote ? (
                <p className="mt-2.5 text-[13px] leading-[1.5]" style={{ color: urgency.ink }}>
                  {urgencyNote}
                </p>
              ) : null}
              <p className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-mist/80 pt-3 font-mono text-[11.5px] text-quiet">
                <span>{subject.escalation.reason}</span>
                {subject.otherRoutes > 0 ? (
                  <span>
                    + otras {subject.otherRoutes} razones acaban en esta misma persona
                  </span>
                ) : null}
              </p>
            </div>

            {/* The disclaimer. Full size, above the fold, in the same type as
                everything else: the call really does run the production
                pipeline, and the only thing switched off is the submit. That
                is worth saying out loud rather than hiding in a footnote. */}
            <div className="mt-5 rounded-[14px] border-2 border-ember-orange/45 bg-ember-orange/[0.06] px-5 py-4">
              <p className="font-heading text-[15px] leading-tight text-ember-orange">
                Esto es una demostración, no una llamada de verdad.
              </p>
              <p className="mt-2 text-[14px] leading-[1.55] text-steel">
                El QR abre el mismo agente que atiende las llamadas, con el envío
                desactivado: nada de lo que se diga llega a la plataforma de Prosper, no se
                crea ninguna cita y no se avisa a{" "}
                <span className="text-graphite">{subject.role.label}</span> de verdad. En
                producción, este botón marcaría su teléfono.
              </p>
            </div>
          </div>

          <div className="min-w-0">
            <div className="flex flex-col items-center rounded-[16px] border border-mist bg-white p-5">
              <QrCodeSvg url={url} />
              <p className="mt-4 text-center font-heading text-[17px] leading-tight text-graphite">
                Escanéalo y habla con el agente
              </p>
              <p className="mt-1.5 text-center text-[13px] leading-[1.45] text-steel">
                Se abre en el navegador del móvil y pide el micrófono. No hace falta
                instalar nada.
              </p>
              <p className="mt-3 w-full text-center font-mono text-[13px] leading-[1.4] break-all text-steel">
                {url}
              </p>
              <a
                href={url}
                target="_blank"
                rel="noreferrer"
                className={cn(
                  "mt-3 cursor-pointer rounded-full border border-mist px-4 py-1.5 font-heading text-[12.5px] text-steel",
                  "hover:border-graphite/30 hover:text-graphite focus-visible:ring-2 focus-visible:ring-brass/40 focus-visible:outline-none",
                )}
              >
                Abrirlo aquí
              </a>
            </div>

            {unreachable ? (
              <p className="mt-3 rounded-[12px] border border-brass/35 bg-ivory px-4 py-3 text-[12.5px] leading-[1.5] text-steel">
                Esa dirección es local, así que un móvil no la alcanza. Apunta{" "}
                <span className="font-mono">VOICE_PUBLIC_BASE_URL</span> al agente
                desplegado para que el QR sirva delante de gente.
              </p>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
