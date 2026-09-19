"use client";

import { useMemo, useState } from "react";

import { useFrontdesk } from "@/components/frontdesk-provider";
import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { parseSpanishId } from "@/lib/dni";
import {
  fullName,
  outcomeFromAction,
  OUTCOME_STYLES,
  REASON_LABELS,
  triageFromAppointments,
  TRIAGE_STYLES,
} from "@/lib/outcomes";
import { formatMadrid } from "@/lib/timezone";
import type { Patient } from "@/lib/types";

export function PatientDirectory({ embedded = false }: { embedded?: boolean }) {
  const { patients, appointments, demo, searchPatients, clinicLoading, clinicSearched, clinicError } = useFrontdesk();
  const [nameQuery, setNameQuery] = useState("");
  const [idQuery, setIdQuery] = useState("");
  const [selected, setSelected] = useState<Patient | null>(null);

  const parsedId = parseSpanishId(idQuery);

  const canSearch = parsedId.status === "valid" ||
    (parsedId.status === "empty" && nameQuery.trim().split(/\s+/).length >= 2);

  const rows = useMemo(() => {
    if (!demo) return patients;
    if (parsedId.status === "invalid") {
      return [];
    }
    const name = nameQuery.trim().toLowerCase();
    return patients.filter((patient) => {
      const matchesName =
        !name || fullName(patient).toLowerCase().includes(name);
      if (!matchesName) {
        return false;
      }
      if (parsedId.status === "empty") {
        return true;
      }
      if (parsedId.status === "partial") {
        return patient.national_id
          .toUpperCase()
          .startsWith(parsedId.normalized);
      }
      return patient.national_id.toUpperCase() === parsedId.normalized;
    });
  }, [demo, nameQuery, parsedId, patients]);

  const history = selected
    ? appointments.filter((item) => item.patient_id === selected.patient_id)
    : [];
  const triage = triageFromAppointments(history);

  return (
    <div>
      {!embedded ? (
        <PageHeader kicker="Directory" title="Patients">
          {demo ? "Simulated directory." : "Directory of the clinic configured in the backend."}
          {demo ? " Filter results by name or DNI/NIE." :
            " Search by first and last name or a full DNI/NIE. The search refreshes every minute."}
        </PageHeader>
      ) : null}

      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (!demo && canSearch) {
            setSelected(null);
            searchPatients(parsedId.status === "valid"
              ? { national_id: parsedId.normalized }
              : { name: nameQuery.trim() });
          }
        }}
        data-reveal=""
        data-delay={embedded ? undefined : "1"}
        className="mb-8 rounded-[18px] border border-mist bg-ash/70 p-[var(--card-padding)] shadow-[var(--shadow-sm)] sm:mb-10"
      >
        <p className="font-heading text-[17px] text-graphite">{demo ? "Filters" : "Search patients"}</p>
        <p className="mt-2 max-w-xl text-[14px] leading-relaxed text-steel sm:text-[15px]">
          {demo ? "Full name and ID. A wrong letter does not fire a search." :
            "Enter a first name and at least one surname, or a full ID. If you complete the ID, the search uses that identifier."}
        </p>
        <div className="mt-7 grid gap-5 md:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="name" className="font-heading text-[13px] text-quiet">
              Full name
            </Label>
            <Input
              id="name"
              value={nameQuery}
              placeholder="Marta Ruiz"
              autoComplete="off"
              className="border-mist bg-canvas-white"
              onChange={(event) => setNameQuery(event.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="dni" className="font-heading text-[13px] text-quiet">
              ID (DNI/NIE)
            </Label>
            <Input
              id="dni"
              autoComplete="off"
              value={idQuery}
              placeholder="12345678Z"
              aria-invalid={parsedId.status === "invalid"}
              className="border-mist bg-canvas-white"
              onChange={(event) => setIdQuery(event.target.value)}
            />
            {parsedId.status === "invalid" ? (
              <p className="text-[13px] text-ember-orange">{parsedId.error}</p>
            ) : (
              <p className="text-[13px] text-quiet">
                Include the control letter. NIE with prefix X, Y, or Z.
              </p>
            )}
          </div>
        </div>
        {!demo && (
          <div className="mt-5 flex flex-wrap items-center gap-4">
            <Button type="submit" disabled={!canSearch || clinicLoading}>
              {clinicLoading ? "Searching…" : "Search patients"}
            </Button>
            <p role="status" className="text-[14px] text-steel">
              {clinicLoading ? "Querying patients and appointments…" : clinicError
                ? clinicError
                : clinicSearched ? `${patients.length} patients in the last search.`
                : "Run a search to look up patients and their appointments."}
            </p>
          </div>
        )}
      </form>

      <section
        data-reveal=""
        data-delay={embedded ? undefined : "2"}
        className="surface overflow-hidden rounded-[18px]"
      >
        <Table className="min-w-[760px]">
          <TableHeader>
            <TableRow className="border-mist hover:bg-transparent">
              <TableHead className="font-heading text-[13px] text-quiet">
                Patient
              </TableHead>
              <TableHead className="font-heading text-[13px] text-quiet">
                DNI/NIE
              </TableHead>
              <TableHead className="font-heading text-[13px] text-quiet">
                Date of birth
              </TableHead>
              <TableHead className="font-heading text-[13px] text-quiet">
                Plan
              </TableHead>
              <TableHead className="font-heading text-[13px] text-quiet">
                Referrals
              </TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.length === 0 ? (
              <TableRow className="border-mist hover:bg-transparent">
                <TableCell colSpan={6} className="text-quiet">
                  {!demo ? (clinicLoading ? "Searching patients…" : clinicError
                    ? "The search could not complete. You can try again."
                    : !clinicSearched ? "Search for a patient by first and last name or a full ID."
                    : "No patient matches the last search.")
                    : parsedId.status === "invalid" ? "ID filter rejected."
                    : "No patient matches."}
                </TableCell>
              </TableRow>
            ) : (
              rows.map((patient) => (
                <TableRow
                  key={patient.patient_id}
                  className="animate-in fade-in border-mist duration-200 hover:bg-fog"
                >
                  <TableCell>
                    <div className="font-heading text-[16px] text-graphite">
                      {fullName(patient)}
                    </div>
                    <div className="font-mono text-[13px] text-quiet">
                      {patient.patient_id}
                    </div>
                  </TableCell>
                  <TableCell className="font-mono text-steel">
                    {patient.national_id}
                  </TableCell>
                  <TableCell className="text-steel">
                    {patient.date_of_birth}
                  </TableCell>
                  <TableCell className="uppercase text-steel">
                    {patient.insurer}
                  </TableCell>
                  <TableCell className="text-steel">
                    {patient.referrals.length
                      ? patient.referrals.join(", ")
                      : "—"}
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="outline"
                      onClick={() => setSelected(patient)}
                    >
                      Record
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </section>

      <Dialog open={selected !== null} onOpenChange={() => setSelected(null)}>
        <DialogContent className="max-w-xl border-mist bg-canvas-white">
          {selected ? (
            <>
              <DialogHeader>
                <DialogTitle className="pr-10 font-heading text-[clamp(1.75rem,5vw,2.25rem)] font-medium tracking-[-0.04em]">
                  {fullName(selected)}
                </DialogTitle>
                <DialogDescription className="font-mono text-quiet">
                  {selected.patient_id} · {selected.national_id}
                </DialogDescription>
              </DialogHeader>
              {demo ? (
                <div className="flex flex-wrap items-center gap-3">
                  <span className="font-heading text-[13px] text-quiet">
                    Reception triage
                  </span>
                  <Badge
                    variant="outline"
                    className={TRIAGE_STYLES[triage].className}
                  >
                    {TRIAGE_STYLES[triage].label}
                  </Badge>
                  <span className="text-[13px] text-quiet">
                    Derived from the agent&apos;s last simulated action, not a clinical score.
                  </span>
                </div>
              ) : null}
              <p className="text-[16px] leading-[1.5] text-steel">
                {selected.note}
              </p>
              <div>
                <h3 className="mb-5 font-heading text-[18px] text-graphite">
                  {demo ? "Appointment history" : "Appointments on file at the clinic"}
                </h3>
                <div className="space-y-4">
                  {history.length === 0 ? (
                    <p className="text-steel">No appointments on file.</p>
                  ) : (
                    history.map((item) => {
                      const outcome = outcomeFromAction(item.action);
                      return (
                        <div
                          key={item.appointment_id}
                          className="flex flex-col items-start justify-between gap-3 border-t border-mist pt-4 text-[14px] sm:flex-row"
                        >
                          <div>
                            <p className="font-heading text-[16px] text-graphite">
                              {formatMadrid(item.start_time, "d MMM yyyy HH:mm")}{" "}
                              · {item.location_name}
                            </p>
                            <p className="mt-1 text-steel">
                              {item.provider_name} · {item.appointment_type_name}
                            </p>
                          </div>
                          <div className="sm:text-right">
                            <Badge
                              variant="outline"
                              className={OUTCOME_STYLES[outcome].className}
                            >
                              {OUTCOME_STYLES[outcome].label}
                            </Badge>
                            {item.reason ? (
                              <p className="mt-1 text-[13px] text-quiet">
                                {REASON_LABELS[item.reason]}
                              </p>
                            ) : null}
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            </>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}
