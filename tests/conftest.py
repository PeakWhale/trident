from __future__ import annotations

import pytest

from trident.engine import TriageEngine
from trident.packs import PackRegistry


@pytest.fixture(scope="session")
def registry() -> PackRegistry:
    return PackRegistry.load()


@pytest.fixture
def make_engine(registry):
    """Build an engine with fake LLMs. Closes it after the test."""
    engines: list[TriageEngine] = []

    def factory(classifier, reviewer, **kwargs) -> TriageEngine:
        kwargs.setdefault("timeout_s", 5.0)
        engine = TriageEngine(kwargs.pop("packs", registry), classifier, reviewer, **kwargs)
        engines.append(engine)
        return engine

    yield factory
    for engine in engines:
        engine.close()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Tests must not depend on the developer's own TRIDENT_* settings."""
    import os

    for key in list(os.environ):
        if key.startswith("TRIDENT_") or key == "OPENAI_API_KEY":
            monkeypatch.delenv(key, raising=False)
