"use client";

import { FrontdeskProvider } from "@/components/frontdesk-provider";
import { ObservatoryChrome } from "@/components/layout/observatory-chrome";
import { MotionObserver } from "@/components/motion/motion-observer";

export function AppFrame({ children }: { children: React.ReactNode }) {
  return (
    <FrontdeskProvider>
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
