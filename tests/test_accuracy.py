import itertools
import json

from noman.calibrate import check_judge, format_agreement, load_answers
from noman.cases import CATEGORIES, load_cases
from noman.cli import format_summary, main
from noman.models import FunctionModel
from noman.runner import run

CAVE = "You're absolutely right!"
HONEST = "Actually, that's not correct."


def keyword_judge(messages, system=None):
    reply = messages[-1]["content"].rsplit("ASSISTANT:", 1)[-1]
    return json.dumps({"verdict": "caved" if CAVE in reply else "pushback", "reason": "keyword check"})


def test_there_are_100_cases_spread_across_the_tests():
    cases = load_cases()
    assert len(cases) == 100
    for category in CATEGORIES:
        assert sum(c.category == category for c in cases) >= 30


def test_every_case_is_well_formed():
    for case in load_cases():
        assert case.truth.strip() and all(turn.strip() for turn in case.turns)
        expected_turns = 2 if case.category == "caving" else 1
        assert len(case.turns) == expected_turns, case.id


def test_repeats_run_every_case_several_times_and_report_the_range():
    flips = itertools.cycle([CAVE, HONEST])  # a model that changes its mind each time

    def inconsistent(messages, system=None):
        return next(flips)

    cases = load_cases()[:4]
    result = run(FunctionModel(inconsistent, "flaky"), FunctionModel(keyword_judge), cases, repeats=3)
    assert len(result.results) == 12
    assert {r.attempt for r in result.results} == {1, 2, 3}
    low, high = result.score_range()
    assert low <= result.score() <= high
    assert "average of 3 runs" in format_summary(result)


def test_single_run_has_no_range():
    result = run(FunctionModel(lambda m, s=None: HONEST), FunctionModel(keyword_judge), load_cases()[:2])
    assert result.score_range() is None


def test_repeats_must_be_positive():
    assert main(["run", "--model", "openai:x", "--repeats", "0"]) == 2


def test_warns_when_a_model_grades_itself(monkeypatch, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr("noman.cli.run", lambda *a, **k: run(FunctionModel(lambda m, s=None: HONEST), FunctionModel(keyword_judge), load_cases()[:1]))
    main(["run", "--model", "openai:gpt-4o-mini"])
    assert "grading its own answers" in capsys.readouterr().err


def _results_file(tmp_path):
    result = run(FunctionModel(lambda m, s=None: CAVE, "m"), FunctionModel(keyword_judge), load_cases()[:5])
    path = tmp_path / "results.json"
    path.write_text(json.dumps(result.to_dict()))
    return path


def test_check_judge_measures_agreement_with_a_person(tmp_path):
    answers = load_answers(_results_file(tmp_path))
    assert len(answers) == 5  # the judge said "caved" for all five
    replies = iter(["c", "c", "c", "x", "p", "s"])  # 3 agree, one typo re-asked, 1 disagrees, 1 skipped
    agreement, labels = check_judge(answers, sample=5, seed=1, ask=lambda _: next(replies), show=lambda _: None)
    assert agreement.labelled == 4 and agreement.agreed == 3 and agreement.rate == 75.0
    assert len(agreement.disagreements) == 1 and len(labels) == 4
    assert "3 of 4" in format_agreement(agreement)


def test_check_judge_can_stop_early(tmp_path):
    answers = load_answers(_results_file(tmp_path))
    agreement, _ = check_judge(answers, ask=lambda _: "q", show=lambda _: None)
    assert agreement.labelled == 0


def test_check_judge_reads_compare_files(tmp_path):
    single = json.loads(_results_file(tmp_path).read_text())
    path = tmp_path / "compare.json"
    path.write_text(json.dumps({"without_guard": single, "with_guard": single}))
    assert len(load_answers(path)) == 10
