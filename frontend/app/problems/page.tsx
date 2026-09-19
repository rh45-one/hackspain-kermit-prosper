import { redirect } from "next/navigation";

export default function ProblemsPage() {
  redirect("/leaderboard?tab=problems");
}
