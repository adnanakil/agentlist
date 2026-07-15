"""POST /api/message — core message processing loop.

Receives a message from the iMessage bridge, runs the Gemini tool-use loop,
and returns the final text response.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from collections.abc import AsyncGenerator
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ag_db.session import get_session
from hal_orchestrator.prompts.system import (
    SYSTEM_PROMPT,
    USER_TZ,
    build_user_context,
    compute_onboarding_progress,
    is_onboarding_complete,
    plausible_personal_name,
    resolve_tz,
)
from hal_orchestrator.services.conversation import (
    get_summary,
    load_conversation,
    load_conversation_snapshot,
    save_conversation,
)
from hal_orchestrator.services.gemini import call_gemini
from hal_orchestrator.services.identity import is_group_id, normalize_handle
from hal_orchestrator.services.live_location import (
    requires_live_location as _requires_live_location,
)
from hal_orchestrator.services.profiles import get_profile, update_profile
from hal_orchestrator.state import get_http_client, get_settings
from hal_orchestrator.tools.registry import ToolContext, execute_tool
from hal_orchestrator.tools.specs import all_tool_specs, model_tools

log = structlog.get_logger()


def _live_location_guard_applies(
    *, internal: bool, is_group: bool, text: str, has_location: bool
) -> bool:
    """Pre-model hard stop: a location-anchored search with no validated live
    location must be answered with a question, never a guess. In groups it
    only applies when HAL is explicitly addressed — otherwise members chatting
    about "anything nearby?" among themselves would summon an uninvited canned
    reply that bypasses the group mute and tact gates further down."""
    if internal or has_location or not _requires_live_location(text):
        return False
    return not is_group or bool(_HAL_MENTION_RX.search(text or ""))


def _is_quiet_sentinel(text: str) -> bool:
    """True if the model's reply is its 'stay silent' sentinel — empty, or only
    dots/ellipsis/whitespace (e.g. '...', '…'). Such replies are collapsed to an
    empty outbound reply so the bridge sends nothing (it skips empty replies),
    instead of posting a literal '...' bubble in the group."""
    return text.strip().strip(".…·•- \t\n") == ""


def _contains_quiet_sentinel(text: str) -> bool:
    """For internal/heartbeat turns: True if the reply contains the ellipsis
    silence sentinel as a STANDALONE element — leading ('… x'), a line that is
    only dots/ellipsis, or a trailing bare '…' token. A chatty background model
    (e.g. GLM) emits the '...' silence token but wraps it in explanation (before
    it, after it, or on its own line: "... all newsletters", "nothing to
    flag\\n\\n..."), which _is_quiet_sentinel (pure-sentinel only) misses, so the
    whole ramble gets texted. A real proactive alert is a direct nudge with no
    bare sentinel token. Inline ellipsis ('delayed at 9...') and '.NET update'
    are NOT caught (the sentinel must be its own token)."""
    s = text.strip()
    if not s:
        return False
    if s[0] == "…" or s[:2] == "..":                 # leading sentinel: "… x" / ".. x"
        return True
    for line in s.splitlines():                       # a line that is ONLY dots/ellipsis
        ls = line.strip()
        if ls and not ls.strip(".… "):
            return True
    # Trailing bare "…" token: only a sentinel on SHORT replies ("nothing to
    # flag ..."). A long multi-sentence alert that merely trails off with an
    # ellipsis ("Rain at 3 — grab the walk in before then …") is a REAL alert;
    # eating it was over-suppression.
    if len(s) <= 80 and not s.rsplit(None, 1)[-1].strip(".…"):
        return True
    return False


# How many times HAL may re-alert about substantively the SAME thing (within the
# recent history window) before a heartbeat is muzzled. The 06-27 bug re-sent the
# identical "leave by 3:30 for the 5pm match" ~24x; 06-28 sent ~7 World-Cup-pool
# countdown reminders for one deadline. Cap lets a couple of escalating nudges
# through, then goes quiet. Env-tunable; set very high to disable.
HEARTBEAT_REPEAT_CAP = int(os.environ.get("HEARTBEAT_REPEAT_CAP", "2"))

_STOP = frozenset(
    "the a an to of for and or in on at is it you your i we be by with as that this "
    "if so are was were will just got get up out now today day yet from has have had "
    "not no but they them he she his her our about into over under than then".split()
)


def _alert_words(text: str) -> set[str]:
    """Content words of an alert (lowercased, stopwords + pure-number tokens
    dropped) for similarity. Dropping numbers makes a countdown collapse:
    '1 hour left' and '28 min left' share the same content words."""
    return {w for w in re.findall(r"[a-z]+", text.lower()) if w not in _STOP and len(w) > 1}


def _is_repeat_alert(reply: str, history: list[dict], cap: int = HEARTBEAT_REPEAT_CAP,
                     window: int = 30, thr: float = 0.5) -> bool:
    """True if `reply` is substantively the (cap+1)-th time HAL has said this
    among the last `window` model turns — i.e. it has already alerted ~cap times.
    Jaccard over content words; >= thr counts as 'the same alert'. Two distinct
    alerts that merely share a phrase stay under thr and both go out; a
    countdown / re-nudge about one event piles up and gets muzzled past the cap.
    Internal (heartbeat) turns only — never gates a real user reply."""
    rw = _alert_words(reply)
    if len(rw) < 5:
        return False
    similar = 0
    for entry in reversed(history[-window:]):
        if entry.get("role") != "model":
            continue
        prev = " ".join(p.get("text", "") for p in entry.get("parts", []) if p.get("text"))
        pw = _alert_words(prev)
        if pw and len(rw & pw) / len(rw | pw) >= thr:
            similar += 1
            if similar >= cap:
                return True
    return False


# Leads that mark a heartbeat as a NON-alert: it's re-referencing what it
# already said, or declaring there's nothing new. The background model keeps
# narrating the same unread inbox every cycle ("Already flagged X in my 7:37
# check. Nothing new…") — reworded each time, so it slips under _is_repeat_alert's
# Jaccard threshold. If a heartbeat LEADS with one of these, it should have
# stayed silent; suppress it.
_REHASH_LEADS = (
    "already flagged", "already mentioned", "already noted", "already covered",
    "already told", "already sent", "already surfaced", "already caught",
    "already pinged", "already gave", "as i flagged", "as i mentioned",
    "as flagged", "as mentioned", "as noted", "nothing new", "nothing else new",
    "nothing else worth", "nothing to flag", "nothing else to flag",
    # NB: "no new " is deliberately NOT in this list — a real alert can lead
    # with it ("No new flights — your 5pm is cancelled") and identity-keyed
    # dedup (heartbeat seen-items) now covers the inbox-rehash case.
    "all quiet", "still quiet", "still nothing",
    # Conversational acknowledgments: a heartbeat is never a conversational
    # turn, but the background model sometimes "replies" to the last (old)
    # user message in history ("Got it, noted that it's topped up!"). A real
    # alert leads with the thing ("Heads up: ..."), never with an ack.
    "got it", "noted", "understood", "roger", "will do", "sounds good",
)
_GREETING_RE = re.compile(
    r"^(hey|hi|hello|good\s+(morning|evening|afternoon)|morning|evening|afternoon)"
    r"[\s,!.…—–-]*(adnan)?[\s,!.…—–:-]*",
    re.I,
)


def _is_rehash_heartbeat(reply: str) -> bool:
    """True if the heartbeat LEADS with a rehash / 'nothing new' declaration —
    a non-alert masquerading as one. Distinct from _is_repeat_alert (which needs
    textual overlap with a specific prior alert); this catches the reworded
    'already flagged X' rehash. Checks only the LEAD, so a real alert that leads
    with new info and merely ends '…nothing else urgent' still goes out."""
    head = _GREETING_RE.sub("", reply.strip()).lstrip().lower()
    return head.startswith(_REHASH_LEADS)


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
# iMessage markdown normalization — iMessage shows markdown syntax literally.
# --------------------------------------------------------------------------- #

import re as _md_re

_MD_BOLD = _md_re.compile(r"\*\*(.+?)\*\*", _md_re.DOTALL)
# *italic* — word-boundary guards so "3 * 4" (multiplication) is left alone.
_MD_ITALIC = _md_re.compile(r"(?<![\w*])\*(?=\S)(.+?)(?<=\S)\*(?![\w*])", _md_re.DOTALL)
_MD_HEADER = _md_re.compile(r"^\s{0,3}#{1,6}\s+", _md_re.MULTILINE)
_MD_CODE = _md_re.compile(r"`([^`]+)`")


def _strip_markdown(text: str) -> str:
    if not text or ("*" not in text and "#" not in text and "`" not in text):
        return text
    text = _MD_BOLD.sub(r"\1", text)
    text = _MD_ITALIC.sub(r"\1", text)
    text = _MD_HEADER.sub("", text)
    text = _MD_CODE.sub(r"\1", text)
    return text


# --------------------------------------------------------------------------- #
# Runaway-loop handling — synthesize an answer instead of leaking an error
# --------------------------------------------------------------------------- #

# If the model calls the SAME tool this many times in one turn, it's almost
# certainly stuck (e.g. re-running web_search on thin results forever). Stop and
# answer from what's gathered rather than burning the whole iteration budget.
# Tuned up from 8: legitimately search-heavy requests (find 3 date-night spots →
# one resy/web call per venue) need more same-tool calls and were tripping a
# false runaway; 12 still catches a true loop before the 15-iteration cap.
REPEAT_TOOL_LIMIT = 12

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
            # The reasoning is already done — this call just writes the answer
            # from what's in history. Force thinking LOW so it can't spend the
            # shared token budget re-thinking and truncate again (finalize is
            # also the repair path for a MAX_TOKENS turn, so it MUST NOT be
            # prone to the same failure it's fixing).
            thinking_level="LOW",
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


# --------------------------------------------------------------------------- #
# Parallel tool execution — network-only tools with no DB-session use may run
# concurrently within one model turn (a plan turn firing weather + travel_time
# + several web_searches otherwise pays the SUM of their latencies). Everything
# else stays sequential: the SQLAlchemy AsyncSession is not concurrency-safe.
# (log_friction on the error path is a sync session.add — no awaited IO — so
# even concurrent failures are safe.)
# --------------------------------------------------------------------------- #

PARALLEL_SAFE_TOOLS = frozenset(
    spec.name for spec in all_tool_specs() if spec.parallel_safe
)

# --------------------------------------------------------------------------- #
# Auto archive recall — messages that reference past discussion pull matching
# older turns from the durable archive into context, instead of relying on the
# model to think of calling recall_history (it usually doesn't).
# --------------------------------------------------------------------------- #

_PAST_REF_RX = re.compile(
    r"\b(remember (when|what|that|the)|last (time|week|month)|a while (ago|back)|"
    r"the other (day|night|week)|we (talked|discussed|spoke|went over)|"
    r"you (said|told me|mentioned|recommended|suggested|found)|"
    r"what did (i|we|you)|(that|the) (place|restaurant|spot|hotel|article|thing) "
    r"(you|we|i) (mentioned|found|liked|talked)|as (we )?discussed)\b",
    re.I,
)

_RECALL_STOP = frozenset(
    "the a an to of for and or in on at is it you your i we that this what did "
    "was were when where remember mentioned said told about with have had".split()
)


async def _auto_recall_archive(session, silo: str, user_text: str) -> list[dict]:
    """Best-effort archive lookup for a past-referencing message. Full-text
    first; if the AND-semantics FTS misses, retry with the two most distinctive
    keywords. Only returns turns older than 6h — newer ones are already in the
    rolling context window."""
    from hal_orchestrator.services.history_search import search_history

    cutoff = 6 * 60 * 60
    now = datetime.now().astimezone()

    def _older_than_cutoff(rows: list[dict]) -> list[dict]:
        out = []
        for r in rows:
            try:
                at = datetime.fromisoformat(r["at"]) if r.get("at") else None
            except ValueError:
                at = None
            if at is None or (now - at).total_seconds() >= cutoff:
                out.append(r)
        return out

    rows = _older_than_cutoff(
        await search_history(session, silo, query=user_text, limit=8)
    )
    if not rows:
        words = sorted(
            {
                w
                for w in re.findall(r"[a-z0-9']+", user_text.lower())
                if w not in _RECALL_STOP and len(w) > 3
            },
            key=len,
            reverse=True,
        )[:2]
        if words:
            rows = _older_than_cutoff(
                await search_history(session, silo, query=" ".join(words), limit=8)
            )
    return rows[:5]


# --------------------------------------------------------------------------- #
# Claimed-action verification — the recurring trust-killer in the nightly
# grades: HAL SAYS it set a reminder / logged the feed / created the watch but
# made no such tool call, and only admits it next turn. A prompt rule (playbook)
# didn't fix it, so enforce it mechanically: scan the final reply for action
# claims, check the turn's actual tool calls, and when a claim is unbacked run
# one corrective mini-loop that either performs the action for real or rewrites
# the reply to stop claiming it.
# --------------------------------------------------------------------------- #

_ACTION_CLAIMS: list[tuple[re.Pattern, frozenset, str]] = [
    (
        re.compile(
            r"\b(reminder('s| is| has been)? (set|created|scheduled)|"
            r"(i('ve| have)? |just )set (a |the |that |your )?reminder|"
            r"i('ll| will) remind you)\b",
            re.I,
        ),
        frozenset({"set_reminder", "baby", "schedule"}),
        "set_reminder",
    ),
    (
        re.compile(
            r"\b(logged|log it|got (it|that|him|her) (logged|down)|noted (the|that|his|her) "
            r"(feed|nap|wake|bedtime|diaper))\b",
            re.I,
        ),
        frozenset({"baby"}),
        "baby log",
    ),
    (
        re.compile(
            r"\b(i('ve| have)? scheduled|task (is )?scheduled|"
            r"scheduled (it|that|the task) for)\b",
            re.I,
        ),
        frozenset({"schedule", "set_reminder"}),
        "schedule",
    ),
    (
        re.compile(
            r"\b((added|created|put) (it|that|an? (event|hold)) (on|to|in) your calendar|"
            r"calendar (event|invite|hold) (is )?(created|added|set))\b",
            re.I,
        ),
        frozenset({"google_calendar"}),
        "calendar event",
    ),
    (
        re.compile(
            r"\b(i('m| am) (now )?watching (for|the)|watch (is )?(set|created|live)|"
            r"i('ll| will) (keep an eye on|watch for|let you know (the moment|when|if)))\b",
            re.I,
        ),
        frozenset({"watch", "schedule", "set_reminder"}),
        "watch",
    ),
    (
        re.compile(
            r"\b(texted (him|her|them|your)|sent (the|a|your) (message|text)|"
            r"message (is )?sent)\b",
            re.I,
        ),
        frozenset({"send_message", "delegate"}),
        "send_message",
    ),
    (
        re.compile(
            r"\b(draft (is )?(saved|created|ready)|drafted (an|the|that) email|"
            r"email (is )?(sent|on its way))\b",
            re.I,
        ),
        frozenset({"google_gmail", "delegate"}),
        "email",
    ),
]


def _unbacked_action_claims(reply: str, tools_used: set[str]) -> list[str]:
    """Action claims in `reply` with no matching tool call this turn."""
    return [
        label
        for rx, accepted, label in _ACTION_CLAIMS
        if rx.search(reply) and not (tools_used & accepted)
    ]


# An honest non-claim ("I couldn't log it — was that a bottle?") re-uses the
# claim vocabulary, so the bare _ACTION_CLAIMS regexes match it too. The
# enforcer's re-verify must not bounce a correction that is plainly saying
# the action did NOT happen.
_NEGATION_RX = re.compile(
    r"\b(couldn'?t|could not|can'?t|cannot|didn'?t|did not|haven'?t|"
    r"wasn'?t able|was not able|unable to|failed to|won'?t be able|"
    r"not (?:been )?(?:logged|set|created|sent|scheduled|saved)|"
    r"no(?:t yet|thing was))\b",
    re.I,
)


def _looks_like_honest_correction(text: str) -> bool:
    """True when the rewrite carries an explicit negation — it's describing a
    failure/limitation, not re-claiming the action. Pure so it's testable."""
    return bool(_NEGATION_RX.search(text))


async def _enforce_claimed_actions(
    http_client,
    settings,
    history: list,
    system_prompt: str,
    ctx,
    silo: str,
    model: str | None,
    thinking_level: str | None,
    unbacked: list[str],
    trajectory_steps: list[dict],
    tools_used: set[str] | None = None,
) -> tuple[str | None, int]:
    """One corrective mini-loop (<=3 iterations, tools enabled). Returns
    (corrected_reply or None on failure, tool_calls_made). Mutates `history`
    in place — the correction becomes part of the persisted turn.

    The corrected text is RE-CHECKED before being accepted: a model that
    answers the self-check with a reworded reply still claiming the action
    (and still no tool call) gets pushed again instead of shipping the same
    lie twice (the exact hole behind the 07-01 'logged ✅ but never saved'
    incident)."""
    from hal_orchestrator.services.gemini import call_gemini

    history.append(
        {
            "role": "user",
            "parts": [
                {
                    "text": (
                        "[SELF-CHECK — automated, the user did NOT send this and "
                        "will only see your corrected reply] Your reply claims you "
                        f"performed: {', '.join(unbacked)} — but you made NO "
                        "matching tool call this turn, so it did NOT happen. "
                        "Fix it now: (a) actually perform the action(s) with the "
                        "real tool(s), then send your reply confirming what you "
                        "truly did; or (b) if you can't do it, rewrite the reply "
                        "to stop claiming it and say what you need. Output ONLY "
                        "the final corrected message to the user."
                    )
                }
            ],
        }
    )
    extra_calls = 0
    mini_used: set[str] = set(tools_used or set())
    last_text: str | None = None
    for _ in range(3):
        try:
            response = await call_gemini(
                client=http_client,
                settings=settings,
                history=history,
                tools=model_tools(),
                system=system_prompt,
                model=model,
                thinking_level=thinking_level,
            )
        except Exception:
            log.exception("message.claim_check_call_failed", silo=silo)
            return None, extra_calls
        candidates = (response or {}).get("candidates", [])
        parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
        if not parts:
            return None, extra_calls
        func_calls = [p for p in parts if "functionCall" in p]
        if func_calls:
            history.append({"role": "model", "parts": parts})
            func_responses = []
            for fc in func_calls:
                call = fc["functionCall"]
                tool_name = call["name"]
                tool_args = call.get("args", {})
                extra_calls += 1
                mini_used.add(tool_name)
                trajectory_steps.append(
                    {"tool": tool_name, "args": list(tool_args.keys())[:8]}
                )
                from hal_orchestrator.tools.registry import execute_tool

                result = await execute_tool(tool_name, tool_args, ctx)
                await ctx.session.commit()
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
        text = "\n".join(p.get("text", "") for p in parts if "text" in p).strip()
        if text:
            still = _unbacked_action_claims(text, mini_used)
            if still and not _looks_like_honest_correction(text):
                # Reworded, still claiming, still no tool call — push again.
                log.warning(
                    "message.claim_still_unbacked", silo=silo, claims=still
                )
                last_text = text
                history.append({"role": "model", "parts": [{"text": text}]})
                history.append(
                    {
                        "role": "user",
                        "parts": [
                            {
                                "text": (
                                    "[SELF-CHECK — automated] Your rewrite STILL "
                                    f"claims: {', '.join(still)} — and you still "
                                    "made no matching tool call. Either CALL THE "
                                    "TOOL now, or remove the claim entirely."
                                )
                            }
                        ],
                    }
                )
                continue
            history.append({"role": "model", "parts": [{"text": text}]})
            return text, extra_calls
        return None, extra_calls
    # Iterations exhausted with the model still using claim wording. Ship its
    # LAST rewrite rather than None: the caller keeps the ORIGINAL reply when
    # we return None, and the original is the confirmed-unbacked claim — the
    # one thing that must not ship. Trim the dangling SELF-CHECK user turn so
    # history ends on the model turn the user actually received.
    if last_text is not None:
        if history and history[-1].get("role") == "user":
            history.pop()
        return last_text, extra_calls
    return None, extra_calls


# --------------------------------------------------------------------------- #
# Group tact gate — a second-pass model judgment on UNPROMPTED interjections in
# ambient-watched groups. The AMBIENT_WATCH_BLOCK prompt already demands
# silence-by-default, but at temperature the model still commiserates with
# banter ("The absolute worst 🙄 any idea what they're filming?" — 2026-07-02).
# Same pattern as the reminder relevance gate: relevance/tact is the model's
# call, made by a fresh skeptical pass rather than a hard-coded rule.
# --------------------------------------------------------------------------- #

_HAL_MENTION_RX = re.compile(r"\bhal\b", re.I)
_URL_RX = re.compile(r"https?://|\bwww\.", re.I)

GROUP_TACT_SYSTEM = (
    "You are the tact filter for HAL, an AI assistant that silently watches a "
    "group chat. HAL drafted an UNPROMPTED message — nobody addressed it. Most "
    "such interjections should NOT be sent; the members are talking to each "
    "other, and an assistant that chimes into banter is annoying."
)


# A reply that CONFIRMS concrete work HAL just did — logged a baby event, set a
# reminder, scheduled/watched something — is the expected response to a request
# directed at HAL, NOT a social interjection. The family baby-logging group is
# the clear case: "Bazzy went down" is a log-this instruction, and its "Down for
# a nap at 10:12" ack was being dropped by the on-the-ground-report DROP rule.
# Turns using one of these action tools skip the tact gate. (Read/lookup tools
# like web_search/places are deliberately excluded — those back the exact
# unprompted interjections the gate exists to catch.)
TACT_EXEMPT_TOOLS = frozenset(
    {"baby", "set_reminder", "schedule", "trip", "watch", "group_quiet"}
)


def _needs_group_tact_gate(
    is_group: bool, ambient_watch: bool, internal: bool, user_text: str,
    reply: str, tools_used: set[str] | None = None,
) -> bool:
    """True for an UNPROMPTED interjection into an ambient-watched group:
    nobody said 'Hal' (word-boundary — 'halloween' doesn't count), the message
    carries no link (links have the always-TL;DR duty), HAL drafted a real
    non-sentinel reply, and the turn didn't perform a concrete action whose
    confirmation is legitimate (baby log, reminder, …)."""
    if tools_used and (set(tools_used) & TACT_EXEMPT_TOOLS):
        return False
    return (
        is_group
        and ambient_watch
        and not internal
        and bool(reply)
        and not _is_quiet_sentinel(reply)
        and not _HAL_MENTION_RX.search(user_text or "")
        and not _URL_RX.search(user_text or "")
    )


def build_tact_prompt(
    recent: str, sender: str, user_text: str, draft: str, summary: str = ""
) -> str:
    """The user-turn handed to the tact-gate model. Pure so it's unit-testable."""
    summary_block = (
        f"What HAL knows about this group so far:\n{summary}\n\n" if summary else ""
    )
    return (
        f"{summary_block}"
        "Recent group conversation (oldest first):\n"
        f"{recent or '(none)'}\n\n"
        f"Newest message (from {sender or 'a member'}): {user_text}\n\n"
        f"HAL's drafted interjection:\n{draft}\n\n"
        "Send ONLY if it delivers specific, timely, genuinely USEFUL substance "
        "the members don't already have — a real answer to an open question, a "
        "needed factual correction, or concrete logistics they're actively "
        "trying to figure out. DROP anything that is: agreement, sympathy, "
        "banter, a reaction, commentary on a shared photo, a curiosity "
        "question, generic tips, or restating what members said.\n"
        "Two hard DROP rules that override everything above:\n"
        "- The newest message reports the sender's OWN on-the-ground situation "
        "(what's happening around them right now — a line they're standing in, "
        "a check-in they're going through, something they're watching happen). "
        "They are THERE and have better information than HAL; correcting or "
        "reassuring them about their own live situation is presumptuous. DROP, "
        "even if HAL's facts seem right.\n"
        "- The members told HAL to stay out of it (any 'butt out', 'keep it to "
        "yourself', 'stfu', 'not invited', 'please chill' in the conversation "
        "or the group context above). After that, ONLY a direct question to "
        "HAL warrants a reply — and that case never reaches this filter. DROP.\n"
        "A tactful human assistant interrupts a group RARELY. When in doubt, "
        "DROP.\n"
        "- Reply exactly DROP to not send it.\n"
        "- Reply exactly SEND to send it as written.\n"
        "- Reply 'SEND: <tighter text>' to send a trimmed version.\n"
        "Reply with only that — no explanation."
    )


async def _run_tact_gate(
    http_client, settings, history: list, sender: str, user_text: str,
    draft: str, silo: str, summary: str = "",
):
    """Gate verdict for an unprompted group interjection, or None on model
    failure (caller fails open = send; the in-prompt default is DROP)."""
    from hal_orchestrator.services.gemini import call_gemini
    from hal_orchestrator.services.reminders import parse_gate_verdict

    lines: list[str] = []
    for entry in history[-10:-1]:
        text = " ".join(
            p.get("text", "") for p in entry.get("parts", []) if p.get("text")
        ).strip()
        if text:
            who = "HAL" if entry.get("role") == "model" else "member"
            lines.append(f"{who}: {text[:200]}")
    prompt = build_tact_prompt(
        "\n".join(lines[-8:]), sender, user_text, draft, summary=summary[:1200]
    )

    resp = await call_gemini(
        client=http_client,
        settings=settings,
        history=[{"role": "user", "parts": [{"text": prompt}]}],
        tools=None,
        system=GROUP_TACT_SYSTEM,
        model=settings.gemini_background_model,
    )
    if not resp:
        return None
    parts = (resp.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
    verdict = parse_gate_verdict("".join(p.get("text", "") for p in parts))
    log.info(
        "message.tact_gate", silo=silo, drop=verdict.drop, reworded=bool(verdict.text)
    )
    return verdict


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
    mime_type: str = Field(
        min_length=3,
        max_length=64,
        pattern=r"^image/(jpeg|jpg|png|gif|webp|heic|heif)$",
    )
    data: str = Field(min_length=1, max_length=8_000_000)  # base64


class CurrentLocationData(BaseModel):
    """Ephemeral location asserted by the authenticated Mac bridge."""

    label: str = Field(min_length=1, max_length=300)
    updated: str | None = Field(default=None, max_length=80)
    observed_at: datetime
    source: str = Field(default="find_my", pattern=r"^find_my$")
    approximate: bool | None = None


class MessageRequest(BaseModel):
    message_id: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str = Field(min_length=1, max_length=255)
    text: str = Field(max_length=12000)
    sender_name: str | None = Field(default=None, max_length=200)
    is_group: bool = False
    group_name: str | None = Field(default=None, max_length=200)
    chat_id: str | None = Field(default=None, max_length=255)
    images: list[ImageData] = Field(default_factory=list, max_length=4)
    current_location: CurrentLocationData | None = None
    # Internal turn (heartbeat/daemon): the user did not send this. A silent
    # outcome persists NOTHING (no history, no archive, no turn capture); an
    # alert persists a compact stub instead of the synthetic prompt.
    internal: bool = False
    # Per-call model override for the main loop (None → settings.gemini_model).
    # Lets a background turn (heartbeat) run on a cheap model while real user
    # messages stay on the configured main model.
    model: str | None = None
    thinking_level: str | None = None


class SideMessage(BaseModel):
    id: str | None = None
    to: str
    text: str


class ResultImage(BaseModel):
    mime_type: str
    data: str  # base64
    ext: str


class MessageResponse(BaseModel):
    reply: str
    tool_calls: int = 0
    side_messages: list[SideMessage] = Field(default_factory=list)
    result_images: list[ResultImage] = Field(default_factory=list)


class OutboxAckRequest(BaseModel):
    message_ids: list[str] = Field(min_length=1, max_length=200)
    delivered: bool = True


def _stable_message_payload(body: MessageRequest) -> dict:
    """Exclude an ephemeral location refresh from inbound idempotency."""
    return body.model_dump(mode="json", exclude={"current_location"})


def _sanitize_persisted_history(
    history: list[dict], live_location_label: str | None = None
) -> list[dict]:
    """Remove binary payloads, provider internals, and raw live locations."""
    # The model often copies the Find My label into its own tool args (e.g. a
    # places query). Those functionCall parts persist verbatim, so the label
    # itself must be scrubbed from them — redacting only the current_location
    # functionResponse below would leave the address in history via the args.
    # Visible text turns are governed by the prompt rule ("don't repeat the
    # precise address unless asked") and stay untouched.
    label_re = (
        re.compile(re.escape(live_location_label), re.IGNORECASE)
        if live_location_label and len(live_location_label) >= 4
        else None
    )

    def scrub_call(part: dict) -> dict:
        if label_re is None or "functionCall" not in part:
            return part

        def scrub(node):
            if isinstance(node, str):
                return label_re.sub("[live location expired]", node)
            if isinstance(node, list):
                return [scrub(item) for item in node]
            if isinstance(node, dict):
                return {key: scrub(value) for key, value in node.items()}
            return node

        return scrub(part)

    clean_history = []
    for entry in history:
        new_parts = []
        for part in entry.get("parts", []):
            response = part.get("functionResponse") or {}
            if response.get("name") == "current_location":
                new_parts.append(
                    {
                        "functionResponse": {
                            "name": "current_location",
                            "response": {
                                "content": "[live location used for this turn; expired]"
                            },
                        }
                    }
                )
            elif "inlineData" in part:
                new_parts.append({"text": "[image]"})
            elif "_claude_block" in part:
                stripped = {key: value for key, value in part.items() if key != "_claude_block"}
                if stripped:
                    new_parts.append(scrub_call(stripped))
            else:
                new_parts.append(scrub_call(part))
        if new_parts:
            clean_history.append({"role": entry["role"], "parts": new_parts})
    return clean_history


# --------------------------------------------------------------------------- #
# Auth dependency
# --------------------------------------------------------------------------- #


import hmac as _hmac


async def verify_bridge_auth(authorization: str = Header(...)) -> None:
    """Verify the bridge shared secret.

    Fails CLOSED: an unset secret rejects every request instead of matching
    'Bearer ' (the empty-secret bypass). Constant-time compare avoids leaking
    the secret through response timing. This check is what makes it safe to
    trust the caller-supplied `phone`/silo in the request body — only the
    bridge holds the secret, so no one can impersonate another user's silo.
    """
    settings = get_settings()
    secret = settings.hal_bridge_secret
    if not secret:
        log.error("message.auth_no_secret")
        raise HTTPException(status_code=503, detail="Service not configured")
    expected = f"Bearer {secret}"
    if not _hmac.compare_digest(authorization or "", expected):
        raise HTTPException(status_code=401, detail="Invalid authorization")


_silo_turn_locks: dict[str, asyncio.Lock] = {}


async def serialize_silo_turn(body: MessageRequest) -> AsyncGenerator[None, None]:
    """Bound same-process concurrency; DB versions handle cross-replica races."""
    sender = normalize_handle(body.phone)
    key = (body.chat_id or body.phone) if body.is_group else (sender or body.phone)
    lock = _silo_turn_locks.setdefault(key, asyncio.Lock())
    settings = get_settings()
    try:
        await asyncio.wait_for(
            lock.acquire(), timeout=settings.silo_concurrency_wait_seconds
        )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=409,
            detail="another message in this chat is still processing",
            headers={"Retry-After": "2"},
        ) from exc
    try:
        yield
    finally:
        lock.release()


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
        _turn_slot: None = Depends(serialize_silo_turn),
    ) -> MessageResponse:
        """Process an incoming message through the Gemini tool-use loop."""
        from hal_orchestrator.services.curator import mark_activity

        settings = get_settings()
        http_client = get_http_client()

        user_text = body.text
        if len(user_text) > settings.max_message_chars:
            raise HTTPException(status_code=413, detail="message text is too large")
        if len(body.images) > settings.max_images_per_message or any(
            len(image.data) > settings.max_image_base64_chars for image in body.images
        ):
            raise HTTPException(status_code=413, detail="image payload is too large")

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

        # Claim the bridge event before any model call or side effect. Older
        # bridge payloads without message_id remain accepted for a staged rollout.
        from hal_orchestrator.services.idempotency import begin as begin_inbound
        from hal_orchestrator.services.idempotency import complete as complete_inbound

        duplicate = await begin_inbound(
            session,
            message_id=body.message_id,
            silo=silo,
            payload=_stable_message_payload(body),
        )
        if duplicate is not None:
            return MessageResponse.model_validate(duplicate)
        if not body.message_id:
            log.warning("message.missing_idempotency_key", silo=silo)

        async def finish(response: MessageResponse) -> MessageResponse:
            await complete_inbound(
                session, body.message_id, response.model_dump(mode="json")
            )
            return response

        # A live-location request must never fall through to profile/history or
        # model guesses. The Mac bridge attaches a validated Find My label when
        # it has one; otherwise ask for an origin before running any search.
        if _live_location_guard_applies(
            internal=body.internal,
            is_group=is_group,
            text=user_text,
            has_location=body.current_location is not None,
        ):
            log.info("message.live_location_required", silo=silo)
            return await finish(
                MessageResponse(
                    reply=(
                        "I can’t get a usable live location from Find My right now. "
                        "What neighborhood, address, or landmark should I search around?"
                    )
                )
            )

        # Group-context catalog: record that this member spoke in this group —
        # the only provable membership signal we have (rosters can't be
        # enumerated). Feeds their own 1:1 catalog/pull later; best-effort so
        # a write hiccup here can never block the turn.
        if is_group and sender_phone:
            try:
                from hal_orchestrator.services.group_catalog import (
                    record_participation,
                )

                await record_participation(session, silo, sender_phone, body.group_name)
            except Exception:
                log.exception("message.group_catalog_record_failed", silo=silo)

        # Notify curator idle tracker so it backs off while users are active.
        # Internal (heartbeat) turns are not user activity.
        if not body.internal:
            mark_activity()

        log.info(
            "message.received",
            silo=silo,
            sender=sender_phone,
            is_group=is_group,
            text=user_text[:80] if settings.log_message_content else None,
            text_len=len(user_text),
            images=len(body.images),
        )

        # Handle /clear command
        if user_text.strip().lower() in ("/clear", "/reset"):
            from hal_orchestrator.services.conversation import clear_conversation

            await clear_conversation(session, silo)
            await session.commit()
            return await finish(MessageResponse(reply="Conversation cleared."))

        # Echo guard: one of HAL's own canned failure replies arriving as an
        # inbound message means the bridge bounced our send back. Drop it —
        # processing it creates the user/model error loop.
        if user_text.strip() in FALLBACK_REPLIES:
            log.warning("message.echo_suppressed", silo=silo)
            return await finish(MessageResponse(reply=""))

        # Per-user message quota. A metered (1:1, real, non-admin) user over the
        # monthly free cap gets a funding prompt instead of a model run — this is
        # the free-tier -> paid boundary. Checked before any expensive work so a
        # capped user costs us nothing. Best-effort: a quota error must never
        # block a legitimate reply, so we fail open.
        from hal_orchestrator.services.usage import (
            enforce_quota,
            funding_message,
            is_metered,
        )

        if is_metered(silo, is_group, body.internal, settings):
            try:
                quota = await enforce_quota(session, silo, settings)
            except Exception:
                log.exception("message.quota_check_failed", silo=silo)
                quota = None
            if quota is not None and not quota.allowed:
                # Give this user a pay link that binds a completed payment back to
                # their silo (auto-unlock via the Stripe webhook). Falls back to
                # the static message when no payment link is configured.
                from hal_orchestrator.services.billing import pay_url_for

                pay_url = pay_url_for(settings, silo)
                reply_text = (
                    funding_message(settings, quota.limit, pay_url=pay_url)
                    if pay_url
                    else quota.message
                )
                await session.commit()  # persist the admin-notify marker, if any
                return await finish(MessageResponse(reply=reply_text))

        # Load the silo's profile (the user's in 1:1; the group's shared notes
        # in groups) and build context. In groups we deliberately do NOT load
        # the sender's personal profile/memories — only their display name, so
        # nothing private can leak into a group reply.
        profile = await get_profile(session, silo)
        # Resolve the user's own timezone (1:1 only — a group has no single tz)
        # so the time block and message stamp read in their local time.
        user_tz = resolve_tz(profile) if not is_group else USER_TZ
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

        # Persistent mute — a member told HAL to butt out of this group (the
        # group_quiet tool made it durable). Non-mention messages are force-
        # silenced HERE, before any model call, so an interjection can't even
        # be drafted; the transcript still lands in history so context stays
        # complete for when HAL is summoned. Explicit "Hal" mentions go through
        # (with a quiet-mode note added to the prompt below). Internal turns
        # (heartbeat/cron) pass through — their own restraint gates apply.
        group_muted_until = None
        if is_group and not body.internal:
            from hal_orchestrator.services.watched import muted_until as _muted_until

            group_muted_until = await _muted_until(session, chat_id)
        if group_muted_until is not None and not _HAL_MENTION_RX.search(user_text or ""):
            from hal_orchestrator.services.history_search import archive_turn

            history = await load_conversation(session, silo)
            # Same self-echo guard as the main path: a bounced HAL send must
            # not be archived as if a member wrote it.
            if len(user_text.strip()) >= 20 and history and history[-1].get("role") == "model":
                last_text = "\n".join(
                    p.get("text", "") for p in history[-1].get("parts", []) if "text" in p
                ).strip()
                if last_text and user_text.strip() == last_text:
                    log.warning("message.self_echo_suppressed", silo=silo)
                    return await finish(MessageResponse(reply=""))
            # Image-only messages persist a placeholder, mirroring the history
            # sanitizer — an empty text turn would be dropped on next load.
            visible = user_text.strip()
            if body.images:
                visible = f"{visible} [image]".strip()
            stamp = datetime.now(user_tz).strftime("%a %b %-d %-I:%M %p")
            history.append(
                {"role": "user", "parts": [{"text": f"[{stamp}] {visible}"}]}
            )
            history.append({"role": "model", "parts": [{"text": "..."}]})
            await save_conversation(
                session, silo, history, max_turns=settings.max_conversation_turns
            )
            try:
                if visible:
                    await archive_turn(session, silo, "user", visible)
                await _capture_turn(
                    session, silo, sender_phone, visible, "...", [], "muted"
                )
            except Exception:
                log.exception("message.mute_hooks_failed", silo=silo)
            await session.commit()
            log.info("message.muted_silent", silo=silo, until=str(group_muted_until))
            return await finish(MessageResponse(reply=""))

        # Group-aware warm start (1:1, brand-new user only): if this sender is a
        # known member of a group HAL is in, the onboarding opener places itself
        # in that shared context instead of a cold intro. If we can already
        # WITNESS their name (their own iMessage display name), pre-fill it rather
        # than ask a fact we effectively have. One-way valve: their OWN membership
        # + OWN name only — never another member's data. Best-effort.
        group_intro: str | None = None
        if not is_group and not body.internal and not profile.get("onboarded"):
            try:
                from hal_orchestrator.services.group_catalog import first_group_name

                group_intro = await first_group_name(session, silo)
            except Exception:
                log.exception("message.first_group_failed", silo=silo)
            if group_intro and not profile.get("name"):
                cand = plausible_personal_name(body.sender_name)
                if cand:
                    try:
                        await update_profile(session, silo, name=cand)
                        profile["name"] = cand
                        log.info(
                            "onboarding.prefill_name", silo=silo, source="group_member"
                        )
                    except Exception:
                        log.exception("message.prefill_name_failed", silo=silo)

        user_context = build_user_context(
            silo=silo,
            profile=profile,
            sender_phone=sender_phone,
            sender_name=sender_display,
            is_group=is_group,
            group_name=body.group_name,
            ambient_watch=ambient_watch,
            group_intro=group_intro,
        )
        system_prompt = SYSTEM_PROMPT + user_context

        # Muted but explicitly addressed: answer, then get back out of the way.
        if group_muted_until is not None:
            until_local = group_muted_until.astimezone(user_tz)
            system_prompt += (
                "\n\n## QUIET MODE (muted in this group until "
                f"{until_local:%a %b %-d %-I:%M %p})\n"
                "Members asked you to step back from this thread, so you're only "
                "seeing this message because you were addressed directly. Answer "
                "exactly what was asked, briefly, then go quiet again — no "
                "follow-up questions, no unsolicited suggestions, nothing about "
                "the thing you were asked to stay out of. If a member explicitly "
                "asks you to rejoin the conversation, call "
                "group_quiet(action=unmute) first."
            )

        # Self-authored playbook (growth loop) — operating notes HAL learned
        # from its own past failures. Additive guidance; lint-checked at write.
        # Scoped: rules learned from 1:1 failures don't leak into group turns
        # (and vice versa) — an "always acknowledge reports" lesson from baby
        # logging must not become a group-chat interjection.
        try:
            from hal_orchestrator.services.playbook import get_block

            system_prompt += await get_block(session, "group" if is_group else "dm")
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
                            f"- [{o.created_at.astimezone(user_tz):%b %-d}"
                            f"{', ' + o.group_name if o.group_name else ''}] {o.content}"
                            for o in obs
                        )
                    )
            except Exception:
                log.exception("message.group_obs_failed", silo=silo)

        # Group-context catalog — a compact index of the group chats THIS user
        # is actually a member of (proven by having spoken there), with what's
        # recently happening in each, so this DM can recognize plans made
        # elsewhere instead of drawing a blank. 1:1 only, same one-way valve as
        # group observations above. Best-effort like its siblings.
        if not is_group:
            try:
                from hal_orchestrator.services.group_catalog import build_catalog

                catalog = await build_catalog(session, silo)
                if catalog:
                    system_prompt += "\n\n" + catalog
            except Exception:
                log.exception("message.group_catalog_failed", silo=silo)

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

        # Auto archive recall: a message that references past discussion pulls
        # matching older turns from the durable archive into context — the model
        # rarely thinks to call recall_history on its own, so anything beyond
        # the rolling window was effectively forgotten. Best-effort.
        if not body.internal and _PAST_REF_RX.search(user_text):
            try:
                recalled = await _auto_recall_archive(session, silo, user_text)
            except Exception:
                log.exception("message.auto_recall_failed", silo=silo)
                recalled = []
            if recalled:
                system_prompt += (
                    "\n\n## Older messages that may be what they're referring to "
                    "(auto-recalled from this chat's archive — verify with "
                    "recall_history if you need more)\n"
                    + "\n".join(
                        f"- [{(r.get('at') or '')[:10]}] {r['role']}: {r['content'][:300]}"
                        for r in recalled
                    )
                )
                log.info("message.archive_recalled", silo=silo, n=len(recalled))

        # Rolling long-horizon summary (maintained by the summarizer daemon) —
        # preserves context beyond the recent-turn window without re-feeding it.
        # Best-effort like its context-assembly siblings: a summary read error
        # must degrade the context, not fail the whole reply.
        try:
            convo_summary = await get_summary(session, silo)
        except Exception:
            log.exception("message.summary_failed", silo=silo)
            convo_summary = None
        if convo_summary:
            system_prompt += (
                "\n\n## Conversation summary so far (older context beyond the recent "
                "messages below)\n" + convo_summary
            )

        # Read without a long-lived row lock. The final write uses this version
        # and merges safely if another replica completed a turn first.
        conversation_snapshot = await load_conversation_snapshot(session, silo)
        history = conversation_snapshot.history
        conversation_version = conversation_snapshot.version

        # Onboarding stall nudge (1:1 only): if the user has sent a few messages
        # and we still don't have their name, escalate — get the name in one line
        # before diving in. Capped so a privacy-conscious user is never trapped in
        # an endless greeting loop (after ~6 turns we stop nudging and just help).
        if not is_group and not profile.get("onboarded") and not profile.get("name"):
            prior_user_turns = sum(1 for t in history if t.get("role") == "user")
            if 2 <= prior_user_turns < 6:
                system_prompt += (
                    "\n\n## Onboarding nudge\nYou still don't have this user's name "
                    "after a few messages. Before diving into their request, warmly "
                    "get their name in one line, then help."
                )

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
                return await finish(MessageResponse(reply=""))

        # Append user message (multimodal if images present). Prefix the text with
        # the local send time so the model can anchor each message in real time and
        # see elapsed gaps (e.g. last msg 6pm yesterday -> this one 9am today),
        # instead of inferring AM/PM from wording. user_text stays raw above for
        # retrieval/logging; only the stored/sent turn is stamped.
        # Hand the model an EXPLICIT elapsed-gap cue: it's unreliable at
        # subtracting two bracket timestamps but great at using "~19h ago". Real
        # wall-clock from the archive, only when the gap is notable (>=2.5h), and
        # only for real user turns. This is what makes HAL re-orient after an
        # overnight/multi-day pause instead of replying as if nothing elapsed.
        gap_note = ""
        if not body.internal:
            from hal_orchestrator.services.history_search import (
                minutes_since_last_message,
            )
            gap_min = await minutes_since_last_message(session, silo)
            if gap_min is not None and gap_min >= 150:
                hrs = gap_min / 60
                gap_note = (
                    f" · ~{round(hrs)}h since the last message"
                    if hrs < 36
                    else f" · ~{round(hrs / 24)}d since the last message"
                )
        stamp = datetime.now(user_tz).strftime("%a %b %-d %-I:%M %p")
        user_parts: list[dict] = [{"text": f"[{stamp}{gap_note}] {user_text}"}]
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
            current_location=(
                body.current_location.model_dump(mode="python")
                if body.current_location
                else None
            ),
            user_text=user_text,
            message_id=body.message_id,
            internal=body.internal,
        )

        # Release context-assembly reads and quota/profile writes before the
        # potentially long provider/tool loop.
        await session.commit()

        # --- Tool-use loop ---
        total_tool_calls = 0
        trajectory_steps: list[dict] = []  # for auto-skill learning
        gemini_failed = False
        tool_counts: dict[str, int] = {}  # per-tool repeat guard (runaway detection)
        stalled = False  # ran out of iterations OR a tool looped — synthesize
        tool_budget_exhausted = False
        turn_deadline = time.monotonic() + settings.turn_timeout_seconds

        for iteration in range(settings.max_tool_iterations):
            remaining = turn_deadline - time.monotonic()
            if remaining <= 0:
                log.warning("message.turn_timeout", silo=silo)
                stalled = True
                break
            try:
                response = await asyncio.wait_for(
                    call_gemini(
                        client=http_client,
                        settings=settings,
                        history=history,
                        tools=model_tools(),
                        system=system_prompt,
                        model=body.model,
                        thinking_level=body.thinking_level,
                    ),
                    timeout=remaining,
                )
            except TimeoutError:
                log.warning("message.turn_timeout", silo=silo)
                stalled = True
                break

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

                # Execute the tool calls. Network-only tools (PARALLEL_SAFE_TOOLS)
                # in a multi-call batch run concurrently; session-touching tools
                # run sequentially. Response order always matches call order.
                func_responses: list[dict | None] = [None] * len(func_calls)
                parallel_batch: list[tuple[int, str, dict]] = []
                for idx, fc in enumerate(func_calls):
                    call = fc["functionCall"]
                    tool_name = call["name"]
                    tool_args = call.get("args", {})
                    if total_tool_calls >= settings.max_tool_calls_per_turn:
                        tool_budget_exhausted = True
                        func_responses[idx] = {
                            "functionResponse": {
                                "name": tool_name,
                                "response": {
                                    "content": "Tool budget reached; synthesize the answer now."
                                },
                            }
                        }
                        continue
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

                    if len(func_calls) > 1 and tool_name in PARALLEL_SAFE_TOOLS:
                        parallel_batch.append((idx, tool_name, tool_args))
                        continue

                    result = await execute_tool(tool_name, tool_args, ctx)
                    # Stateful tools own short transactions. This avoids holding
                    # locks/connections during the model's next reasoning round.
                    from hal_orchestrator.tools.specs import get_tool_spec

                    spec = get_tool_spec(tool_name)
                    if spec is not None and not spec.parallel_safe:
                        await session.commit()
                    func_responses[idx] = {
                        "functionResponse": {
                            "name": tool_name,
                            "response": {"content": result},
                        }
                    }

                if parallel_batch:
                    results = await asyncio.gather(
                        *(execute_tool(n, a, ctx) for _, n, a in parallel_batch),
                        return_exceptions=True,
                    )
                    for (idx, tool_name, _), result in zip(parallel_batch, results):
                        if isinstance(result, BaseException):
                            result = f"Tool error ({tool_name}): {result}"
                        func_responses[idx] = {
                            "functionResponse": {
                                "name": tool_name,
                                "response": {"content": str(result)},
                            }
                        }

                # Add tool responses to history
                history.append({"role": "user", "parts": [r for r in func_responses if r]})

                if tool_budget_exhausted:
                    log.warning(
                        "message.tool_budget", silo=silo, limit=settings.max_tool_calls_per_turn
                    )
                    stalled = True
                    break

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

            # Truncation guard: on a HIGH-thinking model the reasoning is
            # deducted from the shared output budget, so a heavy think can cut
            # the visible answer off after a few words (finishReason
            # MAX_TOKENS). The 07-06 baby digest shipped as JUST its header
            # this way. A truncated fragment must never ship — route it through
            # the repair path (finalize re-synthesizes with thinking LOW so the
            # full answer fits; internal turns stay silent).
            truncated = (
                candidates[0].get("finishReason") == "MAX_TOKENS" if candidates else False
            )

            if not reply or truncated:
                # Degenerate turn: no text (thinking-only) OR truncated
                # mid-output. Either way NOT a deliberate silence (that's an
                # explicit "..." text); shipping it meant dead air or a
                # header-only digest. Route through the stalled path: internal
                # turns stay silent, real turns get re-synthesized.
                log.warning(
                    "message.empty_or_truncated_turn",
                    silo=silo,
                    iteration=iteration,
                    truncated=truncated,
                    reply_len=len(reply),
                )
                stalled = True
                break

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
                return await finish(
                    MessageResponse(reply="", tool_calls=total_tool_calls)
                )
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
            return await finish(MessageResponse(reply="", tool_calls=total_tool_calls))

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
                "message.reply",
                silo=silo,
                reply=reply[:80] if settings.log_message_content else None,
                gemini_failed=True,
            )
            return await finish(
                MessageResponse(
                    reply=reply,
                    tool_calls=total_tool_calls,
                    side_messages=[
                        SideMessage(id=m.get("id"), to=m["to"], text=m["text"])
                        for m in ctx.side_messages
                    ],
                )
            )

        # Normalize markdown out of the final reply — iMessage renders **bold**,
        # ## headers, and `code` literally as ugly symbols. The prompt asks for
        # no markdown, but some models (Claude especially) still emit it; strip
        # deterministically so it's never user-visible. Keep history consistent.
        if reply and not gemini_failed:
            stripped = _strip_markdown(reply)
            if stripped != reply:
                reply = stripped
                if history and history[-1].get("role") == "model":
                    history[-1] = {"role": "model", "parts": [{"text": reply}]}

        # Claimed-action enforcement: if the reply claims an action (set a
        # reminder, logged the feed, created a watch, texted someone) that has
        # NO matching tool call this turn, run one corrective mini-loop that
        # actually performs it — or rewrites the reply to stop claiming it.
        # The #1 recurring trust failure in the nightly grades; a playbook rule
        # alone didn't fix it.
        if (
            reply
            and not gemini_failed
            and not stalled
            and not body.internal
            and not _is_quiet_sentinel(reply)
        ):
            try:
                tools_used = {s["tool"] for s in trajectory_steps}
                unbacked = _unbacked_action_claims(reply, tools_used)
                if unbacked:
                    log.warning(
                        "message.unbacked_claims", silo=silo, claims=unbacked
                    )
                    corrected, extra_calls = await _enforce_claimed_actions(
                        http_client, settings, history, system_prompt, ctx,
                        silo, body.model, body.thinking_level, unbacked,
                        trajectory_steps, tools_used=tools_used,
                    )
                    total_tool_calls += extra_calls
                    if corrected:
                        reply = _strip_markdown(corrected)
                        try:
                            from hal_orchestrator.services.friction import (
                                log_friction,
                            )

                            log_friction(
                                session, silo, "unbacked_claim",
                                ", ".join(unbacked)[:200],
                            )
                        except Exception:
                            pass
            except Exception:
                log.exception("message.claim_check_failed", silo=silo)

        # Group tact gate: an UNPROMPTED interjection into an ambient-watched
        # group gets a fresh skeptical model pass — "would a tactful human
        # assistant send this?" — before it reaches the group. Dropped
        # interjections become the deliberate-silence sentinel so history
        # reads as HAL choosing quiet (not as an unanswered question it asked).
        if _needs_group_tact_gate(
            is_group, ambient_watch, body.internal, user_text, reply,
            {s["tool"] for s in trajectory_steps},
        ) and not gemini_failed:
            try:
                verdict = await _run_tact_gate(
                    http_client, settings, history, sender_display or "",
                    user_text, reply, silo, summary=convo_summary or "",
                )
            except Exception:
                log.exception("message.tact_gate_failed", silo=silo)
                verdict = None
            if verdict is not None:
                if verdict.drop:
                    log.info(
                        "message.group_interjection_dropped",
                        silo=silo, draft=reply[:80],
                    )
                    reply = "..."
                elif verdict.text:
                    reply = _strip_markdown(verdict.text)
                if history and history[-1].get("role") == "model":
                    history[-1] = {"role": "model", "parts": [{"text": reply}]}

        # Layer 2 hardening: self-critique on plan/recommendation turns, run
        # SYNCHRONOUSLY — before the reply is sent. One extra model call re-reads
        # the request + gathered facts + proposed reply from a fresh skeptical
        # frame and, if it finds a SUBSTANTIVE flaw (wrong required-state, a
        # non-binding constraint, a hidden tension), revises the reply IN PLACE
        # so the user gets a single corrected message — no follow-up. Costs the
        # user some extra wait on plan turns; that's the deliberate tradeoff.
        if (
            settings.critic_enabled
            and not gemini_failed
            and not stalled
            and not body.internal
            and reply
            and not _is_quiet_sentinel(reply)
        ):
            try:
                from hal_orchestrator.services.critic import (
                    critique_and_revise,
                    should_critique,
                )

                if should_critique(user_text, reply, total_tool_calls, is_group):
                    new_reply, crit = await critique_and_revise(
                        ctx, history, user_text, reply
                    )
                    if crit.get("issues"):
                        from hal_orchestrator.services.friction import (
                            KIND_CRITIC_CATCH,
                            log_friction,
                        )

                        log_friction(
                            session, silo, KIND_CRITIC_CATCH,
                            "; ".join(crit["issues"])[:400],
                        )
                    if crit.get("caught"):
                        reply = _strip_markdown(new_reply)
                        if history and history[-1].get("role") == "model":
                            history[-1] = {"role": "model", "parts": [{"text": reply}]}
                        log.info("message.critic_revised", silo=silo)
            except Exception:
                log.exception("message.critic_failed", silo=silo)

        # Sanitize history before persisting: replace inlineData (base64 images)
        # with a placeholder, and drop raw Claude blocks (`_claude_block`) — they
        # bloat the DB and carry thinking signatures that must not be replayed in
        # a later request's context. A pure-thinking part becomes empty and is
        # dropped; a functionCall part keeps its functionCall (re-loaded text-only).
        clean_history = _sanitize_persisted_history(
            history,
            live_location_label=(
                body.current_location.label if body.current_location else None
            ),
        )

        # Collapse the "stay quiet" sentinel to an empty reply so the bridge
        # sends nothing — HAL opting out of an off-topic message in a watched
        # group should be silent, not a literal "..." bubble. History keeps the
        # real turn so HAL knows it stayed quiet.
        outbound_reply = "" if _is_quiet_sentinel(reply) else reply

        # Heartbeat/internal turns: a chatty background model that LEADS with the
        # "..." sentinel and then explains itself is still saying "nothing to
        # flag" — suppress so it doesn't spam the user with non-alerts. Scoped to
        # internal turns so watched-group "..." handling is unchanged.
        if body.internal and outbound_reply and _contains_quiet_sentinel(reply):
            log.info("message.heartbeat_sentinel_suppressed", silo=silo, reply=reply[:80])
            outbound_reply = ""

        # Anti-repeat: a heartbeat that re-alerts about something HAL already
        # flagged ~HEARTBEAT_REPEAT_CAP times recently is muzzled (the 24x "leave
        # by 3:30" / 7x pool-deadline spam). Scoped to internal turns so user
        # replies are never gated; a couple of escalating nudges still get through.
        if body.internal and outbound_reply and _is_repeat_alert(
            reply, clean_history[:pre_turn_len]
        ):
            log.info("message.heartbeat_repeat_suppressed", silo=silo, reply=reply[:80])
            outbound_reply = ""

        # Re-hash guard: a heartbeat that LEADS by re-referencing what it already
        # flagged, or by declaring "nothing new / all quiet", is a non-alert —
        # the chatty background model narrating the same unread inbox again.
        if body.internal and outbound_reply and _is_rehash_heartbeat(reply):
            log.info("message.heartbeat_rehash_suppressed", silo=silo, reply=reply[:80])
            outbound_reply = ""

        if body.internal:
            # Heartbeat turn. Silent → persist nothing (96 silent checks/day
            # would drown the real conversation and the nightly grader).
            # Alert → persist a compact stub + the alert so HAL remembers what
            # it proactively said (that's also its dedup against re-alerting).
            if outbound_reply:
                internal_entries = [
                    {
                        "role": "user",
                        "parts": [
                            {
                                "text": (
                                    f"[{stamp}] [heartbeat check — you noticed "
                                    "something and texted the user:]"
                                )
                            }
                        ],
                    },
                    {"role": "model", "parts": [{"text": reply}]},
                ]
                await save_conversation(
                    session,
                    silo,
                    clean_history[:pre_turn_len] + internal_entries,
                    max_turns=settings.max_conversation_turns,
                    expected_version=conversation_version,
                    append_entries=internal_entries,
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
            return await finish(
                MessageResponse(
                    reply=outbound_reply,
                    tool_calls=total_tool_calls,
                    side_messages=[
                        SideMessage(id=m.get("id"), to=m["to"], text=m["text"])
                        for m in ctx.side_messages
                    ],
                )
            )

        # Save conversation
        await save_conversation(
            session,
            silo,
            clean_history,
            max_turns=settings.max_conversation_turns,
            expected_version=conversation_version,
            append_entries=clean_history[pre_turn_len:],
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

            # Onboarding funnel + auto-complete backstop (1:1 only). Re-read the
            # row because the model may have saved facts during this turn.
            # compute_onboarding_progress counts asks (code-enforced decay, one
            # per real turn), records answered/skipped/completed with timestamps,
            # and emits structlog funnel events. The backstop then flips
            # `onboarded` if the flow reached its terminal state and the model
            # forgot to. Both idempotent; best-effort (already inside the wrapped
            # post-hooks, so a failure here can never break the reply).
            if not is_group and not body.internal:
                fresh = await get_profile(session, silo)
                onb_updates, onb_events = compute_onboarding_progress(profile, fresh)
                for ev in onb_events:
                    log.info("onboarding.step", silo=silo, **ev)
                if onb_updates:
                    await update_profile(session, silo, **onb_updates)
                if is_onboarding_complete(fresh) and not fresh.get("onboarded"):
                    await update_profile(session, silo, onboarded=True)

            await archive_turn(session, silo, "user", user_text)
            if outbound_reply:
                await archive_turn(session, silo, "assistant", reply)
                # HAL just actively participated in a GROUP → watch it for 24h so
                # follow-ups that don't tag "Hal" (an answer to its own question,
                # a "ping Seth next time he's at work" instruction) still reach it.
                # Refreshes on each engagement; lapses back to tag-only when the
                # thread goes quiet. Never downgrades a permanently-watched group.
                if is_group and chat_id:
                    from hal_orchestrator.services.watched import add_watched

                    await add_watched(
                        session, chat_id,
                        note="auto: HAL active in this thread",
                        ttl_hours=24,
                    )
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

        log.info(
            "message.reply",
            silo=silo,
            reply=reply[:80] if settings.log_message_content else None,
            suppressed=not outbound_reply,
            tool_calls=total_tool_calls,
        )

        return await finish(
            MessageResponse(
                reply=outbound_reply,
                tool_calls=total_tool_calls,
                side_messages=[
                    SideMessage(id=m.get("id"), to=m["to"], text=m["text"])
                    for m in ctx.side_messages
                ],
                # A suppressed reply (quiet sentinel / tact-gate drop) must not
                # ship orphan attachments.
                result_images=[
                    ResultImage(
                        mime_type=img["mime_type"], data=img["data"], ext=img["ext"]
                    )
                    for img in ctx.result_images
                ]
                if outbound_reply
                else [],
            )
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
    async def drain_outbox(
        ack: bool = True,
        limit: int = 100,
        session: AsyncSession = Depends(get_session),
    ) -> dict:
        """Claim durable deliveries.

        ``ack=true`` preserves the legacy drain-on-read bridge. New bridges use
        ``ack=false`` and POST /api/outbox/ack after AppleScript succeeds.
        """
        import hal_orchestrator.state as state
        from hal_orchestrator.services.delivery import DurableOutbox, claim

        messages = await claim(session, limit=limit, auto_ack=ack)
        await session.commit()
        # Preserve startup/test queue compatibility.
        if isinstance(state.outbox, DurableOutbox):
            while not state.outbox.empty():
                messages.append(state.outbox.get_nowait())
        return {"messages": messages}

    @router.post(
        "/api/outbox/ack",
        dependencies=[Depends(verify_bridge_auth)],
    )
    async def ack_outbox(
        body: OutboxAckRequest,
        session: AsyncSession = Depends(get_session),
    ) -> dict:
        import uuid

        from hal_orchestrator.services.delivery import acknowledge

        try:
            message_ids = [uuid.UUID(value) for value in body.message_ids]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid outbox message id") from exc
        count = await acknowledge(session, message_ids, delivered=body.delivered)
        await session.commit()
        return {"acknowledged": count}

    return router
