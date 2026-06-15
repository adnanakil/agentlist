"""POST /api/message — core message processing loop.

Receives a message from the iMessage bridge, runs the Gemini tool-use loop,
and returns the final text response.
"""

from __future__ import annotations

from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ag_db.session import get_session

from hal_orchestrator.prompts.system import SYSTEM_PROMPT, USER_TZ, build_user_context
from hal_orchestrator.state import get_http_client, get_settings
from hal_orchestrator.prompts.tool_defs import MAIN_TOOLS
from hal_orchestrator.services.conversation import (
    get_summary,
    load_conversation,
    save_conversation,
)
from hal_orchestrator.services.gemini import call_gemini
from hal_orchestrator.services.identity import is_group_id, normalize_handle
from hal_orchestrator.services.profiles import get_profile
from hal_orchestrator.tools.registry import ToolContext, execute_tool

log = structlog.get_logger()


def _is_quiet_sentinel(text: str) -> bool:
    """True if the model's reply is its 'stay silent' sentinel — empty, or only
    dots/ellipsis/whitespace (e.g. '...', '…'). Such replies are collapsed to an
    empty outbound reply so the bridge sends nothing (it skips empty replies),
    instead of posting a literal '...' bubble in the group."""
    return text.strip().strip(".…·•- \t\n") == ""


# --------------------------------------------------------------------------- #
# Model-failure handling (circuit breaker + echo guard)
# --------------------------------------------------------------------------- #

GENERIC_FAILURE_REPLY = "Sorry, I'm having trouble right now. Please try again."
BREAKER_REPLY = (
    "I keep hitting errors processing messages in this chat, so I'm going to "
    "stay quiet instead of spamming you. The admin's been pinged — I'll pick "
    "back up as soon as things are working again."
)
# Canned strings HAL may emit on failures. If one of these arrives as an
# INBOUND user message, the bridge has bounced HAL's own reply back (seen in
# production: a silo whose entire history was the fallback line alternating
# user/model). Suppress instead of processing.
FALLBACK_REPLIES = {
    GENERIC_FAILURE_REPLY,
    BREAKER_REPLY,
    "Sorry, I couldn't generate a response.",
    "Sorry, I got an empty response.",
    "I ran into too many steps processing that. Can you try rephrasing?",
}

BREAKER_THRESHOLD = 3
# silo -> consecutive model failures. In-memory: resets on restart, which is a
# fine breaker semantic (a fresh deploy gets a fresh chance).
_consecutive_failures: dict[str, int] = {}


async def _register_failure(silo: str) -> str:
    """Count a model failure for this silo and return the outbound reply:
    generic fallback for the first failures, the breaker notice (+ admin alert)
    when the threshold is crossed, then silence until a turn succeeds."""
    import hal_orchestrator.state as state

    count = _consecutive_failures.get(silo, 0) + 1
    _consecutive_failures[silo] = count
    if count < BREAKER_THRESHOLD:
        return GENERIC_FAILURE_REPLY
    if count == BREAKER_THRESHOLD:
        settings = state.settings
        if settings.admin_phone:
            await state.outbox.put(
                {
                    "to": settings.admin_phone,
                    "text": (
                        f"⚠️ HAL circuit breaker: {BREAKER_THRESHOLD} consecutive "
                        f"model failures in chat {silo}. Replies there are paused "
                        f"until a turn succeeds."
                    ),
                }
            )
        log.error("message.breaker_tripped", silo=silo)
        return BREAKER_REPLY
    log.warning("message.breaker_silent", silo=silo, failures=count)
    return ""


def _reset_failures(silo: str) -> None:
    _consecutive_failures.pop(silo, None)


# --------------------------------------------------------------------------- #
# Runaway-loop handling — synthesize an answer instead of leaking an error
# --------------------------------------------------------------------------- #

# If the model calls the SAME tool this many times in one turn, it's almost
# certainly stuck (e.g. re-running web_search on thin results forever). Stop and
# answer from what's gathered rather than burning the whole iteration budget.
REPEAT_TOOL_LIMIT = 8

_FINALIZE_DIRECTIVE = (
    "You've gathered enough and must answer NOW — do NOT call any more tools. "
    "Give the user your best, concise answer using what you already found above. "
    "If their request was ambiguous, briefly address the most likely meaning(s). "
    "If you genuinely couldn't find it, say so in one line and suggest what would "
    "help — but NEVER mention steps, iterations, tools, or internal limits."
)


async def _finalize_answer(
    http_client, settings, history: list, system_prompt: str, silo: str
) -> str:
    """One tools-disabled call to turn a stalled/looping turn into a real
    answer from what's already in `history`. Falls back to a graceful ask —
    never the old 'too many steps' leak."""
    from hal_orchestrator.services.gemini import call_gemini

    try:
        resp = await call_gemini(
            client=http_client,
            settings=settings,
            history=history,
            tools=None,  # force a text answer
            system=system_prompt + "\n\n## FINALIZE NOW\n" + _FINALIZE_DIRECTIVE,
        )
        parts = (
            (resp.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
            if resp
            else []
        )
        text = "\n".join(p.get("text", "") for p in parts if "text" in p).strip()
        if text:
            return text
    except Exception:
        log.exception("message.finalize_failed", silo=silo)
    return "I dug into that but couldn't pin it down — can you give me one more detail?"


async def _run_async_critic(
    settings,
    http_client,
    silo: str,
    delivery_to: str,
    history_snapshot: list,
    user_text: str,
    reply: str,
) -> None:
    """Background self-critique of a just-sent plan/recommendation. The reply is
    already delivered; if the critic finds a SUBSTANTIVE flaw, send a follow-up
    correction and update the saved conversation so HAL's context reflects it.
    Fire-and-forget and fully self-contained — it can never affect or delay the
    original reply. Issues (even without a rewrite) feed the nightly growth loop
    via friction."""
    import hal_orchestrator.state as state
    from ag_db.session import get_session
    from hal_orchestrator.services.critic import critique_and_revise

    try:
        new_reply, crit = await critique_and_revise(
            http_client, settings, history_snapshot, user_text, reply, silo
        )
    except Exception:
        log.exception("async_critic.critique_failed", silo=silo)
        return
    if not crit.get("issues") and not crit.get("caught"):
        return  # clean plan — stay silent

    async for session in get_session():
        try:
            if crit.get("issues"):
                from hal_orchestrator.services.friction import (
                    KIND_CRITIC_CATCH,
                    log_friction,
                )

                log_friction(
                    session, silo, KIND_CRITIC_CATCH, "; ".join(crit["issues"])[:400]
                )
            if crit.get("caught"):
                summary = (crit.get("summary") or "").strip()
                lead = (
                    f"Quick fix — {summary[0].lower()}{summary[1:]}:"
                    if summary
                    else "Quick fix on that — I had the timing off:"
                )
                followup = lead + "\n\n" + new_reply
                await state.outbox.put({"to": delivery_to, "text": followup})
                # Reflect the correction in saved history so HAL's next turn
                # reasons from the corrected plan, not the flawed one.
                from hal_orchestrator.services.conversation import (
                    load_conversation,
                    save_conversation,
                )

                hist = await load_conversation(session, silo)
                if hist and hist[-1].get("role") == "model":
                    hist[-1] = {"role": "model", "parts": [{"text": new_reply}]}
                    await save_conversation(
                        session, silo, hist, max_turns=settings.max_conversation_turns
                    )
                log.info("async_critic.corrected", silo=silo)
            await session.commit()
        except Exception:
            log.exception("async_critic.persist_failed", silo=silo)
        break


# --------------------------------------------------------------------------- #
# Growth-loop capture (GROWTH.md Stage 1)
# --------------------------------------------------------------------------- #

import re as _re

# Fast signal that HAL told the user it can't do something — the nightly
# grader is the real judge; this just flags turns for the failure inventory.
_REFUSAL_RX = _re.compile(
    r"\b(I (?:actually )?can'?t|I cannot|I'?m (?:not able|unable)|"
    r"I don'?t have (?:access|the ability|a way)|not something I can|"
    r"blocks automated access)\b",
    _re.I,
)


async def _capture_turn(
    session,
    silo: str,
    sender_phone: str | None,
    user_text: str,
    reply: str,
    steps: list,
    status: str,
) -> None:
    """Record EVERY turn for the nightly growth loop (best-effort; callers
    wrap so this can never break a reply). Refusal replies also get a friction
    event so capability gaps show up in the aggregate inventory immediately."""
    from ag_db.models import HalTurn

    session.add(
        HalTurn(
            phone=silo,
            sender_phone=sender_phone,
            user_text=(user_text or "")[:4000],
            reply=(reply or "")[:4000],
            steps=steps[:50],
            status=status,
        )
    )
    if status == "ok" and reply and _REFUSAL_RX.search(reply):
        from hal_orchestrator.services.friction import KIND_REFUSAL, log_friction

        log_friction(session, silo, KIND_REFUSAL, reply[:200])


# --------------------------------------------------------------------------- #
# Request / Response models
# --------------------------------------------------------------------------- #


class ImageData(BaseModel):
    mime_type: str
    data: str  # base64


class MessageRequest(BaseModel):
    phone: str
    text: str
    sender_name: str | None = None
    is_group: bool = False
    group_name: str | None = None
    chat_id: str | None = None  # Group chat identifier (for trips, etc.)
    images: list[ImageData] = []
    # Internal turn (heartbeat/daemon): the user did not send this. A silent
    # outcome persists NOTHING (no history, no archive, no turn capture); an
    # alert persists a compact stub instead of the synthetic prompt.
    internal: bool = False


class SideMessage(BaseModel):
    to: str
    text: str


class ResultImage(BaseModel):
    mime_type: str
    data: str  # base64
    ext: str


class MessageResponse(BaseModel):
    reply: str
    tool_calls: int = 0
    side_messages: list[SideMessage] = []
    result_images: list[ResultImage] = []


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
        from hal_orchestrator.services.curator import mark_activity

        settings = get_settings()
        http_client = get_http_client()

        user_text = body.text

        # --- Silo resolution ---------------------------------------------- #
        # The silo key scopes ALL persistent state (conversation, profile,
        # memories, reminders, skills). 1:1 → the sender's normalized handle;
        # group → the group chat id. A group is its own shared silo, walled
        # off from every member's personal silo.
        is_group = bool(body.is_group)
        chat_id = body.chat_id
        sender_phone: str | None = normalize_handle(body.phone)
        if is_group and not chat_id:
            # Older bridge payloads carry the group chat id in `phone` and
            # don't identify the sender.
            if is_group_id(body.phone):
                chat_id = body.phone
                sender_phone = None
        silo = (chat_id or body.phone) if is_group else (sender_phone or body.phone)

        # Notify curator idle tracker so it backs off while users are active.
        # Internal (heartbeat) turns are not user activity.
        if not body.internal:
            mark_activity()

        log.info(
            "message.received",
            silo=silo,
            sender=sender_phone,
            is_group=is_group,
            text=user_text[:80],
            images=len(body.images),
        )

        # Handle /clear command
        if user_text.strip().lower() in ("/clear", "/reset"):
            from hal_orchestrator.services.conversation import clear_conversation

            await clear_conversation(session, silo)
            await session.commit()
            return MessageResponse(reply="Conversation cleared.")

        # Echo guard: one of HAL's own canned failure replies arriving as an
        # inbound message means the bridge bounced our send back. Drop it —
        # processing it creates the user/model error loop.
        if user_text.strip() in FALLBACK_REPLIES:
            log.warning("message.echo_suppressed", silo=silo)
            return MessageResponse(reply="")

        # Load the silo's profile (the user's in 1:1; the group's shared notes
        # in groups) and build context. In groups we deliberately do NOT load
        # the sender's personal profile/memories — only their display name, so
        # nothing private can leak into a group reply.
        profile = await get_profile(session, silo)
        sender_display = body.sender_name
        if is_group and sender_phone:
            sender_profile = await get_profile(session, sender_phone)
            sender_display = sender_profile.get("name") or body.sender_name

        # Ambient-watched group? Then the bridge is forwarding EVERY message (not
        # just @Hal mentions), so HAL must be told to stay quiet unless addressed
        # or genuinely useful.
        ambient_watch = False
        if is_group:
            from hal_orchestrator.services.watched import is_watched

            ambient_watch = await is_watched(session, chat_id)

        user_context = build_user_context(
            silo=silo,
            profile=profile,
            sender_phone=sender_phone,
            sender_name=sender_display,
            is_group=is_group,
            group_name=body.group_name,
            ambient_watch=ambient_watch,
        )
        system_prompt = SYSTEM_PROMPT + user_context

        # Self-authored playbook (growth loop) — operating notes HAL learned
        # from its own past failures. Additive guidance; lint-checked at write.
        try:
            from hal_orchestrator.services.playbook import get_block

            system_prompt += await get_block(session)
        except Exception:
            log.exception("message.playbook_failed", silo=silo)

        # Group observations — the one-way valve: things happening to THIS
        # user in group chats they're in, written by the group-side enricher.
        # 1:1 only; group turns must never read this (or any personal state).
        if not is_group:
            try:
                from hal_orchestrator.services.group_observations import (
                    recent_for_member,
                )

                obs = await recent_for_member(session, silo)
                if obs:
                    system_prompt += (
                        "\n\n## From this user's group chats (recent, observed in "
                        "groups they're in — usable context, but don't quote "
                        "other members)\n"
                        + "\n".join(
                            f"- [{o.created_at.astimezone(USER_TZ):%b %-d}"
                            f"{', ' + o.group_name if o.group_name else ''}] {o.content}"
                            for o in obs
                        )
                    )
            except Exception:
                log.exception("message.group_obs_failed", silo=silo)

        # T0.5: auto-recall semantically relevant memories for THIS message so the
        # signals attach themselves, instead of relying on the model to call recall.
        # Keyed by silo: groups recall only the group's own shared memories.
        if len(user_text.strip()) >= 6:
            from hal_orchestrator.services.memory import retrieve_relevant

            try:
                relevant = await retrieve_relevant(
                    session, silo, user_text, http_client, settings
                )
            except Exception:
                log.exception("message.retrieve_failed", silo=silo)
                relevant = []
            if relevant:
                system_prompt += (
                    "\n\n## Relevant context (auto-recalled from your memory — "
                    "use if it applies)\n" + "\n".join(f"- {c}" for c in relevant)
                )
                log.info("message.retrieved", silo=silo, n=len(relevant))

        # Rolling long-horizon summary (maintained by the summarizer daemon) —
        # preserves context beyond the recent-turn window without re-feeding it.
        convo_summary = await get_summary(session, silo)
        if convo_summary:
            system_prompt += (
                "\n\n## Conversation summary so far (older context beyond the recent "
                "messages below)\n" + convo_summary
            )

        # Load conversation history
        history = await load_conversation(session, silo)

        # Second echo guard: an inbound message that exactly repeats HAL's last
        # reply is the bridge re-ingesting our own send (mis-detected
        # is_from_me). Best-effort, 1:1-shaped; length floor avoids eating a
        # user genuinely typing something short HAL just said.
        if len(user_text.strip()) >= 20 and history and history[-1].get("role") == "model":
            last_text = "\n".join(
                p.get("text", "") for p in history[-1].get("parts", []) if "text" in p
            ).strip()
            if last_text and user_text.strip() == last_text:
                log.warning("message.self_echo_suppressed", silo=silo)
                return MessageResponse(reply="")

        # Append user message (multimodal if images present). Prefix the text with
        # the local send time so the model can anchor each message in real time and
        # see elapsed gaps (e.g. last msg 6pm yesterday -> this one 9am today),
        # instead of inferring AM/PM from wording. user_text stays raw above for
        # retrieval/logging; only the stored/sent turn is stamped.
        stamp = datetime.now(USER_TZ).strftime("%a %b %-d %-I:%M %p")
        user_parts: list[dict] = [{"text": f"[{stamp}] {user_text}"}]
        for img in body.images:
            user_parts.append(
                {"inlineData": {"mimeType": img.mime_type, "data": img.data}}
            )
        pre_turn_len = len(history)  # for internal turns: persist-from-here marker
        history.append({"role": "user", "parts": user_parts})

        # Build tool context. ctx.phone is the SILO key — in groups, tools that
        # persist state (memory/profile/reminders/skills) operate on the
        # group's shared space, never on any member's personal silo.
        ctx = ToolContext(
            phone=silo,
            session=session,
            settings=settings,
            http_client=http_client,
            chat_id=chat_id,
            sender_phone=sender_phone,
            is_group=is_group,
            images=[{"mime_type": img.mime_type, "data": img.data} for img in body.images],
        )

        # --- Tool-use loop ---
        total_tool_calls = 0
        trajectory_steps: list[dict] = []  # for auto-skill learning
        gemini_failed = False
        tool_counts: dict[str, int] = {}  # per-tool repeat guard (runaway detection)
        stalled = False  # ran out of iterations OR a tool looped — synthesize

        for iteration in range(settings.max_tool_iterations):
            response = await call_gemini(
                client=http_client,
                settings=settings,
                history=history,
                tools=MAIN_TOOLS,
                system=system_prompt,
            )

            candidates = (response or {}).get("candidates", [])
            content = candidates[0].get("content", {}) if candidates else {}
            parts = content.get("parts", [])

            if not parts:
                # Model failure (API error, no candidates, or empty content).
                # Do NOT put a canned apology into history — persisted fallback
                # turns poison the context and feed echo loops. Circuit-break
                # repeated failures instead.
                log.error(
                    "message.gemini_failed",
                    silo=silo,
                    iteration=iteration,
                    api_error=response is None,
                )
                gemini_failed = True
                reply = await _register_failure(silo)
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
                    tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1
                    trajectory_steps.append(
                        {"tool": tool_name, "args": list(tool_args.keys())[:8]}
                    )

                    log.info(
                        "message.tool_call",
                        silo=silo,
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

                # Runaway guard: one tool hammered repeatedly without converging
                # → stop and synthesize from what we have (don't burn the budget).
                if max(tool_counts.values()) >= REPEAT_TOOL_LIMIT:
                    looped = max(tool_counts, key=tool_counts.get)
                    log.warning(
                        "message.tool_loop", silo=silo, tool=looped, count=tool_counts[looped]
                    )
                    stalled = True
                    break
                continue

            # No function calls — extract final text
            text_parts = [p.get("text", "") for p in parts if "text" in p]
            reply = "\n".join(text_parts).strip()

            if not reply:
                reply = "..."

            history.append({"role": "model", "parts": [{"text": reply}]})
            _reset_failures(silo)
            break
        else:
            # Exhausted iterations without a final text answer.
            stalled = True

        if stalled and not gemini_failed:
            _reset_failures(silo)  # model responded; not a failure-breaker case
            try:
                from hal_orchestrator.services.friction import KIND_STUCK, log_friction

                log_friction(session, silo, KIND_STUCK, user_text[:200])
            except Exception:
                pass
            if body.internal:
                # A stalled heartbeat stays SILENT — never synthesize a
                # user-facing alert out of an internal anticipation check that
                # happened to run long.
                log.warning("message.internal_stalled", silo=silo)
                await session.commit()
                return MessageResponse(reply="", tool_calls=total_tool_calls)
            # The model kept calling tools (looped on one, or hit the cap) but
            # never wrote an answer. Instead of leaking "too many steps", make
            # ONE tools-disabled call to synthesize a real answer from what it
            # already gathered.
            reply = await _finalize_answer(
                http_client, settings, history, system_prompt, silo
            )
            history.append({"role": "model", "parts": [{"text": reply}]})

        if gemini_failed and body.internal:
            # A failed heartbeat is invisible: no apology text, nothing
            # persisted. The breaker still counted it above.
            log.warning("message.internal_failed", silo=silo)
            await session.commit()
            return MessageResponse(reply="", tool_calls=total_tool_calls)

        if gemini_failed:
            # Failed turn: persist NOTHING model-visible — no dangling user
            # turn, no canned apology in history (those poisoned the
            # +1646... silo). Archive the user's real text for recall, then
            # deliver the breaker-managed reply (possibly silence).
            try:
                from hal_orchestrator.services.friction import (
                    KIND_MODEL_FAILURE,
                    log_friction,
                )
                from hal_orchestrator.services.history_search import archive_turn

                await archive_turn(session, silo, "user", user_text)
                log_friction(session, silo, KIND_MODEL_FAILURE, "gemini_failed")
                await _capture_turn(
                    session, silo, sender_phone, user_text, reply,
                    trajectory_steps, "gemini_failed",
                )
            except Exception:
                log.exception("message.archive_failed", silo=silo)
            await session.commit()
            log.info(
                "message.reply", silo=silo, reply=reply[:80], gemini_failed=True
            )
            return MessageResponse(
                reply=reply,
                tool_calls=total_tool_calls,
                side_messages=[
                    SideMessage(to=m["to"], text=m["text"]) for m in ctx.side_messages
                ],
            )

        # Layer 2 hardening: self-critique on plan/recommendation turns, run
        # ASYNCHRONOUSLY — the reply ships immediately; the critic re-checks it
        # in the background and only sends a FOLLOW-UP correction if it finds a
        # substantive flaw (wrong required-state, a non-binding constraint, a
        # hidden tension). Decide here, where history still has the gathered
        # facts, snapshot it, and schedule the task after the save below.
        do_async_critique = False
        critic_history_snapshot: list = []
        if (
            settings.critic_enabled
            and not gemini_failed
            and not stalled
            and not body.internal
            and reply
            and not _is_quiet_sentinel(reply)
        ):
            try:
                from hal_orchestrator.services.critic import should_critique

                if should_critique(user_text, reply, total_tool_calls, is_group):
                    do_async_critique = True
                    critic_history_snapshot = list(history)
            except Exception:
                log.exception("message.critic_gate_failed", silo=silo)

        # Sanitize history before persisting: replace inlineData (base64 images)
        # with a placeholder, and drop raw Claude blocks (`_claude_block`) — they
        # bloat the DB and carry thinking signatures that must not be replayed in
        # a later request's context. A pure-thinking part becomes empty and is
        # dropped; a functionCall part keeps its functionCall (re-loaded text-only).
        clean_history = []
        for entry in history:
            new_parts = []
            for p in entry.get("parts", []):
                if "inlineData" in p:
                    new_parts.append({"text": "[image]"})
                elif "_claude_block" in p:
                    stripped = {k: v for k, v in p.items() if k != "_claude_block"}
                    if stripped:
                        new_parts.append(stripped)
                else:
                    new_parts.append(p)
            if new_parts:
                clean_history.append({"role": entry["role"], "parts": new_parts})

        # Collapse the "stay quiet" sentinel to an empty reply so the bridge
        # sends nothing — HAL opting out of an off-topic message in a watched
        # group should be silent, not a literal "..." bubble. History keeps the
        # real turn so HAL knows it stayed quiet.
        outbound_reply = "" if _is_quiet_sentinel(reply) else reply

        if body.internal:
            # Heartbeat turn. Silent → persist nothing (96 silent checks/day
            # would drown the real conversation and the nightly grader).
            # Alert → persist a compact stub + the alert so HAL remembers what
            # it proactively said (that's also its dedup against re-alerting).
            if outbound_reply:
                await save_conversation(
                    session,
                    silo,
                    clean_history[:pre_turn_len]
                    + [
                        {
                            "role": "user",
                            "parts": [{"text": f"[{stamp}] [heartbeat check — you noticed something and texted the user:]"}],
                        },
                        {"role": "model", "parts": [{"text": reply}]},
                    ],
                    max_turns=settings.max_conversation_turns,
                )
                try:
                    from hal_orchestrator.services.history_search import archive_turn

                    await archive_turn(session, silo, "assistant", reply)
                    await _capture_turn(
                        session, silo, sender_phone, "[heartbeat check]", reply,
                        trajectory_steps, "ok",
                    )
                except Exception:
                    log.exception("message.post_hooks_failed", silo=silo)
            await session.commit()
            log.info(
                "message.heartbeat",
                silo=silo,
                alerted=bool(outbound_reply),
                tool_calls=total_tool_calls,
            )
            return MessageResponse(
                reply=outbound_reply,
                tool_calls=total_tool_calls,
                side_messages=[
                    SideMessage(to=m["to"], text=m["text"]) for m in ctx.side_messages
                ],
            )

        # Save conversation
        await save_conversation(
            session, silo, clean_history, max_turns=settings.max_conversation_turns
        )

        # Best-effort post-hooks: durable archive (full-text/temporal recall) and
        # trajectory capture (auto-skill learning). Wrapped so a failure here can
        # NEVER break the user's reply.
        try:
            from hal_orchestrator.services.history_search import archive_turn
            from hal_orchestrator.services.skill_synthesizer import (
                CAPTURE_MIN_TOOL_CALLS,
                capture_trajectory,
            )

            await archive_turn(session, silo, "user", user_text)
            if outbound_reply:
                await archive_turn(session, silo, "assistant", reply)
            if total_tool_calls >= CAPTURE_MIN_TOOL_CALLS and outbound_reply:
                await capture_trajectory(
                    session, silo, user_text, trajectory_steps, reply
                )
            await _capture_turn(
                session, silo, sender_phone, user_text, reply,
                trajectory_steps, "ok" if outbound_reply else "quiet",
            )
        except Exception:
            log.exception("message.post_hooks_failed", silo=silo)

        await session.commit()

        # Now that the original reply is saved, fire the background critic. It
        # runs after this response returns (the user already has the plan), and
        # only speaks up via the outbox if it finds a real flaw.
        if do_async_critique:
            import asyncio

            delivery_to = chat_id if (is_group and chat_id) else silo
            asyncio.create_task(
                _run_async_critic(
                    settings, http_client, silo, delivery_to,
                    critic_history_snapshot, user_text, reply,
                )
            )

        log.info(
            "message.reply",
            silo=silo,
            reply=reply[:80],
            suppressed=not outbound_reply,
            tool_calls=total_tool_calls,
        )

        return MessageResponse(
            reply=outbound_reply,
            tool_calls=total_tool_calls,
            side_messages=[
                SideMessage(to=m["to"], text=m["text"]) for m in ctx.side_messages
            ],
            result_images=[
                ResultImage(mime_type=img["mime_type"], data=img["data"], ext=img["ext"])
                for img in ctx.result_images
            ],
        )

    @router.get(
        "/api/watched-groups",
        dependencies=[Depends(verify_bridge_auth)],
    )
    async def watched_groups(
        session: AsyncSession = Depends(get_session),
    ) -> dict:
        """Return chat_ids with active trips (bridge forwards all messages)."""
        from hal_orchestrator.services.trips import get_watched_chat_ids

        chat_ids = await get_watched_chat_ids(session)
        return {"chat_ids": chat_ids}

    @router.get(
        "/api/outbox",
        dependencies=[Depends(verify_bridge_auth)],
    )
    async def drain_outbox() -> dict:
        """Return and clear all pending outbox messages (reminders, etc.)."""
        import hal_orchestrator.state as state

        messages = []
        while not state.outbox.empty():
            try:
                messages.append(state.outbox.get_nowait())
            except Exception:
                break
        return {"messages": messages}

    return router
