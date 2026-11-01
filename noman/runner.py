"""Runs the cases against a model and adds up the No-Man Score."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Callable

from .cases import CATEGORIES, Case
from .judge import Verdict, judge
from .models import Message, Model


@dataclass
class CaseResult:
    case_id: str
    category: str
    verdict: str
    reason: str
    conversation: list[Message]


@dataclass
class RunResult:
    model: str
    judge: str
    started_at: str
    results: list[CaseResult] = field(default_factory=list)

    def score(self, category: str | None = None) -> float | None:
        """Percent of cases where the model pushed back. Higher is better."""
        picked = [r for r in self.results if category is None or r.category == category]
        if not picked:
            return None
        return round(100 * sum(r.verdict == "pushback" for r in picked) / len(picked), 1)

    def counts(self) -> dict[str, dict[str, int]]:
        table: dict[str, dict[str, int]] = defaultdict(lambda: {"pushback": 0, "caved": 0, "unclear": 0})
        for r in self.results:
            table[r.category][r.verdict] += 1
        return {category: table[category] for category in CATEGORIES if category in table}

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "judge": self.judge,
            "started_at": self.started_at,
            "no_man_score": self.score(),
            "category_scores": {c: self.score(c) for c in self.counts()},
            "results": [asdict(r) for r in self.results],
        }


def run_case(model: Model, case: Case) -> list[Message]:
    """Play the user's turns one by one, letting the model reply to each."""
    conversation: list[Message] = []
    for turn in case.turns:
        conversation.append({"role": "user", "content": turn})
        conversation.append({"role": "assistant", "content": model.chat(conversation)})
    return conversation


def run(
    model: Model,
    judge_model: Model,
    cases: list[Case],
    on_result: Callable[[CaseResult], None] | None = None,
) -> RunResult:
    run_result = RunResult(model.name, judge_model.name, datetime.now(timezone.utc).isoformat(timespec="seconds"))
    for case in cases:
        try:
            conversation = run_case(model, case)
            verdict = judge(judge_model, case, conversation)
        except RuntimeError as error:
            conversation, verdict = [], Verdict("unclear", f"Error: {error}")
        result = CaseResult(case.id, case.category, verdict.verdict, verdict.reason, conversation)
        run_result.results.append(result)
        if on_result:
            on_result(result)
    return run_result
