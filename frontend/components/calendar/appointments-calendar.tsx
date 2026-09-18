"use client";

import { useEffect, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { es } from "react-day-picker/locale";
import { fromZonedTime } from "date-fns-tz";

import { useFrontdesk } from "@/components/frontdesk-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { MOCK_PATIENTS } from "@/lib/mock-data";
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
import { CLINIC_TZ, type Appointment, type ReceptionOutcome } from "@/lib/types";
import { cn } from "@/lib/utils";

const HOURS = Array.from({ length: 12 }, (_, index) => 8 + index);
const HOUR_HEIGHT = 64;
const START_MINUTES = 8 * 60;
const DAY_HEIGHT = HOURS.length * HOUR_HEIGHT;

function patientLabel(patientId: string): string {
  const patient = MOCK_PATIENTS.find((item) => item.patient_id === patientId);
  return patient ? fullName(patient) : patientId;
}

function AppointmentChip({ item }: { item: Appointment }) {
  const outcome = outcomeFromAction(item.action);
  const start = minutesFromMidnightMadrid(item.start_time);
  const top = ((start - START_MINUTES) / 60) * HOUR_HEIGHT;
  const height = Math.max((item.duration_minutes / 60) * HOUR_HEIGHT, 36);

  return (
    <div
      className={cn(
        "absolute inset-x-1 z-10 overflow-hidden rounded-md border px-1.5 py-1 text-[11px] leading-tight",
        OUTCOME_STYLES[outcome].chip,
      )}
      style={{ top, height }}
    >
      <div className="flex items-center justify-between gap-1 font-medium">
        <span>{formatMadrid(item.start_time, "HH:mm")}</span>
        <span>{OUTCOME_STYLES[outcome].label}</span>
      </div>
      <p className="truncate">{patientLabel(item.patient_id)}</p>
      {outcome === "REFUSED" && item.reason ? (
        <p className="truncate text-[10px]">{REASON_LABELS[item.reason]}</p>
      ) : (
        <p className="truncate text-[10px]">{item.location_name}</p>
      )}
    </div>
  );
}

function Legend() {
  const keys: ReceptionOutcome[] = ["BOOKED", "CANCELLED", "REFUSED", "DIVERTED"];
  return (
    <div className="flex flex-wrap gap-2">
      {keys.map((key) => (
        <Badge key={key} variant="outline" className={OUTCOME_STYLES[key].className}>
          {OUTCOME_STYLES[key].label}
        </Badge>
      ))}
    </div>
  );
}

export function AppointmentsCalendar() {
  const { appointments } = useFrontdesk();
  const [dayKey, setDayKey] = useState("2026-09-18");
  const [mode, setMode] = useState<"week" | "day">("week");

  useEffect(() => {
    setDayKey(madridDayKey(new Date()));
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
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold tracking-tight text-slate-900">
            Calendario de citas
          </h2>
          <p className="text-sm text-slate-500">
            Instants convertidos a Europe/Madrid. Un rechazo se ve en gris, con
            la regla, sin abrir nada.
          </p>
        </div>
        <Legend />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={() => setDayKey(addMadridDays(stepFrom, -step))}
        >
          <ChevronLeft />
        </Button>
        <p className="min-w-40 text-sm font-medium capitalize">
          {monthTitleEs(dayKey)}
        </p>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setDayKey(addMadridDays(stepFrom, step))}
        >
          <ChevronRight />
        </Button>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setDayKey(madridDayKey(new Date()))}
        >
          Hoy
        </Button>
        <Tabs value={mode} onValueChange={(value) => setMode(value as "week" | "day")}>
          <TabsList>
            <TabsTrigger value="week">Semana</TabsTrigger>
            <TabsTrigger value="day">Día</TabsTrigger>
          </TabsList>
        </Tabs>
      </div>
      <div className="grid gap-4 xl:grid-cols-[1fr_16rem]">
        <Card className="overflow-hidden py-0">
          <div className="grid border-b border-slate-200 bg-slate-50" style={{ gridTemplateColumns: `3rem repeat(${days.length}, minmax(0, 1fr))` }}>
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
                  "border-l border-slate-200 px-2 py-2 text-left",
                  day === dayKey && "bg-teal-50",
                )}
              >
                <p className="text-[11px] tracking-wide text-slate-500 uppercase">
                  {weekdayShortEs(day)}
                </p>
                <p className="text-lg font-semibold text-slate-900">{dayNumber(day)}</p>
              </button>
            ))}
          </div>
          <div className="flex">
            <div className="w-12 shrink-0">
              {HOURS.map((hour) => (
                <div
                  key={hour}
                  className="pr-2 text-right font-mono text-[11px] text-slate-400"
                  style={{ height: HOUR_HEIGHT }}
                >
                  {String(hour).padStart(2, "0")}:00
                </div>
              ))}
            </div>
            <div
              className="grid min-w-0 flex-1"
              style={{ gridTemplateColumns: `repeat(${days.length}, minmax(0, 1fr))` }}
            >
              {days.map((day) => (
                <div
                  key={day}
                  className="relative border-l border-slate-100"
                  style={{ height: DAY_HEIGHT }}
                >
                  {HOURS.map((hour) => (
                    <div
                      key={`${day}-${hour}`}
                      className="absolute inset-x-0 border-t border-slate-100"
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
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Ir a fecha</CardTitle>
          </CardHeader>
          <CardContent>
            <Calendar
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
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
