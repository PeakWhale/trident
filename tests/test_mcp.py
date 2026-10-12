"""MCP server: tools work through a real MCP client session (in memory)."""

from __future__ import annotations

import json

import anyio
from fakes import FakeLLM, agree, classified
from mcp.shared.memory import create_connected_server_and_client_session

from trident.mcp_server import build_server

TEXT = "How do I export my contacts to a CSV file?"


def run_session(engine, action):
    server = build_server(lambda: engine)

    async def main():
        async with create_connected_server_and_client_session(server._mcp_server) as session:
            return await action(session)

    return anyio.run(main)


def payload(result):
    assert result.structuredContent is not None
    return result.structuredContent


def test_tools_are_listed(make_engine):
    async def action(session):
        return await session.list_tools()

    tools = {tool.name: tool for tool in run_session(make_engine(FakeLLM(), FakeLLM()), action).tools}
    assert set(tools) == {"triage", "list_packs"}
    schema = tools["triage"].inputSchema
    assert set(schema["required"]) == {"text", "pack"}


def test_list_packs_tool(make_engine):
    async def action(session):
        return await session.call_tool("list_packs", {})

    result = run_session(make_engine(FakeLLM(), FakeLLM()), action)
    assert not result.isError
    packs = payload(result)["result"]
    assert {p["id"] for p in packs} == {"customer-support", "it-incidents", "medical-demo"}
    medical = next(p for p in packs if p["id"] == "medical-demo")
    assert "DEMO ONLY" in medical["disclaimer"]


def test_triage_tool(make_engine):
    engine = make_engine(
        FakeLLM(classified("how_to_question", 0.9, ["export my contacts"])),
        FakeLLM(agree("how_to_question")),
    )

    async def action(session):
        return await session.call_tool("triage", {"text": TEXT, "pack": "customer-support"})

    result = run_session(engine, action)
    assert not result.isError
    data = payload(result)
    assert data["outcome"] == "DECIDED"
    assert data["level"] == "low"
    assert data["route_to"] == "Customer success team"
    assert "steps" not in data  # short answer by default
    assert json.loads(result.content[0].text)["outcome"] == "DECIDED"


def test_triage_tool_with_steps_and_failure(make_engine):
    engine = make_engine(FakeLLM(RuntimeError("model offline")), FakeLLM())

    async def action(session):
        return await session.call_tool("triage", {"text": TEXT, "pack": "customer-support", "include_steps": True})

    data = payload(run_session(engine, action))
    assert data["outcome"] == "NEEDS_HUMAN_REVIEW"
    assert data["level"] == "normal"  # never the lowest level ("low")
    assert data["steps"][-1]["name"] == "decide"


def test_triage_tool_unknown_pack_is_a_tool_error(make_engine):
    async def action(session):
        return await session.call_tool("triage", {"text": TEXT, "pack": "nope"})

    result = run_session(make_engine(FakeLLM(), FakeLLM()), action)
    assert result.isError
    assert "Available packs" in result.content[0].text
