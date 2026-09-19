import { Suspense } from "react";

import { ArenaDashboard } from "@/components/leaderboard/arena-dashboard";

export default function LeaderboardPage() {
  return (
    <Suspense fallback={null}>
      <ArenaDashboard />
    </Suspense>
  );
}
