"use client";

import { usePathname } from "next/navigation";

import { FrontdeskProvider } from "@/components/frontdesk-provider";
import { ObservatoryChrome } from "@/components/layout/observatory-chrome";
import { MotionObserver } from "@/components/motion/motion-observer";

function isMarketing(pathname: string | null) {
  return pathname === "/" || pathname === "/login";
}

export function AppFrame({ children, demo }: { children: React.ReactNode; demo: boolean }) {
  const pathname = usePathname();

  if (isMarketing(pathname)) {
    return (
      <>
        <MotionObserver />
        {children}
      </>
    );
  }

  return (
    <FrontdeskProvider demo={demo}>
      <div className="min-h-full bg-background">
        <MotionObserver />
        <ObservatoryChrome />
        <main className="mx-auto w-full max-w-[var(--page-max-width)] px-[var(--page-gutter)] pt-10 pb-20 sm:pt-14 sm:pb-24">
          {children}
        </main>
      </div>
    </FrontdeskProvider>
  );
}
