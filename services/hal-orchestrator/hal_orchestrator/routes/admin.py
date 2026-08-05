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
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import case, func, or_ as sa_or, select
from sqlalchemy.ext.asyncio import AsyncSession

from ag_db.models import (
    HalConversation,
    HalFunnelEvent,
    HalLearningCandidate,
    HalMessage,
    HalPageHit,
    HalTurn,
    HalUserProfile,
)
from ag_db.session import get_session
from hal_orchestrator.prompts.system import USER_TZ
from hal_orchestrator.routes.landing import _pretty_number
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

    @router.get("/api/admin/learning-candidates")
    async def learning_candidates(
        token: str = Query(""),
        authorization: str = Header(""),
        session: AsyncSession = Depends(get_session),
    ) -> JSONResponse:
        bearer = authorization.removeprefix("Bearer ").strip()
        _check_token(bearer or token)
        rows = (
            (
                await session.execute(
                    select(HalLearningCandidate)
                    .where(HalLearningCandidate.status == "pending")
                    .order_by(HalLearningCandidate.created_at.desc())
                    .limit(100)
                )
            )
            .scalars()
            .all()
        )
        return JSONResponse(
            {
                "candidates": [
                    {
                        "id": str(row.id),
                        "kind": row.kind,
                        "payload": row.payload,
                        "created_at": row.created_at.isoformat(),
                    }
                    for row in rows
                ]
            }
        )

    @router.post("/api/admin/learning-candidates/{candidate_id}/approve")
    async def approve_learning_candidate(
        candidate_id: UUID,
        token: str = Query(""),
        authorization: str = Header(""),
        session: AsyncSession = Depends(get_session),
    ) -> JSONResponse:
        bearer = authorization.removeprefix("Bearer ").strip()
        _check_token(bearer or token)
        candidate = await session.get(
            HalLearningCandidate, candidate_id, with_for_update=True
        )
        if candidate is None:
            raise HTTPException(status_code=404, detail="candidate not found")
        from hal_orchestrator.services.growth import build_denylist
        from hal_orchestrator.services.learning_candidates import promote

        result = await promote(session, candidate, await build_denylist(session))
        if result.get("error"):
            await session.rollback()
            return JSONResponse(status_code=400, content=result)
        await session.commit()
        return JSONResponse({"ok": True, "result": result})

    @router.post("/api/admin/learning-candidates/{candidate_id}/reject")
    async def reject_learning_candidate(
        candidate_id: UUID,
        note: str = Query(""),
        token: str = Query(""),
        authorization: str = Header(""),
        session: AsyncSession = Depends(get_session),
    ) -> JSONResponse:
        bearer = authorization.removeprefix("Bearer ").strip()
        _check_token(bearer or token)
        candidate = await session.get(
            HalLearningCandidate, candidate_id, with_for_update=True
        )
        if candidate is None:
            raise HTTPException(status_code=404, detail="candidate not found")
        from hal_orchestrator.services.learning_candidates import reject

        await reject(session, candidate, note)
        await session.commit()
        return JSONResponse({"ok": True})

    @router.get("/admin/traffic", response_class=HTMLResponse)
    async def site_traffic(
        token: str = Query(""),
        format: str = Query("html"),
        authorization: str = Header(""),
        session: AsyncSession = Depends(get_session),
    ):
        bearer = ""
        if authorization.startswith("Bearer "):
            bearer = authorization[len("Bearer ") :].strip()
        _check_token(bearer or token)
        now = datetime.now(timezone.utc)
        since_30d = now - timedelta(days=30)
        since_14d = now - timedelta(days=14)

        day = func.date_trunc("day", HalPageHit.created_at).label("day")
        daily = (
            await session.execute(
                select(
                    day,
                    func.count().filter(HalPageHit.is_bot.is_(False)).label("views"),
                    func.count(func.distinct(HalPageHit.visitor_hash))
                    .filter(HalPageHit.is_bot.is_(False))
                    .label("uniques"),
                    func.count().filter(HalPageHit.is_bot.is_(True)).label("bots"),
                )
                .where(HalPageHit.created_at >= since_30d)
                .group_by(day)
                .order_by(day.desc())
            )
        ).all()
        referrers = (
            await session.execute(
                select(HalPageHit.referrer, func.count().label("n"))
                .where(
                    HalPageHit.created_at >= since_14d,
                    HalPageHit.is_bot.is_(False),
                    HalPageHit.referrer.is_not(None),
                )
                .group_by(HalPageHit.referrer)
                .order_by(func.count().desc())
                .limit(15)
            )
        ).all()
        paths = (
            await session.execute(
                select(HalPageHit.path, func.count().label("n"))
                .where(HalPageHit.created_at >= since_14d, HalPageHit.is_bot.is_(False))
                .group_by(HalPageHit.path)
                .order_by(func.count().desc())
            )
        ).all()

        # Funnel: landing views -> sms taps -> first texts to HAL (attributed
        # via the "(code)" sms prefill -> profile acquisition_source). Test taps
        # (utm_source=verify-test) are excluded.
        code_to_source = {"g1": "google", "r1": "reddit", "p1": "pinterest", "m1": "meta"}
        tap_day = func.date_trunc("day", HalFunnelEvent.created_at).label("day")
        not_test = sa_or(
            HalFunnelEvent.utm_source.is_(None),
            HalFunnelEvent.utm_source != "verify-test",
        )
        taps_daily = (
            await session.execute(
                select(tap_day, func.count().label("n"))
                .where(
                    HalFunnelEvent.event_type == "sms_tap",
                    HalFunnelEvent.created_at >= since_14d,
                    not_test,
                )
                .group_by(tap_day)
            )
        ).all()
        tap_src = func.coalesce(HalFunnelEvent.utm_source, "(direct)").label("src")
        taps_by_source = (
            await session.execute(
                select(tap_src, func.count().label("n"))
                .where(
                    HalFunnelEvent.event_type == "sms_tap",
                    HalFunnelEvent.created_at >= since_14d,
                    not_test,
                )
                .group_by(tap_src)
            )
        ).all()
        view_src = func.coalesce(HalPageHit.utm_source, "(direct)").label("src")
        views_by_source = (
            await session.execute(
                select(view_src, func.count().label("n"))
                .where(
                    HalPageHit.created_at >= since_14d,
                    HalPageHit.is_bot.is_(False),
                    HalPageHit.path == "/",
                )
                .group_by(view_src)
            )
        ).all()
        # Hero-CTA A/B (landing.py). Rows predating the experiment have a NULL
        # variant and are excluded from both arms rather than silently pooled.
        views_by_variant = (
            await session.execute(
                select(HalPageHit.variant, func.count().label("n"))
                .where(
                    HalPageHit.created_at >= since_14d,
                    HalPageHit.is_bot.is_(False),
                    HalPageHit.path == "/",
                    HalPageHit.variant.is_not(None),
                )
                .group_by(HalPageHit.variant)
            )
        ).all()
        taps_by_variant = (
            await session.execute(
                select(HalFunnelEvent.variant, func.count().label("n"))
                .where(
                    HalFunnelEvent.event_type == "sms_tap",
                    HalFunnelEvent.created_at >= since_14d,
                    HalFunnelEvent.variant.is_not(None),
                    not_test,
                )
                .group_by(HalFunnelEvent.variant)
            )
        ).all()

        first_seen = (
            select(
                HalTurn.phone.label("phone"),
                func.min(HalTurn.created_at).label("first_at"),
            )
            .where(HalTurn.phone.not_like("%1555555%"))
            .group_by(HalTurn.phone)
            .subquery()
        )
        new_households = (
            await session.execute(
                select(
                    first_seen.c.first_at,
                    func.jsonb_extract_path_text(
                        HalUserProfile.extra_data, "acquisition_source"
                    ).label("code"),
                )
                .select_from(
                    first_seen.outerjoin(
                        HalUserProfile, HalUserProfile.phone == first_seen.c.phone
                    )
                )
                .where(first_seen.c.first_at >= since_14d)
            )
        ).all()

        taps_day_map = {r.day.strftime("%Y-%m-%d"): r.n for r in taps_daily}
        hh_day_map: dict[str, int] = {}
        hh_src_map: dict[str, int] = {}
        for r in new_households:
            d_key = r.first_at.strftime("%Y-%m-%d")
            hh_day_map[d_key] = hh_day_map.get(d_key, 0) + 1
            src = code_to_source.get(r.code or "", r.code) or "(organic/unknown)"
            hh_src_map[src] = hh_src_map.get(src, 0) + 1
        src_views = {r.src: r.n for r in views_by_source}
        src_taps = {r.src: r.n for r in taps_by_source}
        all_sources = sorted(
            set(src_views) | set(src_taps) | set(hh_src_map),
            key=lambda s: -(src_views.get(s, 0)),
        )
        var_views = {r.variant: r.n for r in views_by_variant}
        var_taps = {r.variant: r.n for r in taps_by_variant}
        var_labels = {
            "a": "Text HAL",
            "b": f"Text {_pretty_number(get_settings().hal_public_number)}",
        }
        funnel_days = sorted(set(taps_day_map) | set(hh_day_map), reverse=True)
        total_views_14d = sum(src_views.values())
        total_taps_14d = sum(src_taps.values())
        total_hh_14d = sum(hh_day_map.values())

        data = {
            "daily": [
                {
                    "day": r.day.strftime("%Y-%m-%d"),
                    "views": r.views,
                    "uniques": r.uniques,
                    "bots": r.bots,
                }
                for r in daily
            ],
            "referrers_14d": [{"referrer": r.referrer, "hits": r.n} for r in referrers],
            "paths_14d": [{"path": r.path, "hits": r.n} for r in paths],
            "funnel_14d": {
                "totals": {
                    "landing_views": total_views_14d,
                    "sms_taps": total_taps_14d,
                    "tap_rate": round(total_taps_14d / total_views_14d, 4)
                    if total_views_14d
                    else None,
                    "new_households": total_hh_14d,
                },
                "by_source": [
                    {
                        "source": s,
                        "views": src_views.get(s, 0),
                        "taps": src_taps.get(s, 0),
                        "new_households": hh_src_map.get(s, 0),
                    }
                    for s in all_sources
                ],
                "daily": [
                    {
                        "day": d,
                        "taps": taps_day_map.get(d, 0),
                        "new_households": hh_day_map.get(d, 0),
                    }
                    for d in funnel_days
                ],
            },
            "cta_experiment_14d": [
                {
                    "variant": v,
                    "cta_copy": var_labels.get(v, v),
                    "views": var_views.get(v, 0),
                    "taps": var_taps.get(v, 0),
                    "tap_rate": round(var_taps.get(v, 0) / var_views[v], 4)
                    if var_views.get(v)
                    else None,
                }
                for v in sorted(set(var_views) | set(var_taps))
            ],
        }
        if format == "json":
            return JSONResponse(data)

        esc = html.escape
        day_rows = "".join(
            f"<tr><td>{d['day']}</td><td>{d['views']}</td>"
            f"<td>{d['uniques']}</td><td class='dim'>{d['bots']}</td></tr>"
            for d in data["daily"]
        ) or "<tr><td colspan=4>No hits recorded yet</td></tr>"
        ref_rows = "".join(
            f"<tr><td>{esc(r['referrer'] or '')}</td><td>{r['hits']}</td></tr>"
            for r in data["referrers_14d"]
        ) or "<tr><td colspan=2>No referrers yet (direct visits only)</td></tr>"
        path_rows = "".join(
            f"<tr><td>{esc(p['path'])}</td><td>{p['hits']}</td></tr>"
            for p in data["paths_14d"]
        )
        fn = data["funnel_14d"]
        tap_rate = fn["totals"]["tap_rate"]
        funnel_totals = (
            f"{fn['totals']['landing_views']} landing views → "
            f"{fn['totals']['sms_taps']} sms taps"
            + (f" ({tap_rate:.2%})" if tap_rate is not None else "")
            + f" → {fn['totals']['new_households']} new households"
        )
        src_rows = "".join(
            f"<tr><td>{esc(s['source'])}</td><td>{s['views']}</td>"
            f"<td>{s['taps']}</td><td>{s['new_households']}</td></tr>"
            for s in fn["by_source"]
        ) or "<tr><td colspan=4>No funnel data yet</td></tr>"
        funnel_day_rows = "".join(
            f"<tr><td>{d['day']}</td><td>{d['taps']}</td>"
            f"<td>{d['new_households']}</td></tr>"
            for d in fn["daily"]
        ) or "<tr><td colspan=3>No taps or new households in window</td></tr>"
        # NB: the route's `format` query param shadows the builtin, so the rate
        # is formatted here rather than with format() inside the row template.
        ab_rates = [
            "—" if v["tap_rate"] is None else f"{v['tap_rate']:.2%}"
            for v in data["cta_experiment_14d"]
        ]
        ab_rows = "".join(
            f"<tr><td>{esc(v['variant'])}</td><td>{esc(v['cta_copy'])}</td>"
            f"<td>{v['views']}</td><td>{v['taps']}</td><td>{rate}</td></tr>"
            for v, rate in zip(data["cta_experiment_14d"], ab_rates)
        ) or "<tr><td colspan=5>No variant-tagged traffic yet</td></tr>"
        return HTMLResponse(f"""<!doctype html><html><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Site traffic — HAL admin</title><style>
body {{ background:#111; color:#ddd; font-family:-apple-system, system-ui, sans-serif;
       max-width:720px; margin:0 auto; padding:32px 16px; }}
h1 {{ font-size:20px; margin-bottom:4px; }} h2 {{ font-size:15px; margin:26px 0 8px; }}
p.sub {{ color:#888; font-size:13px; }}
table {{ border-collapse:collapse; width:100%; font-size:14px; }}
td, th {{ text-align:left; padding:5px 10px 5px 0; border-bottom:1px solid #2a2a2a; }}
th {{ color:#888; font-weight:600; font-size:12px; }} .dim {{ color:#666; }}
</style></head><body>
<h1>Site traffic</h1>
<p class="sub">Server-side counts for texthal.com — no client tracker. Uniques are
day-salted visitor hashes (no IPs stored). Bots counted separately.</p>
<h2>Daily (last 30 days)</h2>
<table><tr><th>Day (UTC)</th><th>Views</th><th>Uniques</th><th>Bot hits</th></tr>{day_rows}</table>
<h2>Funnel (14 days)</h2>
<p class="sub">{funnel_totals}. Households attribute via the "(code)" sms
prefill — users can delete it, so paid counts are a floor. g1=google ads.</p>
<table><tr><th>Source</th><th>Views (/)</th><th>SMS taps</th><th>New households</th></tr>{src_rows}</table>
<h2>Funnel by day (14 days)</h2>
<table><tr><th>Day (UTC)</th><th>SMS taps</th><th>New households</th></tr>{funnel_day_rows}</table>
<h2>Hero CTA A/B (14 days)</h2>
<p class="sub">Coin flip on the hero + sticky-bar button copy, sticky per visitor
per day. Views count only "/" (non-bot); rows from before the experiment have no
variant and are excluded from both arms.</p>
<table><tr><th>Arm</th><th>CTA copy</th><th>Views</th><th>SMS taps</th><th>Tap rate</th></tr>{ab_rows}</table>
<h2>Top referrers (14 days)</h2>
<table><tr><th>Referrer</th><th>Hits</th></tr>{ref_rows}</table>
<h2>Pages (14 days)</h2>
<table><tr><th>Path</th><th>Hits</th></tr>{path_rows}</table>
</body></html>""")

    return router
