"""HTTP API, through FastAPI's TestClient."""

from __future__ import annotations

import pytest
from fakes import FakeLLM, agree, classified
from fastapi.testclient import TestClient

from trident.server import create_app

TEXT = "The checkout page returns HTTP 503 for all customers since 10:05."
OUTAGE = classified("service_outage", 0.95, ["returns HTTP 503"])


@pytest.fixture
def client_for(make_engine):
    def factory(classifier, reviewer, **engine_kwargs):
        return TestClient(create_app(make_engine(classifier, reviewer, **engine_kwargs)), base_url="http://localhost")

    return factory


def test_health(client_for):
    client = client_for(FakeLLM(name="clf"), FakeLLM(name="rev"))
    data = client.get("/api/health").json()
    assert data["status"] == "ok"
    assert data["models"] == {"classifier": "clf", "reviewer": "rev"}
    assert sorted(data["packs"]) == ["customer-support", "it-incidents", "medical-demo"]


def test_list_and_get_packs(client_for):
    client = client_for(FakeLLM(), FakeLLM())
    packs = client.get("/api/packs").json()
    assert {p["id"] for p in packs} == {"customer-support", "it-incidents", "medical-demo"}
    it = client.get("/api/packs/it-incidents").json()
    assert [lvl["id"] for lvl in it["levels"]] == ["P1", "P2", "P3", "P4"]
    assert it["lowest_level"] == "P4"
    assert it["examples"]
    medical = client.get("/api/packs/medical-demo").json()
    assert "not for real patients" in medical["disclaimer"].lower()


def test_get_unknown_pack(client_for):
    response = client_for(FakeLLM(), FakeLLM()).get("/api/packs/nope")
    assert response.status_code == 404
    assert "Available packs" in response.json()["detail"]


def test_triage_decided(client_for):
    client = client_for(FakeLLM(OUTAGE), FakeLLM(agree("service_outage")))
    response = client.post("/api/triage", json={"text": TEXT, "pack": "it-incidents"})
    assert response.status_code == 200
    data = response.json()
    assert data["outcome"] == "DECIDED"
    assert data["level"] == "P1"
    assert data["route_to"] == "SRE on-call"
    assert data["evidence"] == ["returns HTTP 503"]
    assert [s["name"] for s in data["steps"]] == [
        "validate_input",
        "screen_rules",
        "classify",
        "apply_rules",
        "review",
        "decide",
    ]
    assert data["timing_ms"]["total"] >= 0
    assert data["rule_matched"]["category"] == "service_outage"


def test_triage_model_down_gives_human_review_not_an_error(client_for):
    client = client_for(FakeLLM(ConnectionError("ollama is not running")), FakeLLM())
    response = client.post("/api/triage", json={"text": TEXT, "pack": "it-incidents"})
    assert response.status_code == 200
    data = response.json()
    assert data["outcome"] == "NEEDS_HUMAN_REVIEW"
    assert data["needs_human_review"] is True
    assert data["level"] != "P4"
    assert "ollama is not running" in data["reasons"][0]


def test_triage_unknown_pack(client_for):
    response = client_for(FakeLLM(), FakeLLM()).post("/api/triage", json={"text": TEXT, "pack": "nope"})
    assert response.status_code == 404


@pytest.mark.parametrize(
    "body",
    [{"text": "", "pack": "it-incidents"}, {"text": TEXT}, {"pack": "it-incidents"}, {"text": TEXT, "pack": ""}],
)
def test_triage_bad_request(client_for, body):
    response = client_for(FakeLLM(), FakeLLM()).post("/api/triage", json=body)
    assert response.status_code == 422


# ---- a web page must not be able to use the local server --------------------


@pytest.mark.parametrize("host", ["rebind.attacker.example:8765", "evil.example", "127.0.0.1.nip.io:8000", ""])
def test_unknown_host_header_is_rejected(make_engine, host):
    classifier = FakeLLM(OUTAGE)
    client = TestClient(create_app(make_engine(classifier, FakeLLM(agree("service_outage")))))
    headers = {"Host": host, "Origin": f"http://{host}"}
    assert client.get("/api/health", headers=headers).status_code == 400
    response = client.post("/api/triage", json={"text": TEXT, "pack": "it-incidents"}, headers=headers)
    assert response.status_code == 400
    assert classifier.calls == []


@pytest.mark.parametrize("host", ["localhost", "localhost:8000", "127.0.0.1:8765", "[::1]:8000", "LOCALHOST"])
def test_local_host_headers_are_allowed(make_engine, host):
    client = TestClient(create_app(make_engine(FakeLLM(), FakeLLM())))
    assert client.get("/api/health", headers={"Host": host}).status_code == 200


def test_allowed_hosts_setting(make_engine, monkeypatch):
    monkeypatch.setenv("TRIDENT_ALLOWED_HOSTS", "trident.internal, Other.Example")
    client = TestClient(create_app(make_engine(FakeLLM(), FakeLLM())))
    assert client.get("/api/health", headers={"Host": "trident.internal:8000"}).status_code == 200
    assert client.get("/api/health", headers={"Host": "other.example"}).status_code == 200
    assert client.get("/api/health", headers={"Host": "localhost"}).status_code == 400
    any_host = TestClient(create_app(make_engine(FakeLLM(), FakeLLM()), allowed_hosts=["*"]))
    assert any_host.get("/api/health", headers={"Host": "anything.example"}).status_code == 200


@pytest.mark.parametrize("content_type", [None, "text/plain", "application/x-www-form-urlencoded", "multipart/form-data"])
def test_triage_needs_a_json_content_type(client_for, content_type):
    import json

    classifier = FakeLLM(OUTAGE)
    client = client_for(classifier, FakeLLM(agree("service_outage")))
    headers = {"Content-Type": content_type} if content_type else {}
    body = json.dumps({"text": TEXT, "pack": "it-incidents"}).encode()
    response = client.post("/api/triage", content=body, headers=headers)
    assert response.status_code == 415
    assert classifier.calls == []


def test_json_content_type_with_charset_is_fine(client_for):
    import json

    client = client_for(FakeLLM(OUTAGE), FakeLLM(agree("service_outage")))
    body = json.dumps({"text": TEXT, "pack": "it-incidents"}).encode()
    response = client.post("/api/triage", content=body, headers={"Content-Type": "application/json; charset=utf-8"})
    assert response.status_code == 200
    assert response.json()["outcome"] == "DECIDED"


def test_web_ui_is_served(client_for):
    client = client_for(FakeLLM(), FakeLLM())
    page = client.get("/")
    assert page.status_code == 200
    assert "TRIDENT" in page.text
    assert client.get("/app.js").status_code == 200
    assert client.get("/style.css").status_code == 200
