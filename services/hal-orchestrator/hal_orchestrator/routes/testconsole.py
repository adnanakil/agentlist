"""GET /admin/test — HAL test console (token-protected, test-namespace only).

A parallel UI into the REAL message pipeline for exercising onboarding and
group flows repeatedly without touching iMessage: simulated people live on the
reserved +1-555-555-xxxx range, simulated group chats on ids starting
"chattest". Every send goes through POST /api/message with the bridge secret —
the same entry, auth, idempotency, silo locking, quota, prompts, and
post-hooks a real bridge message gets — but on channel="test", so
hal_silo_channels routes ALL outbound traffic for these silos (replies,
welcomes, heartbeats, digests) to this console's outbox drain instead of the
Mac or WhatsApp bridge.

Guard rails:
- Every endpoint validates the test namespace; the console can never message
  or reset a real user's silo.
- Group sends emulate the Mac bridge's forwarding gate (mention of "hal" or a
  watched thread) so group behavior matches production; force-forward covers
  the bridge's image/link forwarding cases.
- Reset is the REAL forget-me path (services/forget.forget_silo) plus the
  group-side rows forget doesn't own (member rows, watch, observations).

The page ships its own CSP (script-src 'unsafe-inline'); the global
SecurityHeadersMiddleware only fills in headers a response hasn't already set,
so the rest of the service keeps its no-JS policy.
"""

from __future__ import annotations

import hmac
import os
import re
import uuid

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ag_db.models import (
    HalFamilyMember,
    HalGroupMember,
    HalGroupObservation,
    HalOutboxMessage,
    HalSiloChannel,
    HalTurn,
    HalUserProfile,
    HalWatchedGroup,
)
from ag_db.session import get_session
from hal_orchestrator.services.identity import normalize_handle
from hal_orchestrator.state import get_http_client, get_settings

log = structlog.get_logger()

# Reserved fake namespace: +1-555-555-xxxx (fictional range, same convention as
# scripts/eval_hal_behavior.py) and "chattest…" group ids ("chat" prefix keeps
# identity.is_group_id() classifying them as groups).
TEST_PHONE_RX = re.compile(r"^\+1555555\d{4}$")
TEST_GROUP_PREFIX = "chattest"

# Mirror of the Mac bridge's group forwarding gate (and message.py's mention
# regex): a group message reaches HAL only when it mentions him or the thread
# is watched. Emulated here so group tests match production behavior.
_MENTION_RX = re.compile(r"\bhal\b", re.IGNORECASE)


def _as_silo(handle: str) -> str:
    h = (handle or "").strip()
    return h if h.startswith("chat") else normalize_handle(h)


def is_test_silo(silo: str) -> bool:
    return silo.startswith(TEST_GROUP_PREFIX) or bool(TEST_PHONE_RX.match(silo))


def _require_test(*handles: str | None) -> None:
    """400 unless every non-empty handle is inside the fake namespace. This is
    the guard that makes the console incapable of touching a real user."""
    for handle in handles:
        if not handle:
            continue
        if not is_test_silo(_as_silo(handle)):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"'{handle}' is outside the test namespace "
                    "(+1555555xxxx numbers or chattest* group ids)"
                ),
            )


def _verify_console_auth(
    authorization: str = Header(""), token: str = Query("")
) -> None:
    """Same dual header/query scheme as /admin; fails closed."""
    settings = get_settings()
    secret = settings.admin_token or settings.hal_bridge_secret
    bearer = ""
    if authorization.startswith("Bearer "):
        bearer = authorization[len("Bearer ") :].strip()
    supplied = bearer or token
    if not secret or not hmac.compare_digest(supplied or "", secret):
        raise HTTPException(status_code=403, detail="Bad token")


async def _pipeline_call(payload: dict) -> tuple[int, dict]:
    """Re-enter the real pipeline the way cron/heartbeat daemons do: a
    localhost POST authenticated with the bridge secret."""
    settings = get_settings()
    port = os.environ.get("PORT", "8005")
    url = f"http://127.0.0.1:{port}/api/message"
    resp = await get_http_client().post(
        url,
        json=payload,
        headers={"Authorization": f"Bearer {settings.hal_bridge_secret}"},
        timeout=300.0,
    )
    try:
        data = resp.json()
    except Exception:
        data = {"detail": (resp.text or "")[:400]}
    return resp.status_code, data


class TestSend(BaseModel):
    phone: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=12000)
    chat_id: str | None = Field(default=None, max_length=255)
    group_name: str | None = Field(default=None, max_length=200)
    sender_name: str | None = Field(default=None, max_length=200)
    force_forward: bool = False


class TestGroupEvent(BaseModel):
    chat_id: str = Field(min_length=1, max_length=255)
    event: str = Field(pattern=r"^(member_added|member_removed)$")
    actor: str = Field(min_length=1, max_length=64)
    target: str | None = Field(default=None, max_length=64)
    group_name: str | None = Field(default=None, max_length=200)


class TestReset(BaseModel):
    silo: str = Field(min_length=1, max_length=255)


def build_testconsole_router() -> APIRouter:
    router = APIRouter(dependencies=[Depends(_verify_console_auth)])

    @router.get("/admin/test", response_class=HTMLResponse)
    async def console_page() -> HTMLResponse:
        return HTMLResponse(
            CONSOLE_HTML,
            headers={
                "content-security-policy": (
                    "default-src 'none'; img-src 'self' data:; "
                    "style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                    "connect-src 'self'; form-action 'self'; base-uri 'none'; "
                    "frame-ancestors 'none'"
                )
            },
        )

    @router.post("/api/admin/test/send")
    async def send_message(
        body: TestSend, session: AsyncSession = Depends(get_session)
    ) -> dict:
        sender = normalize_handle(body.phone)
        _require_test(sender, body.chat_id)
        is_group = bool(body.chat_id)

        if is_group and not body.force_forward:
            from hal_orchestrator.services.watched import is_watched

            if not _MENTION_RX.search(body.text) and not await is_watched(
                session, body.chat_id
            ):
                return {
                    "forwarded": False,
                    "reason": (
                        "bridge gate: no 'hal' mention and thread not watched "
                        "(use force-forward to emulate an image/link message)"
                    ),
                }

        payload: dict = {
            "message_id": f"testconsole:{uuid.uuid4().hex}",
            "channel": "test",
            "phone": sender,
            "text": body.text,
        }
        if body.sender_name:
            payload["sender_name"] = body.sender_name
        if is_group:
            payload["is_group"] = True
            payload["chat_id"] = body.chat_id
            if body.group_name:
                payload["group_name"] = body.group_name

        status, data = await _pipeline_call(payload)
        if status == 409:
            return {
                "forwarded": True,
                "busy": True,
                "detail": data.get("detail") or "another turn is processing",
            }
        if status != 200:
            raise HTTPException(
                status_code=502, detail=f"pipeline {status}: {data.get('detail')}"
            )
        log.info("testconsole.sent", silo=body.chat_id or sender, group=is_group)
        return {"forwarded": True, "response": data}

    @router.post("/api/admin/test/group-event")
    async def group_event(body: TestGroupEvent) -> dict:
        actor = normalize_handle(body.actor)
        _require_test(body.chat_id, actor, body.target)
        payload: dict = {
            "message_id": f"testconsole:{uuid.uuid4().hex}",
            "channel": "test",
            "phone": actor,
            "text": "",
            "is_group": True,
            "chat_id": body.chat_id,
            "group_event": body.event,
        }
        if body.group_name:
            payload["group_name"] = body.group_name
        if body.target:
            payload["group_event_target"] = normalize_handle(body.target)
        status, data = await _pipeline_call(payload)
        if status != 200:
            raise HTTPException(
                status_code=502, detail=f"pipeline {status}: {data.get('detail')}"
            )
        log.info("testconsole.group_event", silo=body.chat_id, kind=body.event)
        return {"response": data}

    @router.get("/api/admin/test/state")
    async def silo_state(
        silo: str, session: AsyncSession = Depends(get_session)
    ) -> dict:
        s = _as_silo(silo)
        _require_test(s)
        is_group = s.startswith("chat")

        turns = (
            (
                await session.execute(
                    select(HalTurn)
                    .where(HalTurn.phone == s)
                    .order_by(HalTurn.created_at)
                    .limit(300)
                )
            )
            .scalars()
            .all()
        )
        outbox_rows = (
            (
                await session.execute(
                    select(HalOutboxMessage)
                    .where(
                        HalOutboxMessage.destination == s,
                        HalOutboxMessage.channel == "test",
                    )
                    .order_by(HalOutboxMessage.created_at)
                    .limit(300)
                )
            )
            .scalars()
            .all()
        )

        from hal_orchestrator.services.baby import get_family_for_silo
        from hal_orchestrator.services.profiles import get_profile

        prof = await get_profile(session, s)
        extra = prof.get("extra_data") or {}

        family = None
        fam = await get_family_for_silo(session, s)
        if fam is not None:
            member_count = (
                await session.execute(
                    select(func.count()).where(HalFamilyMember.family_id == fam.id)
                )
            ).scalar_one()
            family = {
                "baby_name": fam.baby_name,
                "timezone": fam.timezone,
                "members": int(member_count),
            }

        group = None
        if is_group:
            from hal_orchestrator.services.watched import is_watched, muted_until

            member_rows = (
                (
                    await session.execute(
                        select(HalGroupMember)
                        .where(HalGroupMember.group_silo == s)
                        .order_by(HalGroupMember.first_seen)
                    )
                )
                .scalars()
                .all()
            )
            muted = await muted_until(session, s)
            group = {
                "watched": await is_watched(session, s),
                "muted_until": muted.isoformat() if muted else None,
                "members": [
                    {
                        "silo": m.member_silo,
                        "last_spoke_at": m.last_spoke_at.isoformat(),
                    }
                    for m in member_rows
                ],
                "epochs": len(prof.get("member_epochs") or []),
            }

        return {
            "silo": s,
            "is_group": is_group,
            "profile": {
                "name": prof.get("name"),
                "onboarded": bool(prof.get("onboarded")),
                "track": prof.get("onboarding_track"),
                "acquisition_source": prof.get("acquisition_source"),
                "onboarded_at": prof.get("onboarded_at"),
                "asked": {
                    key: prof.get(f"asked_{key}", 0)
                    for key in (
                        "name",
                        "little_one",
                        "city",
                        "baby",
                        "timezone",
                        "home",
                        "work",
                    )
                },
                "forget_pending": extra.get("forget_pending"),
                "plan": extra.get("plan"),
                "usage": extra.get("usage"),
            },
            "family": family,
            "group": group,
            "turns": [
                {
                    "id": str(t.id),
                    "at": t.created_at.isoformat(),
                    "sender": t.sender_phone,
                    "text": t.user_text,
                    "reply": t.reply,
                    "status": t.status,
                }
                for t in turns
            ],
            "outbox": [
                {
                    "id": str(o.id),
                    "at": o.created_at.isoformat(),
                    "text": o.text,
                    "status": o.status,
                    "images": o.images or [],
                }
                for o in outbox_rows
            ],
        }

    @router.get("/api/admin/test/outbox")
    async def drain_outbox(session: AsyncSession = Depends(get_session)) -> dict:
        """Claim pending test-channel deliveries — the console IS the test
        bridge. Claimed rows flip to delivered and stay visible via /state."""
        from hal_orchestrator.services.delivery import claim

        messages = await claim(session, limit=50, auto_ack=True, channel="test")
        await session.commit()
        return {"messages": messages}

    @router.get("/api/admin/test/personas")
    async def personas(session: AsyncSession = Depends(get_session)) -> dict:
        test_like = or_(
            HalUserProfile.phone.like("+1555555%"),
            HalUserProfile.phone.like(f"{TEST_GROUP_PREFIX}%"),
        )
        profiles = (
            (await session.execute(select(HalUserProfile).where(test_like)))
            .scalars()
            .all()
        )
        people = [
            {"phone": p.phone, "name": p.name, "onboarded": p.onboarded}
            for p in profiles
            if not p.phone.startswith("chat")
        ]
        known_people = {p["phone"] for p in people}

        member_rows = (
            (
                await session.execute(
                    select(HalGroupMember).where(
                        HalGroupMember.group_silo.like(f"{TEST_GROUP_PREFIX}%")
                    )
                )
            )
            .scalars()
            .all()
        )
        groups: dict[str, dict] = {}
        for p in profiles:
            if p.phone.startswith("chat"):
                groups[p.phone] = {"chat_id": p.phone, "group_name": None, "members": []}
        for m in member_rows:
            g = groups.setdefault(
                m.group_silo,
                {"chat_id": m.group_silo, "group_name": None, "members": []},
            )
            g["group_name"] = g["group_name"] or m.group_name
            g["members"].append(m.member_silo)
            if m.member_silo not in known_people and TEST_PHONE_RX.match(m.member_silo):
                people.append(
                    {"phone": m.member_silo, "name": None, "onboarded": False}
                )
                known_people.add(m.member_silo)

        turn_phones = (
            await session.execute(
                select(HalTurn.phone)
                .where(HalTurn.phone.like("+1555555%"))
                .distinct()
            )
        ).scalars().all()
        for phone in turn_phones:
            if phone not in known_people:
                people.append({"phone": phone, "name": None, "onboarded": False})
                known_people.add(phone)

        return {"people": people, "groups": list(groups.values())}

    @router.post("/api/admin/test/reset")
    async def reset_silo(
        body: TestReset, session: AsyncSession = Depends(get_session)
    ) -> dict:
        s = _as_silo(body.silo)
        _require_test(s)

        from hal_orchestrator.services.forget import forget_silo

        counts = await forget_silo(session, s)
        if s.startswith("chat"):
            # Group-side rows forget_silo doesn't own: who spoke here, the
            # watch/mute shell, and observations sourced from this thread.
            for label, model, col in (
                ("group_member_rows", HalGroupMember, HalGroupMember.group_silo),
                ("watched", HalWatchedGroup, HalWatchedGroup.chat_id),
                (
                    "group_observations",
                    HalGroupObservation,
                    HalGroupObservation.group_silo,
                ),
            ):
                result = await session.execute(sa_delete(model).where(col == s))
                if result.rowcount:
                    counts[label] = counts.get(label, 0) + result.rowcount
        await session.execute(
            sa_delete(HalSiloChannel).where(HalSiloChannel.silo == s)
        )
        await session.commit()
        log.info("testconsole.reset", silo=s, tables=len(counts))
        return {"silo": s, "deleted": counts}

    return router


# --------------------------------------------------------------------------- #
# The console page. Raw string: JS regexes keep their backslashes.
# --------------------------------------------------------------------------- #

CONSOLE_HTML = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>HAL — Test Console</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  * { box-sizing: border-box; }
  body { background:#101014; color:#e8e8ea; font:15px -apple-system,system-ui,sans-serif;
         margin:0; height:100vh; overflow:hidden; }
  #app { display:flex; height:100vh; }
  #side { width:270px; min-width:270px; border-right:1px solid #2a2a32; padding:14px;
          overflow-y:auto; background:#131318; }
  .sideHead { font-size:17px; font-weight:650; margin-bottom:14px; }
  .secHead { color:#8b8b93; font-size:12px; text-transform:uppercase; letter-spacing:.4px;
             margin:14px 0 6px; display:flex; justify-content:space-between; align-items:center; }
  .secHead button { background:#26262e; color:#e8e8ea; border:1px solid #34343e;
                    border-radius:6px; width:22px; height:22px; cursor:pointer; }
  .item { padding:8px 10px; border-radius:8px; cursor:pointer; margin-bottom:2px;
          display:flex; justify-content:space-between; align-items:center; gap:6px; }
  .item:hover { background:#1a1a20; }
  .item.sel { background:#20202a; }
  .item .lbl { font-weight:550; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .item .sub { display:block; color:#6b6b73; font-size:11px; font-weight:400; }
  .dot { width:8px; height:8px; min-width:8px; border-radius:4px; background:#e0b430; }
  .ok { color:#5fbf77; font-size:11px; }
  .note { color:#6b6b73; font-size:11px; margin-top:18px; line-height:1.5; }
  #main { flex:1; display:flex; flex-direction:column; min-width:0; }
  #chatHead { padding:12px 18px; border-bottom:1px solid #2a2a32; display:flex;
              align-items:center; gap:10px; flex-wrap:wrap; }
  #chatTitle { font-weight:650; font-size:16px; }
  #chatSilo { color:#6b6b73; font-size:11px; }
  #headBtns { margin-left:auto; display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
  select, button.act { background:#1e1e26; color:#e8e8ea; border:1px solid #34343e;
           border-radius:7px; padding:5px 9px; font-size:13px; cursor:pointer; }
  button.danger { border-color:#5d2a2a; color:#e08d8d; }
  #chips { padding:8px 18px 0; display:flex; gap:6px; flex-wrap:wrap; min-height:20px; }
  .chip { background:#1a1a20; border:1px solid #2a2a32; border-radius:20px; padding:3px 10px;
          font-size:11.5px; color:#a8a8b0; }
  .chip b { color:#e8e8ea; font-weight:600; }
  .chip.good { border-color:#2c4a35; color:#5fbf77; }
  .chip.warn { border-color:#5a4a20; color:#e0b430; }
  #log { flex:1; overflow-y:auto; padding:14px 18px; display:flex; flex-direction:column; gap:8px; }
  .msg { max-width:68%; padding:9px 13px; border-radius:14px; white-space:pre-wrap;
         word-wrap:break-word; line-height:1.4; }
  .msg .who { font-size:11px; color:#8b8b93; margin-bottom:3px; font-weight:600; }
  .msg .tag { font-size:10px; color:#e0b430; margin-top:4px; }
  .msg img { max-width:100%; border-radius:8px; margin-top:6px; }
  .them { align-self:flex-start; background:#26262e; border-bottom-left-radius:4px; }
  .me   { align-self:flex-end; background:#0a5bd3; border-bottom-right-radius:4px; }
  .me .who { color:#bcd4f7; }
  .dropped { align-self:flex-end; background:#1a1a20; color:#6b6b73; border:1px dashed #34343e; }
  .sys { align-self:center; color:#8b8b93; font-size:12px; text-align:center;
         padding:2px 0; max-width:85%; }
  .err { border:1px solid #5d2a2a; }
  #composer { padding:12px 18px; border-top:1px solid #2a2a32; display:flex; gap:8px;
              align-items:center; flex-wrap:wrap; }
  #msg { flex:1; min-width:200px; background:#1a1a20; border:1px solid #34343e; color:#e8e8ea;
         border-radius:10px; padding:10px 14px; font-size:14px; outline:none; }
  #msg:focus { border-color:#4a4a58; }
  #ffWrap { color:#8b8b93; font-size:12px; display:none; align-items:center; gap:4px;
            white-space:nowrap; }
  #send { background:#0a5bd3; color:#fff; border:none; border-radius:10px;
          padding:10px 18px; font-size:14px; font-weight:600; cursor:pointer; }
  #send:disabled { opacity:.4; cursor:default; }
  #empty { color:#6b6b73; text-align:center; margin-top:20vh; }
</style></head>
<body>
<div id="app">
  <div id="side">
    <div class="sideHead">HAL test console</div>
    <div class="secHead">People <button id="addPerson" title="New test person">+</button></div>
    <div id="people"></div>
    <div class="secHead">Group chats <button id="addGroup" title="New test group">+</button></div>
    <div id="groups"></div>
    <div class="note">Everything here runs through the real pipeline on fake
    +1&#8209;555&#8209;555 numbers and a "test" outbox channel — nothing reaches iMessage
    or WhatsApp.<br><br>⚠️ Don't ask HAL to text a real number from here: tool
    side&#8209;effects (reminders to others) deliver for real.</div>
  </div>
  <div id="main">
    <div id="chatHead">
      <span id="chatTitle">Pick a person or group</span>
      <span id="chatSilo"></span>
      <span id="headBtns"></span>
    </div>
    <div id="chips"></div>
    <div id="log"><div id="empty">← Create a test person, then open their DM.<br>
      Onboarding starts from their first message.</div></div>
    <div id="composer">
      <span id="asWrap"></span>
      <input id="msg" placeholder="Message…" autocomplete="off">
      <label id="ffWrap"><input type="checkbox" id="ff"> force&#8209;forward</label>
      <button id="send">Send</button>
    </div>
  </div>
</div>
<script>
'use strict';
const TOKEN = new URLSearchParams(location.search).get('token') || '';

async function api(path, method, body) {
  const r = await fetch(path, {
    method: method || 'GET',
    headers: {'Authorization': 'Bearer ' + TOKEN, 'Content-Type': 'application/json'},
    body: body ? JSON.stringify(body) : null,
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || ('HTTP ' + r.status));
  return d;
}

function load(key, dflt) {
  try { const v = JSON.parse(localStorage.getItem(key)); return v == null ? dflt : v; }
  catch (e) { return dflt; }
}
function save(key, val) { localStorage.setItem(key, JSON.stringify(val)); }

let people = load('htc.people', []);   // [{phone,label}]
let groups = load('htc.groups', []);   // [{id,name,members:[phone]}]
let extras = load('htc.extras', {});   // {silo:[{at,seq,kind,who,text,img}]}
let cur = null;                        // {silo,isGroup}
let lastState = null;
let sending = false;
let seq = 0;
const badges = {};

const $ = id => document.getElementById(id);
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}
function labelOf(phone) {
  if (!phone) return '?';
  const p = people.find(x => x.phone === phone);
  return (p && p.label) || phone.slice(-4);
}
function groupOf(id) { return groups.find(g => g.id === id); }
function addExtra(silo, item) {
  item.at = new Date().toISOString();
  item.seq = ++seq;
  (extras[silo] = extras[silo] || []).push(item);
  save('htc.extras', extras);
}
function nextNumber() {
  for (let i = 100; i < 1000; i++) {
    const n = '+1555555' + String(i).padStart(4, '0');
    if (!people.find(p => p.phone === n)) return n;
  }
  return null;
}

/* ---------- sidebar ---------- */
function renderSidebar() {
  const pl = $('people'); pl.replaceChildren();
  people.forEach(p => {
    const it = el('div', 'item' + (cur && !cur.isGroup && cur.silo === p.phone ? ' sel' : ''));
    const left = el('span');
    const lbl = el('span', 'lbl', p.label || p.phone);
    if (p.onboarded) lbl.append(' ', Object.assign(el('span', 'ok', '✓'), {title: 'onboarded'}));
    left.append(lbl, el('span', 'sub', p.phone));
    it.append(left);
    if (badges[p.phone]) it.append(el('span', 'dot'));
    it.onclick = () => openChat(p.phone, false);
    pl.append(it);
  });
  const gl = $('groups'); gl.replaceChildren();
  groups.forEach(g => {
    const it = el('div', 'item' + (cur && cur.isGroup && cur.silo === g.id ? ' sel' : ''));
    const left = el('span');
    left.append(el('span', 'lbl', '👥 ' + g.name),
                el('span', 'sub', g.members.map(labelOf).join(', ') || 'no members yet'));
    it.append(left);
    if (badges[g.id]) it.append(el('span', 'dot'));
    it.onclick = () => openChat(g.id, true);
    gl.append(it);
  });
}

$('addPerson').onclick = () => {
  const label = prompt('Name for this test person (e.g. "Maya (mom)")');
  if (!label) return;
  const phone = nextNumber();
  if (!phone) return alert('Test number range exhausted');
  people.push({phone, label, onboarded: false});
  save('htc.people', people);
  renderSidebar();
  openChat(phone, false);
};

$('addGroup').onclick = () => {
  const name = prompt('Group chat name (e.g. "Baby Akil 👶")');
  if (!name) return;
  const id = 'chattest' + Math.random().toString(16).slice(2, 12);
  groups.push({id, name, members: []});
  save('htc.groups', groups);
  renderSidebar();
  openChat(id, true);
};

/* ---------- chat header / chips ---------- */
function renderHead() {
  const g = cur.isGroup ? groupOf(cur.silo) : null;
  $('chatTitle').textContent = cur.isGroup ? '👥 ' + (g ? g.name : cur.silo)
                                           : labelOf(cur.silo);
  $('chatSilo').textContent = cur.silo;
  const btns = $('headBtns'); btns.replaceChildren();

  if (cur.isGroup && g) {
    const addSel = el('select');
    addSel.append(el('option', null, '+ add member…'));
    people.filter(p => !g.members.includes(p.phone))
          .forEach(p => addSel.append(
            Object.assign(el('option', null, p.label), {value: p.phone})));
    addSel.onchange = () => {
      if (addSel.value) addMember(g, addSel.value);
      addSel.selectedIndex = 0;
    };
    btns.append(addSel);

    const remSel = el('select');
    remSel.append(el('option', null, '– remove member…'));
    g.members.forEach(ph => remSel.append(
      Object.assign(el('option', null, labelOf(ph)), {value: ph})));
    remSel.onchange = () => {
      if (remSel.value) removeMember(g, remSel.value);
      remSel.selectedIndex = 0;
    };
    btns.append(remSel);
  }

  const reset = el('button', 'act danger', cur.isGroup ? 'Reset group' : 'Forget person');
  reset.onclick = doReset;
  btns.append(reset);

  const asWrap = $('asWrap'); asWrap.replaceChildren();
  if (cur.isGroup && g) {
    const sel = el('select'); sel.id = 'actAs'; sel.title = 'Send as';
    g.members.forEach(ph => sel.append(
      Object.assign(el('option', null, labelOf(ph)), {value: ph})));
    asWrap.append(sel);
    $('ffWrap').style.display = 'flex';
  } else {
    $('ffWrap').style.display = 'none';
  }
}

function renderChips(st) {
  const chips = $('chips'); chips.replaceChildren();
  if (!st) return;
  const add = (html, cls) => {
    const c = el('span', 'chip' + (cls ? ' ' + cls : ''));
    c.innerHTML = html;
    chips.append(c);
  };
  const escMap = {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'};
  const esc = s => String(s).replace(/[&<>"]/g, ch => escMap[ch]);
  const p = st.profile || {};
  if (!st.is_group) {
    add(p.onboarded ? 'onboarded <b>✓</b>' : 'onboarding <b>in progress</b>',
        p.onboarded ? 'good' : 'warn');
    if (p.track) add('track <b>' + esc(p.track) + '</b>');
    if (p.name) add('name <b>' + esc(p.name) + '</b>');
    if (p.acquisition_source) add('via <b>' + esc(p.acquisition_source) + '</b>');
    const asked = Object.entries(p.asked || {}).filter(x => x[1] > 0)
      .map(x => x[0] + '×' + x[1]).join(' ');
    if (asked) add('asked <b>' + esc(asked) + '</b>');
    if (p.forget_pending) add('forget armed ⚠', 'warn');
    if (p.plan && p.plan.unlimited) add('plan <b>unlimited</b>', 'good');
  } else {
    const gr = st.group || {};
    add(gr.watched ? 'watched <b>✓</b>' : '<b>not watched</b> — only "hal" mentions get through',
        gr.watched ? 'good' : 'warn');
    if (gr.muted_until) add('muted until <b>' + esc(gr.muted_until.slice(0, 16)) + '</b>', 'warn');
    if (gr.epochs) add('membership epochs <b>' + gr.epochs + '</b>');
    add('spoke here <b>' + (gr.members || []).length + '</b>');
  }
  if (st.family) add('👶 <b>' + esc(st.family.baby_name) + '</b> · ' + esc(st.family.timezone)
                     + ' · ' + st.family.members + ' member silos', 'good');
}

/* ---------- transcript ---------- */
function renderLog(st) {
  const logEl = $('log'); logEl.replaceChildren();
  const items = [];
  let n = 0;
  (st ? st.turns : []).forEach(t => {
    const ts = Date.parse(t.at);
    const who = st.is_group ? labelOf(t.sender) : labelOf(st.silo);
    if (t.text) items.push({t: ts, n: n++, side: 'me', who, text: t.text});
    if (t.reply) items.push({t: ts, n: n++, side: 'them', who: 'HAL', text: t.reply,
                             tag: t.status !== 'ok' ? t.status : null});
    else items.push({t: ts, n: n++, sys: true, text: '— HAL stayed silent —'});
  });
  (st ? st.outbox : []).forEach(o => {
    items.push({t: Date.parse(o.at), n: n++, side: 'them', who: 'HAL', text: o.text,
                tag: 'proactive · ' + o.status, images: o.images});
  });
  ((cur && extras[cur.silo]) || []).forEach(e => {
    const base = {t: Date.parse(e.at), n: 100000 + (e.seq || 0)};
    if (e.kind === 'dropped') items.push({...base, side: 'me', cls: 'dropped', who: e.who,
      text: e.text, tag: 'not forwarded — no "hal" mention, thread not watched'});
    else if (e.kind === 'welcome') items.push(
      {...base, side: 'them', who: 'HAL', text: e.text, tag: 'welcome'});
    else if (e.kind === 'image') items.push(
      {...base, side: 'them', who: 'HAL', text: '', img: e.img});
    else items.push({...base, sys: true, text: e.text});
  });
  items.sort((a, b) => a.t - b.t || a.n - b.n);

  items.forEach(m => {
    if (m.sys) { logEl.append(el('div', 'sys', m.text)); return; }
    const d = el('div', 'msg ' + (m.side === 'me' ? 'me' : 'them') + (m.cls ? ' ' + m.cls : '')
                 + (m.tag && /error|failed/.test(m.tag) ? ' err' : ''));
    d.append(el('div', 'who', m.who));
    if (m.text) d.append(document.createTextNode(m.text));
    (m.images || []).forEach(im => {
      const img = el('img');
      img.src = 'data:' + im.mime_type + ';base64,' + im.data;
      d.append(img);
    });
    if (m.img) { const img = el('img'); img.src = m.img; d.append(img); }
    if (m.tag) d.append(el('div', 'tag', m.tag));
    logEl.append(d);
  });
  logEl.scrollTop = logEl.scrollHeight;
}

/* ---------- actions ---------- */
async function openChat(silo, isGroup) {
  cur = {silo, isGroup};
  delete badges[silo];
  renderSidebar();
  renderHead();
  await refreshState();
}

async function refreshState() {
  if (!cur) return;
  try {
    lastState = await api('/api/admin/test/state?silo=' + encodeURIComponent(cur.silo));
    if (!cur.isGroup) {
      const p = people.find(x => x.phone === cur.silo);
      if (p) {
        p.onboarded = lastState.profile.onboarded;
        if (!p.label && lastState.profile.name) p.label = lastState.profile.name;
        save('htc.people', people);
      }
    }
    renderChips(lastState);
    renderLog(lastState);
    renderSidebar();
  } catch (e) { console.error(e); }
}

async function sendMsg() {
  if (!cur || sending) return;
  const text = $('msg').value.trim();
  if (!text) return;
  sending = true; $('send').disabled = true;
  try {
    const g = cur.isGroup ? groupOf(cur.silo) : null;
    const actAs = cur.isGroup ? ($('actAs') && $('actAs').value) : cur.silo;
    if (cur.isGroup && !actAs) {
      throw new Error('Add a member to this group first — someone has to do the talking.');
    }
    const body = {phone: actAs, text, sender_name: labelOf(actAs)};
    if (cur.isGroup) {
      body.chat_id = cur.silo;
      body.group_name = g ? g.name : null;
      body.force_forward = $('ff').checked;
    }
    const r = await api('/api/admin/test/send', 'POST', body);
    if (!r.forwarded) {
      addExtra(cur.silo, {kind: 'dropped', who: labelOf(actAs), text});
    } else if (r.busy) {
      alert('That chat is mid-turn (409). Wait a moment and resend.');
      sending = false; $('send').disabled = false;
      return;
    } else {
      const resp = r.response || {};
      (resp.side_messages || []).forEach(sm => {
        addExtra(cur.silo, {kind: 'system', text: '➡️ side message to ' + sm.to + ': ' + sm.text});
        const target = people.find(p => p.phone === sm.to);
        if (target) addExtra(sm.to, {kind: 'welcome', who: 'HAL', text: sm.text});
      });
      (resp.result_images || []).forEach(im => {
        addExtra(cur.silo, {kind: 'image', img: 'data:' + im.mime_type + ';base64,' + im.data});
      });
    }
    $('msg').value = '';
    await refreshState();
  } catch (e) { alert(e.message); }
  sending = false; $('send').disabled = false;
  $('msg').focus();
}
$('send').onclick = sendMsg;
$('msg').addEventListener('keydown', e => { if (e.key === 'Enter') sendMsg(); });

async function addMember(g, phone) {
  // First add = this person starts the group with HAL (they're the actor);
  // later adds are performed by the current "send as" member.
  const actor = g.members.length === 0 ? phone : (($('actAs') && $('actAs').value) || g.members[0]);
  try {
    const r = await api('/api/admin/test/group-event', 'POST', {
      chat_id: g.id, event: 'member_added', actor,
      group_name: g.name,
    });
    g.members.push(phone);
    save('htc.groups', groups);
    addExtra(g.id, {kind: 'system', text: labelOf(phone) + ' was added by ' + labelOf(actor)});
    const reply = r.response && r.response.reply;
    if (reply) addExtra(g.id, {kind: 'welcome', who: 'HAL', text: reply});
    renderHead(); await refreshState();
  } catch (e) { alert(e.message); }
}

async function removeMember(g, phone) {
  const others = g.members.filter(m => m !== phone);
  const actAsEl = $('actAs');
  const actor = (actAsEl && actAsEl.value !== phone && actAsEl.value) || others[0] || phone;
  try {
    await api('/api/admin/test/group-event', 'POST', {
      chat_id: g.id, event: 'member_removed', actor, target: phone, group_name: g.name,
    });
    g.members = others;
    save('htc.groups', groups);
    addExtra(g.id, {kind: 'system', text: labelOf(phone) + ' was removed by ' + labelOf(actor)});
    renderHead(); await refreshState();
  } catch (e) { alert(e.message); }
}

async function doReset() {
  if (!cur) return;
  const what = cur.isGroup ? 'this group\'s entire server-side state' :
    labelOf(cur.silo) + '\'s entire state (same as the real "forget me" flow)';
  if (!confirm('Wipe ' + what + '? Onboarding will start fresh.')) return;
  try {
    await api('/api/admin/test/reset', 'POST', {silo: cur.silo});
    delete extras[cur.silo]; save('htc.extras', extras);
    if (!cur.isGroup) {
      const p = people.find(x => x.phone === cur.silo);
      if (p) { p.onboarded = false; save('htc.people', people); }
    }
    await refreshState();
  } catch (e) { alert(e.message); }
}

/* ---------- background sync ---------- */
async function syncPersonas() {
  try {
    const d = await api('/api/admin/test/personas');
    (d.people || []).forEach(sp => {
      let p = people.find(x => x.phone === sp.phone);
      if (!p) { p = {phone: sp.phone, label: sp.name || ''}; people.push(p); }
      p.onboarded = sp.onboarded;
      if (!p.label && sp.name) p.label = sp.name;
    });
    (d.groups || []).forEach(sg => {
      let g = groups.find(x => x.id === sg.chat_id);
      if (!g) {
        g = {id: sg.chat_id, name: sg.group_name || sg.chat_id, members: []};
        groups.push(g);
      }
      (sg.members || []).forEach(m => { if (!g.members.includes(m)) g.members.push(m); });
    });
    save('htc.people', people); save('htc.groups', groups);
    renderSidebar();
  } catch (e) { console.error(e); }
}

async function poll() {
  try {
    const d = await api('/api/admin/test/outbox');
    (d.messages || []).forEach(m => {
      if (!cur || m.to !== cur.silo) badges[m.to] = true;
    });
    if ((d.messages || []).length) renderSidebar();
    if (cur) await refreshState();
  } catch (e) { console.error(e); }
}

renderSidebar();
syncPersonas();
setInterval(poll, 4000);
</script>
</body></html>
"""
