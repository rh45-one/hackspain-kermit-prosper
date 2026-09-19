import { redirect } from "next/navigation";

/** Rutas de retos ocultas en UI; el catálogo en lib/problems se conserva. */
export default function ProblemsPage() {
  redirect("/leaderboard");
}
