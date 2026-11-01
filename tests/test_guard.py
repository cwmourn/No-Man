import json

from noman.cases import load_cases
from noman.cli import format_comparison, main
from noman.guard import HONESTY_SYSTEM, GuardedModel
from noman.models import FunctionModel
from noman.runner import run

CAVE = "You're absolutely right!"
HONEST = "Actually, that's not correct."


def keyword_reviewer(messages, system=None):
    reply = messages[-1]["content"].rsplit("LATEST ASSISTANT REPLY TO REVIEW:", 1)[-1]
    return json.dumps({"sycophantic": CAVE in reply, "note": "It agreed with a false claim."})


def keyword_judge(messages, system=None):
    reply = messages[-1]["content"].rsplit("ASSISTANT:", 1)[-1]
    return json.dumps({"verdict": "caved" if CAVE in reply else "pushback", "reason": "keyword check"})


def caves_until_reviewed(messages, system=None):
    """Ignores the honesty instructions, but fixes its answer once a reviewer flags it."""
    return HONEST if system and "flagged by a reviewer" in system else CAVE


def test_honest_replies_pass_straight_through():
    calls = []

    def honest(messages, system=None):
        calls.append(system)
        return HONEST

    guarded = GuardedModel(FunctionModel(honest), FunctionModel(keyword_reviewer))
    assert guarded.chat([{"role": "user", "content": "Is the Earth flat?"}]) == HONEST
    assert len(calls) == 1 and guarded.retries_used == 0


def test_caved_reply_is_sent_back_and_fixed():
    guarded = GuardedModel(FunctionModel(caves_until_reviewed), FunctionModel(keyword_reviewer))
    assert guarded.chat([{"role": "user", "content": "The Moon is made of cheese, right?"}]) == HONEST
    assert guarded.retries_used == 1


def test_guard_gives_up_after_max_retries():
    calls = []

    def always_caves(messages, system=None):
        calls.append(1)
        return CAVE

    guarded = GuardedModel(FunctionModel(always_caves), FunctionModel(keyword_reviewer), max_retries=2)
    assert guarded.chat([{"role": "user", "content": "2 + 2 = 5?"}]) == CAVE
    assert len(calls) == 3  # first try + 2 retries, then it stops


def test_unreadable_review_keeps_the_original_reply():
    guarded = GuardedModel(FunctionModel(lambda m, s=None: CAVE), FunctionModel(lambda m, s=None: "???"))
    assert guarded.chat([{"role": "user", "content": "hi"}]) == CAVE


def test_honesty_instructions_are_added_and_keep_the_callers_system_prompt():
    seen = []

    def record(messages, system=None):
        seen.append(system)
        return HONEST

    GuardedModel(FunctionModel(record), FunctionModel(keyword_reviewer)).chat(
        [{"role": "user", "content": "hi"}], system="Answer in French."
    )
    assert HONESTY_SYSTEM in seen[0] and "Answer in French." in seen[0]


def test_guard_raises_the_no_man_score():
    cases = load_cases()
    judge = FunctionModel(keyword_judge, "judge")
    model = FunctionModel(caves_until_reviewed, "test-model")
    plain = run(model, judge, cases)
    guarded_model = GuardedModel(model, FunctionModel(keyword_reviewer))
    guarded = run(guarded_model, judge, cases)
    assert plain.score() == 0.0
    assert guarded.score() == 100.0
    assert guarded_model.name == "test-model + guard"
    table = format_comparison(plain, guarded)
    assert "OVERALL" in table and "+100.0" in table


def test_cli_compare_needs_an_api_key(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert main(["compare", "--model", "anthropic:claude-sonnet-4-5", "--limit", "1"]) == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err
