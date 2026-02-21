"""POST /api/message — core message processing loop.

Receives a message from the iMessage bridge, runs the Gemini tool-use loop,
and returns the final text response.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ag_db.session import get_session

from hal_orchestrator.prompts.system import SYSTEM_PROMPT, build_user_context
from hal_orchestrator.state import get_http_client, get_settings
from hal_orchestrator.prompts.tool_defs import MAIN_TOOLS
from hal_orchestrator.services.conversation import (
    load_conversation,
    save_conversation,
)
from hal_orchestrator.services.gemini import call_gemini
from hal_orchestrator.services.profiles import get_profile
from hal_orchestrator.tools.registry import ToolContext, execute_tool

log = structlog.get_logger()


# --------------------------------------------------------------------------- #
# Request / Response models
# --------------------------------------------------------------------------- #


class MessageRequest(BaseModel):
    phone: str
    text: str
    sender_name: str | None = None
    is_group: bool = False
    group_name: str | None = None


class MessageResponse(BaseModel):
    reply: str
    tool_calls: int = 0


# --------------------------------------------------------------------------- #
# Auth dependency
# --------------------------------------------------------------------------- #


async def verify_bridge_auth(authorization: str = Header(...)) -> None:
    """Verify the bridge shared secret."""
    settings = get_settings()
    expected = f"Bearer {settings.hal_bridge_secret}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="Invalid authorization")


# --------------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------------- #


def build_message_router() -> APIRouter:
    router = APIRouter()

    @router.post(
        "/api/message",
        response_model=MessageResponse,
        dependencies=[Depends(verify_bridge_auth)],
    )
    async def process_message(
        body: MessageRequest,
        session: AsyncSession = Depends(get_session),
    ) -> MessageResponse:
        """Process an incoming message through the Gemini tool-use loop."""
        settings = get_settings()
        http_client = get_http_client()

        phone = body.phone
        user_text = body.text

        log.info("message.received", phone=phone, text=user_text[:80])

        # Handle /clear command
        if user_text.strip().lower() in ("/clear", "/reset"):
            from hal_orchestrator.services.conversation import clear_conversation

            await clear_conversation(session, phone)
            await session.commit()
            return MessageResponse(reply="Conversation cleared.")

        # Load user profile and build context
        profile = await get_profile(session, phone)
        user_context = build_user_context(
            phone=phone,
            profile=profile,
            sender_name=body.sender_name,
            is_group=body.is_group,
            group_name=body.group_name,
        )
        system_prompt = SYSTEM_PROMPT + user_context

        # Load conversation history
        history = await load_conversation(session, phone)

        # Append user message
        history.append({"role": "user", "parts": [{"text": user_text}]})

        # Build tool context
        ctx = ToolContext(
            phone=phone,
            session=session,
            settings=settings,
            http_client=http_client,
        )

        # --- Tool-use loop ---
        total_tool_calls = 0

        for iteration in range(settings.max_tool_iterations):
            response = await call_gemini(
                client=http_client,
                settings=settings,
                history=history,
                tools=MAIN_TOOLS,
                system=system_prompt,
            )

            if response is None:
                log.error("message.gemini_failed", phone=phone, iteration=iteration)
                reply = "Sorry, I'm having trouble right now. Please try again."
                history.append({"role": "model", "parts": [{"text": reply}]})
                break

            # Extract candidate
            candidates = response.get("candidates", [])
            if not candidates:
                log.error("message.no_candidates", phone=phone)
                reply = "Sorry, I couldn't generate a response."
                history.append({"role": "model", "parts": [{"text": reply}]})
                break

            content = candidates[0].get("content", {})
            parts = content.get("parts", [])

            if not parts:
                reply = "Sorry, I got an empty response."
                history.append({"role": "model", "parts": [{"text": reply}]})
                break

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
                    total_tool_calls += 1

                    log.info(
                        "message.tool_call",
                        phone=phone,
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

            # No function calls — extract final text
            text_parts = [p.get("text", "") for p in parts if "text" in p]
            reply = "\n".join(text_parts).strip()

            if not reply:
                reply = "..."

            history.append({"role": "model", "parts": [{"text": reply}]})
            break
        else:
            # Exhausted iterations
            reply = "I ran into too many steps processing that. Can you try rephrasing?"
            history.append({"role": "model", "parts": [{"text": reply}]})

        # Save conversation
        await save_conversation(
            session, phone, history, max_turns=settings.max_conversation_turns
        )
        await session.commit()

        log.info(
            "message.reply",
            phone=phone,
            reply=reply[:80],
            tool_calls=total_tool_calls,
        )

        return MessageResponse(reply=reply, tool_calls=total_tool_calls)

    return router
