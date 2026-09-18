"use client";

import { useMemo, useState } from "react";

import { useFrontdesk } from "@/components/frontdesk-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
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

export function PatientDirectory() {
  const { patients, appointments } = useFrontdesk();
  const [nameQuery, setNameQuery] = useState("");
  const [idQuery, setIdQuery] = useState("");
  const [selected, setSelected] = useState<Patient | null>(null);

  const parsedId = parseSpanishId(idQuery);

  const rows = useMemo(() => {
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
  }, [idQuery, nameQuery, parsedId, patients]);

  const history = selected
    ? appointments.filter((item) => item.patient_id === selected.patient_id)
    : [];
  const triage = triageFromAppointments(history);

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-semibold tracking-tight text-slate-900">
          Directorio de pacientes
        </h2>
        <p className="text-sm text-slate-500">
          Simula GET /api/v1/directory. El DNI/NIE valida la letra de control
          antes de consultar.
        </p>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Filtros</CardTitle>
          <CardDescription>
            Nombre completo y documento. Una letra incorrecta no lanza búsqueda.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="name">Nombre completo</Label>
            <Input
              id="name"
              value={nameQuery}
              placeholder="Ruiz Gómez"
              onChange={(event) => setNameQuery(event.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="dni">Documento (DNI/NIE)</Label>
            <Input
              id="dni"
              value={idQuery}
              placeholder="12345678Z"
              aria-invalid={parsedId.status === "invalid"}
              onChange={(event) => setIdQuery(event.target.value)}
            />
            {parsedId.status === "invalid" ? (
              <p className="text-xs text-red-700">{parsedId.error}</p>
            ) : (
              <p className="text-xs text-slate-500">
                Incluye la letra de control. NIE con prefijo X, Y o Z.
              </p>
            )}
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="pt-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Paciente</TableHead>
                <TableHead>DNI/NIE</TableHead>
                <TableHead>Nacimiento</TableHead>
                <TableHead>Póliza</TableHead>
                <TableHead>Volantes</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-slate-500">
                    {parsedId.status === "invalid"
                      ? "Filtro de documento rechazado."
                      : "Ningún paciente coincide."}
                  </TableCell>
                </TableRow>
              ) : (
                rows.map((patient) => (
                  <TableRow key={patient.patient_id}>
                    <TableCell>
                      <div className="font-medium">{fullName(patient)}</div>
                      <div className="font-mono text-xs text-slate-500">
                        {patient.patient_id}
                      </div>
                    </TableCell>
                    <TableCell className="font-mono">
                      {patient.national_id}
                    </TableCell>
                    <TableCell>{patient.date_of_birth}</TableCell>
                    <TableCell className="uppercase">{patient.insurer}</TableCell>
                    <TableCell>
                      {patient.referrals.length
                        ? patient.referrals.join(", ")
                        : "—"}
                    </TableCell>
                    <TableCell>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setSelected(patient)}
                      >
                        Ficha
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
      <Dialog open={selected !== null} onOpenChange={() => setSelected(null)}>
        <DialogContent className="max-w-xl">
          {selected ? (
            <>
              <DialogHeader>
                <DialogTitle>{fullName(selected)}</DialogTitle>
                <DialogDescription>
                  {selected.patient_id} · {selected.national_id}
                </DialogDescription>
              </DialogHeader>
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs text-slate-500">Triaje recepción</span>
                <Badge variant="outline" className={TRIAGE_STYLES[triage].className}>
                  {TRIAGE_STYLES[triage].label}
                </Badge>
                <span className="text-xs text-slate-400">
                  Derivado de la última acción del agente, no es un score clínico.
                </span>
              </div>
              <p className="text-sm text-slate-600">{selected.note}</p>
              <div>
                <h3 className="mb-2 text-sm font-medium">Historial de citas</h3>
                <div className="space-y-2">
                  {history.length === 0 ? (
                    <p className="text-sm text-slate-500">Sin citas en mock.</p>
                  ) : (
                    history.map((item) => {
                      const outcome = outcomeFromAction(item.action);
                      return (
                        <div
                          key={item.appointment_id}
                          className="flex items-start justify-between gap-3 rounded-lg border border-slate-200 p-3 text-sm"
                        >
                          <div>
                            <p className="font-medium">
                              {formatMadrid(item.start_time, "d MMM yyyy HH:mm")}{" "}
                              · {item.location_name}
                            </p>
                            <p className="text-slate-500">
                              {item.provider_name} · {item.appointment_type_name}
                            </p>
                          </div>
                          <div className="text-right">
                            <Badge
                              variant="outline"
                              className={OUTCOME_STYLES[outcome].className}
                            >
                              {OUTCOME_STYLES[outcome].label}
                            </Badge>
                            {item.reason ? (
                              <p className="mt-1 text-xs text-slate-500">
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
