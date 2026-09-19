import { redirect } from "next/navigation";

export default function CalendarPage() {
  redirect("/patients?tab=calendar");
}
