"""The `trident` command line tool."""

from __future__ import annotations

import json

import pytest
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


@pytest.mark.parametrize(
    ("env", "argv", "message"),
    [
        ({"TRIDENT_PACKS_DIR": "/nonexistent-trident-packs"}, ["packs"], "rule pack folder does not exist"),
        ({"TRIDENT_PACKS_DIR": "/nonexistent-trident-packs"}, ["triage", "--pack", "it-incidents", "hi"], "not exist"),
        ({"TRIDENT_PACKS_DIR": "/nonexistent-trident-packs"}, ["validate"], "does not exist"),
        ({"TRIDENT_LLM_TIMEOUT": "abc"}, ["validate"], "TRIDENT_LLM_TIMEOUT must be a number"),
        ({"TRIDENT_LLM_PROVIDER": "anthropic"}, ["triage", "--pack", "it-incidents", "hi"], "TRIDENT_LLM_PROVIDER"),
    ],
)
def test_bad_settings_give_one_line_not_a_traceback(monkeypatch, capsys, env, argv, message):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert cli.main(argv) == 1
    captured = capsys.readouterr()
    assert message in captured.err + captured.out
    assert "Traceback" not in captured.err


def test_broken_pack_in_folder_gives_one_line(tmp_path, monkeypatch, capsys):
    (tmp_path / "broken.yaml").write_text(pack_with(categories__0__level="nope"))
    monkeypatch.setenv("TRIDENT_PACKS_DIR", str(tmp_path))
    assert cli.main(["packs"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("error: ") and "broken.yaml" in err and len(err.strip().splitlines()) == 1


@pytest.mark.parametrize("module", ["server", "mcp_server"])
def test_servers_stop_with_one_line_on_bad_settings(monkeypatch, capsys, module):
    import importlib

    target = importlib.import_module(f"trident.{module}")
    monkeypatch.setenv("TRIDENT_PACKS_DIR", "/nonexistent-trident-packs")
    with pytest.raises(SystemExit) as info:
        target.main()
    assert info.value.code == 1
    assert "error: " in capsys.readouterr().err
