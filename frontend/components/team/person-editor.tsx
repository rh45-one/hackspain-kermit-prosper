"use client";

import { useEffect, useState } from "react";
import { Check, Loader2, PhoneCall, RotateCcw, TriangleAlert } from "lucide-react";

import { SourceBadge } from "@/components/team/marks";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import {
  BRIEF_LABELS,
  BRIEF_ORDER,
  DECLARED_SLUGS,
  LANGUAGES,
  ROLE_LABELS,
  ROLE_OPTIONS,
  TeamError,
  URGENCY,
  ask,
  draftOf,
  emptyDraft,
  isDirty,
  linesToList,
  personBody,
  slugify,
  type Brief,
  type CallProfile,
  type Person,
  type PersonDraft,
  type RouteRow,
  type Urgency,
} from "@/lib/team";
import { REASON_LABELS } from "@/lib/outcomes";
import type { OutcomeReason } from "@/lib/types";
import { cn } from "@/lib/utils";

function reasonLabel(reason: string): string {
  return REASON_LABELS[reason as OutcomeReason] ?? reason;
}

/**
 * One person's row and, beside it, exactly what ringing them would open with.
 *
 * The preview is not rendered from the form: it is `GET .../call-profile`, the
 * same `cover_brief` the real call builds, so the screen cannot drift from the
 * behaviour. That is also why it shows the **saved** person and says so out
 * loud whenever the form has moved away from it — a preview that quietly drew
 * unsaved text would be a preview of something that does not exist.
 */
export function PersonEditor({
  person,
  routes,
  onChanged,
  onFault,
}: {
  person: Person | null;
  routes: RouteRow[];
  onChanged: (people: Person[] | null, focus?: string) => void;
  onFault: (error: TeamError) => void;
}) {
  const [draft, setDraft] = useState<PersonDraft>(() => (person ? draftOf(person) : emptyDraft()));
  const [saving, setSaving] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [profile, setProfile] = useState<CallProfile | null>(null);
  const [previewReason, setPreviewReason] = useState("");
  // Starts true because the first fetch is already on its way; turned back on
  // from the handlers that cause a refetch, never from inside the effect.
  const [previewing, setPreviewing] = useState(true);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const slug = person?.slug ?? "";
  const mine = routes.filter((route) => route.person_slug === slug);
  // Derived, never copied into state: the chosen reason if there is one, and
  // otherwise the first reason that reaches this person. A `useState` kept in
  // step with a prop is a second version of the same fact.
  const activeReason = previewReason || mine[0]?.reason || "";
  // Bumped after a save so the preview asks again for the same person — the
  // only reason a reload is needed when nothing else on screen has moved.
  const [previewNonce, setPreviewNonce] = useState(0);

  useEffect(() => {
    if (!slug) {
      return;
    }
    let alive = true;
    const query = activeReason ? `?reason=${encodeURIComponent(activeReason)}` : "";
    ask<CallProfile>(`people/${slug}/call-profile${query}`)
      .then((loaded) => {
        if (!alive) return;
        setProfile(loaded);
        setPreviewError(null);
      })
      .catch((caught) => {
        if (!alive) return;
        setProfile(null);
        setPreviewError((caught as TeamError).message);
      })
      .finally(() => {
        if (alive) setPreviewing(false);
      });
    return () => {
      alive = false;
    };
  }, [slug, activeReason, previewNonce]);

  const dirty = isDirty(draft, person);
  const targetSlug = person?.slug || slugify(draft.slug || draft.name);
  const valid = draft.name.trim().length > 0 && targetSlug.length > 0;

  async function save() {
    if (!valid) {
      setError("Hace falta un nombre, y un identificador que el agente pueda usar.");
      return;
    }
    setSaving(true);
    setError(null);
    setNote(null);
    try {
      const saved = await ask<Person>(`people/${targetSlug}`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(personBody(draft)),
      });
      setNote(
        saved.source === "configured" && DECLARED_SLUGS.has(saved.slug)
          ? `Guardado. «${saved.name}» sustituye al valor por defecto de ${ROLE_LABELS[saved.slug] ?? saved.slug}.`
          : `Guardado. Ahora la clínica puede llamar a «${saved.name}».`,
      );
      onChanged(null, saved.slug);
      setPreviewing(true);
      setPreviewNonce((current) => current + 1);
    } catch (caught) {
      const failure = caught as TeamError;
      if (failure.fault === "upstream" || failure.status === 400) {
        setError(failure.message);
      } else {
        onFault(failure);
      }
    } finally {
      setSaving(false);
    }
  }

  async function revert() {
    if (!person || person.source !== "configured") {
      return;
    }
    setSaving(true);
    setError(null);
    setNote(null);
    try {
      const after = await ask<Person[]>(`people/${person.slug}`, { method: "DELETE" });
      const restored = after.find((row) => row.slug === person.slug);
      setNote(
        restored
          ? `Borrado lo que había escrito la clínica. Vuelve el valor por defecto: «${restored.name}».`
          : `Borrado. Ya no responde nadie a «${person.slug}»: las razones que le apuntaban se quedan sin destino.`,
      );
      onChanged(after);
    } catch (caught) {
      const failure = caught as TeamError;
      if (failure.fault === "upstream" || failure.status === 400 || failure.status === 404) {
        setError(failure.message);
      } else {
        onFault(failure);
      }
    } finally {
      setSaving(false);
    }
  }

  function patch(next: Partial<PersonDraft>) {
    setDraft((current) => ({ ...current, ...next }));
    setNote(null);
  }

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
      {/* ------------------------------------------------------------ form */}
      <section className="rounded-[16px] border border-mist bg-canvas-white p-5">
        <header className="mb-5 flex flex-wrap items-center gap-2.5">
          <h3 className="font-heading text-[18px] tracking-[-0.02em] text-graphite">
            {person ? person.name : "Alguien nuevo en la clínica"}
          </h3>
          {person ? <SourceBadge source={person.source} /> : null}
          {person && !person.active ? (
            <span className="rounded-full bg-ash px-2.5 py-0.5 font-heading text-[11px] text-quiet">
              No se le llama
            </span>
          ) : null}
        </header>

        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="person-name" className="font-heading text-[12.5px] text-quiet">
                Cómo se llama
              </Label>
              <Input
                id="person-name"
                value={draft.name}
                className="border-mist bg-canvas-white"
                placeholder="Dra. Ortiz"
                onChange={(event) => patch({ name: event.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="person-slug" className="font-heading text-[12.5px] text-quiet">
                Identificador
              </Label>
              <Input
                id="person-slug"
                value={person ? person.slug : draft.slug}
                disabled={Boolean(person)}
                className="border-mist bg-canvas-white font-mono text-[13px]"
                placeholder={slugify(draft.name) || "dra-ortiz"}
                onChange={(event) => patch({ slug: slugify(event.target.value) })}
              />
              <p className="text-[12px] leading-[1.5] text-quiet">
                {person
                  ? "No se cambia: es lo que apuntan las razones de la llamada."
                  : "Es lo que apuntarán las razones. Se escribe una vez."}
              </p>
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="person-role" className="font-heading text-[12.5px] text-quiet">
                Qué papel tiene
              </Label>
              <select
                id="person-role"
                value={draft.role}
                onChange={(event) => patch({ role: event.target.value })}
                className="h-10 w-full rounded-[10px] border border-mist bg-canvas-white px-3 font-heading text-[14px] text-graphite outline-none focus-visible:ring-2 focus-visible:ring-brass/35"
              >
                {ROLE_OPTIONS.map((role) => (
                  <option key={role} value={role}>
                    {ROLE_LABELS[role] ?? role}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="person-provider" className="font-heading text-[12.5px] text-quiet">
                Su id en el catálogo
              </Label>
              <Input
                id="person-provider"
                value={draft.provider_id ?? ""}
                className="border-mist bg-canvas-white font-mono text-[13px]"
                placeholder="PR10 · opcional"
                onChange={(event) => patch({ provider_id: event.target.value })}
              />
              <p className="text-[12px] leading-[1.5] text-quiet">
                Si es un médico de la clínica, de aquí salen sus idiomas cuando no los escribes.
              </p>
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="person-detail" className="font-heading text-[12.5px] text-quiet">
              Qué hace
            </Label>
            <Input
              id="person-detail"
              value={draft.detail}
              className="border-mist bg-canvas-white"
              placeholder="Traumatología, sede Sagasta"
              onChange={(event) => patch({ detail: event.target.value })}
            />
          </div>

          <div className="space-y-2">
            <Label className="font-heading text-[12.5px] text-quiet">
              En qué idioma se le abre la llamada
            </Label>
            <div className="flex flex-wrap gap-2">
              {Object.entries(LANGUAGES).map(([code, said]) => {
                const on = draft.languages.includes(code);
                return (
                  <button
                    key={code}
                    type="button"
                    aria-pressed={on}
                    onClick={() =>
                      patch({
                        languages: on
                          ? draft.languages.filter((item) => item !== code)
                          : [...draft.languages, code],
                      })
                    }
                    className={cn(
                      "cursor-pointer rounded-full px-3 py-1.5 font-heading text-[12.5px] transition-colors duration-200",
                      on
                        ? "bg-graphite text-canvas-white"
                        : "border border-mist bg-canvas-white text-steel hover:border-quiet",
                    )}
                  >
                    {said}
                  </button>
                );
              })}
            </div>
            <p className="text-[12px] leading-[1.5] text-quiet">
              El primero es en el que se abre. Sin ninguno, se usa el del catálogo si es médico.
            </p>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="person-opening" className="font-heading text-[12.5px] text-quiet">
              Cómo abrir con ella cuando descuelga
            </Label>
            <Textarea
              id="person-opening"
              rows={2}
              value={draft.opening}
              className="border-mist bg-canvas-white"
              placeholder="Hola Dra. Ortiz, soy el recepcionista de Arenal. Es por un hueco de mañana."
              onChange={(event) => patch({ opening: event.target.value })}
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="person-may" className="font-heading text-[12.5px] text-quiet">
                Se le puede pedir
              </Label>
              <Textarea
                id="person-may"
                rows={3}
                value={draft.may_ask.join("\n")}
                className="border-mist bg-canvas-white"
                placeholder={"doblar un sábado\nadelantar una revisión"}
                onChange={(event) => patch({ may_ask: linesToList(event.target.value) })}
              />
              <p className="text-[12px] text-quiet">Una cosa por línea.</p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="person-must-not" className="font-heading text-[12.5px] text-quiet">
                No se le pide
              </Label>
              <Textarea
                id="person-must-not"
                rows={3}
                value={draft.must_not_ask.join("\n")}
                className="border-mist bg-canvas-white"
                placeholder={"guardias de noche\ncubrir en otra sede"}
                onChange={(event) => patch({ must_not_ask: linesToList(event.target.value) })}
              />
              <p className="text-[12px] text-quiet">Una cosa por línea.</p>
            </div>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="person-phone" className="font-heading text-[12.5px] text-quiet">
                Teléfono
              </Label>
              <Input
                id="person-phone"
                value={draft.phone}
                className="border-mist bg-canvas-white"
                placeholder="+34 600 11 22 33"
                onChange={(event) => patch({ phone: event.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="person-email" className="font-heading text-[12.5px] text-quiet">
                Correo
              </Label>
              <Input
                id="person-email"
                value={draft.email}
                className="border-mist bg-canvas-white"
                placeholder="ortiz@clinicaarenal.es"
                onChange={(event) => patch({ email: event.target.value })}
              />
            </div>
          </div>
          <p className="text-[12px] leading-[1.5] text-quiet">
            El teléfono y el correo son para que los marque una persona. No entran nunca en lo que
            lee el modelo.
          </p>

          <div className="flex items-center gap-3 rounded-[12px] border border-mist bg-ash/50 px-3.5 py-3">
            <Switch
              id="person-active"
              checked={draft.active}
              onCheckedChange={(value) => patch({ active: value })}
            />
            <Label htmlFor="person-active" className="font-heading text-[13px] text-graphite">
              {draft.active ? "Se le puede llamar" : "No se le llama, aunque siga en la lista"}
            </Label>
          </div>
        </div>

        {error ? (
          <p className="mt-4 flex items-start gap-2 rounded-[12px] bg-ivory px-3.5 py-3 text-[13px] leading-[1.55] text-ember-orange">
            <TriangleAlert className="mt-px size-4 shrink-0" />
            {error}
          </p>
        ) : null}
        {note ? (
          <p className="mt-4 flex items-start gap-2 rounded-[12px] bg-ash/70 px-3.5 py-3 text-[13px] leading-[1.55] text-steel">
            <Check className="mt-px size-4 shrink-0 text-brass" />
            {note}
          </p>
        ) : null}

        <footer className="mt-5 flex flex-wrap items-center gap-3">
          <Button onClick={() => void save()} disabled={saving || !valid || !dirty}>
            {saving ? <Loader2 className="animate-spin" /> : null}
            {person ? "Guardar y ver el efecto" : "Añadir a la clínica"}
          </Button>
          {person && person.source === "configured" ? (
            <Button variant="outline" onClick={() => void revert()} disabled={saving}>
              <RotateCcw />
              {DECLARED_SLUGS.has(person.slug)
                ? "Volver al valor por defecto"
                : "Quitar de la clínica"}
            </Button>
          ) : null}
          {person && person.source === "default" ? (
            <p className="text-[12.5px] leading-[1.5] text-quiet">
              Nadie ha tocado esta ficha. En cuanto guardes, deja de ser el valor por defecto y
              podrás devolverla.
            </p>
          ) : null}
        </footer>
      </section>

      {/* --------------------------------------------------------- preview */}
      <aside className="rounded-[16px] border border-graphite/15 bg-ash/60 p-5">
        <header className="flex items-center gap-2">
          <PhoneCall className="size-4 text-brass" />
          <h3 className="font-heading text-[15px] tracking-[-0.01em] text-graphite">
            Así abriría la llamada
          </h3>
        </header>
        <p className="mt-2 text-[12.5px] leading-[1.55] text-steel">
          No es una maqueta: lo construye el agente con la misma función que usa al llamar de
          verdad. Si aquí pone algo raro, en la llamada pondrá lo mismo.
        </p>

        {mine.length > 0 ? (
          <div className="mt-4 space-y-1.5">
            <Label htmlFor="preview-reason" className="font-heading text-[12px] text-quiet">
              Por cuál de sus razones
            </Label>
            <select
              id="preview-reason"
              value={activeReason}
              onChange={(event) => {
                setPreviewing(true);
                setPreviewReason(event.target.value);
              }}
              className="h-9 w-full rounded-[10px] border border-mist bg-canvas-white px-3 font-heading text-[13px] text-graphite outline-none focus-visible:ring-2 focus-visible:ring-brass/35"
            >
              {mine.map((route) => (
                <option key={route.reason} value={route.reason}>
                  {reasonLabel(route.reason)} · {URGENCY[route.urgency].word}
                </option>
              ))}
            </select>
          </div>
        ) : person ? (
          <p className="mt-4 rounded-[10px] border border-dashed border-mist px-3 py-2.5 text-[12.5px] leading-[1.5] text-quiet">
            Ninguna de las dieciocho razones le apunta todavía, así que la vista previa sale sin
            motivo. Asígnale una en «Qué llega a quién».
          </p>
        ) : null}

        {dirty && person ? (
          <p className="mt-4 flex items-start gap-2 rounded-[10px] bg-ivory px-3 py-2.5 text-[12.5px] leading-[1.5] text-brass">
            <TriangleAlert className="mt-px size-3.5 shrink-0" />
            Tienes cambios sin guardar. Esto sigue siendo lo que abriría la llamada ahora mismo.
          </p>
        ) : null}

        <div className="mt-4 space-y-2.5">
          {previewing ? (
            <p className="text-[13px] text-quiet">Preguntándole al agente…</p>
          ) : previewError ? (
            <p className="text-[13px] leading-[1.55] text-ember-orange">{previewError}</p>
          ) : !person ? (
            <p className="text-[13px] leading-[1.55] text-quiet">
              Guarda a esta persona y el agente te enseñará con qué abriría.
            </p>
          ) : profile ? (
            <BriefRows brief={profile.brief} urgencyOf={mine.find((r) => r.reason === activeReason)?.urgency} />
          ) : null}
        </div>
      </aside>
    </div>
  );
}

/** The brief, key by key, in the words a person uses rather than the API's. */
function BriefRows({ brief, urgencyOf }: { brief: Brief; urgencyOf?: Urgency }) {
  const rows = BRIEF_ORDER.filter((key) => (brief[key] ?? "").trim().length > 0);
  if (rows.length === 0) {
    return (
      <p className="text-[13px] leading-[1.55] text-quiet">
        El agente no abriría con nada: esta ficha está vacía. Escríbele un idioma y una frase de
        apertura y mira qué cambia aquí.
      </p>
    );
  }
  return (
    <dl className="space-y-2.5">
      {rows.map((key) => (
        <div key={key} className="rounded-[10px] bg-canvas-white px-3 py-2.5">
          <dt className="font-heading text-[10.5px] tracking-[0.05em] text-quiet uppercase">
            {BRIEF_LABELS[key]}
          </dt>
          <dd className="mt-1 text-[13.5px] leading-[1.5] text-graphite">
            {key === "reason"
              ? reasonLabel(brief.reason ?? "")
              : key === "urgency"
                ? `${URGENCY[(brief.urgency as Urgency) ?? urgencyOf ?? "queue"]?.word ?? brief.urgency} — ${URGENCY[(brief.urgency as Urgency) ?? "queue"]?.gloss ?? ""}`
                : brief[key]}
          </dd>
        </div>
      ))}
    </dl>
  );
}
