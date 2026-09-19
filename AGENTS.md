# Prosper evaluation context

- Read `integration/HANDOFF.md` and `integration/INCIDENT-2026-09-19.md` before touching a live runtime. Worktrees do not inherit ignored credentials, call audits, dependencies or running processes.
- Prosper has one active-run slot per team, shared across all worktrees and browsers. Confirm the platform has no active run before changing a shared endpoint; an idle local socket is not sufficient evidence.
- The practice panel's endpoint override applies only to its Call buttons. Run All always uses the endpoint saved in Settings.
- A second named tunnel on the same ngrok account can return the existing public hostname. Check that an experimental endpoint is actually distinct before treating it as isolated.
- Live scoring documentation checked on 2026-09-19 uses `sum(passed cases * problem weight)`, with 196 points for the full roster. The checked-in scoring notes and local evaluator may describe older rules; verify current official rules before equating local and official points.
- The official specialties API checked on 2026-09-19 has `physiotherapy.referral_required=true`. Local seed-v1 has it false. Use the configured clinic's catalogue and availability restrictions rather than assuming the local fixture matches production.
- An accepted submission or an action queued locally is not an official pass. Check the team's final case verdict. Compare official recordings with transcripts and wire metrics when investigating silence; local text or serialized audio alone does not prove remote recognition.
- Verification commands are in the root Makefile. For backend-only changes, run `uv run --project backend --frozen pytest -q` and `uv run --project backend --frozen ruff check backend/src backend/tests integration`. Cross-package contracts use `PYTHONPATH=evaluator/src uv run --project backend --frozen pytest integration -q`.
