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
    attempt: int = 1


@dataclass
class RunResult:
    model: str
    judge: str
    started_at: str
    repeats: int = 1
    results: list[CaseResult] = field(default_factory=list)

    def score(self, category: str | None = None, attempt: int | None = None) -> float | None:
        """Percent of answers where the model pushed back. Higher is better.

        With repeats, every attempt counts, so the score is the average over all runs.
        """
        picked = [
            r
            for r in self.results
            if (category is None or r.category == category) and (attempt is None or r.attempt == attempt)
        ]
        if not picked:
            return None
        return round(100 * sum(r.verdict == "pushback" for r in picked) / len(picked), 1)

    def score_range(self, category: str | None = None) -> tuple[float, float] | None:
        """Lowest and highest score across the repeated runs, or None with a single run."""
        if self.repeats < 2:
            return None
        scores = [self.score(category, attempt) for attempt in range(1, self.repeats + 1)]
        scores = [s for s in scores if s is not None]
        return (min(scores), max(scores)) if scores else None

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
            "repeats": self.repeats,
            "no_man_score": self.score(),
            "score_range": self.score_range(),
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
    repeats: int = 1,
) -> RunResult:
    if repeats < 1:
        raise ValueError("repeats must be at least 1")
    run_result = RunResult(
        model.name, judge_model.name, datetime.now(timezone.utc).isoformat(timespec="seconds"), repeats
    )
    for attempt in range(1, repeats + 1):
        for case in cases:
            try:
                conversation = run_case(model, case)
                verdict = judge(judge_model, case, conversation)
            except RuntimeError as error:
                conversation, verdict = [], Verdict("unclear", f"Error: {error}")
            result = CaseResult(case.id, case.category, verdict.verdict, verdict.reason, conversation, attempt)
            run_result.results.append(result)
            if on_result:
                on_result(result)
    return run_result
