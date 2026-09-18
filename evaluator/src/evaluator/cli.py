"""CLI: `python -m evaluator.cli <command>`.

Commands:
    clinic    serve the local clinic + submission receiver
    double    serve the test-double agent
    run       execute an experiment config end to end
    score     score a recorded submission file against a scenario, offline
    validate  check that scenarios resolve against the clinic fixture
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
    p.add_argument("--port", type=int, default=8090)
    p.add_argument("--api-key", default="pk-local-eval")

    p = sub.add_parser("double", help="test-double agent (evaluator self-check)")
    p.add_argument("--submit-base", required=True, help="clinic base URL, e.g. http://localhost:8090")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=7870)
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


if __name__ == "__main__":
    main()
