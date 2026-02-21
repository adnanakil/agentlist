"""delegate tool — runs specialist agent sub-loops."""

from __future__ import annotations

import structlog

from hal_orchestrator.prompts.system import AGENTS
from hal_orchestrator.prompts.tool_defs import get_agent_tools
from hal_orchestrator.services.gemini import call_gemini, get_model_url
from hal_orchestrator.tools.registry import ToolContext, execute_tool

log = structlog.get_logger()


async def tool_delegate(args: dict, ctx: ToolContext) -> str:
    """Delegate a task to a specialist agent and run its tool-use sub-loop."""
    agent_name = args.get("agent", "")
    task = args.get("task", "")
    context = args.get("context", "")

    if not agent_name or not task:
        return "Error: 'agent' and 'task' are required"

    # Look up agent definition
    agent_def = AGENTS.get(agent_name)
    if agent_def is None:
        available = ", ".join(AGENTS.keys())
        return f"Unknown agent: {agent_name}. Available: {available}"

    log.info(
        "delegate.start",
        agent=agent_name,
        task=task[:80],
        phone=ctx.phone,
    )

    # Build agent's system prompt
    system = agent_def["system_prompt"]

    # Build agent's tool set
    agent_tools = get_agent_tools(agent_def["tools"])

    # Build initial history with the task
    prompt = f"Task: {task}"
    if context:
        prompt += f"\nContext: {context}"

    history: list[dict] = [
        {"role": "user", "parts": [{"text": prompt}]},
    ]

    # Agent model
    model = get_model_url(ctx.settings, agent_def.get("model", "flash"))

    # Run the agent's tool-use loop
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

        # Extract candidate
        candidates = response.get("candidates", [])
        if not candidates:
            return f"Agent '{agent_name}' returned no candidates"

        content = candidates[0].get("content", {})
        parts = content.get("parts", [])

        if not parts:
            return f"Agent '{agent_name}' returned empty response"

        # Check for function calls
        func_calls = [p for p in parts if "functionCall" in p]

        if func_calls:
            # Add model's response to history
            history.append({"role": "model", "parts": parts})

            # Execute each tool call
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

            # Add tool responses to history
            history.append({"role": "user", "parts": func_responses})
            continue

        # No function calls — extract text response
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
