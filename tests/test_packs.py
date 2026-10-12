"""Rule pack loading and validation."""

from __future__ import annotations

import copy
import json

import pytest
import yaml

from trident.packs import PackError, PackNotFoundError, PackRegistry, load_pack, parse_pack

BASE = {
    "id": "test-pack",
    "name": "Test pack",
    "version": 1,
    "levels": [
        {"id": "high", "label": "High", "color": "red", "action": "Act now."},
        {"id": "mid", "label": "Mid", "color": "yellow", "action": "Act today."},
        {"id": "low", "label": "Low", "color": "green", "action": "Act later."},
    ],
    "categories": [
        {"id": "fire", "description": "Something is on fire.", "level": "high"},
        {"id": "question", "description": "A question.", "level": "low", "examples": ["How do I?"]},
    ],
    "escalation": {
        "min_confidence": 0.8,
        "human_review": {"action": "Ask a person.", "interim_level": "mid"},
        "rules": [{"id": "smoke", "words": ["smoke", "burning smell"], "then": "min_level", "level": "high", "reason": "Smoke."}],
    },
    "examples": [{"name": "Fire", "text": "The bin is on fire", "expect": {"outcome": "DECIDED", "category": "fire", "level": "high"}}],
}


def pack_with(**changes):
    data = copy.deepcopy(BASE)
    for path, value in changes.items():
        target = data
        keys = path.split("__")
        for key in keys[:-1]:
            target = target[int(key)] if isinstance(target, list) else target[key]
        last = keys[-1]
        if isinstance(target, list):
            target[int(last)] = value
        else:
            target[last] = value
    return yaml.safe_dump(data)


def test_base_pack_is_valid():
    pack = parse_pack(pack_with())
    assert pack.id == "test-pack"
    assert pack.version == "1"
    assert pack.lowest_level == "low"
    assert pack.most_urgent("low", "mid", None) == "mid"
    assert pack.most_urgent() is None


def test_builtin_packs(registry):
    assert sorted(registry.ids()) == ["customer-support", "it-incidents", "medical-demo"]
    for pack in registry.all():
        assert pack.escalation.human_review.interim_level != pack.lowest_level
        assert pack.examples


def test_medical_pack_is_clearly_marked_demo_only(registry):
    pack = registry.get("medical-demo")
    text = pack.disclaimer.lower()
    assert "demo only" in text
    assert "not for real patients or clinical decisions" in text
    assert "demo" in pack.name.lower()
    for other in ("it-incidents", "customer-support"):
        assert registry.get(other).disclaimer is None


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"categories__0__level": "nope"}, "unknown level 'nope'"),
        ({"categories__1__id": "fire"}, "duplicate category id 'fire'"),
        ({"levels__1__id": "high"}, "duplicate level id 'high'"),
        ({"categories__1__id": "unknown"}, "'unknown' is reserved"),
        ({"escalation__human_review__interim_level": "low"}, "can not be the lowest level"),
        ({"escalation__human_review__interim_level": "nope"}, "is not a level"),
        ({"escalation__rules__0__level": None}, "needs a 'level'"),
        ({"escalation__rules__0__level": "nope"}, "uses unknown level 'nope'"),
        ({"escalation__rules__0__words": []}, "at least 1 item"),
        ({"escalation__min_confidence": 1.5}, "less than or equal to 1"),
        ({"levels": [BASE["levels"][0]]}, "at least 2 items"),
        ({"categories": []}, "at least 1 item"),
        ({"levels__0__color": "pink"}, "levels.0.color"),
        ({"categories__0__id": "has space"}, "categories.0.id"),
        ({"examples__0__expect__category": "nope"}, "expects unknown category 'nope'"),
        ({"categores": []}, "Extra inputs are not permitted"),
        ({"escalation__human_review__acton": "typo"}, "Extra inputs are not permitted"),
    ],
)
def test_invalid_packs_are_rejected(changes, message):
    with pytest.raises(PackError) as info:
        parse_pack(pack_with(**changes), source="test.yaml")
    assert message in str(info.value)
    assert "test.yaml" in str(info.value)


def test_not_a_mapping_or_bad_yaml():
    with pytest.raises(PackError, match="mapping"):
        parse_pack("- just\n- a list\n")
    with pytest.raises(PackError, match="not valid YAML"):
        parse_pack("id: [unclosed")


def test_json_packs_work(tmp_path):
    path = tmp_path / "test.json"
    path.write_text(json.dumps(BASE))
    assert load_pack(path).id == "test-pack"


def test_missing_file(tmp_path):
    with pytest.raises(PackError, match="can not read"):
        load_pack(tmp_path / "missing.yaml")


def test_extra_folder_adds_and_replaces_packs(tmp_path):
    (tmp_path / "mine.yaml").write_text(pack_with())
    (tmp_path / "it.yaml").write_text(pack_with(id="it-incidents", name="My own IT pack"))
    (tmp_path / "notes.txt").write_text("ignored")
    registry = PackRegistry.load([tmp_path])
    assert "test-pack" in registry
    assert registry.get("it-incidents").name == "My own IT pack"
    assert len(registry) == 4


def test_extra_folder_with_a_broken_pack_fails_loudly(tmp_path):
    (tmp_path / "broken.yaml").write_text(pack_with(categories__0__level="nope"))
    with pytest.raises(PackError, match="broken.yaml"):
        PackRegistry.load([tmp_path])


def test_missing_extra_folder(tmp_path):
    with pytest.raises(PackError, match="does not exist"):
        PackRegistry.load([tmp_path / "nope"])


def test_unknown_pack_lists_the_available_ones(registry):
    with pytest.raises(PackNotFoundError) as info:
        registry.get("nope")
    assert str(info.value) == "Unknown rule pack 'nope'. Available packs: customer-support, it-incidents, medical-demo"


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("I smell SMOKE in the hall", ["smoke"]),
        ("there is a burning   smell", ["burning smell"]),
        ("smoke and a burning smell", ["burning smell", "smoke"]),
        ("smokehouse menu", []),
        ("non-smoker", []),
    ],
)
def test_escalation_words_match_whole_words(text, found):
    rule = parse_pack(pack_with()).escalation.rules[0]
    assert rule.find(text) == found


def test_sue_does_not_match_issue(registry):
    rule = next(r for r in registry.get("customer-support").escalation.rules if r.id == "legal-words")
    assert rule.find("I have an issue with my invoice") == []
    assert rule.find("I will sue you") == ["sue"]
