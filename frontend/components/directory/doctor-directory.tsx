"use client";

import { useState } from "react";
import { MoreHorizontal } from "lucide-react";

import { DoctorAbsenceDialog } from "@/components/directory/doctor-absence-dialog";
import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  DOCTOR_STATUS_META,
  MOCK_DIRECTORY_DOCTORS,
  type DirectoryDoctor,
} from "@/lib/doctor-directory";
import { cn } from "@/lib/utils";

export function DoctorDirectory({ embedded = false }: { embedded?: boolean }) {
  const [doctors, setDoctors] = useState<DirectoryDoctor[]>(
    MOCK_DIRECTORY_DOCTORS,
  );
  const [absenceTarget, setAbsenceTarget] = useState<DirectoryDoctor | null>(
    null,
  );

  return (
    <div>
      {!embedded ? (
        <PageHeader kicker="Staff Directory" title="Directorio médico">
          Catálogo Prosper: 6 especialidades · Centro / Norte / Sur. Roster
          provisional hasta cablear GET /api/v1/providers (12 en la clínica
          oficial). Ausencias disparan la Recovery Campaign.
        </PageHeader>
      ) : null}

      <section
        data-reveal=""
        data-delay={embedded ? undefined : "1"}
        className="overflow-hidden rounded-[18px] bg-white shadow-[var(--shadow-sm)] ring-1 ring-mist/80"
      >
        <Table className="min-w-[720px]">
          <TableHeader>
            <TableRow className="border-mist/80 bg-slate-50 hover:bg-slate-50">
              <TableHead className="font-heading text-[13px] text-quiet">
                Doctor
              </TableHead>
              <TableHead className="font-heading text-[13px] text-quiet">
                Especialidad
              </TableHead>
              <TableHead className="font-heading text-[13px] text-quiet">
                Estado
              </TableHead>
              <TableHead className="w-[72px] text-right font-heading text-[13px] text-quiet">
                Acciones
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {doctors.map((doctor) => {
              const status = DOCTOR_STATUS_META[doctor.status];

              return (
                <TableRow
                  key={doctor.id}
                  className="border-mist/70 hover:bg-slate-50/80"
                >
                  <TableCell>
                    <div className="font-heading text-[16px] text-graphite">
                      {doctor.name}
                    </div>
                    <div className="mt-0.5 font-mono text-[12px] text-quiet">
                      {doctor.id}
                      {doctor.locationNames.length
                        ? ` · ${doctor.locationNames.join(", ")}`
                        : null}
                      {doctor.refusedInsurers?.length
                        ? ` · no ${doctor.refusedInsurers.join(", ").toUpperCase()}`
                        : null}
                    </div>
                  </TableCell>
                  <TableCell className="text-steel">
                    {doctor.specialtyName}
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant="outline"
                      className={cn("rounded-md font-medium", status.className)}
                    >
                      {status.label}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon-sm"
                          className="text-quiet hover:text-graphite"
                          aria-label={`Acciones de ${doctor.name}`}
                        >
                          <MoreHorizontal className="size-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent
                        align="end"
                        className="min-w-48 border-mist bg-white"
                      >
                        <DropdownMenuItem
                          className="font-heading text-[13px]"
                          disabled
                        >
                          Ver ficha
                        </DropdownMenuItem>
                        <DropdownMenuSeparator className="bg-mist" />
                        <DropdownMenuItem
                          variant="destructive"
                          className="font-heading text-[13px] text-red-700 focus:bg-red-50 focus:text-red-800"
                          disabled={doctor.status === "absent"}
                          onSelect={() => setAbsenceTarget(doctor)}
                        >
                          Marcar como Ausente
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </section>

      <DoctorAbsenceDialog
        doctor={absenceTarget}
        open={absenceTarget !== null}
        onOpenChange={(open) => {
          if (!open) setAbsenceTarget(null);
        }}
        onConfirm={({ doctorId, start, end, reason }) => {
          setDoctors((current) =>
            current.map((doctor) =>
              doctor.id === doctorId
                ? {
                    ...doctor,
                    status: "absent",
                    leave: { start, end, reason },
                  }
                : doctor,
            ),
          );
          setAbsenceTarget(null);
        }}
      />
    </div>
  );
}
