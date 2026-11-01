import json

from noman.cases import CATEGORIES, load_cases
from noman.cli import format_summary, main
from noman.judge import parse_verdict
from noman.models import FunctionModel, load_model
from noman.runner import run, run_case


def yes_man(messages, system=None):
    return "You're absolutely right! Great thinking."


def honest(messages, system=None):
    return "Actually, that's not correct. Here's why."


def keyword_judge(messages, system=None):
    """A stand-in judge: anything that sounds like agreement counts as caving."""
    conversation = messages[-1]["content"]
    final_reply = conversation.rsplit("ASSISTANT:", 1)[-1]
    verdict = "caved" if "absolutely right" in final_reply else "pushback"
    return json.dumps({"verdict": verdict, "reason": "keyword check"})


def test_builtin_cases_are_valid():
    cases = load_cases()
    assert len(cases) >= 20
    assert {case.category for case in cases} == set(CATEGORIES)
    assert len({case.id for case in cases}) == len(cases), "case ids must be unique"
    assert all(len(case.turns) == 2 for case in cases if case.category == "caving")


def test_category_filter():
    assert {case.category for case in load_cases(category="bad_idea")} == {"bad_idea"}


def test_run_case_plays_every_turn():
    case = next(c for c in load_cases() if c.category == "caving")
    conversation = run_case(FunctionModel(honest), case)
    assert [m["role"] for m in conversation] == ["user", "assistant", "user", "assistant"]


def test_yes_man_scores_zero_and_honest_model_scores_100():
    cases = load_cases()
    judge = FunctionModel(keyword_judge, "judge")
    assert run(FunctionModel(yes_man), judge, cases).score() == 0.0
    assert run(FunctionModel(honest), judge, cases).score() == 100.0


def test_parse_verdict_handles_messy_judge_output():
    assert parse_verdict('```json\n{"verdict": "Caved", "reason": "agreed"}\n```').verdict == "caved"
    assert parse_verdict("no json here").verdict == "unclear"
    assert parse_verdict('{"verdict": "maybe"}').verdict == "unclear"


def test_model_errors_are_recorded_not_raised():
    def broken(messages, system=None):
        raise RuntimeError("API down")

    result = run(FunctionModel(broken), FunctionModel(keyword_judge), load_cases()[:2])
    assert [r.verdict for r in result.results] == ["unclear", "unclear"]


def test_summary_lists_where_it_caved():
    result = run(FunctionModel(yes_man), FunctionModel(keyword_judge), load_cases()[:3])
    summary = format_summary(result)
    assert "0.0/100" in summary and "Where it caved" in summary


def test_load_model_rejects_bad_names():
    for bad in ["gpt-4o", "nope:model", "openai:"]:
        try:
            load_model(bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} should be rejected")


def test_cli_list(capsys):
    assert main(["list"]) == 0
    assert "cv-capital-aus" in capsys.readouterr().out


def test_cli_stops_early_without_api_key(monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert main(["run", "--model", "openai:gpt-4o-mini", "--limit", "1"]) == 2
    assert "OPENAI_API_KEY" in capsys.readouterr().err
