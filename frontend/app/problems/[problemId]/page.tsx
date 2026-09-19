import { redirect } from "next/navigation";

/** Detalle de reto oculto en UI; datos en lib/problems intactos. */
export default function ProblemPage() {
  redirect("/leaderboard");
}
