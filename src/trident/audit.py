"""Optional audit log: one JSON line per decision."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Protocol


class AuditSink(Protocol):
    def write(self, record: dict[str, Any]) -> None: ...


class JsonlAuditLog:
    """Appends each decision as one JSON line to a file.

    Note: the line includes the input text. Protect this file like any
    other data that may contain personal information.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def write(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
