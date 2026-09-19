"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Expand, Minimize2, Minus, Plus, Scan } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * The drawing surface both views share.
 *
 * Edges are SVG, nodes are HTML on top of them. Pure SVG would mean no text
 * truncation, no Tailwind and no focus ring; pure HTML would mean no curves.
 * Both layers use the same pixel space, so the two never drift apart.
 *
 * Why it zooms
 * ------------
 * It used to be `overflow-x-auto` and nothing else, which is fine while the
 * canvas is 1100 wide and stops being fine the moment it is not. With the
 * whole rota drawn the routing map is about 1500 across, so on a laptop the
 * right-hand column was simply cut — and a chain of substitutes that ends
 * off-screen does not read as "scroll right", it reads as **people missing**.
 * That is exactly how it was reported, and the people were all there.
 *
 * So the canvas now fits itself to the container on first paint, and offers
 * the two things anybody does next with a picture that had to be shrunk:
 * zoom in, and drag it around. Fitting is the default rather than a button
 * nobody presses, because the first impression is the one that gets to be
 * wrong.
 *
 * The zoom is a CSS transform on a wrapper, not a change to the layout maths.
 * Nodes stay in the same pixel space they were placed in, the SVG scales with
 * them, and nothing downstream has to know this exists.
 */
const MIN_SCALE = 0.25;
const MAX_SCALE = 2;
const STEP = 0.2;

export function GraphCanvas({
  width,
  height,
  children,
  label,
}: {
  width: number;
  height: number;
  children: React.ReactNode;
  label: string;
}) {
  const viewport = useRef<HTMLDivElement | null>(null);
  const frame = useRef<HTMLDivElement | null>(null);
  const [full, setFull] = useState(false);
  const [scale, setScale] = useState(1);
  const [fitted, setFitted] = useState(false);
  const [dragging, setDragging] = useState(false);
  // True once the person has zoomed on purpose. From then on the canvas stops
  // re-fitting itself: refitting under somebody's fingers is worse than never
  // fitting at all.
  const touched = useRef(false);

  /**
   * La escala a la que cabe. Nunca agranda por encima del 100%.
   *
   * Fuera de pantalla completa sólo cuenta el ancho: el contenedor crece con
   * el contenido, así que "alto disponible" no significa nada. En pantalla
   * completa el alto sí está acotado, y ahí la gracia es ver el dibujo
   * entero — de nada sirve encajar el ancho si la mitad de la gente sigue
   * por debajo del borde.
   */
  const fitScale = useCallback(() => {
    const box = viewport.current;
    if (!box) return 1;
    const availableWidth = box.clientWidth - 8;
    if (availableWidth <= 0) return 1;
    let ratio = availableWidth / width;
    if (document.fullscreenElement && box.clientHeight > 0) {
      ratio = Math.min(ratio, (box.clientHeight - 8) / height);
    }
    return Math.min(1, Math.max(MIN_SCALE, ratio));
  }, [width, height]);

  const fit = useCallback(() => setScale(fitScale()), [fitScale]);

  // Fit on mount and whenever the window changes shape. `fitted` stops the
  // first measurement — which happens before layout has settled — from being
  // mistaken for a deliberate zoom level the person chose.
  useEffect(() => {
    const apply = () => {
      setScale(fitScale());
      setFitted(true);
    };
    apply();
    const box = viewport.current;
    if (!box || typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", apply);
      return () => window.removeEventListener("resize", apply);
    }
    const observer = new ResizeObserver(() => {
      // Only re-fit while the person has not zoomed themselves; re-fitting
      // under their fingers every time a panel opens would be worse than not
      // fitting at all.
      if (!touched.current) setScale(fitScale());
    });
    observer.observe(box);
    return () => observer.disconnect();
  }, [fitScale]);

  const zoom = useCallback((delta: number) => {
    touched.current = true;
    setScale((current) => Math.min(MAX_SCALE, Math.max(MIN_SCALE, Number((current + delta).toFixed(2)))));
  }, []);

  /**
   * Agrandar de verdad: pantalla completa.
   *
   * El botón que había sólo reencuadraba, y reencuadrar cuando ya cabe no
   * hace nada — pulsabas "agrandar" y no pasaba nada, que es peor que no
   * tener botón. Un mapa de mil seiscientos píxeles metido en una columna de
   * texto no se arregla con zoom: se arregla dándole la pantalla.
   *
   * Al entrar y al salir se vuelve a ajustar, porque el ancho disponible
   * acaba de cambiar por completo.
   */
  const toggleFull = useCallback(() => {
    const box = frame.current;
    if (!box) return;
    if (document.fullscreenElement) {
      void document.exitFullscreen().catch(() => {});
    } else {
      void box.requestFullscreen?.().catch(() => {});
    }
  }, []);

  useEffect(() => {
    const onChange = () => {
      setFull(Boolean(document.fullscreenElement));
      touched.current = false;
      // Un fotograma para que el navegador aplique el nuevo tamaño antes de
      // medirlo; medir durante la transición devuelve el tamaño de antes.
      requestAnimationFrame(() => requestAnimationFrame(() => setScale(fitScale())));
    };
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, [fitScale]);

  // Drag to pan, on the scroll container. Only with the primary button and
  // only from the background: a drag that started on a node is that node
  // being clicked, and stealing it would break selecting anybody.
  const from = useRef<{ x: number; y: number; left: number; top: number } | null>(null);
  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    const box = viewport.current;
    if (!box || event.button !== 0) return;
    if ((event.target as HTMLElement).closest("button, a, input")) return;
    from.current = { x: event.clientX, y: event.clientY, left: box.scrollLeft, top: box.scrollTop };
    setDragging(true);
    box.setPointerCapture(event.pointerId);
  };
  const onPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    const box = viewport.current;
    const start = from.current;
    if (!box || !start) return;
    box.scrollLeft = start.left - (event.clientX - start.x);
    box.scrollTop = start.top - (event.clientY - start.y);
  };
  const endDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    const box = viewport.current;
    if (box?.hasPointerCapture(event.pointerId)) box.releasePointerCapture(event.pointerId);
    from.current = null;
    setDragging(false);
  };

  return (
    <div
      ref={frame}
      className={cn(
        "relative",
        // En pantalla completa el contenedor es la pantalla: fondo propio,
        // porque el elemento en fullscreen se dibuja contra negro y este
        // dibujo es tinta oscura sobre papel claro.
        full && "flex h-screen w-screen flex-col bg-canvas-white p-4",
      )}
    >
      {/*
        La barra va ENCIMA del lienzo y no flotando sobre él. Flotando en la
        esquina tapaba el rótulo de la última columna — "ESPECIALIDADES"
        desaparecía debajo del control de zoom — y un control que esconde
        justo la parte del dibujo que está al lado no es un control, es un
        estorbo.
      */}
      <div className="mb-2 flex items-center justify-end gap-1">
        <div className="flex items-center gap-0.5 rounded-full border border-mist bg-canvas-white/90 p-1">
          <Control label="Alejar" onClick={() => zoom(-STEP)} disabled={scale <= MIN_SCALE}>
            <Minus className="size-3.5" />
          </Control>
          <span className="w-10 text-center font-mono text-[11px] tabular-nums text-steel">
            {Math.round(scale * 100)}%
          </span>
          <Control label="Acercar" onClick={() => zoom(STEP)} disabled={scale >= MAX_SCALE}>
            <Plus className="size-3.5" />
          </Control>
          <Control
            label="Ajustar a la pantalla"
            onClick={() => {
              touched.current = false;
              fit();
            }}
          >
            <Scan className="size-3.5" />
          </Control>
          <Control label={full ? "Salir de pantalla completa" : "Pantalla completa"} onClick={toggleFull}>
            {full ? <Minimize2 className="size-3.5" /> : <Expand className="size-3.5" />}
          </Control>
        </div>
      </div>

      <div
        ref={viewport}
        className={cn(
          "-mx-1 overflow-auto px-1 pb-2 touch-pan-x touch-pan-y",
          full && "min-h-0 flex-1",
          dragging ? "cursor-grabbing select-none" : "cursor-grab",
        )}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
      >
        <div
          style={{
            width: width * scale,
            height: height * scale,
            // Only fade in once the fit is known: at scale 1 for one frame the
            // canvas is wider than the screen and the page jumps sideways.
            opacity: fitted ? 1 : 0,
            transition: "opacity 200ms ease-out",
          }}
        >
          <div
            role="group"
            aria-label={label}
            className="relative origin-top-left"
            style={{ width, height, minWidth: width, transform: `scale(${scale})` }}
          >
            {children}
          </div>
        </div>
      </div>

    </div>
  );
}

function Control({
  label,
  onClick,
  disabled,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={onClick}
      disabled={disabled}
      className="grid size-7 place-items-center rounded-full text-steel transition-colors hover:bg-fog hover:text-graphite disabled:opacity-30 disabled:hover:bg-transparent"
    >
      {children}
    </button>
  );
}

/** The header that sits above a column of nodes. */
export function ColumnTitle({
  x,
  w,
  title,
  note,
  align = "left",
}: {
  x: number;
  w: number;
  title: string;
  note: string;
  align?: "left" | "right";
}) {
  return (
    <div
      className={cn("absolute top-0", align === "right" ? "text-right" : "text-left")}
      style={{ left: x, width: w }}
    >
      <p className="font-heading text-[11px] leading-none tracking-[0.09em] text-brass uppercase">
        {title}
      </p>
      <p className="mt-1.5 text-[11px] leading-none text-quiet">{note}</p>
    </div>
  );
}

/**
 * Keyframes for the two things that move: strokes drawing themselves in, and
 * the single `now` route breathing so it cannot be mistaken for the rest.
 *
 * Kept next to the only components that use them and prefixed, rather than
 * added to the app's shared stylesheet, which other people are editing today.
 */
export function GraphKeyframes() {
  return (
    <style>{`
@keyframes clinic-graph-draw {
  from { stroke-dashoffset: 1; }
  to { stroke-dashoffset: 0; }
}
@keyframes clinic-graph-fade {
  from { opacity: 0; }
}
@keyframes clinic-graph-breathe {
  0%, 100% { opacity: 0.55; }
  50% { opacity: 1; }
}
.clinic-graph-draw {
  stroke-dashoffset: 1;
  animation: clinic-graph-draw 900ms cubic-bezier(0.16, 1, 0.3, 1) both;
}
.clinic-graph-fade {
  animation: clinic-graph-fade 700ms cubic-bezier(0.16, 1, 0.3, 1) both;
}
.clinic-graph-breathe {
  animation: clinic-graph-breathe 2.4s ease-in-out infinite;
}
@media (prefers-reduced-motion: reduce) {
  .clinic-graph-draw,
  .clinic-graph-fade,
  .clinic-graph-breathe {
    animation: none !important;
    stroke-dashoffset: 0 !important;
    opacity: 1 !important;
  }
}
`}</style>
  );
}
