"""baby tool — structured baby event logging, stats, and forecasts.

Replaces the old free-text memory pattern ("Bazzy nap START 2:15pm"). Events go
to the family's shared structured log (visible to every silo in the family —
parents' DMs and the family group chat), and every log returns the updated
forecast so the model can answer with real, data-grounded predictions.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import structlog

from hal_orchestrator.services.baby import (
    EVENT_KINDS,
    add_event,
    apply_auto_reminders,
    as_pairs,
    compute_patterns,
    create_family,
    delete_last_event,
    detect_regression,
    fmt_duration,
    fmt_time,
    forecast_next,
    format_day_summary,
    format_forecast,
    get_family_for_silo,
    load_events,
    summarize_day,
)
from hal_orchestrator.tools.registry import ToolContext

log = structlog.get_logger()

HISTORY_DAYS = 14  # analytics window loaded per call

CONFIG_BOOL_KEYS = {"auto_reminders", "auto_wind_down", "auto_feed_prep"}


def _parse_time(value: str | None, now: datetime) -> datetime | None:
    """ISO timestamp -> aware UTC. Empty/None/'now' -> now."""
    if not value or value.strip().lower() == "now":
        return now
    try:
        at = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if at.tzinfo is None:
        # The model is instructed to pass local ISO times with offset; if it
        # forgets, assume the family timezone is handled by the caller.
        return None
    return at.astimezone(timezone.utc)


async def tool_baby(args: dict, ctx: ToolContext) -> str:
    action = args.get("action", "")
    now = datetime.now(timezone.utc)

    family = await get_family_for_silo(ctx.session, ctx.phone)

    if action == "setup":
        if family is not None:
            return f"A baby profile already exists here for {family.baby_name}."
        baby_name = (args.get("baby_name") or "").strip()
        if not baby_name:
            return "Error: baby_name is required for setup."
        family = await create_family(ctx.session, ctx.phone, baby_name)
        return (
            f"Set up tracking for {baby_name}. Log events with "
            f"baby(action=log, kind=feed|nap_start|wake|bedtime). Auto-reminders "
            f"(wind-down, bottle prep) are on by default — configure with "
            f"baby(action=configure)."
        )

    if family is None:
        return (
            "No baby profile is configured for this chat. Ask for the baby's "
            "name and call baby(action=setup, baby_name=...)."
        )

    tz = ZoneInfo(family.timezone)
    baby = family.baby_name

    if action == "log":
        kind = (args.get("kind") or "").strip()
        if kind not in EVENT_KINDS:
            return f"Error: kind must be one of {sorted(EVENT_KINDS)}."
        event_at = _parse_time(args.get("time"), now)
        if event_at is None:
            return (
                "Error: time must be an ISO timestamp WITH timezone offset "
                "(e.g. 2026-06-11T13:54:00-04:00) or omitted for 'now'. "
                "Use current_time first if unsure."
            )
        if event_at > now + timedelta(minutes=5):
            return "Error: that time is in the future — double-check it."
        # Day naps that start in the evening are really bedtime; let the model
        # decide, but auto-correct the obvious case (nap_start after 5:30pm).
        if kind == "nap_start" and event_at.astimezone(tz).hour >= 18:
            kind = "bedtime"

        await add_event(
            ctx.session, family, kind, event_at,
            logged_by=ctx.sender_phone or ctx.phone, silo=ctx.phone,
            note=(args.get("note") or "")[:500],
        )

        events = as_pairs(
            await load_events(ctx.session, family.id, since=now - timedelta(days=HISTORY_DAYS))
        )
        forecast = forecast_next(events, tz, now)
        auto_set = await apply_auto_reminders(
            ctx.session, family, kind, event_at, ctx.phone, forecast, now
        )

        lines = [
            f"Logged: {baby} {kind.replace('_', ' ')} at {fmt_time(event_at, tz)}.",
            "",
            format_forecast(forecast, tz, baby),
        ]
        if auto_set:
            lines.append("Auto-set reminders (standing preference): " + "; ".join(auto_set))
            lines.append(
                "Tell the user briefly what was set — do NOT ask whether to set reminders."
            )
        return "\n".join(lines)

    if action == "forecast":
        events = as_pairs(
            await load_events(ctx.session, family.id, since=now - timedelta(days=HISTORY_DAYS))
        )
        if not events:
            return f"No events logged yet for {baby}."
        return format_forecast(forecast_next(events, tz, now), tz, baby)

    if action == "card":
        # Render the visual baby-monitor card (last/next feed & nap) and attach
        # it as an image. The bridge sends ctx.result_images as iMessage
        # attachments (same path as image_edit).
        import base64

        from hal_orchestrator.services.baby_card import render_for_silo

        try:
            png = await render_for_silo(ctx.session, ctx.phone)
        except Exception:
            log.exception("baby.card_render_failed", silo=ctx.phone)
            png = None
        if not png:
            return f"No events logged yet for {baby} — nothing to put on a card."
        ctx.result_images.append(
            {"mime_type": "image/png", "data": base64.b64encode(png).decode(), "ext": "png"}
        )
        return (
            f"[Rendered {baby}'s status card — it will be sent as an image with "
            "your reply. Add at most ONE short friendly line; do NOT re-list the "
            "feed/nap times, the card already shows them.]"
        )

    if action == "stats":
        period = (args.get("period") or "today").strip().lower()
        events_raw = await load_events(
            ctx.session, family.id, since=now - timedelta(days=HISTORY_DAYS)
        )
        events = as_pairs(events_raw)
        if not events:
            return f"No events logged yet for {baby}."
        local_today = now.astimezone(tz).date()

        if period in ("today", "yesterday"):
            d = local_today if period == "today" else local_today - timedelta(days=1)
            summary = summarize_day(events, tz, d)
            out = [f"{baby} — {period} ({d.strftime('%a %b %-d')}):",
                   format_day_summary(summary, tz, baby)]
            if period == "today":
                out += ["", format_forecast(forecast_next(events, tz, now), tz, baby)]
            return "\n".join(out)

        # week: per-day digest + patterns + regression flags
        out = [f"{baby} — last 7 days:"]
        for i in range(6, -1, -1):
            d = local_today - timedelta(days=i)
            s = summarize_day(events, tz, d)
            if not s["feeds"] and not s["naps"] and not s["bedtime"]:
                continue
            naps = f"{len(s['naps'])} naps {fmt_duration(s['total_nap_minutes'])}"
            night = (
                f", night {fmt_duration(s['night_minutes'])}" if s["night_minutes"] else ""
            )
            bed = f", bed {fmt_time(s['bedtime'], tz)}" if s["bedtime"] else ""
            out.append(
                f"- {d.strftime('%a')}: {naps}, {len(s['feeds'])} feeds{night}{bed}"
            )
        p = compute_patterns(events, tz, now)
        out.append(
            f"Pattern: naps ~{fmt_duration(int(p['nap_minutes']))}, wake windows "
            f"~{fmt_duration(int(p['wake_window_minutes']))}, feeds every "
            f"~{fmt_duration(int(p['feed_interval_minutes']))}"
        )
        if p["bedtime_minutes"] is not None:
            bm = int(p["bedtime_minutes"])
            out.append(f"Typical bedtime: {bm // 60 % 12 or 12}:{bm % 60:02d} PM")
        flags = detect_regression(events, tz, now)
        if flags:
            out.append("⚠️ Possible sleep regression signals: " + "; ".join(flags))
        return "\n".join(out)

    if action == "recent":
        events_raw = await load_events(
            ctx.session, family.id, since=now - timedelta(days=3)
        )
        if not events_raw:
            return f"No events in the last 3 days for {baby}."
        lines = [f"{baby} — recent events:"]
        for e in events_raw[-20:]:
            local = e.event_at.astimezone(tz)
            note = f" ({e.note})" if e.note else ""
            lines.append(
                f"- {local.strftime('%a %-I:%M %p')}: {e.kind.replace('_', ' ')}{note}"
            )
        return "\n".join(lines)

    if action == "undo":
        event = await delete_last_event(ctx.session, family.id)
        if event is None:
            return "Nothing to undo."
        return (
            f"Removed the last event: {event.kind.replace('_', ' ')} at "
            f"{fmt_time(event.event_at, tz)}."
        )

    if action == "configure":
        settings = dict(family.settings or {})
        changed: list[str] = []
        for key in CONFIG_BOOL_KEYS:
            if key in args:
                settings[key] = bool(args[key])
                changed.append(f"{key}={settings[key]}")
        if "nap_cap_minutes" in args:
            try:
                settings["nap_cap_minutes"] = max(30, int(args["nap_cap_minutes"]))
                changed.append(f"nap_cap_minutes={settings['nap_cap_minutes']}")
            except (TypeError, ValueError):
                return "Error: nap_cap_minutes must be a number."
        if args.get("add_routine"):
            r = args["add_routine"]
            if not isinstance(r, dict) or r.get("after") not in EVENT_KINDS or not r.get("text"):
                return (
                    "Error: add_routine must be {after: <event kind>, "
                    "offset_min: <minutes>, text: <reminder text>}."
                )
            routines = list(settings.get("routines", []))
            routines.append(
                {
                    "after": r["after"],
                    "offset_min": int(r.get("offset_min", 30)),
                    "text": str(r["text"])[:200],
                }
            )
            settings["routines"] = routines
            changed.append(f"routine added ({r['after']} +{r.get('offset_min', 30)}m)")
        if args.get("baby_birthdate"):
            try:
                family.baby_birthdate = datetime.fromisoformat(
                    args["baby_birthdate"]
                ).date()
                changed.append(f"birthdate={family.baby_birthdate}")
            except ValueError:
                return "Error: baby_birthdate must be YYYY-MM-DD."
        if not changed:
            import json

            return "Current settings: " + json.dumps(settings)
        family.settings = settings
        await ctx.session.flush()
        return "Updated: " + ", ".join(changed)

    return (
        f"Unknown baby action: {action}. "
        "Use: log, forecast, stats, recent, undo, setup, configure."
    )
