"use client";

import { useRouter, useSearchParams } from "next/navigation";

import { AppointmentsCalendar } from "@/components/calendar/appointments-calendar";
import { DoctorDirectory } from "@/components/directory/doctor-directory";
import { PageHeader } from "@/components/layout/page-header";
import { PatientDirectory } from "@/components/patients/patient-directory";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

type ClinicTab = "patients" | "calendar" | "staff";

function parseTab(value: string | null): ClinicTab {
  if (value === "calendar") return "calendar";
  if (value === "staff") return "staff";
  return "patients";
}

function hrefForTab(tab: ClinicTab) {
  if (tab === "calendar") return "/patients?tab=calendar";
  if (tab === "staff") return "/patients?tab=staff";
  return "/patients";
}

export function ClinicDashboard() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tab = parseTab(searchParams.get("tab"));

  return (
    <div>
      <PageHeader kicker="Clínica Arenal" title="Clínica">
        Pacientes, directorio médico y agenda en un solo sitio. Marca ausencias
        del personal para iniciar la Recovery Campaign.
      </PageHeader>

      <Tabs
        value={tab}
        onValueChange={(value) => {
          router.replace(hrefForTab(parseTab(value)), { scroll: false });
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
            value="staff"
            className="rounded-lg px-4 py-2 font-heading text-[14px] data-active:bg-graphite data-active:text-canvas-white data-active:shadow-sm"
          >
            Personal
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
        <TabsContent value="staff" className="mt-0 outline-none">
          <DoctorDirectory embedded />
        </TabsContent>
        <TabsContent value="calendar" className="mt-0 outline-none">
          <AppointmentsCalendar embedded />
        </TabsContent>
      </Tabs>
    </div>
  );
}
