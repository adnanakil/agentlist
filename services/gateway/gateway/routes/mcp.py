"""Minimal MCP JSON-RPC gateway.

This is the MVP transport for hosted MCP clients and local bridge binaries. It
implements the tools-only surface from the product docs while reusing the
existing orchestrator invocation path for execution and billing.
"""

import json
from typing import Any

import structlog
from fastapi import APIRouter, Depends
from httpx import AsyncClient
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ag_common.errors import AgentGateError, NotFoundError, ValidationError
from ag_common.models import AuthenticatedAccount, InvokeRequest
from ag_db.models import Agent, McpSubscription
from gateway.config import settings
from gateway.deps import get_db, get_http_client
from gateway.middleware.rate_limit import check_rate_limit

logger = structlog.get_logger()

router = APIRouter(prefix="/v1/mcp", tags=["mcp"])


class McpJsonRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: str | int | None = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


def _tool_name(agent_slug: str, tool_name: str) -> str:
    return f"{agent_slug}__{tool_name}"


def _fallback_tool(agent: Agent) -> dict[str, Any]:
    return {
        "name": "invoke",
        "description": agent.description,
        "inputSchema": agent.input_schema or {"type": "object", "properties": {}},
        "price_cents": agent.price_per_call_cents,
    }


def _agent_tools(agent: Agent) -> list[dict[str, Any]]:
    if agent.mcp_tools:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.input_schema or {"type": "object", "properties": {}},
                "price_cents": (
                    tool.price_cents
                    if tool.price_cents is not None
                    else agent.price_per_call_cents
                ),
            }
            for tool in agent.mcp_tools
        ]
    if agent.tool_schema:
        return list(agent.tool_schema)
    return [_fallback_tool(agent)]


def _jsonrpc_success(request_id: str | int | None, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _jsonrpc_error(request_id: str | int | None, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


async def _subscribed_agents(
    db: AsyncSession,
    account: AuthenticatedAccount,
) -> list[Agent]:
    stmt = (
        select(Agent)
        .join(McpSubscription, McpSubscription.agent_id == Agent.id)
        .where(
            McpSubscription.account_id == account.account_id,
            McpSubscription.status == "active",
            Agent.status == "active",
        )
        .options(selectinload(Agent.mcp_tools), selectinload(Agent.category))
        .order_by(Agent.slug)
    )
    result = await db.execute(stmt)
    return list(result.unique().scalars().all())


async def _resolve_tool(
    db: AsyncSession,
    account: AuthenticatedAccount,
    namespaced_name: str,
) -> tuple[Agent, dict[str, Any]]:
    if "__" not in namespaced_name:
        raise ValidationError("Tool names must be namespaced as server__tool")

    agent_slug, tool_name = namespaced_name.split("__", 1)
    stmt = (
        select(Agent)
        .join(McpSubscription, McpSubscription.agent_id == Agent.id)
        .where(
            McpSubscription.account_id == account.account_id,
            McpSubscription.status == "active",
            Agent.status == "active",
            Agent.slug == agent_slug,
        )
        .options(selectinload(Agent.mcp_tools))
    )
    result = await db.execute(stmt)
    agent = result.unique().scalar_one_or_none()
    if agent is None:
        raise NotFoundError(f"No active subscription for MCP server '{agent_slug}'")

    for tool in _agent_tools(agent):
        if tool.get("name") == tool_name:
            return agent, tool

    raise NotFoundError(f"Tool '{namespaced_name}' not found")


@router.post("")
async def mcp_jsonrpc(
    body: McpJsonRpcRequest,
    account: AuthenticatedAccount = Depends(check_rate_limit),
    db: AsyncSession = Depends(get_db),
    http: AsyncClient = Depends(get_http_client),
) -> dict[str, Any]:
    if body.method == "initialize":
        return _jsonrpc_success(
            body.id,
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "AgentGate MCP Marketplace", "version": "0.1.0"},
            },
        )

    if body.method == "tools/list":
        agents = await _subscribed_agents(db, account)
        tools: list[dict[str, Any]] = []
        for agent in agents:
            for tool in _agent_tools(agent):
                price = tool.get("price_cents", agent.price_per_call_cents)
                description = tool.get("description") or agent.description
                tools.append(
                    {
                        "name": _tool_name(agent.slug, str(tool["name"])),
                        "description": f"{description} Pricing: {price}c/call.",
                        "inputSchema": tool.get("inputSchema")
                        or tool.get("input_schema")
                        or {"type": "object", "properties": {}},
                    }
                )

        return _jsonrpc_success(body.id, {"tools": tools})

    if body.method == "tools/call":
        namespaced_name = body.params.get("name")
        if not isinstance(namespaced_name, str):
            return _jsonrpc_error(body.id, -32602, "Missing params.name")

        arguments = body.params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return _jsonrpc_error(body.id, -32602, "params.arguments must be an object")

        try:
            agent, tool = await _resolve_tool(db, account, namespaced_name)
        except AgentGateError as exc:
            return _jsonrpc_error(body.id, -32000, exc.message)

        invoke_input = dict(arguments)
        if tool.get("name") != "invoke":
            invoke_input["_mcp_tool"] = tool["name"]

        response = await http.post(
            f"{settings.orchestrator_url}/internal/invoke",
            json=InvokeRequest(agent_slug=agent.slug, input=invoke_input).model_dump(mode="json"),
            headers={"X-Account-ID": str(account.account_id)},
            timeout=120.0,
        )

        if response.status_code != 200:
            logger.error("mcp_orchestrator_error", status=response.status_code)
            return _jsonrpc_error(
                body.id,
                -32000,
                f"Invocation failed with upstream status {response.status_code}",
            )

        payload = response.json()
        if payload.get("status") != "completed":
            return _jsonrpc_error(body.id, -32000, payload.get("error") or "Invocation failed")

        return _jsonrpc_success(
            body.id,
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(payload.get("output") or {}, default=str),
                    }
                ],
                "isError": False,
            },
        )

    return _jsonrpc_error(body.id, -32601, f"Unsupported MCP method '{body.method}'")
