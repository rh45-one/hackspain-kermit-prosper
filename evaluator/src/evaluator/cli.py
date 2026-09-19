"""CLI: `python -m evaluator.cli <command>`.

Commands:
    clinic    serve the local clinic + submission receiver
    double    serve the test-double agent
    run       execute an experiment config end to end
    chat      manual tester against a live agent, typing turns by hand
    score     score a recorded submission file against a scenario, offline
    validate  check that scenarios resolve against the clinic fixture
    diff      compare two run directories
    compare   side-by-side of every candidate inside one run
"""
from __future__ import annotations

import argparse
import json
import sys


def main() -> None:
    parser = argparse.ArgumentParser(prog="evaluator")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("clinic", help="local clinic + submission receiver")
    p.add_argument("--dataset", required=True)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=18090)
    p.add_argument("--api-key", default="pk-local-eval")

    p = sub.add_parser("double", help="test-double agent (evaluator self-check)")
    p.add_argument("--submit-base", required=True, help="clinic base URL, e.g. http://localhost:18090")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=18770)
    p.add_argument("--api-key", default="pk-local-eval")

    p = sub.add_parser("run", help="run an experiment")
    p.add_argument("--config", required=True)
    p.add_argument("--out", default=None, help="results root (default: <config dir>/results)")

    p = sub.add_parser("score", help="score a submissions file against a scenario")
    p.add_argument("--scenario", required=True)
    p.add_argument("--record", required=True, help="JSON file: list of action dicts")

    p = sub.add_parser("validate", help="check scenarios resolve against the fixture")
    p.add_argument("--dataset", required=True)
    p.add_argument("--scenarios", nargs="+", required=True, help="YAML paths or globs")

    p = sub.add_parser("diff", help="compare two run directories (A -> B)")
    p.add_argument("run_a", help="results dir of run A (the baseline)")
    p.add_argument("run_b", help="results dir of run B (the candidate)")
    p.add_argument("--json", action="store_true", help="emit machine-readable diff")

    p = sub.add_parser("compare", help="side-by-side of every candidate inside one run")
    p.add_argument("run", help="results dir of the run")
    p.add_argument("--json", action="store_true", help="emit the machine-readable summary")

    p = sub.add_parser("chat", help="manual tester: type to a live agent and read its replies")
    p.add_argument("--ws-url", default="ws://127.0.0.1:17860/ws", help="agent websocket")
    p.add_argument("--clinic-url", default="http://127.0.0.1:18090", help="local clinic")
    p.add_argument("--api-key", default="pk-local-eval")
    p.add_argument("--call-id", default=None, help="default: tester-<random>")
    p.add_argument("--from-number", default=None)
    p.add_argument("--tts", default="espeak-ng", help="espeak-ng | pico2wave")
    p.add_argument("--lang", default="es")
    p.add_argument(
        "--stt",
        default=None,
        help="override EVALUATOR_STT_PROVIDER (deepgram | openai-compat | none)",
    )
    p.add_argument("--scenario", default=None, help="score the recorded call at the end")
    p.add_argument(
        "--agent-audit-dir",
        default=None,
        help="the agent's DATA_DIR or its calls/ dir, to check whether it heard the caller",
    )
    p.add_argument("--save-dir", default=None, help="where WAV evidence goes")
    p.add_argument("--reply-idle-ms", type=float, default=900.0, help="silence that ends a reply")
    p.add_argument("--reply-max-ms", type=float, default=20000.0, help="longest reply to wait for")
    p.add_argument(
        "--reply-start-ms",
        type=float,
        default=6000.0,
        help="how long a reply may take to start (thinking + tools)",
    )
    p.add_argument(
        "--greeting-wait-ms",
        type=float,
        default=20000.0,
        help="how long to wait for the greeting before the caller may speak",
    )
    p.add_argument(
        "--turn-tail-ms",
        type=float,
        default=600.0,
        help="caller silence after each typed turn, so the agent closes the turn",
    )
    p.add_argument("--no-greeting", action="store_true", help="do not wait for the agent's greeting")

    args = parser.parse_args()

    if args.cmd == "clinic":
        from evaluator.clinic.server import serve

        serve(args.dataset, host=args.host, port=args.port, api_key=args.api_key)
    elif args.cmd == "double":
        from evaluator.harness.double_agent import serve

        serve(args.submit_base, host=args.host, port=args.port, api_key=args.api_key)
    elif args.cmd == "run":
        from evaluator.runner.experiment import run_experiment

        out = run_experiment(args.config, args.out)
        print(f"results: {out}")
        print(f"report:  {out}/report.html")
    elif args.cmd == "score":
        from evaluator.compare import compare
        from evaluator.models import Scenario

        scenario = Scenario.load(args.scenario)
        with open(args.record, encoding="utf-8") as fh:
            record = json.load(fh)
        cmp = compare(record, scenario.accepted_outcomes)
        verdict = {
            "passed": cmp.passed,
            "failure_signal": cmp.failure_signal,
            "matched_outcome": cmp.matched_outcome,
            "field_diffs": [d.model_dump() for d in cmp.field_diffs],
        }
        json.dump(verdict, sys.stdout, indent=2)
        print()
    elif args.cmd == "validate":
        import glob

        from evaluator.clinic.dataset import Dataset
        from evaluator.models import Scenario
        from evaluator.runner.experiment import validate_scenario

        dataset = Dataset.load(args.dataset)
        bad = 0
        for pattern in args.scenarios:
            for path in sorted(glob.glob(pattern, recursive=True)):
                scenario = Scenario.load(path)
                problems = validate_scenario(scenario, dataset)
                if problems:
                    bad += 1
                    print(f"{scenario.id}: INVALIDO")
                    for p in problems:
                        print(f"  - {p}")
                else:
                    print(f"{scenario.id}: ok")
        sys.exit(1 if bad else 0)
    elif args.cmd == "diff":
        from evaluator.report.diff import diff_runs, format_diff

        result = diff_runs(args.run_a, args.run_b)
        if args.json:
            import dataclasses

            json.dump(dataclasses.asdict(result), sys.stdout, indent=2, default=str)
            print()
        else:
            print(format_diff(result))
    elif args.cmd == "compare":
        from evaluator.report.side_by_side import (
            format_side_by_side,
            side_by_side,
            side_by_side_json,
        )

        result = side_by_side(args.run)
        print(side_by_side_json(result) if args.json else format_side_by_side(result))
    elif args.cmd == "chat":
        import asyncio

        from evaluator.tester import ChatOptions, run_chat

        options = ChatOptions(
            ws_url=args.ws_url,
            clinic_url=args.clinic_url,
            api_key=args.api_key,
            from_number=args.from_number,
            tts=args.tts,
            lang=args.lang,
            stt_provider=args.stt,
            scenario=args.scenario,
            save_dir=args.save_dir,
            agent_audit_dir=args.agent_audit_dir,
            reply_idle_ms=args.reply_idle_ms,
            reply_max_ms=args.reply_max_ms,
            reply_start_ms=args.reply_start_ms,
            greeting_wait_ms=args.greeting_wait_ms,
            turn_tail_ms=args.turn_tail_ms,
            greet_first=not args.no_greeting,
        )
        if args.call_id:
            options.call_id = args.call_id
        sys.exit(asyncio.run(run_chat(options)))


if __name__ == "__main__":
    main()
