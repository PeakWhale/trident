"""The triage engine.

A small LangGraph state machine:

    validate_input -> screen_rules -> classify -> apply_rules -> review -> decide

* validate_input  checks the text is not empty and not too long.
* screen_rules    runs the pack's red-flag word rules (no AI). This step also
                  runs for text that is too long, so a red flag still counts.
* classify        asks the LLM for {category, confidence, evidence} as JSON,
                  checks it against a schema, and retries once if it is invalid.
* apply_rules     maps the category to a level with the pack's rules (no AI).
* review          a second, independent LLM prompt re-checks the decision.
* decide          the fail-safe gate.

The gate is "default deny": a case is DECIDED only when every check passed
on purpose. Any error, timeout, invalid answer, unknown category, low
confidence, red-flag rule or reviewer disagreement gives NEEDS_HUMAN_REVIEW,
and the case is then never treated as the lowest level.
"""

from __future__ import annotations

import logging
import operator
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from . import DECIDED, HUMAN_REVIEW, __version__, prompts
from .audit import AuditSink, JsonlAuditLog
from .config import Settings
from .llm import LLMClient, client_from_settings
from .models import (
    OutputError,
    Step,
    TriageResult,
    classifier_schema,
    parse_classifier_output,
    parse_reviewer_output,
    reviewer_schema,
)
from .packs import UNKNOWN, PackRegistry, RulePack

logger = logging.getLogger("trident.engine")

# First try, plus one retry when the model answer is invalid.
MAX_ATTEMPTS = 2
RAW_OUTPUT_LIMIT = 4000


class LLMTimeoutError(TimeoutError):
    """The model did not answer in time."""


class _State(TypedDict, total=False):
    text: str
    pack: RulePack
    steps: Annotated[list[dict[str, Any]], operator.add]
    reasons: Annotated[list[str], operator.add]
    halt: bool
    # The text can be screened by the word rules, but must not go to a model.
    skip_llm: bool
    rule_hits: list[dict[str, Any]]
    min_level: str | None
    classification: dict[str, Any] | None
    confidence_ok: bool
    proposed_level: str | None
    final_level: str | None
    route_to: str | None
    rule_matched: dict[str, Any] | None
    review_result: dict[str, Any] | None
    outcome: str
    level: str
    gate_checks: dict[str, bool]


@dataclass
class _NodeResult:
    update: dict[str, Any]
    status: str = "ok"
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _describe(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}".strip()
    return text if len(text) <= 300 else text[:297] + "..."


def _clip(raw: Any) -> str:
    text = raw if isinstance(raw, str) else repr(raw)
    return text if len(text) <= RAW_OUTPUT_LIMIT else text[:RAW_OUTPUT_LIMIT] + "...[cut]"


def _model_name(client: Any) -> str:
    return str(getattr(client, "name", type(client).__name__))


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def interim_level(pack: RulePack, *candidates: str | None) -> str:
    """The "treat as" level for a case that waits for a person.

    It is the most urgent of: the pack's interim level and any level a check
    suggested. The pack loader makes sure the interim level is never the
    lowest level, so this is never the lowest level either.
    """
    level_ids = {lvl.id for lvl in pack.levels}
    known = [c for c in candidates if c in level_ids]
    return pack.most_urgent(pack.escalation.human_review.interim_level, *known)  # type: ignore[return-value]


def _suggested_levels(pack: RulePack, state: dict[str, Any]) -> list[str | None]:
    """Every level a check suggested, including the level of the reviewer's own category."""
    levels = [state.get("level"), state.get("final_level"), state.get("proposed_level"), state.get("min_level")]
    review_category = (state.get("review_result") or {}).get("category")
    cat = pack.category(review_category) if isinstance(review_category, str) else None
    if cat is not None:
        levels.append(cat.level)
    return levels


class TriageEngine:
    """Domain-agnostic "AI plus rules" triage with a fail-safe gate."""

    def __init__(
        self,
        packs: PackRegistry,
        classifier: LLMClient,
        reviewer: LLMClient | None = None,
        *,
        timeout_s: float = 60.0,
        max_input_chars: int = 8000,
        audit: AuditSink | None = None,
    ):
        if timeout_s <= 0:
            raise ValueError("timeout_s must be greater than 0")
        self.packs = packs
        self.classifier = classifier
        self.reviewer = reviewer if reviewer is not None else classifier
        self.timeout_s = timeout_s
        self.max_input_chars = max_input_chars
        self.audit = audit
        self._pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="trident-llm")
        self._graph = self._build_graph()

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> TriageEngine:
        settings = settings or Settings.from_env()
        packs = PackRegistry.load([settings.packs_dir] if settings.packs_dir else [])
        classifier = client_from_settings(settings)
        reviewer = client_from_settings(settings, settings.review_model) if settings.review_model else classifier
        return cls(
            packs,
            classifier,
            reviewer,
            # The HTTP client has its own timeout. This is a hard stop on top of it.
            timeout_s=settings.timeout_s + 5,
            max_input_chars=settings.max_input_chars,
            audit=JsonlAuditLog(settings.audit_log) if settings.audit_log else None,
        )

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    @property
    def model_names(self) -> dict[str, str]:
        return {"classifier": _model_name(self.classifier), "reviewer": _model_name(self.reviewer)}

    # ---- public API -----------------------------------------------------

    def triage(self, text: str, pack_id: str) -> TriageResult:
        """Triage one case. Raises PackNotFoundError for an unknown pack id.

        Every other problem gives a NEEDS_HUMAN_REVIEW result, never an exception.
        """
        pack = self.packs.get(pack_id)
        request_id = uuid.uuid4().hex
        created_at = _now()
        started = time.perf_counter()

        state: dict[str, Any] = {"text": text, "pack": pack, "steps": [], "reasons": [], "halt": False}
        engine_error: str | None = None
        try:
            for snapshot in self._graph.stream(dict(state), stream_mode="values"):
                state = snapshot
        except Exception as exc:  # a bug in the engine itself
            logger.exception("Triage engine error")
            engine_error = _describe(exc)

        total_ms = (time.perf_counter() - started) * 1000
        try:
            result = self._build_result(pack, text, state, request_id, created_at, total_ms, engine_error)
        except Exception as exc:
            logger.exception("Could not build the triage result")
            result = self._fallback_result(pack, text, request_id, created_at, total_ms, _describe(exc))

        result = enforce_failsafe(result, pack)

        if self.audit is not None:
            try:
                self.audit.write(result.model_dump(mode="json"))
            except Exception as exc:
                logger.exception("Could not write the audit log")
                result = escalate(result, pack, f"The audit log could not be written ({_describe(exc)}).")
        return result

    # ---- graph ------------------------------------------------------------

    def _build_graph(self):
        graph = StateGraph(_State)
        order = ["validate_input", "screen_rules", "classify", "apply_rules", "review", "decide"]
        handlers: dict[str, Callable[[dict[str, Any]], _NodeResult]] = {
            "validate_input": self._validate_input,
            "screen_rules": self._screen_rules,
            "classify": self._classify,
            "apply_rules": self._apply_rules,
            "review": self._review,
            "decide": self._decide,
        }
        for name in order:
            graph.add_node(name, self._wrap(name, handlers[name]))
        graph.add_edge(START, order[0])
        for current, following in zip(order[:-2], order[1:-1], strict=True):
            # After a fatal problem, jump straight to the fail-safe gate.
            # Text that is too long still goes through screen_rules (no AI) first.
            graph.add_conditional_edges(
                current,
                _route_to(following, stop_on_skip_llm=current != "validate_input"),
                {following: following, "decide": "decide"},
            )
        graph.add_edge("review", "decide")
        graph.add_edge("decide", END)
        return graph.compile()

    def _wrap(self, name: str, handler: Callable[[dict[str, Any]], _NodeResult]):
        def node(state: dict[str, Any]) -> dict[str, Any]:
            started_at = _now()
            t0 = time.perf_counter()
            try:
                res = handler(state)
            except Exception as exc:
                logger.exception("Step %s failed", name)
                res = _NodeResult(
                    {"halt": True, "reasons": [f"Step '{name}' failed: {_describe(exc)}"]},
                    "error",
                    _describe(exc),
                )
            step = Step(
                name=name,
                status=res.status,  # type: ignore[arg-type]
                started_at=started_at,
                duration_ms=round((time.perf_counter() - t0) * 1000, 2),
                detail=res.detail,
                data=res.data,
            )
            return {**res.update, "steps": [step.model_dump()]}

        return node

    def _ask(self, client: LLMClient, system: str, user: str, schema: dict[str, Any]) -> tuple[str, float]:
        """Call a model with a hard time limit."""
        t0 = time.perf_counter()
        future = self._pool.submit(client.complete, system, user, schema)
        try:
            raw = future.result(timeout=self.timeout_s)
        except FutureTimeoutError:
            future.cancel()
            raise LLMTimeoutError(f"no answer within {self.timeout_s:g} seconds") from None
        return raw, round((time.perf_counter() - t0) * 1000, 2)

    # ---- steps ------------------------------------------------------------

    def _validate_input(self, state: dict[str, Any]) -> _NodeResult:
        text = state.get("text")
        if not isinstance(text, str) or not text.strip():
            reason = "The input text is empty." if isinstance(text, str) else "The input is not text."
            return _NodeResult({"halt": True, "reasons": [reason]}, "escalated", reason)
        if len(text) > self.max_input_chars:
            # Do not send it to a model, but still run the word rules on all of it.
            reason = f"The input text is too long ({len(text)} characters, the limit is {self.max_input_chars})."
            return _NodeResult({"skip_llm": True, "reasons": [reason]}, "escalated", reason)
        return _NodeResult({}, "ok", f"{len(text)} characters.")

    def _screen_rules(self, state: dict[str, Any]) -> _NodeResult:
        pack: RulePack = state["pack"]
        text: str = state["text"]
        hits: list[dict[str, Any]] = []
        reasons: list[str] = []
        min_level: str | None = None
        for rule in pack.escalation.rules:
            words = rule.find(text)
            if not words:
                continue
            hits.append({"id": rule.id, "then": rule.then, "level": rule.level, "words": words, "reason": rule.reason})
            if rule.level:
                min_level = pack.most_urgent(min_level, rule.level)
            if rule.then == "human_review":
                reasons.append(f"Escalation rule '{rule.id}': {rule.reason} (found: {', '.join(words)})")
        detail = (
            "No escalation rule matched."
            if not hits
            else "Matched: " + ", ".join(f"{h['id']} ({', '.join(h['words'])})" for h in hits)
        )
        return _NodeResult(
            {"rule_hits": hits, "min_level": min_level, "reasons": reasons},
            "escalated" if reasons else "ok",
            detail,
            {"matched": hits, "min_level": min_level},
        )

    def _classify(self, state: dict[str, Any]) -> _NodeResult:
        pack: RulePack = state["pack"]
        text: str = state["text"]
        system = prompts.classifier_system_prompt(pack)
        user = prompts.classifier_user_prompt(text)
        schema = classifier_schema(pack)
        name = _model_name(self.classifier)
        attempts: list[dict[str, Any]] = []
        last_error = ""

        for attempt in range(1, MAX_ATTEMPTS + 1):
            message = user if attempt == 1 else user + prompts.retry_note(last_error)
            try:
                raw, ms = self._ask(self.classifier, system, message, schema)
            except Exception as exc:
                attempts.append({"attempt": attempt, "error": _describe(exc)})
                reason = f"The classifier model failed: {_describe(exc)}"
                return _NodeResult(
                    {"halt": True, "reasons": [reason]}, "error", reason, {"model": name, "attempts": attempts}
                )
            try:
                out = parse_classifier_output(raw, pack, text)
            except OutputError as exc:
                last_error = str(exc)
                attempts.append({"attempt": attempt, "ms": ms, "raw_output": _clip(raw), "error": last_error})
                continue
            attempts.append({"attempt": attempt, "ms": ms, "raw_output": _clip(raw)})
            output = out.model_dump()
            return _NodeResult(
                {"classification": output},
                "ok",
                f"category={out.category}, confidence={out.confidence:.2f}"
                + (f" (after {attempt} tries)" if attempt > 1 else ""),
                {"model": name, "attempts": attempts, "output": output},
            )

        reason = f"The classifier answer was invalid {MAX_ATTEMPTS} times: {last_error}"
        return _NodeResult({"halt": True, "reasons": [reason]}, "error", reason, {"model": name, "attempts": attempts})

    def _apply_rules(self, state: dict[str, Any]) -> _NodeResult:
        pack: RulePack = state["pack"]
        c: dict[str, Any] = state["classification"]
        min_level: str | None = state.get("min_level")

        if c["category"] == UNKNOWN:
            reason = "The classifier could not match the text to any category (unknown)."
            return _NodeResult(
                {"reasons": [reason], "confidence_ok": False, "final_level": None, "rule_matched": None},
                "escalated",
                reason,
            )

        cat = pack.category(c["category"])
        if cat is None:  # parse_classifier_output already checks this
            raise ValueError(f"category '{c['category']}' is not in the rule pack")

        reasons: list[str] = []
        threshold = cat.min_confidence if cat.min_confidence is not None else pack.escalation.min_confidence
        confidence_ok = c["confidence"] >= threshold
        if not confidence_ok:
            reasons.append(f"Confidence {c['confidence']:.2f} is below the minimum of {threshold:.2f}.")
        if cat.always_human_review:
            reasons.append(f"The rule pack says category '{cat.id}' always needs a person.")

        final = pack.most_urgent(cat.level, min_level) or cat.level
        raised_by = [
            h["id"] for h in state.get("rule_hits") or [] if final != cat.level and h.get("level") == final
        ]
        rule_matched = {
            "category": cat.id,
            "category_level": cat.level,
            "final_level": final,
            "raised_by": raised_by,
            "min_confidence": threshold,
            "route_to": cat.route_to,
            "always_human_review": cat.always_human_review,
        }
        detail = f"{cat.id} -> {cat.level}"
        if raised_by:
            detail += f", raised to {final} by {', '.join(raised_by)}"
        return _NodeResult(
            {
                "proposed_level": cat.level,
                "final_level": final,
                "route_to": cat.route_to,
                "rule_matched": rule_matched,
                "confidence_ok": confidence_ok,
                "reasons": reasons,
            },
            "escalated" if reasons else "ok",
            detail,
            rule_matched,
        )

    def _review(self, state: dict[str, Any]) -> _NodeResult:
        if state.get("reasons"):
            return _NodeResult({}, "skipped", "Skipped: the case already goes to human review.")

        pack: RulePack = state["pack"]
        text: str = state["text"]
        c: dict[str, Any] = state["classification"]
        level = pack.level(state["final_level"])
        system = prompts.reviewer_system_prompt(pack)
        proposed = state.get("proposed_level")
        user = prompts.reviewer_user_prompt(
            text,
            c["category"],
            level.id,
            level.label,
            c.get("evidence", []),
            raised_from=proposed if proposed and proposed != level.id else None,
        )
        schema = reviewer_schema(pack)
        name = _model_name(self.reviewer)
        attempts: list[dict[str, Any]] = []
        last_error = ""

        for attempt in range(1, MAX_ATTEMPTS + 1):
            message = user if attempt == 1 else user + prompts.retry_note(last_error)
            try:
                raw, ms = self._ask(self.reviewer, system, message, schema)
            except Exception as exc:
                attempts.append({"attempt": attempt, "error": _describe(exc)})
                reason = f"The reviewer model failed: {_describe(exc)}"
                return _NodeResult({"reasons": [reason]}, "error", reason, {"model": name, "attempts": attempts})
            try:
                out = parse_reviewer_output(raw, pack)
            except OutputError as exc:
                last_error = str(exc)
                attempts.append({"attempt": attempt, "ms": ms, "raw_output": _clip(raw), "error": last_error})
                continue
            attempts.append({"attempt": attempt, "ms": ms, "raw_output": _clip(raw)})
            review = {"agrees": out.agrees, "category": out.category, "reason": out.reason, "model": name}
            data = {"model": name, "attempts": attempts, "output": out.model_dump()}
            if out.agrees and out.category == c["category"]:
                return _NodeResult({"review_result": review}, "ok", f"Reviewer agrees: {out.reason}".strip(), data)
            if out.agrees:
                reason = (
                    f"The reviewer said it agrees but chose a different category "
                    f"('{out.category}' instead of '{c['category']}')."
                )
            else:
                reason = f"The independent reviewer disagreed (its category: '{out.category}'). {out.reason}".strip()
            return _NodeResult({"review_result": review, "reasons": [reason]}, "escalated", reason, data)

        reason = f"The reviewer answer was invalid {MAX_ATTEMPTS} times: {last_error}"
        return _NodeResult({"reasons": [reason]}, "error", reason, {"model": name, "attempts": attempts})

    def _decide(self, state: dict[str, Any]) -> _NodeResult:
        pack: RulePack = state["pack"]
        checks = gate_checks(state)
        if all(checks.values()):
            level = state["final_level"]
            return _NodeResult(
                {"outcome": DECIDED, "level": level, "gate_checks": checks},
                "ok",
                f"All checks passed. Level {level}.",
                {"checks": checks},
            )
        extra = [] if state.get("reasons") else ["Safety gate: not every check passed."]
        level = interim_level(pack, *_suggested_levels(pack, state))
        failed = [name for name, passed in checks.items() if not passed]
        return _NodeResult(
            {"outcome": HUMAN_REVIEW, "level": level, "gate_checks": checks, "reasons": extra},
            "escalated",
            f"Needs human review. Failed checks: {', '.join(failed)}. Treat as {level} while waiting.",
            {"checks": checks},
        )

    # ---- result -----------------------------------------------------------

    def _build_result(
        self,
        pack: RulePack,
        text: str,
        state: dict[str, Any],
        request_id: str,
        created_at: str,
        total_ms: float,
        engine_error: str | None,
    ) -> TriageResult:
        steps = [Step.model_validate(s) for s in state.get("steps") or []]
        reasons = _dedupe(list(state.get("reasons") or []))
        if engine_error:
            reasons.append(f"Engine error: {engine_error}")
            steps.append(
                Step(name="engine", status="error", started_at=_now(), duration_ms=0.0, detail=engine_error)
            )

        c = state.get("classification") or {}
        outcome = state.get("outcome")
        level_id = state.get("level")
        if outcome != DECIDED or not level_id or reasons:
            outcome = HUMAN_REVIEW
            level_id = interim_level(pack, *_suggested_levels(pack, state))
            if not reasons:
                reasons = ["The engine did not finish every check."]

        timing: dict[str, float] = {"total": round(total_ms, 2)}
        for step in steps:
            timing[step.name] = round(timing.get(step.name, 0.0) + step.duration_ms, 2)

        result = TriageResult(
            request_id=request_id,
            created_at=created_at,
            engine_version=__version__,
            pack=pack.id,
            pack_version=pack.version,
            input_text=text if isinstance(text, str) else "",
            category=c.get("category"),
            confidence=c.get("confidence"),
            evidence=list(c.get("evidence") or []),
            rule_matched=state.get("rule_matched"),
            escalation_rules_hit=list(state.get("rule_hits") or []),
            review=state.get("review_result"),
            models=self.model_names,
            steps=steps,
            timing_ms=timing,
            disclaimer=pack.disclaimer.strip() if pack.disclaimer else None,
            reasons=reasons,
            **_decision_fields(pack, outcome, level_id, state.get("route_to")),
        )
        return result

    def _fallback_result(
        self, pack: RulePack, text: str, request_id: str, created_at: str, total_ms: float, error: str
    ) -> TriageResult:
        return TriageResult(
            request_id=request_id,
            created_at=created_at,
            engine_version=__version__,
            pack=pack.id,
            pack_version=pack.version,
            input_text=text if isinstance(text, str) else "",
            reasons=[f"Engine error: {error}"],
            models=self.model_names,
            steps=[Step(name="engine", status="error", started_at=_now(), duration_ms=0.0, detail=error)],
            timing_ms={"total": round(total_ms, 2)},
            disclaimer=pack.disclaimer.strip() if pack.disclaimer else None,
            **_decision_fields(pack, HUMAN_REVIEW, interim_level(pack), None),
        )


def _route_to(following: str, stop_on_skip_llm: bool = True):
    def route(state: dict[str, Any]) -> str:
        if state.get("halt") or (stop_on_skip_llm and state.get("skip_llm")):
            return "decide"
        return following

    return route


def gate_checks(state: dict[str, Any]) -> dict[str, bool]:
    """The fail-safe gate. Every check must be True for a DECIDED outcome."""
    c = state.get("classification") or {}
    review = state.get("review_result") or {}
    category = c.get("category")
    return {
        "classifier_answer_valid": bool(c),
        "category_known": category not in (None, UNKNOWN),
        "confidence_ok": state.get("confidence_ok") is True,
        "level_set": bool(state.get("final_level")),
        "reviewer_agrees": review.get("agrees") is True and review.get("category") == category,
        "no_escalation": not state.get("reasons") and not state.get("halt") and not state.get("skip_llm"),
    }


def _decision_fields(pack: RulePack, outcome: str, level_id: str, route_to: str | None) -> dict[str, Any]:
    level = pack.level(level_id)
    if outcome == DECIDED:
        return {
            "outcome": DECIDED,
            "needs_human_review": False,
            "headline": level.label if level.id.lower() == level.label.lower() else f"{level.id} - {level.label}",
            "level": level.id,
            "level_label": level.label,
            "level_color": level.color,
            "action": level.action.strip(),
            "route_to": route_to,
        }
    review = pack.escalation.human_review
    return {
        "outcome": HUMAN_REVIEW,
        "needs_human_review": True,
        "headline": review.label,
        "level": level.id,
        "level_label": level.label,
        "level_color": level.color,
        "action": review.action.strip(),
        "route_to": review.route_to,
    }


def escalate(result: TriageResult, pack: RulePack, reason: str) -> TriageResult:
    """Turn any result into NEEDS_HUMAN_REVIEW, keeping the audit data."""
    candidates = [result.level] if result.level in {lvl.id for lvl in pack.levels} else []
    level_id = interim_level(pack, *candidates)
    update = _decision_fields(pack, HUMAN_REVIEW, level_id, None)
    update["reasons"] = _dedupe([*result.reasons, reason])
    return result.model_copy(update=update)


def enforce_failsafe(result: TriageResult, pack: RulePack) -> TriageResult:
    """Last guard before a result leaves the engine.

    * A result with any reason for review can not be DECIDED.
    * A NEEDS_HUMAN_REVIEW result is never the lowest level.
    """
    level_ids = {lvl.id for lvl in pack.levels}
    if result.outcome == DECIDED and (result.reasons or result.needs_human_review or result.level not in level_ids):
        return escalate(result, pack, "Safety gate: a decided result had open problems.")
    if result.outcome == HUMAN_REVIEW:
        if result.level not in level_ids or result.level == pack.lowest_level or not result.needs_human_review:
            fixed = interim_level(pack, result.level if result.level in level_ids else None)
            update = _decision_fields(pack, HUMAN_REVIEW, fixed, None)
            update["reasons"] = result.reasons or ["Needs human review."]
            return result.model_copy(update=update)
    return result
