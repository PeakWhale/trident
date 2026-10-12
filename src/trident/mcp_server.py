"""MCP server, so AI assistants can use Trident as a tool.

Tools:
* list_packs()          - the rule packs you can use
* triage(text, pack)    - sort one case with a rule pack

Run it with the `trident-mcp` command (stdio transport).
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from typing import Any

import anyio
from mcp.server.fastmcp import FastMCP

from . import __version__
from .engine import TriageEngine
from .packs import PackNotFoundError

INSTRUCTIONS = """\
PeakWhale Trident sorts text (tickets, messages, reports) with an "AI plus rules" engine.
1. Call list_packs to see the rule packs and their levels.
2. Call triage with the text and a pack id.
3. If the result's outcome is NEEDS_HUMAN_REVIEW, tell the user that a person must decide.
   Do not present the level as final. The 'level' is only a safe "treat as" level while waiting.
The medical-demo pack is a demo only. Never use it for real patients or clinical decisions.
"""


def build_server(engine_factory: Callable[[], TriageEngine] | None = None) -> FastMCP:
    """Create the MCP server. The engine is created on first use."""
    factory = engine_factory or TriageEngine.from_settings
    holder: dict[str, TriageEngine] = {}

    def engine() -> TriageEngine:
        if "engine" not in holder:
            holder["engine"] = factory()
        return holder["engine"]

    server = FastMCP("peakwhale-trident", instructions=INSTRUCTIONS)

    @server.tool()
    def list_packs() -> list[dict[str, Any]]:
        """List the rule packs. Each has an id, name, description, levels (most urgent first),
        categories and an optional disclaimer."""
        return [pack.summary() for pack in engine().packs.all()]

    @server.tool()
    async def triage(text: str, pack: str, include_steps: bool = False) -> dict[str, Any]:
        """Sort one case with a rule pack.

        Args:
            text: The case to sort, as plain text (for example a ticket or a message).
            pack: The rule pack id, for example "it-incidents". See list_packs.
            include_steps: Also return the full audit trail of every step.

        Returns the decision. outcome is DECIDED or NEEDS_HUMAN_REVIEW. For
        NEEDS_HUMAN_REVIEW a person must decide; 'reasons' says why.
        """
        eng = engine()
        try:
            result = await anyio.to_thread.run_sync(eng.triage, text, pack)
        except PackNotFoundError as exc:
            raise ValueError(str(exc)) from None
        data = result.model_dump(mode="json")
        if not include_steps:
            data.pop("steps", None)
        return data

    return server


def main() -> None:
    from .config import load_dotenv_if_present

    load_dotenv_if_present()
    # stdout is used by the MCP protocol, so logs go to stderr.
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    logging.getLogger("trident").info("Starting PeakWhale Trident MCP server %s", __version__)
    build_server().run("stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
