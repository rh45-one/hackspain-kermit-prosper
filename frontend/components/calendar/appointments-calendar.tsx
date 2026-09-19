"use client";

import { useEffect, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { es } from "react-day-picker/locale";
import { fromZonedTime } from "date-fns-tz";

import { useFrontdesk } from "@/components/frontdesk-provider";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  fullName,
  outcomeFromAction,
  OUTCOME_STYLES,
  REASON_LABELS,
} from "@/lib/outcomes";
import {
  addMadridDays,
  dayNumber,
  formatMadrid,
  madridDayKey,
  madridWeekDays,
  minutesFromMidnightMadrid,
  monthTitleEs,
  weekdayShortEs,
} from "@/lib/timezone";
import { CLINIC_TZ, type Appointment, type Patient, type ReceptionOutcome } from "@/lib/types";
import { cn } from "@/lib/utils";

const HOURS = Array.from({ length: 12 }, (_, index) => 8 + index);
const HOUR_HEIGHT = 64;
const START_MINUTES = 8 * 60;
const DAY_HEIGHT = HOURS.length * HOUR_HEIGHT;

function patientLabel(patientId: string, patients: Patient[]): string {
  const patient = patients.find((item) => item.patient_id === patientId);
  return patient ? fullName(patient) : patientId;
}

function AppointmentChip({ item }: { item: Appointment }) {
  const { patients } = useFrontdesk();
  const outcome = outcomeFromAction(item.action);
  const start = minutesFromMidnightMadrid(item.start_time);
  const top = ((start - START_MINUTES) / 60) * HOUR_HEIGHT;
  const height = Math.max((item.duration_minutes / 60) * HOUR_HEIGHT, 52);

  return (
    <div
      className={cn(
        "animate-in fade-in zoom-in-95 absolute inset-x-1 z-10 overflow-hidden rounded-md border border-black/5 px-1.5 py-1 text-[11px] leading-tight shadow-sm duration-300",
        OUTCOME_STYLES[outcome].chip,
      )}
      style={{ top, height }}
    >
      <div className="flex items-center justify-between gap-1 font-heading">
        <span>{formatMadrid(item.start_time, "HH:mm")}</span>
        <span>{OUTCOME_STYLES[outcome].label}</span>
      </div>
      <p className="truncate">{patientLabel(item.patient_id, patients)}</p>
      {outcome === "REFUSED" && item.reason ? (
        <p className="truncate text-[10px] text-quiet">
          {REASON_LABELS[item.reason]}
        </p>
      ) : (
        <p className="truncate text-[10px] text-quiet">{item.location_name}</p>
      )}
    </div>
  );
}

function Legend() {
  const keys: ReceptionOutcome[] = ["BOOKED", "CANCELLED", "REFUSED", "DIVERTED"];
  return (
    <div data-reveal="" data-delay="1" className="flex flex-wrap gap-2">
      {keys.map((key) => (
        <span
          key={key}
          className={cn(
            "rounded-full px-3 py-1 font-heading text-[11px]",
            OUTCOME_STYLES[key].className,
          )}
        >
          {OUTCOME_STYLES[key].label}
        </span>
      ))}
    </div>
  );
}

export function AppointmentsCalendar() {
  const { appointments, demo } = useFrontdesk();
  const [dayKey, setDayKey] = useState(() => madridDayKey(new Date()));
  const [mode, setMode] = useState<"week" | "day">("week");

  useEffect(() => {
    if (window.matchMedia("(max-width: 767px)").matches) {
      queueMicrotask(() => setMode("day"));
    }
  }, []);

  const week = madridWeekDays(dayKey);
  const selectedDate = useMemo(
    () => fromZonedTime(`${dayKey}T12:00:00`, CLINIC_TZ),
    [dayKey],
  );

  const byDay = useMemo(() => {
    const map = new Map<string, Appointment[]>();
    for (const item of appointments) {
      const key = madridDayKey(item.start_time);
      const list = map.get(key) ?? [];
      list.push(item);
      map.set(key, list);
    }
    return map;
  }, [appointments]);

  const days = mode === "week" ? week : [dayKey];
  const step = mode === "week" ? 7 : 1;
  const stepFrom = mode === "week" ? week[0] : dayKey;

  return (
    <div>
      <div className="mb-10 flex flex-col items-start justify-between gap-6 lg:flex-row lg:items-end">
        <PageHeader className="mb-0" kicker="Agenda Europe/Madrid" title="Calendario de citas">
          {demo ? "Agenda simulada con resultados del agente." :
            "Citas existentes de la clínica, actualizadas cada minuto. Los envíos del agente no modifican este EHR."}
          {" "}Horas en Europe/Madrid.
        </PageHeader>
        <Legend />
      </div>

      <div
        data-reveal=""
        data-delay="1"
        className="mb-5 flex flex-wrap items-center gap-2 sm:gap-3"
      >
        <Button
          variant="outline"
          onClick={() => setDayKey(addMadridDays(stepFrom, -step))}
        >
          <ChevronLeft />
        </Button>
        <p className="order-first w-full font-heading text-[18px] capitalize text-graphite sm:order-none sm:mx-1 sm:w-auto sm:min-w-40">
          {monthTitleEs(dayKey)}
        </p>
        <Button
          variant="outline"
          onClick={() => setDayKey(addMadridDays(stepFrom, step))}
        >
          <ChevronRight />
        </Button>
        <Button
          variant="ghost"
          onClick={() => setDayKey(madridDayKey(new Date()))}
        >
          Hoy
        </Button>
        <Tabs className="ml-auto" value={mode} onValueChange={(value) => setMode(value as "week" | "day")}>
          <TabsList className="bg-ash">
            <TabsTrigger
              value="week"
              className="font-heading data-active:bg-canvas-white"
            >
              Semana
            </TabsTrigger>
            <TabsTrigger
              value="day"
              className="font-heading data-active:bg-canvas-white"
            >
              Día
            </TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_18rem]">
        <div
          data-reveal=""
          data-delay="1"
          className="surface overflow-x-auto rounded-[18px]"
        >
          <div
            key={`${mode}-${days.join("-")}`}
            className={cn(
              "animate-in fade-in duration-300",
              mode === "week" && "min-w-[720px]",
            )}
          >
          <div
            className="grid border-b border-mist bg-ash/75"
            style={{
              gridTemplateColumns: `3rem repeat(${days.length}, minmax(0, 1fr))`,
            }}
          >
            <div />
            {days.map((day) => (
              <button
                key={day}
                type="button"
                onClick={() => {
                  setDayKey(day);
                  setMode("day");
                }}
                className={cn(
                  "border-l border-mist px-3 py-4 text-left transition-[background-color,transform] duration-200 hover:bg-ivory/60 active:scale-[0.98]",
                  day === dayKey && "bg-ivory",
                )}
              >
                <p className="font-heading text-[13px] uppercase text-quiet">
                  {weekdayShortEs(day)}
                </p>
                <p className="mt-1 font-heading text-[26px] leading-none text-graphite">
                  {dayNumber(day)}
                </p>
              </button>
            ))}
          </div>
          <div className="flex">
            <div className="w-12 shrink-0">
              {HOURS.map((hour) => (
                <div
                  key={hour}
                  className="pr-2 text-right font-mono text-[11px] text-quiet"
                  style={{ height: HOUR_HEIGHT }}
                >
                  {String(hour).padStart(2, "0")}:00
                </div>
              ))}
            </div>
            <div
              className="grid min-w-0 flex-1"
              style={{
                gridTemplateColumns: `repeat(${days.length}, minmax(0, 1fr))`,
              }}
            >
              {days.map((day) => (
                <div
                  key={day}
                  className="relative border-l border-mist"
                  style={{ height: DAY_HEIGHT }}
                >
                  {HOURS.map((hour) => (
                    <div
                      key={`${day}-${hour}`}
                      className="absolute inset-x-0 border-t border-mist"
                      style={{ top: (hour - 8) * HOUR_HEIGHT, height: HOUR_HEIGHT }}
                    />
                  ))}
                  {(byDay.get(day) ?? []).map((item) => (
                    <AppointmentChip key={item.appointment_id} item={item} />
                  ))}
                </div>
              ))}
            </div>
          </div>
          </div>
        </div>
        <aside
          data-reveal=""
          data-delay="2"
          className="surface h-fit rounded-[18px] p-5 sm:p-7"
        >
          <p className="mb-4 font-heading text-[16px] text-graphite">Ir a fecha</p>
          <Calendar
            className="bg-transparent p-0"
            mode="single"
            locale={es}
            weekStartsOn={1}
            selected={selectedDate}
            onSelect={(date) => {
              if (date) {
                setDayKey(madridDayKey(date));
              }
            }}
          />
        </aside>
      </div>
    </div>
  );
}
