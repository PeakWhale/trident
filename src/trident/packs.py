"""Rule packs: the editable rules that drive the triage engine.

A rule pack is a YAML (or JSON) file. It lists:

* levels      - the possible outcomes, most urgent first (for example P1..P4)
* categories  - what the LLM may choose from, with a description and examples,
                and the level each category maps to
* escalation  - when a case must go to a human, and red-flag word rules
* examples    - sample cases with the expected result (used by the UI and tests)

The engine itself knows nothing about any domain. All domain knowledge
lives in the pack.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from functools import cached_property
from importlib import resources
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

logger = logging.getLogger("trident.packs")

UNKNOWN = "unknown"
PACK_SUFFIXES = (".yaml", ".yml", ".json")
ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"

Color = Literal["red", "orange", "yellow", "green", "blue", "gray"]


class PackError(ValueError):
    """A rule pack file is missing, unreadable or invalid."""


class PackNotFoundError(KeyError):
    """No rule pack with the given id is loaded."""

    def __init__(self, pack_id: str, available: Iterable[str]):
        self.pack_id = pack_id
        self.available = sorted(available)
        super().__init__(pack_id)

    def __str__(self) -> str:
        return f"Unknown rule pack '{self.pack_id}'. Available packs: {', '.join(self.available) or 'none'}"


class _Strict(BaseModel):
    # Unknown keys are an error, so a typo in a rule pack is caught early.
    model_config = ConfigDict(extra="forbid", frozen=True)


class Level(_Strict):
    id: str = Field(pattern=ID_PATTERN)
    label: str = Field(min_length=1)
    color: Color = "gray"
    action: str = Field(min_length=1)


class Category(_Strict):
    id: str = Field(pattern=ID_PATTERN)
    description: str = Field(min_length=1)
    examples: list[str] = Field(default_factory=list)
    level: str
    route_to: str | None = None
    # Optional: a stricter confidence limit for this category only.
    min_confidence: float | None = Field(default=None, ge=0, le=1)
    # Optional: always send this category to a human.
    always_human_review: bool = False


class EscalationRule(_Strict):
    id: str = Field(pattern=ID_PATTERN)
    words: list[str] = Field(min_length=1)
    then: Literal["human_review", "min_level"]
    # For "min_level" this is required: the level can not be lower than this.
    # For "human_review" it is optional: the "treat as" level while waiting
    # for a person can not be lower than this.
    level: str | None = None
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> EscalationRule:
        if self.then == "min_level" and not self.level:
            raise ValueError(f"escalation rule '{self.id}': 'then: min_level' needs a 'level'")
        if any(not w.strip() for w in self.words):
            raise ValueError(f"escalation rule '{self.id}': words can not be empty")
        return self

    @cached_property
    def pattern(self) -> re.Pattern[str]:
        parts = []
        for word in self.words:
            escaped = r"\s+".join(re.escape(piece) for piece in word.strip().split())
            parts.append(rf"(?<!\w){escaped}(?!\w)")
        return re.compile("|".join(parts), re.IGNORECASE)

    def find(self, text: str) -> list[str]:
        """Return the words of this rule that appear in the text."""
        return sorted({" ".join(m.group(0).lower().split()) for m in self.pattern.finditer(text)})


class HumanReview(_Strict):
    label: str = "NEEDS HUMAN REVIEW"
    action: str = Field(min_length=1)
    route_to: str | None = None
    # While a case waits for a person, treat it as this level.
    # It must NOT be the lowest level (checked when the pack loads).
    interim_level: str


class Escalation(_Strict):
    min_confidence: float = Field(default=0.7, ge=0, le=1)
    human_review: HumanReview
    rules: list[EscalationRule] = Field(default_factory=list)


class ExampleExpectation(_Strict):
    outcome: Literal["DECIDED", "NEEDS_HUMAN_REVIEW"]
    category: str | None = None
    level: str | None = None


class Example(_Strict):
    name: str = Field(min_length=1)
    text: str = Field(min_length=1)
    expect: ExampleExpectation


class RulePack(_Strict):
    id: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1)
    version: str = "1"
    description: str = ""
    disclaimer: str | None = None
    levels: list[Level] = Field(min_length=2)
    categories: list[Category] = Field(min_length=1)
    escalation: Escalation
    examples: list[Example] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _version_as_text(cls, data: Any) -> Any:
        # Let people write `version: 1` or `version: 1.2` in YAML.
        if isinstance(data, dict) and isinstance(data.get("version"), (int, float)):
            data = {**data, "version": str(data["version"])}
        return data

    @model_validator(mode="after")
    def _check_references(self) -> RulePack:
        level_ids = [lvl.id for lvl in self.levels]
        _no_duplicates("level", level_ids)
        category_ids = [cat.id for cat in self.categories]
        _no_duplicates("category", category_ids)
        _no_duplicates("escalation rule", [rule.id for rule in self.escalation.rules])

        if UNKNOWN in category_ids:
            raise ValueError(f"'{UNKNOWN}' is reserved and can not be a category id")
        known = set(level_ids)
        for cat in self.categories:
            if cat.level not in known:
                raise ValueError(f"category '{cat.id}' uses unknown level '{cat.level}'")
        for rule in self.escalation.rules:
            if rule.level is not None and rule.level not in known:
                raise ValueError(f"escalation rule '{rule.id}' uses unknown level '{rule.level}'")

        interim = self.escalation.human_review.interim_level
        if interim not in known:
            raise ValueError(f"human_review.interim_level '{interim}' is not a level")
        if interim == level_ids[-1]:
            raise ValueError(
                f"human_review.interim_level can not be the lowest level ('{interim}'). "
                "A case that waits for a person must never be treated as the lowest level."
            )

        for ex in self.examples:
            if ex.expect.category not in (None, UNKNOWN, *category_ids):
                raise ValueError(f"example '{ex.name}' expects unknown category '{ex.expect.category}'")
            if ex.expect.level is not None and ex.expect.level not in known:
                raise ValueError(f"example '{ex.name}' expects unknown level '{ex.expect.level}'")
        return self

    # ---- helpers used by the engine -------------------------------------

    @property
    def lowest_level(self) -> str:
        return self.levels[-1].id

    def level(self, level_id: str) -> Level:
        for lvl in self.levels:
            if lvl.id == level_id:
                return lvl
        raise KeyError(level_id)

    def category(self, category_id: str) -> Category | None:
        for cat in self.categories:
            if cat.id == category_id:
                return cat
        return None

    @property
    def category_ids(self) -> list[str]:
        return [cat.id for cat in self.categories]

    def rank(self, level_id: str) -> int:
        """0 is the most urgent level."""
        for index, lvl in enumerate(self.levels):
            if lvl.id == level_id:
                return index
        raise KeyError(level_id)

    def most_urgent(self, *level_ids: str | None) -> str | None:
        present = [lvl for lvl in level_ids if lvl]
        if not present:
            return None
        return min(present, key=self.rank)

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description.strip(),
            "disclaimer": self.disclaimer.strip() if self.disclaimer else None,
            "levels": [lvl.id for lvl in self.levels],
            "categories": self.category_ids,
        }


def _no_duplicates(kind: str, ids: list[str]) -> None:
    seen: set[str] = set()
    for item in ids:
        if item in seen:
            raise ValueError(f"duplicate {kind} id '{item}'")
        seen.add(item)


def load_pack(path: str | Path) -> RulePack:
    """Load and validate one rule pack file (YAML or JSON)."""
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise PackError(f"{path}: can not read file ({exc})") from exc
    return parse_pack(raw, source=str(path))


def parse_pack(raw: str, source: str = "<text>", fmt: Literal["yaml", "json"] | None = None) -> RulePack:
    """Parse and validate a rule pack. The format comes from `fmt`, else from the
    file name in `source` (.json is JSON, anything else is YAML)."""
    if fmt is None:
        fmt = "json" if source.lower().endswith(".json") else "yaml"
    try:
        # JSON goes to a real JSON parser: YAML 1.1 rejects tabs and turns
        # escaped emoji (\ud83d\ude21) into two broken characters.
        data = json.loads(raw) if fmt == "json" else yaml.safe_load(raw)
    except json.JSONDecodeError as exc:
        raise PackError(f"{source}: not valid JSON ({exc})") from exc
    except yaml.YAMLError as exc:
        raise PackError(f"{source}: not valid YAML ({exc})") from exc
    if not isinstance(data, dict):
        raise PackError(f"{source}: a rule pack must be a mapping at the top level")
    bad = _broken_text(data)
    if bad is not None:
        raise PackError(f"{source}: {bad} has an invalid character (a lone surrogate, often a broken emoji escape)")
    try:
        return RulePack.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or 'pack'}: {err['msg']}" for err in exc.errors()
        )
        raise PackError(f"{source}: invalid rule pack - {problems}") from exc


def _broken_text(data: Any, where: str = "pack") -> str | None:
    """The place of the first text that can not be written as UTF-8, or None."""
    if isinstance(data, str):
        try:
            data.encode("utf-8")
        except UnicodeEncodeError:
            return where
    elif isinstance(data, dict):
        for key, value in data.items():
            found = _broken_text(key, where) or _broken_text(value, f"{where}.{key}")
            if found:
                return found
    elif isinstance(data, list):
        for index, value in enumerate(data):
            found = _broken_text(value, f"{where}.{index}")
            if found:
                return found
    return None


def builtin_pack_files() -> list[Path]:
    folder = resources.files("trident") / "packs"
    return sorted(
        Path(str(entry)) for entry in folder.iterdir() if entry.name.endswith(PACK_SUFFIXES)
    )


def pack_files_in(folder: str | Path) -> list[Path]:
    folder = Path(folder)
    if not folder.is_dir():
        raise PackError(f"{folder}: rule pack folder does not exist")
    return sorted(p for p in folder.iterdir() if p.suffix in PACK_SUFFIXES and p.is_file())


class PackRegistry:
    """All loaded rule packs, by id."""

    def __init__(self, packs: Iterable[RulePack]):
        self._packs: dict[str, RulePack] = {}
        for pack in packs:
            if pack.id in self._packs:
                logger.info("Rule pack '%s' is replaced by a later file", pack.id)
            self._packs[pack.id] = pack

    @classmethod
    def load(cls, extra_dirs: Iterable[str | Path] = (), include_builtin: bool = True) -> PackRegistry:
        """Load the built-in packs, then packs from extra folders.

        A pack in an extra folder with the same id as a built-in pack
        replaces the built-in one.
        """
        files: list[Path] = builtin_pack_files() if include_builtin else []
        for folder in extra_dirs:
            files.extend(pack_files_in(folder))
        return cls(load_pack(f) for f in files)

    def get(self, pack_id: str) -> RulePack:
        try:
            return self._packs[pack_id]
        except KeyError:
            raise PackNotFoundError(pack_id, self._packs) from None

    def all(self) -> list[RulePack]:
        return list(self._packs.values())

    def ids(self) -> list[str]:
        return list(self._packs)

    def __contains__(self, pack_id: object) -> bool:
        return pack_id in self._packs

    def __len__(self) -> int:
        return len(self._packs)
