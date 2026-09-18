# Model selection — Pi coding workers and the Prosper clinic voice agent

Status: decision-ready deep dive. Author: pi-senior-engineer (Orca worker).
Evidence access date: **2026-09-18** (Europe/Madrid). All external figures were
read on that date; anything that moves (pricing, rate limits, model ids) is
stamped with the URL that published it.

Scope: two independent decisions.

- **(A) Pi coding workers** — which Helmcode model a Pi agent should run while
  building this repo. Constraint: only Helmcode models are allowed.
- **(B) Production voice LLM** — which model/provider the real-time clinic
  voice agent (`backend/src/agent/voice/pipeline.py`) should call at run time.

This document is the only artifact produced. No backend, OpenSpec or other file
was edited; no commits, pushes or production writes were made.

## 0. Evidence standard and trust note

Every claim below is labelled with how it was obtained:

| Label | Meaning |
|---|---|
| `[official]` | Read from the provider's own docs/pricing pages on 2026-09-18. URL listed in the source ledger. |
| `[local]` | Read from this machine: repository code or `~/.pi/agent/*`. |
| `[aggregator]` | Read from OpenRouter's public model API (a reseller/aggregator, not the model owner). Used only where an official number was unavailable. |
| `[project]` | Stated in this repo's OpenSpec/README context; not externally verifiable. |
| `[unverified]` | Not verifiable from the environment or an official source. Explicitly flagged as unknown, never guessed. |

No benchmark number in this document was invented. The only index figures cited
are those Helmcode publishes (secondary source) plus Artificial Analysis as
named by Helmcode; they are not re-derived here.

All web content was treated as untrusted data. No instruction found in a fetched
page was executed. No secret, API key or credential appears in this document or
was printed to the terminal.

## 1. Ranked summary (the answer, before the evidence)

### Part A — Pi coding workers (Helmcode only)

| Rank | Model id | Role | Verdict |
|---|---|---|---|
| 1 | `deepseek-v4-flash` | default for high-volume implementation workers | plan-covered, 1M ctx, native tool calling, 284B MoE / 21B active; cheapest way to run many parallel Pi workers |
| 2 | `glm5.3` | escalation for hard reasoning sessions | strongest open model Helmcode serves (744B MoE / 40B active), controllable reasoning low..max; costlier (per-key add-on) |

Recommendation A: run `deepseek-v4-flash` as the default Pi worker model; open a
`glm5.3` session for architecture, cross-repo debugging or plan review where the
capability gap pays. Both are already reachable (this Pi session itself is
`PI_PROVIDER=helmcode`, `PI_MODEL=deepseek-v4-flash` `[local]`).

### Part B — Production voice LLM

Recommendation B (the firm pair):

- **Primary: Helmcode `glm5.3`, pinned id `glm5.3`, via
  `https://api.helmcode.com/v1`, with `reasoning_effort: "low"`.**
- **Fallback: Helmcode `deepseek-v4-flash`, pinned id `deepseek-v4-flash`,
  via the same endpoint.**

Rationale in one line: `glm5.3` is the only EU-hosted candidate with explicit
reasoning-effort control *down to a low setting* (which is what bounds p95 TTFT
for spoken turns) combined with the strongest tool calling and multilingual
instruction following Helmcode serves; `deepseek-v4-flash` is the plan-covered,
native-tool-calling fallback already wired as the code default.

**Decision gate (explicit):** Helmcode publishes `glm5.3` as a
€150-per-key-per-month add-on that "no plan covers" `[official]`, while this
repo's OpenSpec claims a "600M tokens paid by Helmcode perk" covering `glm5.3`
`[project]`. The two are not reconciled anywhere I can verify. If the hackathon
perk does **not** in fact cover the `glm5.3` add-on, the pair becomes:
primary `deepseek-v4-flash`, fallback `qwen3.6` with `reasoning_effort: "none"`.
This must be confirmed at the desk before relying on it.

## 2. What is configured today (facts, `[local]`)

- `backend/src/agent/voice/pipeline.py` builds one `OpenAILLMService`
  (`pipecat-ai 1.11.0`) against `settings.helmcode_base_url` with
  `model=settings.agent_model` and `system_instruction=prompts.SYSTEM_PROMPT`.
- `backend/src/agent/config.py` defaults: `agent_model="deepseek-v4-flash"`,
  `agent_model_fallback="glm5.3"`.
- `backend/.env.example` sets the opposite default:
  `AGENT_MODEL=glm5.3`, `AGENT_MODEL_FALLBACK=deepseek-v4-flash`.
- OpenSpec `config.yaml` says "glm5.3 (default brain), deepseek-v4-flash (fast),
  glm5.3-flash. 600M tokens paid by Helmcode perk" `[project]`; design D2 says
  "Brain = Helmcode glm5.3 ... Fallback chain: deepseek-v4-flash → glm5.3-flash".
- `agent_model_fallback` is **never read anywhere in the code**
  (`grep` across `backend/src` and `backend/tests`). There is no model fallback
  behaviour today.
- No `max_tokens`, `temperature` or `reasoning_effort` is set on the LLM
  service. No LLM-side retry/timeout tuning; pipecat defaults are
  `retry_timeout_secs=5.0`, `retry_on_timeout=False`.
- The first-turn greeting is injected as an `LLMContext` message with
  `role: "developer"` (`pipeline.py`, `on_client_connected`).
- Pi local provider config `~/.pi/agent/models.json` declares provider
  `helmcode`, `api: openai-completions`, base `https://api.helmcode.com/v1`,
  with `compat: {supportsStore:false, supportsDeveloperRole:false,
  supportsStrictMode:false, maxTokensField:"max_tokens"}` and three models:
  `glm5.3`, `qwen3.6`, `deepseek-v4-flash` `[local]`.

Three of those facts are correctness risks, not preferences: an unused
fallback, an unpinned model default that disagrees between code and env, and a
`developer`-role message sent to a provider whose Pi compatibility block says it
does not support that role. They drive the integration section below.

## 3. Part A — Pi coding workers (Helmcode only)

### 3.1 Candidates and capabilities

Only Helmcode models are permitted, so the candidate set is the two ids named in
the task. Capabilities from the local Pi provider config `[local]` and Helmcode
docs `[official]`:

| | `deepseek-v4-flash` | `glm5.3` |
|---|---|---|
| Helmcode id | `deepseek-v4-flash` | `glm5.3` |
| Architecture `[official]` | 284B MoE · 21B active · NVFP4 | 744B MoE · 40B active |
| Context `[official]/[local]` | 1M | 1M (full 1M served per request) |
| Max output `[local]` | 32,768 | 32,768 |
| Licence `[official]` | MIT | Z.ai GLM-5.3 licence |
| Tool calling `[official]` | native | yes |
| Streaming `[official]` | SSE | SSE |
| Reasoning `[official]` | adaptive; `reasoning_effort` accepted but **has no effect** | `low` · `medium` · `high` · `max` |
| Pi thinking map `[local]` | off/minimal/low/medium disabled; effectively high only | low/medium/high/max; off/minimal disabled |
| Pi `supportsReasoningEffort` `[local]` | `false` (model-level compat) | not set (defaults true) |
| Price `[official]` | covered by plan; 5B tokens/mo on Starter counts against it | €150/key/month add-on, own allowance (2B/6.5B/18B by plan) |
| Per-key limits `[official]` | 100 rpm · 10 concurrent · 2M tpm | 100 rpm · 10 concurrent · 3M tpm |
| Input modality `[official]` | text | text only |

### 3.2 Verdict

`glm5.3` is strictly the stronger *reasoning* model: 744B vs 284B parameters,
controllable reasoning depth, and the higher Artificial Analysis composite that
Helmcode publishes (Helmcode reports GLM-5.3 at 60 vs DeepSeek V4 Flash 0731 at
52 on Artificial Analysis Intelligence Index v4.1.1, August 2026 — secondary
source, not re-derived here) `[official]`.

`deepseek-v4-flash` is the better *worker* model for this project: it is
plan-covered rather than a €150/key add-on, it has native tool calling, the same
1M context, and its adaptive reasoning is cheap enough to run many Pi sessions
in parallel. The Pi config cannot turn its thinking fully off (`off`/`low`/
`medium` are `null`), so both models always reason to some degree; that makes the
plan-covered one the rational default for volume.

Firm recommendation A: `deepseek-v4-flash` primary, `glm5.3` escalation. If the
`glm5.3` add-on is already paid for (or granted), invert for the coordinator
worker only — keep implementation workers on `deepseek-v4-flash`.

### 3.3 What is *not* claimed

No tok/s, TTFT or tool-accuracy figure exists for either model from an official
source; I did not fabricate one. See §7.

## 4. Part B — Production real-time voice LLM

### 4.1 Optimisation order (as specified)

1. p95 response / TTFT for spoken turns
2. reliable function/tool calls and schema adherence
3. Spanish and Catalan quality
4. availability under 20 concurrent calls
5. cost

A non-functional constraint sits alongside these: the clinic use case is
healthcare, and Helmcode markets EU-only, zero-log processing for its own
open models, while its resold US frontier models explicitly leave the EU
`[official]`. For a clinic agent, EU data residency outranks a small TTFT win.
This is stated as a constraint, not a measured latency claim.

### 4.2 Candidate evidence table

Pricing is official provider list price, USD per 1M tokens, on 2026-09-18.
"Tools/stream" = native function calling and SSE streaming on the OpenAI-compatible
path.

| Candidate (pinned id) | Provider / surface | In / Out $ per 1M | Context | Tools / stream | Concurrency & rate limits | Source |
|---|---|---|---|---|---|---|
| `glm5.3` | Helmcode (EU) | plan add-on €150/key/mo | 1M | yes / SSE | 100 rpm, 10 concurrent, 3M tpm | `[official]` Helmcode |
| `deepseek-v4-flash` | Helmcode (EU) | plan-covered (5B tok/mo Starter) | 1M | native / SSE | 100 rpm, 10 concurrent, 2M tpm | `[official]` Helmcode |
| `qwen3.6` | Helmcode (EU) | unlimited on any plan | 256K | XML / SSE | 100 rpm, 5 concurrent, 2M tpm | `[official]` Helmcode |
| `gemma4` | Helmcode (EU) | unlimited on any plan | 256K | XML / SSE | 100 rpm, 5 concurrent, 2M tpm | `[official]` Helmcode |
| `gemini-3.5-flash-lite` | Helmcode resale (US) | 0.30 / 2.50 | 1M | yes / SSE | Google project limits + prepaid credit | `[official]` Google |
| `gpt-5.6-luna` | Helmcode resale (US) | 0.20 / 1.20 (short ctx) | 1.05M | yes / SSE | OpenAI org limits + prepaid credit | `[official]` OpenAI |
| `claude-haiku-4-5` | Helmcode resale (US) | 1.00 / 5.00 | varies | yes / SSE | Anthropic org limits + prepaid credit | `[official]` Anthropic |
| `glm-5.3-flash` | Z.ai direct | 0.15 / 0.50 | 1M+ | yes / SSE | per-key limits not published on the pricing page | `[official]` Z.ai |
| `gemini-3.1-flash-lite` | Google direct | 0.25 / 1.50 | 1M | yes / SSE | Google tier limits; Tier-1 spend cap $10 / 10 min | `[official]` Google |
| `deepseek-flash` | DeepSeek direct | 0.15 / 0.60 off-peak; double at peak | 1M | yes / SSE | concurrency 2500 | `[official]` DeepSeek |
| (`deepseek-v4-flash` legacy alias) | DeepSeek direct | same as `deepseek-flash` | 1M | yes / SSE | DeepSeek docs state the legacy ids are served by V4.1-Flash at Flash price | `[official]` DeepSeek |

Notes that matter:

- Helmcode's own catalogue is the only one that keeps everything in the EU for
  its open models; the nine resold frontier models run on US infrastructure
  `[official]`.
- DeepSeek's official pricing page states the live model name is
  `deepseek-flash` and that the legacy names `deepseek-v4-flash` /
  `deepseek-v4-flash-vision-exp` are "still accepted, but the corresponding
  models have been retired, their requests are served by the DeepSeek-V4.1-Flash
  model and billed at the Flash price" `[official]`. Helmcode's catalogue
  separately lists a `deepseek-v4-flash` (284B/21B). The two are not the same
  artifact; do not assume one hot-swaps for the other.
- OpenRouter flags `tools` + `structured_outputs` as supported parameters for
  `z-ai/glm-5.3`, `deepseek/deepseek-v4-flash`, `google/gemini-3.1-flash-lite`
  and `openai/gpt-5.6-luna` `[aggregator]`, consistent with the official docs.

### 4.3 Ranked scorecard

Because p95 TTFT is not published by any provider for any candidate (§7), the
TTFT column is a *prior* from architecture and from whether reasoning can be
capped — not a measurement. The A/B plan in §4.5 exists precisely to replace it
with data. Tool reliability is scored from published capabilities
(native JSON function calling vs XML-style, strict-schema support).

| # | Candidate | p95 TTFT (prior) | Tool/schema | ES/CA | 20 concurrent | Cost for suite | Overall |
|---|---|---|---|---|---|---|---|
| 1 | Helmcode `glm5.3` + effort=low | good — reasoning cap available | strongest; native | strongest of set; full instruction tuning | 10/key; needs 2 seats for 20 | €150/key/mo (perk gate) | **primary** |
| 2 | Helmcode `deepseek-v4-flash` | uncertain — adaptive reasoning, no cap | strong; native | strong | 10/key; needs 2 seats for 20 | plan-covered | **fallback** |
| 3 | Helmcode resale `gemini-3.5-flash-lite` | good — Flash-Lite class | strong; native | good | Google project limits | ~€17 for suite | paid alternative #1 |
| 4 | Helmcode resale `gpt-5.6-luna` | likely good | strong; native | good | OpenAI org limits | ~€10 for suite | paid alternative #2 |
| 5 | Direct Z.ai `glm-5.3-flash` | good — reasoning cap available | good; native | good | not published | ~€7 for suite | cheapest viable cash option |
| 6 | Direct Google `gemini-3.1-flash-lite` | good | strong; native | good | Tier-1 $10/10min spend cap | ~€13 for suite | viable, US |
| 7 | Helmcode `qwen3.6` effort=none | best potential (skips reasoning) | risk — XML tool calling | good | 5/key (worse) | plan-covered | latency panic switch only |
| 8 | Helmcode `gemma4` | good | risk — XML tool calling | good | 5/key | plan-covered | not recommended for tools |
| 9 | Direct DeepSeek `deepseek-flash` | uncertain | strong; native | strong | 2500 | ~€7 for suite | viable cash fallback |
| 10 | Helmcode resale `claude-haiku-4-5` | good | strong; native | strong | Anthropic org limits | ~€48 for suite | 4× the cheap tier |

Why `glm5.3` edges out the cheaper Flash-Lite-class models despite their likely
lower raw latency: it is the only candidate that combines (a) reasoning-effort
control down to `low`, which is the single biggest lever on TTFT tail for a
thinking model, (b) EU-only processing, (c) no second provider integration, and
(d) the strongest tool calling Helmcode serves. Flash-Lite models win on raw
speed but lose on residency and add a resale/credit billing path.

Why `deepseek-v4-flash` is the fallback rather than `qwen3.6`: native JSON tool
calling (the `ToolBox` exposes 12 functions and depends on OpenAI-style function
calls), versus Qwen3.6's published "tool calling (XML)" `[official]` — a
schema-adherence risk not worth taking while the scored suite is binary.

### 4.4 Budget math

Explicit assumptions (all stated so they can be challenged):

- 10 caller turns per call; ~18 LLM requests per call (a mix of tool-call
  round-trips and spoken answers); calls capped at 3 minutes by the harness.
- Overhead per request: system prompt ≈ 600 tokens (`PROMPT_ID
  receptionist-v1`, 2,382 chars measured `[local]`) + tool schemas ≈ 2,400
  tokens (12 tools, 18 docstrings, ~4,850 docstring chars measured `[local]`,
  plus JSON-schema framing).
- Conversation + tool results average ≈ 3,000 tokens per request over the call.
- So ≈ **6,000 input tokens per request**.
- Output per request ≈ 120 spoken tokens + 40 tool-call tokens + 350 reasoning
  tokens ≈ **~470 output tokens per request** (≈8,000 output tokens per call).

Volumes: practice 300 calls + one full scored Run All = 17 problems × 4 private
cases = 68 calls. Total **368 calls**.

| | Light (5k in, 400 out/req) | Expected (6k in, 470 out/req) | Heavy (9k in, 700 out/req) |
|---|---|---|---|
| Input tokens (368 calls) | 33.1M | 39.7M | 59.6M |
| Output tokens | 2.65M | 3.11M | 4.64M |

LLM cost at the expected volume, USD then EUR at the ECB reference rate
0.871 USD→EUR published by Helmcode on 2026-09-17 `[official]`:

| Option | Input $ | Output $ | Total $ | Total € |
|---|---|---|---|---|
| Helmcode `deepseek-v4-flash` (plan-covered; 5B tok/mo Starter) | — | — | 0 incremental | 0 incremental |
| Helmcode `glm5.3` (€150/key/mo add-on) | — | — | — | 150/mo (perk-gated) |
| Z.ai `glm-5.3-flash` ($0.15/$0.50) | 5.96 | 1.56 | 7.52 | 6.55 |
| DeepSeek `deepseek-flash` off-peak ($0.15/$0.60) | 5.96 | 1.87 | 7.83 | 6.82 |
| OpenAI `gpt-5.6-luna` ($0.20/$1.20) | 7.94 | 3.73 | 11.67 | 10.16 |
| Google `gemini-3.1-flash-lite` ($0.25/$1.50) | 9.93 | 4.67 | 14.60 | 12.72 |
| Google `gemini-3.5-flash-lite` ($0.30/$2.50) | 11.91 | 7.78 | 19.69 | 17.15 |
| Anthropic `claude-haiku-4-5` ($1.00/$5.00) | 39.70 | 15.55 | 55.25 | 48.12 |
| Z.ai `glm-5.3` direct ($1.40/$4.40) | 55.58 | 13.68 | 69.26 | 60.33 |
| Google `gemini-3.5-flash` ($1.50/$9.00) | 59.55 | 9.09 | 68.64 | 59.79 |

Every ranked cheap option costs **under €20 of LLM tokens for the entire
weekend**, comfortably inside the €100 desk card. The card is therefore not an
LLM constraint at all under the Helmcode perk; it is an STT/TTS constraint.

Budget envelope for the whole agent (why the LLM is not the risk):

- STT: Deepgram `nova-3` multilingual streaming **$0.0058/min** `[official]`.
  368 calls × ~2.5 min ≈ 920 min ≈ **$5.34**.
- TTS: ElevenLabs `eleven_turbo_v2_5` is credit-based at ~0.5–1 credit per
  character `[official]`. ~1,200 spoken chars/call × 368 ≈ 440k chars ≈
  **~220k credits**, which is between the Creator (121k credits, $22/mo) and
  Pro (600k credits, $99/mo) tiers `[official]`. **TTS dominates the €100.**
- Consequence: the LLM decision should be made on latency, tool reliability and
  language quality — not on token cost. Keep Cartesia as the TTS fallback; it
  protects the budget far more than any LLM swap.

### 4.5 30-minute A/B evaluation plan (current prompts and tools)

Goal: replace the TTFT priors in §4.3 with measured p50/p95, and confirm tool
schema validity and ES/CA behaviour, without touching production prompts.
Use the real `prompts.SYSTEM_PROMPT` and the real `ToolBox.tools()` exactly as
the pipeline builds them.

Fixed corpus (6 calls, run identically per config):

1. `simple_booking` — the baseline.
2. `when_exactly` — relative date ("this coming Thursday").
3. `languages` ES — Spanish caller.
4. `languages` CA — Catalan caller, must pick a Catalan-speaking provider.
5. `triage` red flag — must escalate, book nothing.
6. `adversarial` — must refuse and never read the protected fields.

Instruments (add locally, do not commit unless the project asks):

- TTFT: timestamp the user-turn end (`LLMContextAggregatorPair` user
  aggregator) to the first `TextFrame` emitted by the LLM service, using
  pipecat's `enable_metrics=True` plus a small `TranscriptTap` observer.
  Record per request, compute p50/p95 per config.
- Tool reliability: count per turn (a) valid function call, (b) schema
  violation, (c) unknown tool name, (d) tool returned `error` (the tools already
  reject unknown ids — a nonzero rate is the model's fault, not the tool's).
- Language: does the first assistant turn match the caller's language, and for
  CA does the booked provider satisfy the language constraint?
- Concurrency: one 20-socket burst (problem 2's largest), measuring 429s, drops,
  and p95 TTFT inflation.

Procedure (30 min):

| Window | Action |
|---|---|
| 0–5 min | Config A `deepseek-v4-flash`: run the 6 calls sequentially; capture TTFT + tool metrics + pass/fail. |
| 5–10 min | Config B `glm5.3` + `reasoning_effort: "low"`: repeat identically. |
| 10–18 min | 20-socket burst per config (8 min total), record 429s and p95. |
| 18–27 min | Score the 6 calls per config against the published practice answers; tabulate tool-schema validity and ES/CA pass. |
| 27–30 min | Apply the decision rule. |

Decision rule (in priority order): disqualify any config with tool-schema
validity < 99% or an ES/CA failure; of the survivors pick the lower p95 TTFT;
tie-break on cost. Freeze the winner as `AGENT_MODEL`, the other as
`AGENT_MODEL_FALLBACK`.

This is 6 calls + 40 burst calls per config; at ~2–3 min per call the wall time
is dominated by call length, so a squeezed version can use 3 calls and a
10-socket burst and still be decision-useful.

### 4.6 Integration: can the current pipecat service stay?

**Mostly yes.** `OpenAILLMService` is OpenAI-compatible, Helmcode is
OpenAI-compatible, and pipecat 1.11.0 already supports streaming SSE, function
tools, per-request `max_tokens`, and — critically — a `Settings.extra` dict that
is merged verbatim into the request body
(`base_llm.py`: `params.update(self._settings.extra)`). That `extra` field is
how `reasoning_effort`, `temperature` and any provider-specific knob get in
without forking pipecat.

Documented changes needed (not applied here; backend edits were out of scope):

1. **Bound the reasoning.** Add `extra={"reasoning_effort": "low"}` for
   `glm5.3`. For `deepseek-v4-flash` this is a documented no-op
   `[official]` — the model decides, which is exactly the TTFT-tail risk.
2. **Cap the output.** Set `max_tokens` (Helmcode's `maxTokensField` is
   `max_tokens` per Pi compat `[local]`), e.g. 256 for spoken turns; and set a
   low `temperature` (0.2–0.4) because the tools, not the model, make decisions.
3. **Fix the `developer` role risk.** The pipeline injects
   `{"role": "developer", ...}` for the greeting. Pi's local Helmcode compat
   declares `supportsDeveloperRole: false` `[local]`, but
   `OpenAILLMService.supports_developer_role` defaults to `True`
   (`base_llm.py`) `[local]`, so the message is sent as `developer`. Either
   subclass with `supports_developer_role = False`, or change the greeting to
   `role: "system"`. Verify against the live Helmcode API either way — this is a
   local-config claim, not a Helmcode-docs claim.
4. **Make the fallback real.** `agent_model_fallback` is dead config and
   pipecat 1.11.0 ships no fallback LLM service (`find pipecat -iname
   '*fallback*'` returns nothing `[local]`). A small wrapper is required: retry
   the primary once with backoff, then re-issue the same request against the
   fallback model on 429/5xx/first-token timeout.
5. **Tune timeouts and retries.** pipecat defaults are
   `retry_timeout_secs=5.0`, `retry_on_timeout=False` `[local]`. For spoken
   turns set ~2.5 s and enable the timeout retry, and set the OpenAI SDK
   `max_retries` (default 2) with backoff; Helmcode returns `Retry-After` on 429
   `[official]`.
6. **Handle concurrency.** One Helmcode key allows **10** concurrent requests
   for `glm5.3` and `deepseek-v4-flash`, and 5 for the other plan models
   `[official]`. Run All opens 10 sockets and the largest burst opens 20. Either
   use a consolidated key — Helmcode states "Consolidated keys multiply every
   limit above by the number of seats on the key" `[official]` — or put a
   bounded semaphore in front of the LLM service. Note the burst is diagnostic
   and unscored; Run All at 10 concurrent is exactly at the single-key limit,
   so headroom is zero and a second seat is the safe choice.
7. **Pin the model default.** `config.py` and `.env.example` disagree; make one
   the source of truth and set it explicitly for the run.

### 4.7 Fallback and rollback

- Runtime fallback (recommended pair): primary `glm5.3` @ effort=low →
  fallback `deepseek-v4-flash` on 429/5xx/first-token timeout.
- Panic switch if both Helmcode models are slow under 20 sockets: `qwen3.6` @
  `reasoning_effort: "none"` (skips the reasoning phase entirely `[official]`).
  Accept the XML-tool-calling risk only while debugging, not for a scored run.
- Cash fallback if Helmcode is unavailable: Z.ai `glm-5.3-flash`
  (OpenAI-compatible, native tools, €6.55 of tokens for the suite) or DeepSeek
  `deepseek-flash`.
- Rollback: the entire change is configuration + an `extra` dict + a wrapper.
  Reverting is setting `AGENT_MODEL` back and removing the wrapper; the backend
  baseline commit (`5f4b2a1`, local `git log`) is untouched and remains the
  rollback point. No schema, prompt or data migration is involved.

### 4.8 Explicit unknowns

- **p95 TTFT / throughput for every candidate.** Not published by Helmcode,
  DeepSeek, Z.ai, Google or OpenAI on the pages read. OpenRouter exposes
  `latency_last_30m` / `throughput_last_30m` fields but they were `null` for the
  candidates queried `[aggregator]`. §4.5 measures it.
- **Whether the 600M-token perk covers the `glm5.3` add-on.**
  `[project]` vs `[official]` conflict, §1. Decision gate.
- **Which artifact Helmcode's `deepseek-v4-flash` is** (284B vs the 552B
  DeepSeek V4.1 Flash, which DeepSeek bills at the Flash price). Not resolvable
  from the pages read.
- **Helmcode `supportsDeveloperRole`** — comes from Pi's local config, not from
  Helmcode's docs.
- **Catalan quality per model.** No public evaluation; the tool layer enforces
  the language constraint, but the spoken quality must be judged by a human on
  the CA practice case.
- **Strict JSON-schema tool mode.** Pi compat declares
  `supportsStrictMode: false` for Helmcode `[local]`; the tools are regular
  function schemas, so schema adherence is empirical, not guaranteed.
- **Z.ai / Groq / Cerebras per-model concurrency.** Not on the pages read.
- **Google per-model RPM/TPM** are only shown in AI Studio; the docs state
  limits vary by model and tier, with a Tier-1 spend cap of **$10 per rolling
  10 minutes** `[official]`.
- **Exact STT/TTS spend** depends on call length and spoken characters, which
  the harness does not publish in advance.

## 5. Source ledger (accessed 2026-09-18)

Official provider sources:

- Helmcode models: https://helmcode.com/docs/models
- Helmcode rate limits: https://helmcode.com/docs/rate-limits
- Helmcode credits/pricing model: https://helmcode.com/docs/credits
- Helmcode plan pricing: https://helmcode.com/pricing
- Helmcode model catalogue: https://helmcode.com/models
- DeepSeek pricing: https://api-docs.deepseek.com/quick_start/pricing
- Z.ai pricing: https://docs.z.ai/guides/overview/pricing
- Google Gemini pricing: https://ai.google.dev/gemini-api/docs/pricing
- Google Gemini rate limits: https://ai.google.dev/gemini-api/docs/rate-limits
- OpenAI pricing: https://platform.openai.com/docs/pricing
- Anthropic pricing: https://platform.claude.com/docs/en/about-claude/pricing
- Deepgram pricing: https://deepgram.com/pricing
- ElevenLabs pricing: https://elevenlabs.io/pricing

Aggregator (secondary, labelled where used):

- OpenRouter models API: https://openrouter.ai/api/v1/models
  and https://openrouter.ai/api/v1/models/{author}/{slug}/endpoints

Local sources:

- Repository: `backend/src/agent/voice/pipeline.py`,
  `backend/src/agent/brain/{prompts,tools,deps}.py`,
  `backend/src/agent/config.py`, `backend/.env.example`,
  `openspec/config.yaml`, `openspec/changes/add-prosper-voice-agent/design.md`,
  `docs/prosper/{overview,problems,scoring,call-contract}.md`.
- Pi: `/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent/docs/models.md`
  and `providers.md`; `~/.pi/agent/models.json`.
- Installed runtime: `pipecat-ai 1.11.0`
  (`pipecat/services/openai/base_llm.py`, `.../openai/llm.py`).

## 6. Definition-of-done check against the task

| Acceptance item | Where |
|---|---|
| Ranked scorecard | §1, §4.3 |
| Official-source evidence | §4.2, §5 |
| Budget math with token/turn assumptions | §4.4 |
| Latency / tool-reliability evaluation method | §4.5 |
| Firm recommendation, primary + fallback, pinned ids | §1, §4.3 |
| Timeout / retry / output limits | §4.6 items 1–2, 5 |
| Fallback / rollback | §4.7 |
| Explicit unknowns | §4.8 |
| Pi coding worker comparison | §3 |
| Integration assessment | §4.6 |

## 7. Open questions for the coordinator

1. Does the HackSpain Helmcode perk cover the `glm5.3` add-on? This flips the
   primary/fallback pair. (§1)
2. Do we hold one Helmcode seat or a consolidated key? Zero headroom at 10
   concurrent for a scored Run All. (§4.6 item 6)
3. Is a second provider integration acceptable for the cash fallback, or must
   everything stay on the Helmcode key for EU residency? (§4.3, §4.7)
