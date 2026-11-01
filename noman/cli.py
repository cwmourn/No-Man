"""Command line: `no-man run --model openai:gpt-4o-mini`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .cases import CATEGORIES, load_cases
from .models import load_model
from .runner import CaseResult, RunResult, run

MARKS = {"pushback": "PUSHED BACK", "caved": "CAVED", "unclear": "UNCLEAR"}


def format_summary(result: RunResult) -> str:
    lines = [
        "",
        f"No-Man Score for {result.model}: {result.score()}/100",
        "(the share of tests where the model told the user they were wrong)",
        "",
        f"{'Test':<14}{'Score':>7}{'Pushed back':>13}{'Caved':>7}{'Unclear':>9}",
    ]
    for category, counts in result.counts().items():
        lines.append(
            f"{category:<14}{result.score(category):>7}{counts['pushback']:>13}{counts['caved']:>7}{counts['unclear']:>9}"
        )
    caved = [r for r in result.results if r.verdict == "caved"]
    if caved:
        lines += ["", "Where it caved:"]
        lines += [f"  - {r.case_id}: {r.reason}" for r in caved]
    return "\n".join(lines)


def _print_progress(result: CaseResult) -> None:
    print(f"  {MARKS[result.verdict]:<12} {result.case_id}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="no-man", description="Test whether an AI model is a yes man.")
    parser.add_argument("--version", action="version", version=f"no-man {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    run_cmd = commands.add_parser("run", help="Run the tests against a model")
    run_cmd.add_argument("--model", required=True, help='Model to test, e.g. "openai:gpt-4o-mini"')
    run_cmd.add_argument("--judge", help="Model that grades the answers (defaults to the tested model)")
    run_cmd.add_argument("--category", choices=list(CATEGORIES), help="Only run one kind of test")
    run_cmd.add_argument("--cases", help="Path to your own cases.json")
    run_cmd.add_argument("--limit", type=int, help="Only run the first N cases")
    run_cmd.add_argument("--out", help="Save the full results to this JSON file")

    commands.add_parser("list", help="List the built-in test cases")

    args = parser.parse_args(argv)

    if args.command == "list":
        for case in load_cases():
            print(f"{case.category:<12} {case.id:<18} {case.turns[0][:70]}")
        return 0

    cases = load_cases(args.cases, args.category)[: args.limit]
    model = load_model(args.model)
    judge_model = load_model(args.judge) if args.judge else model
    try:
        model.check()
        judge_model.check()
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(f"Testing {model.name} on {len(cases)} cases (judge: {judge_model.name})")
    result = run(model, judge_model, cases, on_result=_print_progress)
    print(format_summary(result))
    if args.out:
        Path(args.out).write_text(json.dumps(result.to_dict(), indent=2))
        print(f"\nFull results saved to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
