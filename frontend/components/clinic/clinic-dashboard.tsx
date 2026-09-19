"use client";

import { useRouter, useSearchParams } from "next/navigation";

import { AppointmentsCalendar } from "@/components/calendar/appointments-calendar";
import { PageHeader } from "@/components/layout/page-header";
import { PatientDirectory } from "@/components/patients/patient-directory";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

type ClinicTab = "patients" | "calendar";

function parseTab(value: string | null): ClinicTab {
  return value === "calendar" ? "calendar" : "patients";
}

export function ClinicDashboard() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tab = parseTab(searchParams.get("tab"));

  return (
    <div>
      <PageHeader kicker="Clínica Arenal" title="Clínica">
        Directorio de pacientes y agenda de citas en un solo sitio. Busca un
        paciente para cargar su historial; la agenda refleja esa misma
        consulta.
      </PageHeader>

      <Tabs
        value={tab}
        onValueChange={(value) => {
          const next = parseTab(value);
          const href =
            next === "calendar" ? "/patients?tab=calendar" : "/patients";
          router.replace(href, { scroll: false });
        }}
        className="gap-6 sm:gap-8"
      >
        <TabsList
          data-reveal=""
          data-delay="1"
          className="h-auto rounded-xl border border-mist bg-canvas-white p-1 shadow-[var(--shadow-sm)]"
        >
          <TabsTrigger
            value="patients"
            className="rounded-lg px-4 py-2 font-heading text-[14px] data-active:bg-graphite data-active:text-canvas-white data-active:shadow-sm"
          >
            Pacientes
          </TabsTrigger>
          <TabsTrigger
            value="calendar"
            className="rounded-lg px-4 py-2 font-heading text-[14px] data-active:bg-graphite data-active:text-canvas-white data-active:shadow-sm"
          >
            Agenda
          </TabsTrigger>
        </TabsList>

        <TabsContent value="patients" className="mt-0 outline-none">
          <PatientDirectory embedded />
        </TabsContent>
        <TabsContent value="calendar" className="mt-0 outline-none">
          <AppointmentsCalendar embedded />
        </TabsContent>
      </Tabs>
    </div>
  );
}
