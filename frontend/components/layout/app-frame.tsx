"use client";

import { FrontdeskProvider } from "@/components/frontdesk-provider";
import { SidebarNav } from "@/components/layout/sidebar-nav";
import { StatusHeader } from "@/components/layout/status-header";

export function AppFrame({ children }: { children: React.ReactNode }) {
  return (
    <FrontdeskProvider>
      <div className="flex min-h-full bg-slate-50">
        <SidebarNav />
        <div className="flex min-w-0 flex-1 flex-col">
          <StatusHeader />
          <main className="flex-1 overflow-auto p-6">{children}</main>
        </div>
      </div>
    </FrontdeskProvider>
  );
}
