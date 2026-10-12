"""Fake LLMs for tests. No network, no Ollama."""

from __future__ import annotations

import json
import time
from typing import Any

from trident import HUMAN_REVIEW
from trident.models import TriageResult
from trident.packs import RulePack


class FakeLLM:
    """Returns scripted answers in order.

    An answer can be:
    * a dict      - sent back as JSON text
    * a str       - sent back as it is
    * an Exception - raised
    * a callable  - called with (system, user) and its return value used
    """

    def __init__(self, *answers: Any, name: str = "fake-llm"):
        self.answers = list(answers)
        self.calls: list[dict[str, Any]] = []
        self.name = name

    def complete(self, system: str, user: str, json_schema: dict[str, Any] | None = None) -> str:
        self.calls.append({"system": system, "user": user, "schema": json_schema})
        if not self.answers:
            raise AssertionError("FakeLLM has no more scripted answers")
        answer = self.answers.pop(0)
        if callable(answer) and not isinstance(answer, BaseException):
            answer = answer(system, user)
        if isinstance(answer, BaseException):
            raise answer
        if isinstance(answer, dict):
            return json.dumps(answer)
        return answer


class SlowLLM:
    """Waits longer than the engine allows, then answers."""

    name = "slow-llm"

    def __init__(self, seconds: float, answer: dict[str, Any] | None = None):
        self.seconds = seconds
        self.answer = answer or {}
        self.calls = 0

    def complete(self, system: str, user: str, json_schema: dict[str, Any] | None = None) -> str:
        self.calls += 1
        time.sleep(self.seconds)
        return json.dumps(self.answer)


def classified(category: str, confidence: float = 0.95, evidence: list[str] | None = None) -> dict[str, Any]:
    return {"category": category, "confidence": confidence, "evidence": evidence if evidence is not None else []}


def agree(category: str, reason: str = "The category fits the text.") -> dict[str, Any]:
    return {"agrees": True, "category": category, "reason": reason}


def disagree(category: str, reason: str = "Another category fits better.") -> dict[str, Any]:
    return {"agrees": False, "category": category, "reason": reason}


def assert_human_review(result: TriageResult, pack: RulePack) -> None:
    """The fail-safe promise, checked on one result."""
    assert result.outcome == HUMAN_REVIEW
    assert result.needs_human_review is True
    assert result.headline == pack.escalation.human_review.label
    assert result.reasons, "a human review result must say why"
    assert result.level != pack.lowest_level, "human review must never be the lowest level"
    assert result.action == pack.escalation.human_review.action.strip()


def step(result: TriageResult, name: str):
    for s in result.steps:
        if s.name == name:
            return s
    return None

