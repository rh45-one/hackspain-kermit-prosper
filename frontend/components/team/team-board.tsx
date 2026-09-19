"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Loader2, Plus, Share2, TriangleAlert, Users } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { SourceBadge } from "@/components/team/marks";
import { PersonEditor } from "@/components/team/person-editor";
import { RoutesPanel } from "@/components/team/routes-panel";
import { TeamUnavailable } from "@/components/team/team-unavailable";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  ROLE_LABELS,
  TeamError,
  ask,
  saidLanguages,
  type Person,
  type RouteRow,
} from "@/lib/team";
import { cn } from "@/lib/utils";

const NEW = "__nueva__";

/**
 * Who answers in this clinic, and how the agent speaks to each of them.
 *
 * Two questions and therefore two tabs: *who exists* and *what reaches whom*.
 * They share one load, because the second is meaningless without the first —
 * a route is only a route if somebody answers to it, and that is precisely
 * what `reachable` is about.
 *
 * Everything here reads and writes through `/api/orgs/*`, this origin's own
 * proxy. The ops token stays in that process. A 401 is expected today and is
 * rendered as a sentence about signing in, not as a stack trace.
 */
export function TeamBoard({ orgId }: { orgId: string }) {
  const [people, setPeople] = useState<Person[] | null>(null);
  const [routes, setRoutes] = useState<RouteRow[] | null>(null);
  const [fault, setFault] = useState<TeamError | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string>("");

  // Both reads in one go: a route only means something next to the people it
  // can point at, and `reachable` is exactly the disagreement between them.
  // Written as a promise chain rather than an `await` so no state is set
  // synchronously inside the effect that calls it.
  const load = useCallback(
    (focus?: string) => {
      let alive = true;
      Promise.all([ask<Person[]>("people"), ask<RouteRow[]>("routes")])
        .then(([loadedPeople, loadedRoutes]) => {
          if (!alive) return;
          setPeople(loadedPeople);
          setRoutes(loadedRoutes);
          setFault(null);
          setSelected((current) => {
            const wanted = focus ?? current;
            if (loadedPeople.some((person) => person.slug === wanted)) {
              return wanted;
            }
            return wanted === NEW ? NEW : (loadedPeople[0]?.slug ?? "");
          });
        })
        .catch((caught) => {
          if (alive) setFault(caught as TeamError);
        })
        .finally(() => {
          if (alive) setLoading(false);
        });
      return () => {
        alive = false;
      };
    },
    [],
  );

  useEffect(() => load(), [load]);

  if (fault) {
    return <TeamUnavailable fault={fault.fault} detail={fault.message} onRetry={() => load()} />;
  }

  if (loading && people === null) {
    return (
      <div>
        <Header orgId={orgId} />
        <p className="flex items-center gap-2 text-[14px] text-quiet">
          <Loader2 className="size-4 animate-spin" /> Preguntándole al agente quién responde…
        </p>
      </div>
    );
  }

  const roster = people ?? [];
  const table = routes ?? [];
  const person = selected === NEW ? null : (roster.find((row) => row.slug === selected) ?? null);
  const broken = table.filter((route) => !route.reachable).length;
  const configuredPeople = roster.filter((row) => row.source === "configured").length;
  const configuredRoutes = table.filter((row) => row.source === "configured").length;

  return (
    <div>
      <Header orgId={orgId} />

      <section className="mb-7 grid gap-3 sm:grid-cols-3">
        <Legend
          title="Lo que trae el sistema"
          body="Cuatro personas y dieciocho rutas que la clínica no ha tocado. Se ven en gris y con el borde punteado."
          mark={<SourceBadge source="default" />}
        />
        <Legend
          title="Lo que ha escrito la clínica"
          body={`${configuredPeople} ficha${configuredPeople === 1 ? "" : "s"} y ${configuredRoutes} ruta${configuredRoutes === 1 ? "" : "s"}. Borrarlo no deja un hueco: vuelve el valor por defecto.`}
          mark={<SourceBadge source="configured" />}
        />
        <Legend
          title="Rutas rotas"
          body={
            broken === 0
              ? "Ninguna. Las dieciocho razones tienen a alguien que responde."
              : "Apuntan a alguien que ya no existe. Salen las primeras y en naranja."
          }
          mark={
            <span
              className={cn(
                "inline-flex h-[22px] items-center gap-1.5 rounded-full px-2.5 font-heading text-[11px]",
                broken === 0 ? "bg-ash text-quiet" : "bg-ember-orange/12 text-ember-orange",
              )}
            >
              {broken > 0 ? <TriangleAlert className="size-3" /> : null}
              {broken === 0 ? "0 rotas" : `${broken} rota${broken === 1 ? "" : "s"}`}
            </span>
          }
        />
      </section>

      <Tabs defaultValue="people">
        <TabsList className="mb-6">
          <TabsTrigger value="people">
            <Users className="mr-1.5 size-4" /> Quién responde
          </TabsTrigger>
          <TabsTrigger value="routes">
            <Share2 className="mr-1.5 size-4" /> Qué llega a quién
          </TabsTrigger>
        </TabsList>

        <TabsContent value="people">
          <div className="grid gap-5 xl:grid-cols-[minmax(0,17rem)_minmax(0,1fr)]">
            <nav className="space-y-2">
              {roster.map((row) => {
                const mine = table.filter((route) => route.person_slug === row.slug);
                const on = row.slug === selected;
                return (
                  <button
                    key={row.slug}
                    type="button"
                    onClick={() => setSelected(row.slug)}
                    aria-current={on}
                    className={cn(
                      "w-full cursor-pointer rounded-[14px] border px-3.5 py-3 text-left transition-colors duration-200",
                      on
                        ? "border-graphite bg-canvas-white"
                        : row.source === "default"
                          ? "border-dashed border-mist bg-transparent hover:border-quiet"
                          : "border-mist bg-canvas-white hover:border-quiet",
                    )}
                  >
                    <span className="flex items-start justify-between gap-2">
                      <span
                        className={cn(
                          "font-heading text-[14.5px] leading-tight",
                          row.source === "default" ? "text-steel" : "text-graphite",
                        )}
                      >
                        {row.name}
                      </span>
                      <SourceBadge source={row.source} />
                    </span>
                    <span className="mt-1 block text-[12.5px] leading-[1.45] text-quiet">
                      {/* What they do, and not their role when the role is
                          already their name: "Recepción · Recepción" tells
                          nobody anything. */}
                      {row.detail || (ROLE_LABELS[row.role] ?? row.role)}
                      {row.languages.length > 0 ? ` · ${saidLanguages(row.languages)}` : ""}
                    </span>
                    <span className="mt-1.5 block text-[12px] text-quiet">
                      {mine.length === 0
                        ? "No le llega ninguna razón"
                        : `Le llegan ${mine.length} de las 18 razones`}
                    </span>
                  </button>
                );
              })}
              <Button
                variant="outline"
                className="w-full"
                onClick={() => setSelected(NEW)}
                aria-current={selected === NEW}
              >
                <Plus /> Añadir a alguien
              </Button>
            </nav>

            <PersonEditor
              key={person?.slug ?? NEW}
              person={person}
              routes={table}
              onChanged={(after, focus) => {
                if (after) {
                  setPeople(after);
                }
                load(focus);
              }}
              onFault={(error) => setFault(error)}
            />
          </div>
        </TabsContent>

        <TabsContent value="routes">
          <RoutesPanel
            routes={table}
            people={roster}
            onChanged={() => load()}
            onFault={(error) => setFault(error)}
          />
          <p className="mt-5 max-w-[46rem] text-[13px] leading-[1.6] text-quiet">
            Las dieciocho razones las declara la clínica y no se pueden inventar aquí: lo que se
            edita es a quién le llega cada una y con qué urgencia. Para ver las mismas rutas
            dibujadas, y llamar desde el móvil,{" "}
            <Link href="/grafo" className="ember-underline text-graphite">
              está el mapa
            </Link>
            .
          </p>
        </TabsContent>
      </Tabs>
    </div>
  );
}

function Header({ orgId }: { orgId: string }) {
  return (
    <>
      <PageHeader kicker={`Clínica · ${orgId}`} title="Quién responde, y cómo se le habla">
        Cuando una llamada acaba sin cita, alguien tiene que enterarse. Aquí se dice quién es esa
        persona para cada uno de los dieciocho finales posibles, y qué le dice el agente cuando
        descuelga: en qué idioma, con qué frase, y qué se le puede pedir y qué no.
      </PageHeader>
    </>
  );
}

function Legend({ title, body, mark }: { title: string; body: string; mark: React.ReactNode }) {
  return (
    <div className="rounded-[12px] border border-mist bg-canvas-white px-3.5 py-3">
      {mark}
      <p className="mt-2 font-heading text-[13.5px] text-graphite">{title}</p>
      <p className="mt-1 text-[12.5px] leading-[1.5] text-steel">{body}</p>
    </div>
  );
}
