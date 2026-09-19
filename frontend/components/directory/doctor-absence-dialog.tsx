"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { DirectoryDoctor } from "@/lib/doctor-directory";

type DoctorAbsenceDialogProps = {
  doctor: DirectoryDoctor | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (payload: {
    doctorId: string;
    start: string;
    end: string;
    reason: string;
  }) => void;
};

export function DoctorAbsenceDialog({
  doctor,
  open,
  onOpenChange,
  onConfirm,
}: DoctorAbsenceDialogProps) {
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [reason, setReason] = useState("");

  const reset = () => {
    setStart("");
    setEnd("");
    setReason("");
  };

  const canSubmit =
    Boolean(doctor) && start.trim().length > 0 && end.trim().length > 0;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
    >
      <DialogContent className="max-w-md border-mist bg-canvas-white sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="font-heading text-[clamp(1.5rem,4vw,1.85rem)] font-medium tracking-[-0.04em] text-graphite">
            Marcar como ausente
          </DialogTitle>
          <DialogDescription className="text-[14px] leading-relaxed text-steel">
            {doctor
              ? `Inicia la Recovery Campaign para reubicar citas de ${doctor.name}.`
              : "Selecciona un médico del directorio."}
          </DialogDescription>
        </DialogHeader>

        {doctor ? (
          <div className="space-y-5">
            <div className="rounded-[14px] bg-slate-50 px-4 py-3">
              <p className="font-heading text-[15px] text-graphite">
                {doctor.name}
              </p>
              <p className="mt-1 text-[13px] text-quiet">
                {doctor.specialtyName}
                {doctor.locationNames.length
                  ? ` · ${doctor.locationNames.join(", ")}`
                  : null}
              </p>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label
                  htmlFor="absence-start"
                  className="font-heading text-[13px] text-quiet"
                >
                  Desde
                </Label>
                <Input
                  id="absence-start"
                  type="date"
                  value={start}
                  className="border-mist bg-white"
                  onChange={(event) => setStart(event.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label
                  htmlFor="absence-end"
                  className="font-heading text-[13px] text-quiet"
                >
                  Hasta
                </Label>
                <Input
                  id="absence-end"
                  type="date"
                  value={end}
                  className="border-mist bg-white"
                  onChange={(event) => setEnd(event.target.value)}
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label
                htmlFor="absence-reason"
                className="font-heading text-[13px] text-quiet"
              >
                Motivo
              </Label>
              <Textarea
                id="absence-reason"
                value={reason}
                placeholder="Baja, congreso, permiso…"
                className="min-h-24 border-mist bg-white"
                onChange={(event) => setReason(event.target.value)}
              />
            </div>
          </div>
        ) : null}

        <DialogFooter className="border-mist bg-slate-50/80 sm:justify-end">
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
          >
            Cancelar
          </Button>
          <Button
            type="button"
            variant="destructive"
            disabled={!canSubmit}
            onClick={() => {
              if (!doctor || !canSubmit) return;
              onConfirm({
                doctorId: doctor.id,
                start,
                end,
                reason: reason.trim() || "Ausencia programada",
              });
              reset();
              onOpenChange(false);
            }}
          >
            Confirmar ausencia
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
