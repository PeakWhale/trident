"""Audit trail: every decision explains itself, and can be logged as JSONL."""

from __future__ import annotations

import json

from fakes import FakeLLM, agree, classified

from trident.audit import JsonlAuditLog
from trident.config import Settings
from trident.engine import TriageEngine

TEXT = "My laptop will not connect to the office Wi-Fi since this morning."
ANSWER = classified("single_user_issue", 0.9, ["will not connect to the office Wi-Fi"])


def test_result_has_steps_models_and_timings(make_engine):
    result = make_engine(FakeLLM(ANSWER, name="clf"), FakeLLM(agree("single_user_issue"), name="rev")).triage(
        TEXT, "it-incidents"
    )
    assert result.models == {"classifier": "clf", "reviewer": "rev"}
    names = [s.name for s in result.steps]
    assert names == ["validate_input", "screen_rules", "classify", "apply_rules", "review", "decide"]
    for s in result.steps:
        assert s.started_at.endswith("+00:00")
        assert s.duration_ms >= 0
        assert result.timing_ms[s.name] == s.duration_ms
    assert result.timing_ms["total"] >= sum(s.duration_ms for s in result.steps) - 0.1

    classify = result.steps[2].data
    assert classify["model"] == "clf"
    assert json.loads(classify["attempts"][0]["raw_output"]) == ANSWER
    assert classify["output"] == ANSWER
    assert result.steps[4].data["output"]["agrees"] is True
    assert result.rule_matched == {
        "category": "single_user_issue",
        "category_level": "P3",
        "final_level": "P3",
        "raised_by": [],
        "min_confidence": 0.7,
        "route_to": "Service desk",
        "always_human_review": False,
    }
    assert result.engine_version
    assert result.pack_version == "1.0"
    assert len(result.request_id) == 32


def test_jsonl_log_gets_one_line_per_decision(make_engine, tmp_path):
    log = tmp_path / "logs" / "audit.jsonl"
    engine = make_engine(
        FakeLLM(ANSWER, RuntimeError("down")),
        FakeLLM(agree("single_user_issue")),
        audit=JsonlAuditLog(log),
    )
    first = engine.triage(TEXT, "it-incidents")
    second = engine.triage(TEXT, "it-incidents")

    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    records = [json.loads(line) for line in lines]
    assert records[0]["request_id"] == first.request_id
    assert records[0]["outcome"] == "DECIDED"
    assert records[1]["request_id"] == second.request_id
    assert records[1]["outcome"] == "NEEDS_HUMAN_REVIEW"
    assert records[1]["steps"][2]["status"] == "error"


def test_audit_log_from_settings(tmp_path):
    settings = Settings.from_env({"TRIDENT_AUDIT_LOG": str(tmp_path / "a.jsonl")})
    engine = TriageEngine.from_settings(settings)
    try:
        assert isinstance(engine.audit, JsonlAuditLog)
        assert engine.audit.path == tmp_path / "a.jsonl"
    finally:
        engine.close()
