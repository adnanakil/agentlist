"""GET /admin — HAL admin dashboard (server-rendered, no JS framework).

One page: how many conversations HAL is in and how much traffic each one
carries — total archived messages, user/HAL split, rolling-window size,
last activity, and 24h volume. Token-protected (the bridge secret):

    https://<host>/admin?token=<HAL_BRIDGE_SECRET>          (HTML)
    https://<host>/admin?token=...&format=json              (raw data)

Read-only; every query is an aggregate over existing tables (no writes).
"""

from __future__ import annotations

import hmac
import html
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ag_db.models import HalConversation, HalMessage, HalUserProfile
from ag_db.session import get_session
from hal_orchestrator.prompts.system import USER_TZ
from hal_orchestrator.services.identity import is_group_id
from hal_orchestrator.state import get_settings

log = structlog.get_logger()

_SKIP_SILOS = {"__shared__"}  # skills pseudo-silo, not a conversation


def _rel_time(dt: datetime | None, now: datetime) -> str:
    """Compact relative age: 'now', '5m', '3h', '2d', '4w'."""
    if dt is None:
        return "—"
    secs = (now - dt).total_seconds()
    if secs < 90:
        return "now"
    if secs < 3600:
        return f"{int(secs // 60)}m"
    if secs < 86400:
        return f"{int(secs // 3600)}h"
    if secs < 86400 * 14:
        return f"{int(secs // 86400)}d"
    return f"{int(secs // (86400 * 7))}w"


def render_dashboard(rows: list[dict], totals: dict, now_local_str: str) -> str:
    """Pure HTML renderer so it's unit-testable without a DB."""
    def esc(s: object) -> str:
        return html.escape(str(s if s is not None else ""))

    cards = "".join(
        f'<div class="card"><div class="num">{esc(v)}</div>'
        f'<div class="lbl">{esc(k)}</div></div>'
        for k, v in totals.items()
    )
    body_rows = "".join(
        "<tr>"
        f"<td class='who'>{'👥 ' if r['is_group'] else ''}{esc(r['label'])}"
        f"<span class='silo'>{esc(r['silo'])}</span></td>"
        f"<td class='n'>{r['total_msgs']:,}</td>"
        f"<td class='n'>{r['user_msgs']:,} / {r['hal_msgs']:,}</td>"
        f"<td class='n'>{r['window_msgs']:,}</td>"
        f"<td class='n'>{r['msgs_24h']:,}</td>"
        f"<td class='age'>{esc(r['last_age'])}</td>"
        "</tr>"
        for r in rows
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>HAL — Admin</title>
<meta http-equiv="refresh" content="120">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body {{ background:#101014; color:#e8e8ea; font:15px -apple-system,system-ui,sans-serif;
          margin:0; padding:24px; }}
  h1 {{ font-size:20px; margin:0 0 4px; }}
  .sub {{ color:#8b8b93; font-size:13px; margin-bottom:20px; }}
  .cards {{ display:flex; gap:12px; flex-wrap:wrap; margin-bottom:24px; }}
  .card {{ background:#1a1a20; border:1px solid #2a2a32; border-radius:10px;
           padding:14px 18px; min-width:120px; }}
  .card .num {{ font-size:24px; font-weight:650; }}
  .card .lbl {{ color:#8b8b93; font-size:12px; margin-top:2px; }}
  table {{ border-collapse:collapse; width:100%; }}
  th {{ text-align:left; color:#8b8b93; font-size:12px; font-weight:500;
        padding:8px 12px; border-bottom:1px solid #2a2a32; }}
  th.n, td.n {{ text-align:right; }}
  td {{ padding:10px 12px; border-bottom:1px solid #1e1e26; }}
  td.who {{ font-weight:550; }}
  .silo {{ display:block; color:#6b6b73; font-size:11px; font-weight:400; }}
  td.age {{ color:#8b8b93; }}
  tr:hover td {{ background:#16161c; }}
</style></head><body>
<h1>HAL — Conversations</h1>
<div class="sub">as of {esc(now_local_str)} · auto-refreshes every 2 min · msgs = full archive; window = rolling context buffer</div>
<div class="cards">{cards}</div>
<table>
<tr><th>Conversation</th><th class="n">Messages</th><th class="n">user / HAL</th>
<th class="n">Window</th><th class="n">24h</th><th>Last</th></tr>
{body_rows}
</table>
</body></html>"""


def build_admin_router() -> APIRouter:
    router = APIRouter()

    def _check_token(token: str) -> None:
        settings = get_settings()
        # Prefer a dedicated admin token so a leaked dashboard URL can't be
        # replayed as bridge auth; fall back to the bridge secret for existing
        # single-secret deploys. Fails closed when neither is configured.
        secret = settings.admin_token or settings.hal_bridge_secret
        if not secret or not hmac.compare_digest(token or "", secret):
            raise HTTPException(status_code=403, detail="Bad token")

    @router.get("/admin", response_class=HTMLResponse)
    async def admin_dashboard(
        token: str = Query(""),
        format: str = Query("html"),
        authorization: str = Header(""),
        session: AsyncSession = Depends(get_session),
    ):
        # Accept the token via Authorization: Bearer <token> (preferred — stays
        # out of proxy/access logs) or the ?token= query param (browser
        # convenience). The header wins when both are present.
        bearer = ""
        if authorization.startswith("Bearer "):
            bearer = authorization[len("Bearer ") :].strip()
        _check_token(bearer or token)
        now = datetime.now(timezone.utc)
        day_ago = now - timedelta(hours=24)

        # Per-silo aggregates over the durable archive.
        msg_rows = (
            await session.execute(
                select(
                    HalMessage.phone,
                    func.count().label("total"),
                    func.sum(case((HalMessage.role == "user", 1), else_=0)).label("user_n"),
                    func.max(HalMessage.created_at).label("last_at"),
                    func.sum(case((HalMessage.created_at >= day_ago, 1), else_=0)).label("n24"),
                ).group_by(HalMessage.phone)
            )
        ).all()
        # Rolling-window sizes + names.
        conv_rows = (
            await session.execute(
                select(HalConversation.phone, HalConversation.message_count,
                       HalConversation.updated_at)
            )
        ).all()
        name_rows = (
            await session.execute(
                select(HalUserProfile.phone, HalUserProfile.name)
            )
        ).all()
        names = {r.phone: r.name for r in name_rows if r.name}
        window = {r.phone: (r.message_count or 0, r.updated_at) for r in conv_rows}

        merged: dict[str, dict] = {}
        for r in msg_rows:
            if r.phone in _SKIP_SILOS:
                continue
            merged[r.phone] = {
                "silo": r.phone,
                "total_msgs": int(r.total or 0),
                "user_msgs": int(r.user_n or 0),
                "hal_msgs": int((r.total or 0) - (r.user_n or 0)),
                "msgs_24h": int(r.n24 or 0),
                "last_at": r.last_at,
            }
        for phone, (wcount, updated) in window.items():
            if phone in _SKIP_SILOS:
                continue
            m = merged.setdefault(phone, {
                "silo": phone, "total_msgs": 0, "user_msgs": 0,
                "hal_msgs": 0, "msgs_24h": 0, "last_at": None,
            })
            m["window_msgs"] = wcount
            if m["last_at"] is None:
                m["last_at"] = updated
        rows = []
        for m in merged.values():
            m.setdefault("window_msgs", 0)
            m["is_group"] = is_group_id(m["silo"])
            m["label"] = names.get(m["silo"]) or ("Group chat" if m["is_group"] else "Unknown")
            m["last_age"] = _rel_time(m["last_at"], now)
            rows.append(m)
        rows.sort(key=lambda m: m["last_at"] or datetime.min.replace(tzinfo=timezone.utc),
                  reverse=True)

        totals = {
            "conversations": len(rows),
            "1:1 chats": sum(1 for r in rows if not r["is_group"]),
            "groups": sum(1 for r in rows if r["is_group"]),
            "total messages": f"{sum(r['total_msgs'] for r in rows):,}",
            "messages (24h)": sum(r["msgs_24h"] for r in rows),
            "active (24h)": sum(1 for r in rows if r["msgs_24h"]),
        }

        if format == "json":
            # Explicit JSONResponse: the route's response_class is HTMLResponse,
            # which would try to encode a plain dict and 500.
            return JSONResponse({
                "totals": totals,
                "conversations": [
                    {k: (v.isoformat() if isinstance(v, datetime) else v)
                     for k, v in r.items()}
                    for r in rows
                ],
            })

        now_local = datetime.now(USER_TZ).strftime("%a %b %-d, %-I:%M %p %Z")
        return HTMLResponse(render_dashboard(rows, totals, now_local))

    @router.post("/api/admin/grant")
    async def grant_plan(
        silo: str = Query(..., description="user handle/phone to grant"),
        unlimited: bool = Query(True),
        limit: int = Query(0, description="monthly cap when not unlimited"),
        token: str = Query(""),
        authorization: str = Header(""),
        session: AsyncSession = Depends(get_session),
    ):
        """Lift a user's message cap after they pay. Admin-tokened; sets the
        profile plan (unlimited, or a higher monthly limit) and resets the
        current period's counter so they're unblocked immediately. This is the
        manual/webhook hook that closes the pay -> unlock loop."""
        bearer = ""
        if authorization.startswith("Bearer "):
            bearer = authorization[len("Bearer ") :].strip()
        _check_token(bearer or token)

        from hal_orchestrator.services.usage import set_plan

        plan = await set_plan(session, silo, unlimited=unlimited, limit=limit)
        await session.commit()
        return JSONResponse({"ok": True, "silo": silo, "plan": plan})

    return router
