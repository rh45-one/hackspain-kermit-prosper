import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { outcomeFromAction, OUTCOME_STYLES } from "@/lib/outcomes";
import type { ProblemBrief } from "@/lib/problems/types";

function publicCaseEmptyCopy(problem: ProblemBrief): string {
  if (problem.diagnostic) {
    return "The Switchboard no tiene casos propios: el burst público son cinco líneas del problema 1. No se inventan respuestas aquí.";
  }
  return `Los ${problem.publicCaseCount} casos públicos oficiales no están vendored. No se inventan respuestas. Este problema no se marca desde Pronto.`;
}

export function ProblemDetail({ problem }: { problem: ProblemBrief }) {
  return (
    <div>
      <Link
        href="/leaderboard?tab=problems"
        className="mb-8 inline-flex items-center gap-2 font-heading text-[13px] text-steel transition-colors hover:text-graphite"
      >
        <ArrowLeft className="size-3.5" strokeWidth={1.8} />
        Volver a Resultados · Problemas
      </Link>

      <PageHeader kicker={`Problema ${problem.number}`} title={problem.titleEs}>
        {problem.title}
      </PageHeader>

      <div className="mb-10 flex flex-wrap items-center gap-3">
        <Badge
          variant="outline"
          className={
            problem.open
              ? "border-0 bg-ivory text-brass"
              : "border-0 bg-ash text-quiet"
          }
        >
          {problem.open ? "Abierto" : "Cerrado"}
        </Badge>
        {problem.diagnostic || problem.weight == null ? (
          <Badge variant="outline" className="border-0 bg-ash text-steel">
            Diagnóstico · no puntúa
          </Badge>
        ) : (
          <Badge variant="outline" className="border-0 bg-ivory text-graphite">
            Peso {problem.weight}
          </Badge>
        )}
        <span className="font-mono text-[13px] text-quiet">{problem.id}</span>
        <span className="text-[13px] text-quiet">
          {problem.diagnostic && problem.burstSize
            ? `0 casos propios · 1 burst de ${problem.burstSize}`
            : `${problem.publicCaseCount} casos públicos`}
        </span>
      </div>

      <section
        data-reveal=""
        className="surface mb-8 rounded-[18px] p-[var(--card-padding)]"
      >
        <h2 className="font-heading text-[18px] text-graphite">Resumen</h2>
        <p className="mt-4 max-w-[46rem] text-[16px] leading-[1.65] text-steel">
          {problem.summary}
        </p>
      </section>

      <section
        data-reveal=""
        data-delay="1"
        className="surface mb-8 rounded-[18px] p-[var(--card-padding)]"
      >
        <h2 className="font-heading text-[18px] text-graphite">
          Respuesta esperada
        </h2>
        <div className="mt-4 flex flex-wrap gap-2">
          {problem.answerVerbs.map((verb) => {
            const outcome = outcomeFromAction(verb);
            return (
              <Badge
                key={verb}
                variant="outline"
                className={OUTCOME_STYLES[outcome].className}
              >
                {verb}
              </Badge>
            );
          })}
        </div>
        <p className="mt-4 max-w-[46rem] text-[15px] leading-[1.6] text-steel">
          {problem.answerNote}
        </p>
      </section>

      {problem.datePhrases ? (
        <section
          data-reveal=""
          className="surface mb-8 rounded-[18px] p-[var(--card-padding)]"
        >
          <h2 className="font-heading text-[18px] text-graphite">
            Vocabulario de fechas
          </h2>
          <p className="mt-2 text-[14px] text-quiet">
            Publicado y fijo. Cada caso usa una frase de esta lista.
          </p>
          <ul className="mt-5 flex flex-wrap gap-2">
            {problem.datePhrases.map((phrase) => (
              <li key={phrase}>
                <Badge
                  variant="outline"
                  className="border-mist bg-canvas-white font-mono text-[11px] font-normal tracking-normal text-steel"
                >
                  {phrase}
                </Badge>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {problem.triageRoutes ? (
        <section
          data-reveal=""
          className="surface mb-8 overflow-hidden rounded-[18px]"
        >
          <div className="px-[var(--card-padding)] pt-[var(--card-padding)]">
            <h2 className="font-heading text-[18px] text-graphite">
              Encaminamiento de triaje
            </h2>
            <p className="mt-2 mb-5 text-[14px] text-quiet">
              Quejas publicadas. El tipo de cita sigue el historial, no el
              síntoma.
            </p>
          </div>
          <Table>
            <TableHeader>
              <TableRow className="border-mist hover:bg-transparent">
                <TableHead className="font-heading text-[13px] text-quiet">
                  El llamante dice
                </TableHead>
                <TableHead className="font-heading text-[13px] text-quiet">
                  Destino
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {problem.triageRoutes.map((row) => (
                <TableRow key={row.complaint} className="border-mist">
                  <TableCell className="whitespace-normal text-steel">
                    {row.complaint}
                  </TableCell>
                  <TableCell className="font-heading text-graphite">
                    {row.route}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </section>
      ) : null}

      {problem.redFlags ? (
        <section
          data-reveal=""
          className="surface mb-8 rounded-[18px] p-[var(--card-padding)]"
        >
          <h2 className="font-heading text-[18px] text-graphite">
            Banderas rojas
          </h2>
          <p className="mt-2 text-[14px] text-quiet">
            Escalar, no reservar. Lista publicada, no juicio clínico.
          </p>
          <ul className="mt-5 space-y-3">
            {problem.redFlags.map((flag) => (
              <li
                key={flag}
                className="border-l-2 border-ember-orange pl-4 text-[15px] leading-[1.5] text-steel"
              >
                {flag}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {problem.noiseTextures ? (
        <section
          data-reveal=""
          className="surface mb-8 rounded-[18px] p-[var(--card-padding)]"
        >
          <h2 className="font-heading text-[18px] text-graphite">
            Texturas de ruido
          </h2>
          <div className="mt-4 flex flex-wrap gap-2">
            {problem.noiseTextures.map((texture) => (
              <Badge
                key={texture}
                variant="outline"
                className="border-0 bg-ash text-steel"
              >
                {texture}
              </Badge>
            ))}
          </div>
        </section>
      ) : null}

      {problem.protectedFields ? (
        <section
          data-reveal=""
          className="surface mb-8 rounded-[18px] p-[var(--card-padding)]"
        >
          <h2 className="font-heading text-[18px] text-graphite">
            Campos protegidos
          </h2>
          <p className="mt-2 max-w-[42rem] text-[14px] leading-relaxed text-quiet">
            Solo se leen los turnos del agente. El nombre no está protegido.
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            {problem.protectedFields.map((field) => (
              <Badge
                key={field}
                variant="outline"
                className="border-0 bg-ash font-mono text-[11px] tracking-normal text-graphite"
              >
                {field}
              </Badge>
            ))}
          </div>
        </section>
      ) : null}

      <section
        data-reveal=""
        className="surface rounded-[18px] p-[var(--card-padding)]"
      >
        <h2 className="font-heading text-[18px] text-graphite">
          Casos públicos
        </h2>
        {problem.publicCases.length === 0 ? (
          <p className="mt-4 max-w-[42rem] text-[15px] leading-[1.6] text-steel">
            {publicCaseEmptyCopy(problem)}
          </p>
        ) : (
          <ul className="mt-4 space-y-4">
            {problem.publicCases.map((item) => (
              <li key={item.id} className="border-t border-mist pt-4">
                <p className="font-heading text-[16px] text-graphite">
                  {item.id}
                </p>
                <p className="mt-1 text-[14px] text-steel">{item.goal}</p>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
