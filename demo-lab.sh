#!/usr/bin/env bash
# Judge-demo lab: clinic double + local Prosper agent + evaluator console.
# Everything lands on laboratory ports; production (7860/7861, fly.dev) is never touched.
#
#   ./demo-lab.sh          # start (or reuse) all three pieces
#   ./demo-lab.sh stop     # stop the three pieces
#   ./demo-lab.sh status   # health check
#
# Screens for the demo:
#   console  http://127.0.0.1:8099/            (Seguimiento / Llamadas / Probar el agente)
#   ops lab  http://127.0.0.1:17861/ops        (agent internals)
# Call evidence: evaluator/experiments/results/agent-data/<org>/calls/*.jsonl
set -euo pipefail
cd "$(dirname "$0")"

CLINIC_PORT=18090
AGENT_PORT=17860
OPS_PORT=17861
CONSOLE_PORT=8099
LAB_DATA="$(pwd)/evaluator/experiments/results/agent-data"
if [[ "${VOICE_ENGINE:-cascade}" == "gemini_live" ]]; then
  AGENT_PORT=17862
  OPS_PORT=17863
  LAB_DATA="${LAB_DATA}-gemini"
fi

start() {
  # 1) Clinic double (fake Prosper platform), key pk-local-eval
  if ! curl -sf -m 2 -H "X-Api-Key: pk-local-eval" "http://127.0.0.1:${CLINIC_PORT}/api/v1/directory" >/dev/null; then
    echo "» clínica doble :${CLINIC_PORT}"
    setsid nohup uv run --project evaluator python -m evaluator.cli clinic \
      --dataset evaluator/data/clinic_dataset.json \
      --host 127.0.0.1 --port "${CLINIC_PORT}" \
      > /tmp/demo-clinic.log 2>&1 < /dev/null &
  else
    echo "• clínica doble ya arriba :${CLINIC_PORT}"
  fi

  # 2) Lab agent (same code as production) on the frozen lab port
  if ! curl -sf -m 2 "http://127.0.0.1:${AGENT_PORT}/healthz" >/dev/null; then
    echo "» agente lab    :${AGENT_PORT} (engine=${VOICE_ENGINE:-cascade}, modelo=${AGENT_MODEL:-deepseek-v4-flash})"
    : "${HELMCODE_API_KEY:?export HELMCODE_API_KEY antes de arrancar (key del brain/juez)}"
    setsid nohup env \
      VOICE_WS_HOST=127.0.0.1 VOICE_WS_PORT="${AGENT_PORT}" PORT="${AGENT_PORT}" \
      OPS_HTTP_PORT="${OPS_PORT}" TURNS_ADAPTER=1 \
      PROSPER_API_BASE_URL="http://127.0.0.1:${CLINIC_PORT}" PROSPER_API_KEY=pk-local-eval \
      VOICE_ENGINE="${VOICE_ENGINE:-cascade}" \
      HELMCODE_API_KEY="${HELMCODE_API_KEY}" AGENT_MODEL="${AGENT_MODEL:-deepseek-v4-flash}" \
      ELEVENLABS_VOICE_ID="${ELEVENLABS_VOICE_ID:-EXAVITQu4vr4xnSDxMaL}" \
      DATA_DIR="${LAB_DATA}" \
      uv run --project backend python -m agent.serve \
      > /tmp/demo-agent.log 2>&1 < /dev/null &
    for _ in $(seq 1 30); do curl -sf -m 2 "http://127.0.0.1:${AGENT_PORT}/healthz" >/dev/null && break; sleep 1; done
  else
    echo "• agente lab ya arriba :${AGENT_PORT}"
  fi

  # 3) Evaluator console, reading the lab audit
  if ! curl -sf -m 2 "http://127.0.0.1:${CONSOLE_PORT}/api/profiles" >/dev/null; then
    echo "» consola       :${CONSOLE_PORT}"
    : "${EVALUATOR_JUDGE_API_KEY:=}"; : "${HELMCODE_API_KEY:=}"
    setsid nohup env \
      EVALUATOR_JUDGE_API_KEY="${EVALUATOR_JUDGE_API_KEY:-${HELMCODE_API_KEY}}" \
      EVALUATOR_JUDGE_BASE_URL="${EVALUATOR_JUDGE_BASE_URL:-https://api.helmcode.com/v1}" \
      EVALUATOR_JUDGE_MODEL="${EVALUATOR_JUDGE_MODEL:-glm5.3}" \
      uv run --project evaluator python -m evaluator.cli dev \
      --port "${CONSOLE_PORT}" --results evaluator/experiments/results \
      --audit-data "${LAB_DATA}" \
      > /tmp/demo-console.log 2>&1 < /dev/null &
    for _ in $(seq 1 20); do curl -sf -m 2 "http://127.0.0.1:${CONSOLE_PORT}/api/profiles" >/dev/null && break; sleep 1; done
  else
    echo "• consola ya arriba :${CONSOLE_PORT}"
  fi

  echo
  ./demo-lab.sh status
  echo "Demo listo: abrí http://127.0.0.1:${CONSOLE_PORT}/ → Probar el agente → Iniciar llamada."
}

stop() {
  for f in /tmp/demo-clinic.log /tmp/demo-agent.log /tmp/demo-console.log; do :; done
  pkill -f "evaluator.cli clinic --dataset evaluator/data/clinic_dataset.json" 2>/dev/null || true
  pkill -f "python -m agent[.]serve" 2>/dev/null || true
  pkill -f "evaluator.cli dev --port ${CONSOLE_PORT}" 2>/dev/null || true
  echo "lab detenido (producción no tocada)."
}

status() {
  fail=0
  curl -sf -m 2 -H "X-Api-Key: pk-local-eval" "http://127.0.0.1:${CLINIC_PORT}/api/v1/directory" >/dev/null \
    && echo "✓ clínica  http://127.0.0.1:${CLINIC_PORT}" || { echo "✗ clínica"; fail=1; }
  curl -sf -m 2 "http://127.0.0.1:${AGENT_PORT}/healthz" >/dev/null \
    && echo "✓ agente   http://127.0.0.1:${AGENT_PORT}/ws" || { echo "✗ agente"; fail=1; }
  curl -sf -m 2 "http://127.0.0.1:${CONSOLE_PORT}/api/profiles" >/dev/null \
    && echo "✓ consola  http://127.0.0.1:${CONSOLE_PORT}" || { echo "✗ consola"; fail=1; }
  return $fail
}

case "${1:-start}" in
  start)  start ;;
  stop)   stop ;;
  status) status ;;
  *) echo "uso: ./demo-lab.sh [start|stop|status]"; exit 2 ;;
esac
