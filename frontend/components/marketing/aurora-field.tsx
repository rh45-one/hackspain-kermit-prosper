"use client";

import { useEffect, useRef } from "react";

export function AuroraField() {
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) {
      return;
    }
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      return;
    }

    const onMove = (event: PointerEvent) => {
      const x = (event.clientX / window.innerWidth) * 100;
      const y = (event.clientY / window.innerHeight) * 100;
      root.style.setProperty("--glow-x", `${x}%`);
      root.style.setProperty("--glow-y", `${y}%`);
    };
    window.addEventListener("pointermove", onMove, { passive: true });
    return () => window.removeEventListener("pointermove", onMove);
  }, []);

  return (
    <div ref={rootRef} className="marketing-aurora" aria-hidden="true">
      <div className="aurora-orb aurora-orb-ember" />
      <div className="aurora-orb aurora-orb-brass" />
      <div className="aurora-orb aurora-orb-paper" />
      <div className="aurora-pointer" />
      <div className="marketing-grain" />
    </div>
  );
}
