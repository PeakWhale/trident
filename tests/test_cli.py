"""The `trident` command line tool."""

from __future__ import annotations

import json

from fakes import FakeLLM, agree, classified
from test_packs import pack_with

from trident import cli
from trident.engine import TriageEngine


def test_packs_command(capsys):
    assert cli.main(["packs"]) == 0
    out = capsys.readouterr().out
    assert "it-incidents" in out
    assert "P1 > P2 > P3 > P4" in out
    assert "[DEMO ONLY]" in out


def test_validate_command(tmp_path, capsys):
    good = tmp_path / "good.yaml"
    good.write_text(pack_with())
    bad = tmp_path / "bad.yaml"
    bad.write_text(pack_with(escalation__human_review__interim_level="low"))

    assert cli.main(["validate"]) == 0
    assert cli.main(["validate", str(good)]) == 0
    assert cli.main(["validate", str(good), str(bad)]) == 1
    out = capsys.readouterr().out
    assert "OK   " in out
    assert "FAIL" in out and "lowest level" in out


def test_triage_command(registry, monkeypatch, capsys):
    engine = TriageEngine(
        registry,
        FakeLLM(classified("feature_request", 0.9, ["dark mode"])),
        FakeLLM(agree("feature_request")),
    )
    monkeypatch.setattr(TriageEngine, "from_settings", classmethod(lambda cls, settings=None: engine))
    assert cli.main(["triage", "--pack", "customer-support", "Please add a dark mode."]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["outcome"] == "DECIDED"
    assert data["level"] == "low"


def test_triage_command_unknown_pack(registry, monkeypatch, capsys):
    engine = TriageEngine(registry, FakeLLM(), FakeLLM())
    monkeypatch.setattr(TriageEngine, "from_settings", classmethod(lambda cls, settings=None: engine))
    assert cli.main(["triage", "--pack", "nope", "text"]) == 2
    assert "Unknown rule pack" in capsys.readouterr().err
