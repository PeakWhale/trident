"""FastAPI web server: JSON API plus the web UI."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .engine import TriageEngine
from .models import TriageResult
from .packs import PackError, PackNotFoundError, RulePack

STATIC_DIR = Path(__file__).parent / "static"
# Hard limit for one request. Text above TRIDENT_MAX_INPUT_CHARS but below this
# limit gets NEEDS_HUMAN_REVIEW. Text above this limit gets HTTP 422.
MAX_REQUEST_CHARS = 50_000
# Host names the server answers to. Other Host headers get HTTP 400, which
# blocks DNS rebinding from a web page. Set TRIDENT_ALLOWED_HOSTS to change it.
DEFAULT_ALLOWED_HOSTS = ("127.0.0.1", "localhost", "[::1]")
WILDCARD_BINDS = ("0.0.0.0", "::", "")

logger = logging.getLogger("trident.server")


class TriageRequest(BaseModel):
    text: str = Field(description="The case to sort, as plain text. Empty text gives NEEDS_HUMAN_REVIEW.")
    pack: str = Field(min_length=1, max_length=100, description="Rule pack id, for example 'it-incidents'.")


def allowed_hosts_from_env() -> list[str] | None:
    """TRIDENT_ALLOWED_HOSTS as a list (comma separated), or None when it is not set."""
    value = os.environ.get("TRIDENT_ALLOWED_HOSTS", "")
    hosts = [h.strip().lower() for h in value.split(",") if h.strip()]
    return hosts or None


def _host_name(header: str) -> str:
    """The host name of a Host header, without the port. Keeps IPv6 brackets."""
    header = header.strip().lower()
    if header.startswith("["):
        end = header.find("]")
        return header[: end + 1] if end != -1 else header
    return header.split(":", 1)[0]


def pack_details(pack: RulePack) -> dict[str, Any]:
    data = pack.model_dump(mode="json")
    data["lowest_level"] = pack.lowest_level
    return data


def create_app(engine: TriageEngine | None = None, allowed_hosts: Iterable[str] | None = None) -> FastAPI:
    """Build the app. Pass an engine to use a custom (or fake) LLM, for example in tests.

    allowed_hosts: host names the server answers to. Default: TRIDENT_ALLOWED_HOSTS,
    else 127.0.0.1, localhost and [::1]. Use ["*"] to allow any host name.
    """
    app = FastAPI(
        title="PeakWhale Trident",
        version=__version__,
        description="Fail-safe AI plus rules triage engine. Unclear cases go to a human.",
    )
    holder: dict[str, TriageEngine] = {}
    if engine is not None:
        holder["engine"] = engine
    if allowed_hosts is None:
        allowed_hosts = allowed_hosts_from_env() or DEFAULT_ALLOWED_HOSTS
    hosts = {h.strip().lower() for h in allowed_hosts}
    allow_any_host = "*" in hosts

    def get_engine() -> TriageEngine:
        if "engine" not in holder:
            holder["engine"] = TriageEngine.from_settings()
        return holder["engine"]

    @app.middleware("http")
    async def guard(request: Request, call_next):
        # A web page in the browser can send requests to localhost. Two checks stop
        # it from using this server: the Host header must be a known name (stops
        # DNS rebinding), and a POST must say it is JSON (a page can only send that
        # cross-site after a CORS preflight, which this server does not allow).
        if not allow_any_host and _host_name(request.headers.get("host", "")) not in hosts:
            return JSONResponse({"detail": "Invalid host header. See TRIDENT_ALLOWED_HOSTS."}, status_code=400)
        if request.method == "POST" and request.url.path.startswith("/api/"):
            content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
            if content_type != "application/json":
                return JSONResponse({"detail": "Content-Type must be application/json."}, status_code=415)
        return await call_next(request)

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        eng = get_engine()
        return {
            "status": "ok",
            "version": __version__,
            "packs": eng.packs.ids(),
            "models": eng.model_names,
            "max_input_chars": eng.max_input_chars,
        }

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
        eng = get_engine()
        limit = max(MAX_REQUEST_CHARS, eng.max_input_chars)
        if len(request.text) > limit:
            raise HTTPException(status_code=422, detail=f"text is longer than {limit} characters")
        try:
            return eng.triage(request.text, request.pack)
        except PackNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    # Static files last, so the API routes win.
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


def main(host: str | None = None, port: int | None = None) -> None:
    import uvicorn

    from .config import load_dotenv_if_present

    load_dotenv_if_present()
    try:
        logging.basicConfig(level=os.environ.get("TRIDENT_LOG_LEVEL", "INFO"))
        host = host or os.environ.get("TRIDENT_HOST", "127.0.0.1")
        port = port or int(os.environ.get("TRIDENT_PORT", "8000"))
        allowed = allowed_hosts_from_env()
        if allowed is None:
            allowed = list(DEFAULT_ALLOWED_HOSTS)
            if host in WILDCARD_BINDS:
                print(
                    "Note: only requests to localhost are accepted. Set TRIDENT_ALLOWED_HOSTS to the "
                    "host names people use to reach this server.",
                    file=sys.stderr,
                )
            else:
                # Also answer to the address the server was started on.
                name = host.strip().lower()
                name = f"[{name}]" if ":" in name and not name.startswith("[") else name
                if name not in allowed:
                    allowed.append(name)
        # Build the engine now, so a broken rule pack or setting fails at start-up.
        app = create_app(TriageEngine.from_settings(), allowed_hosts=allowed)
    except (PackError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    print(f"PEAKWHALE TRIDENT {__version__} - open http://{'localhost' if host in ('0.0.0.0', '127.0.0.1') else host}:{port}")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":  # pragma: no cover
    main()
