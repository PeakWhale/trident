"""Every example case in every shipped rule pack gives the expected result.

The fake classifier answers with the expected category, so these tests
check the deterministic part: rules, levels, escalation and the gate.
"""

from __future__ import annotations

import pytest
from fakes import FakeLLM, agree, assert_human_review, classified

from trident import DECIDED, HUMAN_REVIEW
from trident.packs import UNKNOWN, PackRegistry

CASES = [(pack.id, index, example.name) for pack in PackRegistry.load().all() for index, example in enumerate(pack.examples)]


def _evidence(text: str) -> list[str]:
    # A real quote from the text: its first few words.
    return [" ".join(text.split()[:5])]


@pytest.mark.parametrize(("pack_id", "index", "name"), CASES, ids=[f"{p}:{n}" for p, _, n in CASES])
def test_pack_example(make_engine, registry, pack_id, index, name):
    pack = registry.get(pack_id)
    example = pack.examples[index]
    expect = example.expect

    if expect.category in (None, UNKNOWN):
        classifier = FakeLLM(classified(UNKNOWN, 0.3))
    else:
        classifier = FakeLLM(classified(expect.category, 0.95, _evidence(example.text)))
    reviewer = FakeLLM(agree(expect.category or UNKNOWN))

    result = make_engine(classifier, reviewer).triage(example.text, pack_id)

    assert result.outcome == expect.outcome, result.reasons
    if expect.category:
        assert result.category == expect.category
    if expect.level:
        assert result.level == expect.level
    if expect.outcome == HUMAN_REVIEW:
        assert_human_review(result, pack)
    else:
        assert result.outcome == DECIDED
        assert result.reasons == []
        assert result.action == pack.level(result.level).action.strip()


def test_every_pack_has_examples_for_both_outcomes(registry):
    for pack in registry.all():
        outcomes = {example.expect.outcome for example in pack.examples}
        assert outcomes == {DECIDED, HUMAN_REVIEW}, pack.id

