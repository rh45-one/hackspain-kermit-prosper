# Backend verification

- Run backend tests from the repository root with `uv run --project backend pytest -q`; lint with `uv run --project backend ruff check backend/src backend/tests`.
- Outbound telephony packets use 20 ms: `audio_out_10ms_chunks=2` produces 160-byte 8 kHz mu-law payloads. The transport regression test is in `backend/tests/test_voice_serializer.py`. Packet size alone does not resolve every silence failure: also verify that speech resumes after caller interruptions.
- Registration is two-phase: `register_new_patient` prepares a read-back, then queues the unchanged data only with `caller_confirmed=True` after a subsequent caller transcript. Changed data requires a fresh confirmation; never read the national ID or phone aloud.
- Public practice results do not earn leaderboard points. Check the live dashboard's current scoring cooldown; the event settings can change and older documentation may be stale.
- Call transcripts, recordings and dotenv files contain sensitive data and must remain untracked. Never place published case answers in the runtime or use them to fill missing caller data.

# Evaluator verification

- Run `uv run --project evaluator --locked pytest -c evaluator/pyproject.toml evaluator/tests -q` and `uv run --project evaluator --locked ruff check evaluator/src evaluator/tests` from the repository root. Browser contract/worklet tests run with `node --test evaluator/tests/web.test.cjs` and are also invoked by pytest when Node.js is available.
- Cascade and Gemini laboratory profiles use separate voice ports, 17860 and 17862. Laboratory calls verify `/lab/identity` (requires `TURNS_ADAPTER=1`); experiment jobs reuse only a local clinic whose authenticated `/eval/identity` matches the fixture. Restart outdated laboratory processes explicitly; never stop or reuse an unknown process to pass preflight.
- Node contract tests exercise JavaScript and synthetic audio, not real microphone permissions, browser audio routing, or provider turn-taking. A physical microphone call remains a separate acceptance check.
