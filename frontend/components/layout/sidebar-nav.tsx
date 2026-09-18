"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  CalendarDays,
  PhoneCall,
  Settings2,
  Users,
} from "lucide-react";

import { cn } from "@/lib/utils";

const NAV = [
  { href: "/calls", label: "Monitor de Llamadas", icon: PhoneCall },
  { href: "/calendar", label: "Calendario", icon: CalendarDays },
  { href: "/patients", label: "Pacientes", icon: Users },
  { href: "/settings", label: "Configuración del Agente", icon: Settings2 },
] as const;

export function SidebarNav() {
  const pathname = usePathname();

  return (
    <aside className="flex w-64 shrink-0 flex-col border-r border-slate-200 bg-white">
      <div className="border-b border-slate-200 px-5 py-5">
        <p className="text-[11px] font-medium tracking-[0.18em] text-teal-800 uppercase">
          ClinicReflow
        </p>
        <h1 className="mt-1 text-lg font-semibold tracking-tight text-slate-900">
          Clínica Arenal
        </h1>
        <p className="text-sm text-slate-500">FrontDesk · recepción</p>
      </div>
      <nav className="flex flex-1 flex-col gap-1 p-3">
        {NAV.map((item) => {
          const active = pathname === item.href;
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors",
                active
                  ? "bg-teal-50 font-medium text-teal-950 ring-1 ring-teal-100"
                  : "text-slate-600 hover:bg-slate-50 hover:text-slate-900",
              )}
            >
              <Icon className="size-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>
      <p className="px-5 py-4 text-xs text-slate-400">
        Datos de demostración. El navegador no se une al WebSocket de Twilio.
      </p>
    </aside>
  );
}
