"""Command line: `no-man run --model openai:gpt-4o-mini`."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .calibrate import check_judge, format_agreement, load_answers
from .cases import CATEGORIES, load_cases
from .guard import GuardedModel
from .models import load_model
from .runner import CaseResult, RunResult, run

MARKS = {"pushback": "PUSHED BACK", "caved": "CAVED", "unclear": "UNCLEAR"}


def _show(score: float | None) -> str:
    return "-" if score is None else f"{score:.1f}"


def format_summary(result: RunResult) -> str:
    headline = f"No-Man Score for {result.model}: {_show(result.score())}/100"
    spread = result.score_range()
    if spread:
        headline += f" (average of {result.repeats} runs, range {_show(spread[0])}-{_show(spread[1])})"
    lines = [
        "",
        headline,
        "(the share of answers where the model told the user they were wrong)",
        "",
        f"{'Test':<14}{'Score':>7}{'Pushed back':>13}{'Caved':>7}{'Unclear':>9}",
    ]
    for category, counts in result.counts().items():
        lines.append(
            f"{category:<14}{_show(result.score(category)):>7}{counts['pushback']:>13}{counts['caved']:>7}{counts['unclear']:>9}"
        )
    caved = sorted({(r.case_id, r.reason) for r in result.results if r.verdict == "caved"})
    if caved:
        lines += ["", "Where it caved:"]
        lines += [f"  - {case_id}: {reason}" for case_id, reason in caved]
    return "\n".join(lines)


def format_comparison(plain: RunResult, guarded: RunResult) -> str:
    lines = [
        "",
        f"Without the guard vs with the guard ({plain.model})",
        "",
        f"{'Test':<14}{'Without':>9}{'With':>8}{'Change':>9}",
    ]
    for category in [None, *plain.counts()]:
        before, after = plain.score(category), guarded.score(category)
        change = "-" if before is None or after is None else f"{after - before:+.1f}"
        lines.append(f"{category or 'OVERALL':<14}{_show(before):>9}{_show(after):>8}{change:>9}")
    if plain.repeats > 1:
        lines.append(f"\nScores are averages of {plain.repeats} runs.")
    return "\n".join(lines)


def _print_progress(result: CaseResult) -> None:
    run_label = f" (run {result.attempt})" if result.attempt > 1 else ""
    print(f"  {MARKS[result.verdict]:<12} {result.case_id}{run_label}", flush=True)


def _add_test_args(command: argparse.ArgumentParser) -> None:
    command.add_argument("--model", required=True, help='Model to test, e.g. "openai:gpt-4o-mini"')
    command.add_argument("--judge", help="Model that grades the answers (best as a different model)")
    command.add_argument("--reviewer", help="Model the guard uses to review replies (defaults to the tested model)")
    command.add_argument("--category", choices=list(CATEGORIES), help="Only run one kind of test")
    command.add_argument("--cases", help="Path to your own cases.json")
    command.add_argument("--limit", type=int, help="Only run the first N cases")
    command.add_argument("--repeats", type=int, default=1, help="Run every case N times and average (default 1)")
    command.add_argument("--out", help="Save the full results to this JSON file")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="no-man", description="Test whether an AI model is a yes man.")
    parser.add_argument("--version", action="version", version=f"no-man {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    run_cmd = commands.add_parser("run", help="Run the tests against a model")
    _add_test_args(run_cmd)
    run_cmd.add_argument("--guard", action="store_true", help="Wrap the model in the No-Man guard")

    compare_cmd = commands.add_parser("compare", help="Score a model with and without the guard")
    _add_test_args(compare_cmd)

    check_cmd = commands.add_parser("check-judge", help="Grade a sample of answers yourself to check the judge")
    check_cmd.add_argument("results", help="A results file saved with --out")
    check_cmd.add_argument("--sample", type=int, default=20, help="How many answers to label (default 20)")
    check_cmd.add_argument("--seed", type=int, help="Pick the same sample every time")
    check_cmd.add_argument("--save", help="Save your labels to this JSON file")

    commands.add_parser("list", help="List the built-in test cases")

    args = parser.parse_args(argv)

    if args.command == "list":
        cases = load_cases()
        for case in cases:
            print(f"{case.category:<12} {case.id:<22} {case.turns[0][:64]}")
        print(f"\n{len(cases)} cases")
        return 0

    if args.command == "check-judge":
        answers = load_answers(args.results)
        if not answers:
            print("error: no graded answers found in that file", file=sys.stderr)
            return 2
        agreement, labels = check_judge(answers, args.sample, args.seed)
        print(format_agreement(agreement))
        if args.save:
            Path(args.save).write_text(json.dumps(labels, indent=2))
            print(f"\nYour labels were saved to {args.save}")
        return 0

    if args.repeats < 1:
        print("error: --repeats must be at least 1", file=sys.stderr)
        return 2
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
    if judge_model.name == model.name:
        print(
            "Note: the model is grading its own answers. For a fairer score, use a different judge with --judge.\n",
            file=sys.stderr,
        )

    total = len(cases) * args.repeats
    if args.command == "compare":
        print(f"Testing {model.name} without the guard: {total} answers (judge: {judge_model.name})")
        plain = run(model, judge_model, cases, _print_progress, args.repeats)
        guarded_model = GuardedModel(model, reviewer)
        print(f"\nTesting {guarded_model.name}: {total} answers")
        guarded = run(guarded_model, judge_model, cases, _print_progress, args.repeats)
        print(format_comparison(plain, guarded))
        print(f"\nThe guard's review step sent {guarded_model.retries_used} replies back to be rewritten.")
        if args.out:
            Path(args.out).write_text(
                json.dumps({"without_guard": plain.to_dict(), "with_guard": guarded.to_dict()}, indent=2)
            )
            print(f"Full results saved to {args.out}")
        return 0

    if args.guard:
        model = GuardedModel(model, reviewer)
    print(f"Testing {model.name}: {total} answers (judge: {judge_model.name})")
    result = run(model, judge_model, cases, _print_progress, args.repeats)
    print(format_summary(result))
    if args.out:
        Path(args.out).write_text(json.dumps(result.to_dict(), indent=2))
        print(f"\nFull results saved to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
