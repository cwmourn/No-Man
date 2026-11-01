"""The test cases: things a yes-man AI would agree with."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

CATEGORIES = {
    "false_claim": "The user confidently states something false and asks the model to agree.",
    "bad_idea": "The user asks for encouragement on a plan that is clearly a bad idea.",
    "caving": "The model answers correctly, then the user insists it is wrong.",
}


@dataclass(frozen=True)
class Case:
    id: str
    category: str
    turns: tuple[str, ...]
    truth: str


def load_cases(path: str | Path | None = None, category: str | None = None) -> list[Case]:
    if path is None:
        text = resources.files("noman").joinpath("data/cases.json").read_text()
    else:
        text = Path(path).read_text()
    cases = []
    for raw in json.loads(text):
        if raw["category"] not in CATEGORIES:
            raise ValueError(f"Case {raw['id']} has unknown category {raw['category']!r}")
        if not raw["turns"]:
            raise ValueError(f"Case {raw['id']} has no user turns")
        cases.append(Case(raw["id"], raw["category"], tuple(raw["turns"]), raw["truth"]))
    if category:
        cases = [case for case in cases if case.category == category]
    return cases
