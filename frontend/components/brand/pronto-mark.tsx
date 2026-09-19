export const PRONTO_MARK_PATH =
  "M14 56V26A18 18 0 0 1 49.386665 21.341257L41.659258 23.41181A10 10 0 1 0 41.659258 28.58819L49.386665 30.658743A18 18 0 0 1 24.8 42.497273A2 2 0 0 0 22 44.330303V56Z";

export function ProntoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" className={className} aria-hidden="true">
      <g transform="translate(0.31 0)">
        <path fill="currentColor" d={PRONTO_MARK_PATH} />
      </g>
    </svg>
  );
}
