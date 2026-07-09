"""Code-owned authorization for sensitive tool actions."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ag_db.models import HalActionConfirmation

_SEND_INTENT = re.compile(
    r"\b(text|message|imessage|send|reply to|tell|let\s+.+\s+know)\b", re.I
)
_APPROVAL = re.compile(
    r"^\s*(yes|yep|yeah|ok(?:ay)?|confirm(?:ed)?|send it|do it|go ahead|please do)\b",
    re.I,
)


def arguments_hash(args: dict) -> str:
    safe_args = {k: v for k, v in args.items() if k != "confirmation_token"}
    raw = json.dumps(safe_args, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _explicit_send_request(user_text: str, args: dict) -> bool:
    """Authorize only from the actual inbound text, never model/tool content."""
    if not _SEND_INTENT.search(user_text or ""):
        return False
    target = str(args.get("to") or "").strip().lower()
    if not target:
        return False
    normalized_text = (user_text or "").lower()
    if target in normalized_text:
        return True
    digits = re.sub(r"\D", "", target)
    return bool(digits and digits in re.sub(r"\D", "", normalized_text))


async def _consume_confirmation(args: dict, ctx) -> bool:
    token = str(args.get("confirmation_token") or "").strip()
    if not token or not _APPROVAL.search(ctx.user_text or ""):
        return False
    try:
        token_id = uuid.UUID(token)
    except ValueError:
        return False
    now = datetime.now(timezone.utc)
    row = (
        await ctx.session.execute(
            select(HalActionConfirmation)
            .where(
                HalActionConfirmation.id == token_id,
                HalActionConfirmation.silo == ctx.phone,
                HalActionConfirmation.tool_name == "send_message",
                HalActionConfirmation.arguments_hash == arguments_hash(args),
                HalActionConfirmation.consumed_at.is_(None),
                HalActionConfirmation.expires_at > now,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        return False
    row.consumed_at = now
    await ctx.session.flush()
    return True


async def _stage_confirmation(args: dict, ctx) -> str:
    now = datetime.now(timezone.utc)
    digest = arguments_hash(args)
    row = (
        await ctx.session.execute(
            select(HalActionConfirmation).where(
                HalActionConfirmation.silo == ctx.phone,
                HalActionConfirmation.tool_name == "send_message",
                HalActionConfirmation.arguments_hash == digest,
                HalActionConfirmation.consumed_at.is_(None),
                HalActionConfirmation.expires_at > now,
            ).limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        row = HalActionConfirmation(
            silo=ctx.phone,
            tool_name="send_message",
            arguments_hash=digest,
            source_message_id=ctx.message_id,
            expires_at=now + timedelta(minutes=10),
        )
        ctx.session.add(row)
        await ctx.session.flush()
    return (
        "CONFIRMATION REQUIRED. Do not send yet. Show the user the exact recipient "
        "and message, then ask them to confirm. If their next message explicitly "
        f"approves, call send_message with the same arguments and confirmation_token={row.id}."
    )


async def authorize_tool(spec, args: dict, ctx) -> str | None:
    """Return an error/tool result when blocked, otherwise ``None``."""
    scope = "group" if ctx.is_group else "dm"
    if scope not in spec.scopes:
        return f"Policy blocked {spec.name}: it is not available in {scope} chats."
    if spec.name != "send_message":
        return None
    if ctx.is_group or ctx.internal:
        return "Policy blocked send_message from a group or background turn."
    if _explicit_send_request(ctx.user_text, args):
        return None
    if await _consume_confirmation(args, ctx):
        return None
    return await _stage_confirmation(args, ctx)
