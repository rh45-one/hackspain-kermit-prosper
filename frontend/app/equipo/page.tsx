import { TeamBoard } from "@/components/team/team-board";

/**
 * The clinic's own directory: who answers, and how the agent talks to them.
 *
 * A thin server component on purpose. Everything here is read and written
 * through `/api/orgs/*`, this origin's proxy, because the screen edits and an
 * edit has to come back with the agent's own answer — including its refusals,
 * which are half of what makes this screen honest.
 *
 * The one thing the server contributes is the organisation id, which the
 * browser has no business guessing: the proxy resolves it the same way from
 * the same variable, and this copy is only what the header reads out.
 */

export const dynamic = "force-dynamic";

export const metadata = {
  title: "Quién responde · Clínica Arenal",
  description:
    "Quién se entera de cada una de las dieciocho formas en que una llamada puede acabar sin cita, y cómo abre el agente cuando llama a cada persona.",
};

export default function EquipoPage() {
  const orgId = (process.env.ORG_ID ?? "clinica-arenal").trim().toLowerCase();
  return <TeamBoard orgId={orgId} />;
}
