import { Suspense } from "react";

import { ClinicDashboard } from "@/components/clinic/clinic-dashboard";

export default function PatientsPage() {
  return (
    <Suspense fallback={null}>
      <ClinicDashboard />
    </Suspense>
  );
}
