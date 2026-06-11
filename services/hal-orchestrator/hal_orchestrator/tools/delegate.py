"""delegate tool — routes to AgentList marketplace agents or local sub-loops."""

from __future__ import annotations

import structlog

from hal_orchestrator.prompts.system import AGENTS
from hal_orchestrator.prompts.tool_defs import get_agent_tools
from hal_orchestrator.services.gemini import call_gemini, get_model_url
from hal_orchestrator.tools.registry import ToolContext, execute_tool

log = structlog.get_logger()

# Maps HAL agent names → AgentList slugs + I/O transforms.
# Agents listed here are invoked via the AgentList orchestrator API
# instead of running an in-process Gemini sub-loop.
AGENT_REGISTRY = {
    "research": {
        "slug": "hal-research",
        "transform_input": lambda args: {
            "query": args.get("task", ""),
            "context": args.get("context", ""),
        },
        "extract_output": lambda data: data.get("answer", str(data)),
    },
    "brainstorm": {
        "slug": "hal-brainstorm",
        "transform_input": lambda args: {
            "topic": args.get("task", ""),
            "style": "freeform",
        },
        "extract_output": lambda data: data.get("response", str(data)),
    },
}


async def _invoke_agentlist(
    slug: str,
    input_data: dict,
    ctx: ToolContext,
) -> dict | None:
    """Call the AgentList orchestrator's internal invoke endpoint."""
    # Prefer internal URL (same Railway private network), fall back to gateway
    base_url = ctx.settings.agentlist_orchestrator_url
    headers: dict[str, str] = {}

    if base_url:
        url = f"{base_url}/internal/invoke"
        account_id = ctx.settings.agentlist_account_id
        if account_id:
            headers["X-Account-ID"] = account_id
    elif ctx.settings.agentlist_gateway_url:
        url = f"{ctx.settings.agentlist_gateway_url}/v1/invoke"
        api_key = ctx.settings.agentlist_api_key
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
    else:
        return None

    payload = {
        "agent_slug": slug,
        "input": input_data,
    }

    try:
        resp = await ctx.http_client.post(
            url,
            json=payload,
            headers=headers,
            timeout=120.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "completed" and data.get("output"):
                return data["output"]
            error = data.get("error", f"status={data.get('status')}")
            log.error("delegate.agentlist_error", slug=slug, error=error)
            return None
        else:
            log.error(
                "delegate.agentlist_http_error",
                slug=slug,
                status=resp.status_code,
                body=resp.text[:300],
            )
            return None
    except Exception as exc:
        log.exception("delegate.agentlist_exception", slug=slug, error=str(exc))
        return None


async def _run_local_agent(agent_name: str, args: dict, ctx: ToolContext) -> str:
    """Run a local Gemini sub-loop for agents that need direct access to ctx
    (e.g. texting agent needs side_messages)."""
    agent_def = AGENTS[agent_name]
    task = args.get("task", "")
    context = args.get("context", "")

    system = agent_def["system_prompt"]
    agent_tools = get_agent_tools(agent_def["tools"])

    prompt = f"Task: {task}"
    if context:
        prompt += f"\nContext: {context}"

    history: list[dict] = [
        {"role": "user", "parts": [{"text": prompt}]},
    ]

    model = get_model_url(ctx.settings, agent_def.get("model", "flash"))
    max_iterations = ctx.settings.max_specialist_iterations

    for iteration in range(max_iterations):
        response = await call_gemini(
            client=ctx.http_client,
            settings=ctx.settings,
            history=history,
            tools=agent_tools if agent_tools else None,
            system=system,
            model=model,
        )

        if response is None:
            log.error("delegate.gemini_failed", agent=agent_name, iteration=iteration)
            return f"Agent '{agent_name}' failed: no response from Gemini"

        candidates = response.get("candidates", [])
        if not candidates:
            return f"Agent '{agent_name}' returned no candidates"

        content = candidates[0].get("content", {})
        parts = content.get("parts", [])

        if not parts:
            return f"Agent '{agent_name}' returned empty response"

        func_calls = [p for p in parts if "functionCall" in p]

        if func_calls:
            history.append({"role": "model", "parts": parts})

            func_responses = []
            for fc in func_calls:
                call = fc["functionCall"]
                tool_name = call["name"]
                tool_args = call.get("args", {})

                log.info(
                    "delegate.tool_call",
                    agent=agent_name,
                    tool=tool_name,
                    iteration=iteration,
                )

                result = await execute_tool(tool_name, tool_args, ctx)

                func_responses.append(
                    {
                        "functionResponse": {
                            "name": tool_name,
                            "response": {"content": result},
                        }
                    }
                )

            history.append({"role": "user", "parts": func_responses})
            continue

        text_parts = [p.get("text", "") for p in parts if "text" in p]
        final_text = "\n".join(text_parts).strip()

        if final_text:
            log.info(
                "delegate.complete",
                agent=agent_name,
                iterations=iteration + 1,
                result_len=len(final_text),
            )
            return final_text

        return f"Agent '{agent_name}' completed but returned no text"

    log.warning("delegate.max_iterations", agent=agent_name, max=max_iterations)
    return f"Agent '{agent_name}' reached max iterations ({max_iterations})"


async def tool_delegate(args: dict, ctx: ToolContext) -> str:
    """Delegate a task to a specialist agent.

    Agents in AGENT_REGISTRY are invoked via the AgentList marketplace API.
    Agents in AGENTS (system.py) are run as local Gemini sub-loops (e.g. texting).
    """
    agent_name = args.get("agent", "")
    task = args.get("task", "")
    context = args.get("context", "")

    if not agent_name or not task:
        return "Error: 'agent' and 'task' are required"

    log.info(
        "delegate.start",
        agent=agent_name,
        task=task[:80],
        phone=ctx.phone,
    )

    # Check if this agent should be invoked via AgentList
    registry_entry = AGENT_REGISTRY.get(agent_name)
    if registry_entry:
        slug = registry_entry["slug"]
        input_data = registry_entry["transform_input"](args)

        log.info("delegate.agentlist_invoke", agent=agent_name, slug=slug)

        output = await _invoke_agentlist(slug, input_data, ctx)
        if output is not None:
            result = registry_entry["extract_output"](output)
            log.info(
                "delegate.complete",
                agent=agent_name,
                via="agentlist",
                result_len=len(result),
            )
            return result

        # Fallback: if AgentList invoke failed and agent also exists locally, run locally
        if agent_name in AGENTS:
            log.warning("delegate.agentlist_fallback", agent=agent_name)
            return await _run_local_agent(agent_name, args, ctx)

        return f"Agent '{agent_name}' (AgentList) failed and no local fallback available"

    # Local agent (e.g. texting — needs ctx.side_messages)
    if agent_name in AGENTS:
        return await _run_local_agent(agent_name, args, ctx)

    # Unknown agent
    all_agents = set(AGENT_REGISTRY.keys()) | set(AGENTS.keys())
    available = ", ".join(sorted(all_agents))
    return f"Unknown agent: {agent_name}. Available: {available}"
