"""The fail-safe promise.

Any error, timeout, invalid answer, unknown category, low confidence,
red-flag rule or reviewer disagreement gives NEEDS_HUMAN_REVIEW, and the
case is never treated as the lowest level.

Most tests use a text that would be the LOWEST level (P4) if everything
went well, so the "never the lowest level" check really means something.
"""

from __future__ import annotations

import httpx
import pytest
from fakes import FakeLLM, SlowLLM, agree, assert_human_review, classified, disagree, step

from trident import DECIDED, HUMAN_REVIEW
from trident.audit import JsonlAuditLog
from trident.engine import TriageEngine, enforce_failsafe

PACK = "it-incidents"
LOW_TEXT = "Please give me read access to the finance shared drive for the quarterly report."
LOW_OK = classified("access_request", 0.95, ["read access to the finance shared drive"])


@pytest.fixture
def pack(registry):
    return registry.get(PACK)


# ---- control: the lowest level is allowed only when every check passes ----


def test_all_checks_pass_gives_decided_lowest_level(make_engine, pack):
    engine = make_engine(FakeLLM(LOW_OK), FakeLLM(agree("access_request")))
    result = engine.triage(LOW_TEXT, PACK)
    assert result.outcome == DECIDED
    assert result.needs_human_review is False
    assert result.level == "P4" == pack.lowest_level
    assert result.reasons == []
    assert result.route_to == "Service desk"
    assert all(s.status == "ok" for s in result.steps)
    assert step(result, "decide").data["checks"] == {
        "classifier_answer_valid": True,
        "category_known": True,
        "confidence_ok": True,
        "level_set": True,
        "reviewer_agrees": True,
        "no_escalation": True,
    }


# ---- errors and timeouts ---------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError("connection refused"),
        httpx.ReadTimeout("read timed out"),
        httpx.HTTPStatusError("500", request=httpx.Request("POST", "http://x"), response=httpx.Response(500)),
        RuntimeError("model crashed"),
    ],
    ids=["connect-error", "http-timeout", "http-500", "runtime-error"],
)
def test_classifier_error_needs_human_review(make_engine, pack, error):
    reviewer = FakeLLM()
    engine = make_engine(FakeLLM(error), reviewer)
    result = engine.triage(LOW_TEXT, PACK)
    assert_human_review(result, pack)
    assert result.level == "P2"
    assert "classifier model failed" in result.reasons[0]
    assert step(result, "classify").status == "error"
    assert step(result, "review") is None  # nothing to review
    assert reviewer.calls == []


def test_classifier_timeout_needs_human_review(make_engine, pack):
    engine = make_engine(SlowLLM(2.0, LOW_OK), FakeLLM(), timeout_s=0.2)
    result = engine.triage(LOW_TEXT, PACK)
    assert_human_review(result, pack)
    assert "no answer within" in result.reasons[0]
    assert result.timing_ms["total"] < 1500


def test_reviewer_timeout_needs_human_review(make_engine, pack):
    engine = make_engine(FakeLLM(LOW_OK), SlowLLM(2.0, agree("access_request")), timeout_s=0.2)
    result = engine.triage(LOW_TEXT, PACK)
    assert_human_review(result, pack)
    assert "reviewer model failed" in result.reasons[0]
    assert step(result, "review").status == "error"


def test_reviewer_error_is_never_validated(make_engine, pack):
    """The old bug: a review that throws was reported as validated."""
    engine = make_engine(FakeLLM(LOW_OK), FakeLLM(RuntimeError("reviewer down")))
    result = engine.triage(LOW_TEXT, PACK)
    assert_human_review(result, pack)
    assert result.review is None
    assert step(result, "decide").data["checks"]["reviewer_agrees"] is False


# ---- invalid model output, retry once ---------------------------------------


def test_invalid_json_twice_needs_human_review(make_engine, pack):
    classifier = FakeLLM("P4 obviously", "Sure! The category is access_request.")
    engine = make_engine(classifier, FakeLLM())
    result = engine.triage(LOW_TEXT, PACK)
    assert_human_review(result, pack)
    assert len(classifier.calls) == 2
    assert "invalid 2 times" in result.reasons[0]
    attempts = step(result, "classify").data["attempts"]
    assert [a["attempt"] for a in attempts] == [1, 2]
    assert all("error" in a and "raw_output" in a for a in attempts)


def test_invalid_then_valid_answer_is_retried_once(make_engine, pack):
    classifier = FakeLLM("not json at all", LOW_OK)
    engine = make_engine(classifier, FakeLLM(agree("access_request")))
    result = engine.triage(LOW_TEXT, PACK)
    assert result.outcome == DECIDED
    assert len(classifier.calls) == 2
    assert "previous answer was not valid" in classifier.calls[1]["user"]
    assert "after 2 tries" in step(result, "classify").detail


@pytest.mark.parametrize(
    "bad_answer",
    [
        {"category": "access_request", "confidence": "high", "evidence": ["read access"]},
        {"category": "access_request", "confidence": 95, "evidence": ["read access"]},
        {"category": "access_request", "evidence": ["read access"]},
        {"category": "access_request", "confidence": 0.9, "evidence": "read access"},
        {"category": "made_up_category", "confidence": 0.9, "evidence": ["read access"]},
        {"category": "access_request", "confidence": 0.9, "evidence": []},
        {"category": "access_request", "confidence": 0.9, "evidence": ["the user is the CEO"]},
        ["access_request", 0.9],
        None,
    ],
    ids=[
        "confidence-text",
        "confidence-percent",
        "confidence-missing",
        "evidence-not-list",
        "category-not-in-pack",
        "evidence-empty",
        "evidence-not-in-text",
        "not-an-object",
        "not-text",
    ],
)
def test_schema_violations_need_human_review(make_engine, pack, bad_answer):
    import json

    raw = bad_answer if bad_answer is None else json.dumps(bad_answer)

    class Bad:
        name = "bad"

        def complete(self, system, user, json_schema=None):
            return raw

    engine = make_engine(Bad(), FakeLLM())
    result = engine.triage(LOW_TEXT, PACK)
    assert_human_review(result, pack)
    assert len(step(result, "classify").data["attempts"]) == 2


def test_json_in_code_fence_is_accepted(make_engine):
    import json

    fenced = "```json\n" + json.dumps(LOW_OK) + "\n```"
    engine = make_engine(FakeLLM(fenced), FakeLLM(agree("access_request")))
    assert engine.triage(LOW_TEXT, PACK).outcome == DECIDED


# ---- unknown category and low confidence -----------------------------------


def test_unknown_category_needs_human_review(make_engine, pack):
    reviewer = FakeLLM()
    engine = make_engine(FakeLLM(classified("unknown", 0.4)), reviewer)
    result = engine.triage("Something is weird with the thing.", PACK)
    assert_human_review(result, pack)
    assert result.category == "unknown"
    assert "unknown" in result.reasons[0]
    assert step(result, "review").status == "skipped"
    assert reviewer.calls == []


def test_low_confidence_needs_human_review(make_engine, pack):
    answer = classified("access_request", 0.55, ["read access"])
    engine = make_engine(FakeLLM(answer), FakeLLM())
    result = engine.triage(LOW_TEXT, PACK)
    assert_human_review(result, pack)
    assert "below the minimum of 0.70" in result.reasons[0]
    assert result.level == "P2"


def test_confidence_at_the_limit_is_enough(make_engine):
    answer = classified("access_request", 0.7, ["read access"])
    engine = make_engine(FakeLLM(answer), FakeLLM(agree("access_request")))
    assert engine.triage(LOW_TEXT, PACK).outcome == DECIDED


# ---- reviewer -------------------------------------------------------------------


def test_reviewer_disagreement_needs_human_review(make_engine, pack):
    engine = make_engine(FakeLLM(LOW_OK), FakeLLM(disagree("data_loss", "Sounds like lost data.")))
    result = engine.triage(LOW_TEXT, PACK)
    assert_human_review(result, pack)
    assert "disagreed" in result.reasons[0]
    assert result.level == "P1"  # the reviewer's category (data_loss) is P1
    assert result.review == {
        "agrees": False,
        "category": "data_loss",
        "reason": "Sounds like lost data.",
        "model": "fake-llm",
    }


def test_reviewer_says_agree_but_picks_other_category(make_engine, pack):
    engine = make_engine(FakeLLM(LOW_OK), FakeLLM(agree("how_to_question")))
    result = engine.triage(LOW_TEXT, PACK)
    assert_human_review(result, pack)
    assert "different category" in result.reasons[0]
    assert result.level == "P2"  # both categories are P4, so the interim level


def test_reviewer_agrees_but_names_a_more_urgent_category(make_engine, pack):
    engine = make_engine(FakeLLM(LOW_OK), FakeLLM(agree("security_incident")))
    result = engine.triage(LOW_TEXT, PACK)
    assert_human_review(result, pack)
    assert result.level == "P1"


@pytest.mark.parametrize(
    ("pack_id", "text", "answer", "review_category", "level"),
    [
        ("medical-demo", "I have a small itchy rash on my arm.", classified("skin_minor", 0.9, ["itchy rash"]), "cardiac", "RED"),
        ("it-incidents", LOW_TEXT, LOW_OK, "security_incident", "P1"),
        ("it-incidents", LOW_TEXT, LOW_OK, "degraded_performance", "P2"),
        ("it-incidents", LOW_TEXT, LOW_OK, "unknown", "P2"),
    ],
)
def test_reviewer_category_raises_the_treat_as_level(make_engine, registry, pack_id, text, answer, review_category, level):
    pack = registry.get(pack_id)
    engine = make_engine(FakeLLM(answer), FakeLLM(disagree(review_category)))
    result = engine.triage(text, pack_id)
    assert_human_review(result, pack)
    assert result.review["category"] == review_category
    assert result.level == level
    assert step(result, "decide").detail.endswith(f"Treat as {level} while waiting.")


def test_reviewer_text_yes_is_not_a_boolean(make_engine, pack):
    """The old bug: 'YES' anywhere in the text counted as validated."""
    loose = {"agrees": "YES", "category": "access_request", "reason": "VALIDATED: YES"}
    engine = make_engine(FakeLLM(LOW_OK), FakeLLM(loose, loose))
    result = engine.triage(LOW_TEXT, PACK)
    assert_human_review(result, pack)
    assert "reviewer answer was invalid 2 times" in result.reasons[0]


def test_reviewer_invalid_then_valid(make_engine):
    reviewer = FakeLLM("VALIDATED: YES", agree("access_request"))
    engine = make_engine(FakeLLM(LOW_OK), reviewer)
    result = engine.triage(LOW_TEXT, PACK)
    assert result.outcome == DECIDED
    assert len(reviewer.calls) == 2


def test_reviewer_sees_the_decision_and_the_rules(make_engine):
    reviewer = FakeLLM(agree("access_request"))
    make_engine(FakeLLM(LOW_OK), reviewer).triage(LOW_TEXT, PACK)
    call = reviewer.calls[0]
    assert "independent reviewer" in call["system"]
    assert "access_request -> P4" in call["system"]
    assert "category: access_request" in call["user"]
    assert call["schema"]["properties"]["agrees"] == {"type": "boolean"}


# ---- rules from the pack ------------------------------------------------------


def test_human_review_word_rule(make_engine, registry):
    pack = registry.get("customer-support")
    text = "You charged me twice for March. My lawyer will contact you."
    reviewer = FakeLLM()
    engine = make_engine(FakeLLM(classified("billing_problem", 0.9, ["charged me twice"])), reviewer)
    result = engine.triage(text, "customer-support")
    assert_human_review(result, pack)
    assert result.level == "urgent"  # raised by the rule, not the interim "normal"
    assert result.escalation_rules_hit[0]["id"] == "legal-words"
    assert result.escalation_rules_hit[0]["words"] == ["lawyer"]
    assert reviewer.calls == []


def test_min_level_word_rule_raises_the_level(make_engine):
    text = "I fell off my bike and my wrist hurts a lot. My friend says I was unconscious for a minute."
    engine = make_engine(
        FakeLLM(classified("injury", 0.9, ["my wrist hurts"])),
        FakeLLM(agree("injury")),
    )
    result = engine.triage(text, "medical-demo")
    assert result.outcome == DECIDED
    assert result.level == "RED"
    assert "level: RED (Emergency), raised from YELLOW" in engine.reviewer.calls[0]["user"]
    assert result.rule_matched["category_level"] == "YELLOW"
    assert result.rule_matched["raised_by"] == ["life-threat-words"]


def test_always_human_review_category(make_engine, registry):
    pack = registry.get(PACK)
    text = "I clicked a link in a strange email and typed my password."
    engine = make_engine(FakeLLM(classified("security_incident", 0.99, ["clicked a link"])), FakeLLM())
    result = engine.triage(text, PACK)
    assert_human_review(result, pack)
    assert result.level == "P1"  # the category's own level is more urgent than the interim P2
    assert "always needs a person" in result.reasons[0]


# ---- input problems ------------------------------------------------------------


@pytest.mark.parametrize("text", ["", "   \n\t ", None, 12345])
def test_empty_or_wrong_input_needs_human_review(make_engine, pack, text):
    classifier = FakeLLM()
    engine = make_engine(classifier, FakeLLM())
    result = engine.triage(text, PACK)
    assert_human_review(result, pack)
    assert classifier.calls == []
    assert [s.name for s in result.steps] == ["validate_input", "decide"]


def test_too_long_input_needs_human_review(make_engine, pack):
    classifier = FakeLLM()
    engine = make_engine(classifier, FakeLLM(), max_input_chars=100)
    result = engine.triage("x" * 101, PACK)
    assert_human_review(result, pack)
    assert "too long" in result.reasons[0]
    assert classifier.calls == []


# ---- bugs inside the engine itself ---------------------------------------------


def test_crash_inside_a_step_needs_human_review(make_engine, pack, monkeypatch):
    def boom(self, state):
        raise ZeroDivisionError("bug in apply_rules")

    monkeypatch.setattr(TriageEngine, "_apply_rules", boom)
    engine = make_engine(FakeLLM(LOW_OK), FakeLLM())
    result = engine.triage(LOW_TEXT, PACK)
    assert_human_review(result, pack)
    assert "Step 'apply_rules' failed" in result.reasons[0]
    assert step(result, "apply_rules").status == "error"


def test_crash_of_the_whole_graph_needs_human_review(make_engine, pack, monkeypatch):
    engine = make_engine(FakeLLM(LOW_OK), FakeLLM(agree("access_request")))

    def broken_stream(*args, **kwargs):
        raise RuntimeError("graph exploded")

    monkeypatch.setattr(engine._graph, "stream", broken_stream)
    result = engine.triage(LOW_TEXT, PACK)
    assert_human_review(result, pack)
    assert "Engine error" in result.reasons[0]
    assert result.steps[-1].name == "engine"


def test_audit_log_failure_needs_human_review(make_engine, pack, tmp_path):
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("this is a file, so the log can not be created inside it")
    audit = JsonlAuditLog(blocker / "audit.jsonl")
    engine = make_engine(FakeLLM(LOW_OK), FakeLLM(agree("access_request")), audit=audit)
    result = engine.triage(LOW_TEXT, PACK)
    assert_human_review(result, pack)
    assert "audit log could not be written" in result.reasons[-1]


def test_unknown_pack_is_a_caller_error(make_engine):
    from trident.packs import PackNotFoundError

    engine = make_engine(FakeLLM(), FakeLLM())
    with pytest.raises(PackNotFoundError) as info:
        engine.triage("text", "no-such-pack")
    assert "it-incidents" in str(info.value)


# ---- the last guard -------------------------------------------------------------


def test_enforce_failsafe_blocks_decided_with_open_reasons(make_engine, pack):
    engine = make_engine(FakeLLM(LOW_OK), FakeLLM(agree("access_request")))
    good = engine.triage(LOW_TEXT, PACK)
    tampered = good.model_copy(update={"reasons": ["something went wrong"]})
    fixed = enforce_failsafe(tampered, pack)
    assert_human_review(fixed, pack)


def test_enforce_failsafe_lifts_lowest_level(make_engine, pack):
    engine = make_engine(FakeLLM(classified("unknown", 0.1)), FakeLLM())
    result = engine.triage(LOW_TEXT, PACK)
    tampered = result.model_copy(update={"level": pack.lowest_level})
    fixed = enforce_failsafe(tampered, pack)
    assert fixed.level == "P2"
    assert fixed.outcome == HUMAN_REVIEW


# ---- every pack, every failure: never the lowest level ---------------------------


FAILURES = {
    "classifier-error": lambda cat, text: (FakeLLM(RuntimeError("down")), FakeLLM()),
    "invalid-json": lambda cat, text: (FakeLLM("oops", "oops again"), FakeLLM()),
    "unknown": lambda cat, text: (FakeLLM(classified("unknown", 0.3)), FakeLLM()),
    "low-confidence": lambda cat, text: (FakeLLM(classified(cat, 0.2, [text[:20]])), FakeLLM()),
    "reviewer-disagrees": lambda cat, text: (FakeLLM(classified(cat, 0.99, [text[:20]])), FakeLLM(disagree(cat))),
    "reviewer-error": lambda cat, text: (FakeLLM(classified(cat, 0.99, [text[:20]])), FakeLLM(TimeoutError("slow"))),
}


@pytest.mark.parametrize("failure", list(FAILURES))
@pytest.mark.parametrize("pack_id", ["medical-demo", "it-incidents", "customer-support"])
def test_no_failure_ever_gives_the_lowest_level(make_engine, registry, pack_id, failure):
    pack = registry.get(pack_id)
    lowest_categories = [c for c in pack.categories if c.level == pack.lowest_level]
    category = lowest_categories[0]
    text = category.examples[0] if category.examples else category.description
    classifier, reviewer = FAILURES[failure](category.id, text)
    result = make_engine(classifier, reviewer).triage(text, pack_id)
    assert_human_review(result, pack)
