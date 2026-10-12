"""FastAPI web server: JSON API plus the web UI."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .engine import TriageEngine
from .models import TriageResult
from .packs import PackNotFoundError, RulePack

STATIC_DIR = Path(__file__).parent / "static"
MAX_REQUEST_CHARS = 50_000

logger = logging.getLogger("trident.server")


class TriageRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_REQUEST_CHARS, description="The case to sort, as plain text.")
    pack: str = Field(min_length=1, max_length=100, description="Rule pack id, for example 'it-incidents'.")


def pack_details(pack: RulePack) -> dict[str, Any]:
    data = pack.model_dump(mode="json")
    data["lowest_level"] = pack.lowest_level
    return data


def create_app(engine: TriageEngine | None = None) -> FastAPI:
    """Build the app. Pass an engine to use a custom (or fake) LLM, for example in tests."""
    app = FastAPI(
        title="PeakWhale Trident",
        version=__version__,
        description="Fail-safe AI plus rules triage engine. Unclear cases go to a human.",
    )
    holder: dict[str, TriageEngine] = {}
    if engine is not None:
        holder["engine"] = engine

    def get_engine() -> TriageEngine:
        if "engine" not in holder:
            holder["engine"] = TriageEngine.from_settings()
        return holder["engine"]

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        eng = get_engine()
        return {"status": "ok", "version": __version__, "packs": eng.packs.ids(), "models": eng.model_names}

    @app.get("/api/packs")
    def list_packs() -> list[dict[str, Any]]:
        return [pack_details(p) for p in get_engine().packs.all()]

    @app.get("/api/packs/{pack_id}")
    def get_pack(pack_id: str) -> dict[str, Any]:
        try:
            return pack_details(get_engine().packs.get(pack_id))
        except PackNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    # A plain `def` runs in a worker thread, so slow model calls do not block the server.
    @app.post("/api/triage", response_model=TriageResult)
    def triage(request: TriageRequest) -> TriageResult:
        try:
            return get_engine().triage(request.text, request.pack)
        except PackNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    # Static files last, so the API routes win.
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


def main(host: str | None = None, port: int | None = None) -> None:
    import uvicorn

    from .config import load_dotenv_if_present

    load_dotenv_if_present()
    logging.basicConfig(level=os.environ.get("TRIDENT_LOG_LEVEL", "INFO"))
    host = host or os.environ.get("TRIDENT_HOST", "127.0.0.1")
    port = port or int(os.environ.get("TRIDENT_PORT", "8000"))
    # Build the engine now, so a broken rule pack or setting fails at start-up.
    app = create_app(TriageEngine.from_settings())
    print(f"PEAKWHALE TRIDENT {__version__} - open http://{'localhost' if host in ('0.0.0.0', '127.0.0.1') else host}:{port}")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":  # pragma: no cover
    main()
