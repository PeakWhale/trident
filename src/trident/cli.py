"""The `trident` command.

    trident serve                       start the web UI and API
    trident mcp                         start the MCP server (stdio)
    trident packs                       list the loaded rule packs
    trident validate [FILE ...]         check rule pack files (default: all loaded packs)
    trident triage --pack ID "text"     sort one case and print the JSON result
"""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .config import Settings, load_dotenv_if_present
from .packs import PackError, PackNotFoundError, PackRegistry, load_pack


def _registry(settings: Settings) -> PackRegistry:
    return PackRegistry.load([settings.packs_dir] if settings.packs_dir else [])


def cmd_packs(args: argparse.Namespace) -> int:
    for pack in _registry(Settings.from_env()).all():
        levels = " > ".join(lvl.id for lvl in pack.levels)
        note = "  [DEMO ONLY]" if pack.disclaimer else ""
        print(f"{pack.id:<20} {levels:<28} {len(pack.categories):>2} categories  {pack.name}{note}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    failed = 0
    if args.files:
        for path in args.files:
            try:
                pack = load_pack(path)
            except PackError as exc:
                failed += 1
                print(f"FAIL {exc}")
            else:
                print(f"OK   {path} ({pack.id}: {len(pack.levels)} levels, {len(pack.categories)} categories)")
    else:
        try:
            registry = _registry(Settings.from_env())
        except PackError as exc:
            print(f"FAIL {exc}")
            return 1
        for pack in registry.all():
            print(f"OK   {pack.id} ({len(pack.levels)} levels, {len(pack.categories)} categories)")
    return 1 if failed else 0


def cmd_triage(args: argparse.Namespace) -> int:
    from .engine import TriageEngine

    text = args.text if args.text != "-" else sys.stdin.read()
    engine = TriageEngine.from_settings()
    try:
        result = engine.triage(text, args.pack)
    except PackNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        engine.close()
    print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .server import main as serve

    serve(host=args.host, port=args.port)
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    from .mcp_server import main as mcp_main

    mcp_main()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trident", description="PeakWhale Trident - fail-safe AI plus rules triage.")
    parser.add_argument("--version", action="version", version=f"trident {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="start the web UI and API")
    serve.add_argument("--host", default=None, help="default: TRIDENT_HOST or 127.0.0.1")
    serve.add_argument("--port", type=int, default=None, help="default: TRIDENT_PORT or 8000")
    serve.set_defaults(func=cmd_serve)

    sub.add_parser("mcp", help="start the MCP server (stdio)").set_defaults(func=cmd_mcp)
    sub.add_parser("packs", help="list the loaded rule packs").set_defaults(func=cmd_packs)

    validate = sub.add_parser("validate", help="check rule pack files")
    validate.add_argument("files", nargs="*", help="pack files; default: all loaded packs")
    validate.set_defaults(func=cmd_validate)

    triage = sub.add_parser("triage", help="sort one case and print the JSON result")
    triage.add_argument("--pack", required=True, help="rule pack id")
    triage.add_argument("text", help="the case text, or - to read from stdin")
    triage.set_defaults(func=cmd_triage)
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv_if_present()
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (PackError, ValueError) as exc:
        # A bad setting or rule pack: one clear line, no traceback.
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
