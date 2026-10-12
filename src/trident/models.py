"""Data shapes: what the models must answer, and what the engine returns."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, ValidationError

from .packs import UNKNOWN, RulePack

Outcome = Literal["DECIDED", "NEEDS_HUMAN_REVIEW"]
StepStatus = Literal["ok", "escalated", "error", "skipped"]


class OutputError(ValueError):
    """The model answer is not valid JSON or does not match the schema."""


# ---- what the models must answer ---------------------------------------


class ClassifierOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    category: StrictStr
    confidence: float = Field(ge=0, le=1, strict=True)
    evidence: list[StrictStr] = Field(default_factory=list, max_length=5)


class ReviewerOutput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # A real JSON true/false. Text like "YES" is rejected on purpose.
    agrees: StrictBool
    category: StrictStr
    reason: StrictStr = ""


def classifier_schema(pack: RulePack) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": [*pack.category_ids, UNKNOWN]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
        },
        "required": ["category", "confidence", "evidence"],
    }


def reviewer_schema(pack: RulePack) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "agrees": {"type": "boolean"},
            "category": {"type": "string", "enum": [*pack.category_ids, UNKNOWN]},
            "reason": {"type": "string"},
        },
        "required": ["agrees", "category", "reason"],
    }


def extract_json(raw: str) -> dict[str, Any]:
    """Read one JSON object from a model answer.

    Accepts plain JSON or JSON inside a ```code fence```. Nothing else.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise OutputError("the answer is empty")
    text = raw.strip()
    fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OutputError(f"the answer is not valid JSON ({exc.msg})") from None
    if not isinstance(data, dict):
        raise OutputError("the answer must be one JSON object")
    return data


def _normalize(text: str) -> str:
    text = text.lower().replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", text).strip()


def quote_in_text(quote: str, text: str) -> bool:
    """True if the quote really appears in the text (case and spaces ignored)."""
    q = _normalize(quote).strip(" \"'.,;:!?")
    return bool(q) and q in _normalize(text)


def parse_classifier_output(raw: str, pack: RulePack, text: str) -> ClassifierOutput:
    data = extract_json(raw)
    try:
        out = ClassifierOutput.model_validate(data)
    except ValidationError as exc:
        raise OutputError(_short_errors(exc)) from None
    if out.category != UNKNOWN and pack.category(out.category) is None:
        raise OutputError(f"category '{out.category}' is not in the rule pack")
    if out.category != UNKNOWN:
        if not out.evidence:
            raise OutputError("evidence is empty; give at least one exact quote from the text")
        missing = [q for q in out.evidence if not quote_in_text(q, text)]
        if missing:
            raise OutputError(f"evidence quote not found in the text: {missing[0]!r}")
    return out


def parse_reviewer_output(raw: str, pack: RulePack) -> ReviewerOutput:
    data = extract_json(raw)
    try:
        out = ReviewerOutput.model_validate(data)
    except ValidationError as exc:
        raise OutputError(_short_errors(exc)) from None
    if out.category != UNKNOWN and pack.category(out.category) is None:
        raise OutputError(f"category '{out.category}' is not in the rule pack")
    return out


def _short_errors(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in err['loc']) or 'answer'}: {err['msg']}" for err in exc.errors()
    )


# ---- what the engine returns -------------------------------------------


class Step(BaseModel):
    name: str
    status: StepStatus
    started_at: str
    duration_ms: float
    detail: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class TriageResult(BaseModel):
    request_id: str
    created_at: str
    engine_version: str
    pack: str
    pack_version: str
    input_text: str

    # The decision.
    outcome: Outcome
    needs_human_review: bool
    headline: str
    # When outcome is DECIDED: the final level.
    # When outcome is NEEDS_HUMAN_REVIEW: the level to treat the case as while
    # a person looks at it. It is never the lowest level of the pack.
    level: str
    level_label: str
    level_color: str
    action: str
    route_to: str | None = None
    reasons: list[str] = Field(default_factory=list)

    # What the checks found.
    category: str | None = None
    confidence: float | None = None
    evidence: list[str] = Field(default_factory=list)
    rule_matched: dict[str, Any] | None = None
    escalation_rules_hit: list[dict[str, Any]] = Field(default_factory=list)
    review: dict[str, Any] | None = None

    # Audit trail.
    models: dict[str, str] = Field(default_factory=dict)
    steps: list[Step] = Field(default_factory=list)
    timing_ms: dict[str, float] = Field(default_factory=dict)
    disclaimer: str | None = None
