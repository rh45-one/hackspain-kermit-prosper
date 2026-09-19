import { IncidentBoard } from "@/components/incidents/incident-board";

/**
 * Lo que va mal en la clínica, mientras va mal.
 *
 * Servidor fino a propósito: todo se lee y se escribe por `/api/live` y
 * `/api/incidents`, los proxies de este origen, porque la pantalla cambia
 * cosas y un cambio tiene que volver con la respuesta del propio agente
 * —incluidas sus negativas, que son la mitad de lo que hace honesta a esta
 * pantalla.
 */
export const dynamic = "force-dynamic";

export const metadata = {
  title: "Incidencias · Clínica Arenal",
  description:
    "Lo que va mal ahora mismo, a quién le toca, y quién lo ha decidido: la ruta configurada o Jev.",
};

export default function IncidenciasPage() {
  const callBase = (
    process.env.VOICE_PUBLIC_BASE_URL ??
    process.env.AGENT_HTTP_BASE_URL ??
    "http://127.0.0.1:7860"
  ).replace(/\/$/, "");
  return <IncidentBoard callBase={`${callBase}/call/`} />;
}
