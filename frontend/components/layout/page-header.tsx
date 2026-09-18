export function PageHeader({
  kicker,
  title,
  children,
  className,
}: {
  kicker?: string;
  title: string;
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <header className={className ?? "mb-10 sm:mb-14"}>
      {kicker ? (
        <p className="mb-3 flex items-center gap-2.5 font-heading text-[11px] leading-none tracking-[0.08em] text-brass uppercase sm:mb-4">
          <span className="h-px w-5 bg-brass/70" />
          <span>{kicker}</span>
        </p>
      ) : null}
      <h1 className="max-w-4xl font-heading text-[clamp(2.25rem,4.5vw,3.75rem)] leading-[0.98] tracking-[-0.05em] text-graphite">
        {title}
      </h1>
      {children ? (
        <p className="mt-5 max-w-[42rem] text-[15px] leading-[1.65] text-steel sm:mt-6 sm:text-[17px]">
          {children}
        </p>
      ) : null}
    </header>
  );
}
