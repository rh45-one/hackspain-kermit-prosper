import { addDays } from "date-fns";
import { enGB } from "date-fns/locale";
import { formatInTimeZone, fromZonedTime } from "date-fns-tz";

import { CLINIC_TZ } from "@/lib/types";

/** Noon in Madrid avoids DST midnight edges when doing calendar-day arithmetic. */
function madridNoon(dayKey: string): Date {
  return fromZonedTime(`${dayKey}T12:00:00`, CLINIC_TZ);
}

export function madridDayKey(instant: Date | string): string {
  const date = typeof instant === "string" ? new Date(instant) : instant;
  return formatInTimeZone(date, CLINIC_TZ, "yyyy-MM-dd");
}

export function formatMadrid(
  instant: Date | string,
  pattern: string,
): string {
  const date = typeof instant === "string" ? new Date(instant) : instant;
  return formatInTimeZone(date, CLINIC_TZ, pattern, { locale: enGB });
}

export function addMadridDays(dayKey: string, days: number): string {
  return formatInTimeZone(addDays(madridNoon(dayKey), days), CLINIC_TZ, "yyyy-MM-dd");
}

export function mondayOfMadridWeek(dayKey: string): string {
  const noon = madridNoon(dayKey);
  const isoDow = Number(formatInTimeZone(noon, CLINIC_TZ, "i"));
  return addMadridDays(dayKey, 1 - isoDow);
}

export function madridWeekDays(anchorDayKey: string): string[] {
  const monday = mondayOfMadridWeek(anchorDayKey);
  return Array.from({ length: 7 }, (_, index) => addMadridDays(monday, index));
}

export function minutesFromMidnightMadrid(instant: Date | string): number {
  const hours = Number(formatMadrid(instant, "H"));
  const minutes = Number(formatMadrid(instant, "m"));
  return hours * 60 + minutes;
}

export function weekdayShortEs(dayKey: string): string {
  return formatInTimeZone(madridNoon(dayKey), CLINIC_TZ, "EEE", { locale: enGB });
}

export function dayNumber(dayKey: string): string {
  return formatInTimeZone(madridNoon(dayKey), CLINIC_TZ, "d");
}

export function monthTitleEs(dayKey: string): string {
  return formatInTimeZone(madridNoon(dayKey), CLINIC_TZ, "LLLL yyyy", { locale: enGB });
}
