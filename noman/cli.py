"""Command line: `no-man run --model openai:gpt-4o-mini`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .cases import CATEGORIES, load_cases
from .guard import GuardedModel
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


def format_comparison(plain: RunResult, guarded: RunResult) -> str:
    def show(score):
        return "-" if score is None else f"{score:.1f}"

    lines = [
        "",
        f"Without the guard vs with the guard ({plain.model})",
        "",
        f"{'Test':<14}{'Without':>9}{'With':>8}{'Change':>9}",
    ]
    for category in [None, *plain.counts()]:
        before, after = plain.score(category), guarded.score(category)
        change = "-" if before is None or after is None else f"{after - before:+.1f}"
        lines.append(f"{category or 'OVERALL':<14}{show(before):>9}{show(after):>8}{change:>9}")
    return "\n".join(lines)


def _add_common_args(command: argparse.ArgumentParser) -> None:
    command.add_argument("--model", required=True, help='Model to test, e.g. "openai:gpt-4o-mini"')
    command.add_argument("--judge", help="Model that grades the answers (defaults to the tested model)")
    command.add_argument("--reviewer", help="Model the guard uses to review replies (defaults to the tested model)")
    command.add_argument("--category", choices=list(CATEGORIES), help="Only run one kind of test")
    command.add_argument("--cases", help="Path to your own cases.json")
    command.add_argument("--limit", type=int, help="Only run the first N cases")
    command.add_argument("--out", help="Save the full results to this JSON file")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="no-man", description="Test whether an AI model is a yes man.")
    parser.add_argument("--version", action="version", version=f"no-man {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    run_cmd = commands.add_parser("run", help="Run the tests against a model")
    _add_common_args(run_cmd)
    run_cmd.add_argument("--guard", action="store_true", help="Wrap the model in the No-Man guard")

    compare_cmd = commands.add_parser("compare", help="Score a model with and without the guard")
    _add_common_args(compare_cmd)

    commands.add_parser("list", help="List the built-in test cases")

    args = parser.parse_args(argv)

    if args.command == "list":
        for case in load_cases():
            print(f"{case.category:<12} {case.id:<18} {case.turns[0][:70]}")
        return 0

    cases = load_cases(args.cases, args.category)[: args.limit]
    model = load_model(args.model)
    judge_model = load_model(args.judge) if args.judge else model
    reviewer = load_model(args.reviewer) if args.reviewer else model
    try:
        for m in (model, judge_model, reviewer):
            m.check()
    except RuntimeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    if args.command == "compare":
        print(f"Testing {model.name} on {len(cases)} cases, without the guard (judge: {judge_model.name})")
        plain = run(model, judge_model, cases, on_result=_print_progress)
        guarded_model = GuardedModel(model, reviewer)
        print(f"\nTesting {guarded_model.name} on {len(cases)} cases")
        guarded = run(guarded_model, judge_model, cases, on_result=_print_progress)
        print(format_comparison(plain, guarded))
        print(f"\nThe guard's review step sent {guarded_model.retries_used} replies back to be rewritten.")
        if args.out:
            Path(args.out).write_text(json.dumps({"without_guard": plain.to_dict(), "with_guard": guarded.to_dict()}, indent=2))
            print(f"Full results saved to {args.out}")
        return 0

    if args.guard:
        model = GuardedModel(model, reviewer)
    print(f"Testing {model.name} on {len(cases)} cases (judge: {judge_model.name})")
    result = run(model, judge_model, cases, on_result=_print_progress)
    print(format_summary(result))
    if args.out:
        Path(args.out).write_text(json.dumps(result.to_dict(), indent=2))
        print(f"\nFull results saved to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
