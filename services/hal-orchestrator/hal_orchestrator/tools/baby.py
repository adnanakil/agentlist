"""baby tool — structured baby event logging, stats, and forecasts.

Replaces the old free-text memory pattern ("Bazzy nap START 2:15pm"). Events go
to the family's shared structured log (visible to every silo in the family —
parents' DMs and the family group chat), and every log returns the updated
forecast so the model can answer with real, data-grounded predictions.
"""

from __future__ import annotations

import base64
from collections import Counter
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import structlog

from hal_orchestrator.services.baby import (
    AUX_KINDS,
    EVENT_KINDS,
    add_event,
    apply_auto_reminders,
    as_pairs,
    as_triples,
    compute_patterns,
    create_family,
    day_aux,
    delete_last_event,
    detect_regression,
    ensure_family_member,
    event_trigger_stats,
    fmt_duration,
    fmt_time,
    forecast_next,
    format_day_aux,
    format_day_summary,
    format_forecast,
    get_family_for_silo,
    infer_wake_if_napping,
    load_events,
    search_events,
    summarize_day,
)
from hal_orchestrator.tools.registry import ToolContext

log = structlog.get_logger()

HISTORY_DAYS = 14  # analytics window loaded per call

CONFIG_BOOL_KEYS = {"auto_reminders", "auto_wind_down", "auto_feed_prep", "digests"}
CARD_KINDS = {"feed", "nap_start", "wake", "bedtime"}
_CARD_IMAGE_SOURCE = "baby_status_card"
_DAY_CARD_IMAGE_SOURCE = "baby_day_card"
_EXAMPLE_CARD_IMAGE_SOURCE = "baby_example_card"


async def _attach_card(ctx: ToolContext, render, source: str) -> bool:
    """Render a card and add it to the bridge's image attachments. `render` is
    an async callable returning PNG bytes (or None for no data)."""
    try:
        png = await render()
    except Exception:
        log.exception("baby.card_render_failed", silo=ctx.phone, source=source)
        return False
    if not png:
        return False

    # A turn can render the same card several times (multiple logged events).
    # Keep only the latest copy of THIS card without discarding other cards or
    # unrelated attachments added by other tools.
    ctx.result_images[:] = [
        image for image in ctx.result_images if image.get("_source") != source
    ]
    ctx.result_images.append(
        {
            "mime_type": "image/png",
            "data": base64.b64encode(png).decode("ascii"),
            "ext": "png",
            "_source": source,
        }
    )
    return True


async def _attach_status_card(ctx: ToolContext) -> bool:
    from hal_orchestrator.services.baby_card import render_for_silo

    return await _attach_card(
        ctx, lambda: render_for_silo(ctx.session, ctx.phone), _CARD_IMAGE_SOURCE
    )


def _age_str(birthdate, now: datetime) -> str | None:
    """Human age ('11 weeks old') so age-dependent answers (wake windows,
    feed norms) are grounded in the tool result, not the model's guess."""
    if birthdate is None:
        return None
    days = (now.date() - birthdate).days
    if days < 0:
        return None
    weeks = days // 7
    if weeks < 16:
        return f"{weeks} weeks old"
    months = days // 30
    if months < 24:
        return f"{months} months old"
    return f"{days // 365} years old"


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
    return at.astimezone(UTC)


async def tool_baby(args: dict, ctx: ToolContext) -> str:
    action = args.get("action", "")
    now = datetime.now(UTC)

    family = await get_family_for_silo(ctx.session, ctx.phone)

    # A group thread whose SENDER already has a family: link the thread to
    # that family the first time baby traffic happens here — never create a
    # second, competing log. "The moment I'm in, everyone's texts land in one
    # log." Membership means baby traffic happened there (the one-way valve).
    linked_thread_now = False
    if family is None and ctx.is_group and ctx.sender_phone:
        sender_family = await get_family_for_silo(ctx.session, ctx.sender_phone)
        if sender_family is not None:
            await ensure_family_member(ctx.session, sender_family, ctx.phone)
            family = sender_family
            linked_thread_now = True
            log.info(
                "onboarding.family_thread_joined",
                family=str(family.id),
                thread=ctx.phone,
                via=ctx.sender_phone,
            )

    # A family thread must be PERMANENTLY watched: the bridge only forwards
    # group messages that mention "hal" / carry an image or link / are in the
    # watched set, and the auto-watch from HAL's replies expires after 24h of
    # quiet. Without this, a bare "4oz at 3:15" texted to a lapsed thread is
    # silently dropped at the bridge — invisible log loss, the one failure
    # this product can never have. Idempotent; promotes any TTL watch.
    if ctx.is_group and family is not None:
        try:
            from hal_orchestrator.services.watched import add_watched

            await add_watched(
                ctx.session, ctx.phone,
                note="family thread — baby log (permanent)",
                ttl_hours=None,
            )
        except Exception:
            log.exception("baby.family_watch_failed", silo=ctx.phone)

    if action == "setup":
        if family is not None:
            return f"A baby profile already exists here for {family.baby_name}."
        baby_name = (args.get("baby_name") or "").strip()
        if not baby_name:
            return "Error: baby_name is required for setup."
        birthdate = None
        if args.get("baby_birthdate"):
            try:
                birthdate = datetime.fromisoformat(
                    str(args["baby_birthdate"])
                ).date()
            except ValueError:
                birthdate = None
        tz_name = (args.get("timezone") or "").strip() or None
        if tz_name:
            try:
                ZoneInfo(tz_name)
            except Exception:
                tz_name = None
        if not tz_name:
            # Every baby time renders in family.timezone — inherit the
            # creator's profile timezone instead of defaulting a non-Eastern
            # household to New York time.
            from hal_orchestrator.services.profiles import get_profile

            creator = ctx.sender_phone or ctx.phone
            prof = await get_profile(ctx.session, creator)
            tz_name = prof.get("timezone") or None
        family = await create_family(
            ctx.session,
            ctx.phone,
            baby_name,
            timezone_name=tz_name,
            baby_birthdate=birthdate,
        )

        # Show, don't tell: attach an EXAMPLE status card so the parent sees
        # the nap/feed monitor they're getting before a single event exists.
        # A real event logged later this same turn replaces it (see the log
        # action's supersede below).
        async def _render_example() -> bytes:
            from hal_orchestrator.services.baby_card import render_example_card

            return render_example_card(
                family.baby_name,
                ZoneInfo(family.timezone),
                datetime.now(UTC),
            )

        example_attached = await _attach_card(
            ctx, _render_example, _EXAMPLE_CARD_IMAGE_SOURCE
        )
        return (
            f"Set up tracking for {baby_name}"
            + (f" (born {birthdate})" if birthdate else "")
            + (f", timezone {family.timezone}" if tz_name else "")
            + ". Log events with baby(action=log, kind=feed|nap_start|wake|"
            "bedtime). Auto-reminders (wind-down, bottle prep) are on by "
            "default — configure with baby(action=configure)."
            + (
                ""
                if tz_name
                else " NOTE: timezone not set yet — when you learn their city, "
                "call baby(action=configure, timezone=<IANA zone>)."
            )
            + (
                " [An EXAMPLE status card image is attached — the live "
                f"baby-monitor view they'll get for {baby_name}: nap state, "
                "expected wake, next feed, bedtime. Point at it in ONE short "
                "line — it fills itself in as they text feeds and naps. Do "
                "NOT re-list the times on the card.]"
                if example_attached
                else ""
            )
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
        note = (args.get("note") or "").strip()[:500]
        filed_kind: str | None = None
        if kind and kind not in EVENT_KINDS:
            # People log things no taxonomy predicts ("haircut", "vaccine",
            # "grandma visited"). Never bounce a real event over vocabulary —
            # file it as a note carrying the original word so history finds it.
            filed_kind = kind
            note = f"{kind} — {note}"[:500] if note else kind[:500]
            kind = "note"
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

        logger_id = ctx.sender_phone or ctx.phone
        total_before, loggers_before = await event_trigger_stats(
            ctx.session, family.id
        )

        # Infer the missed wake BEFORE inserting this event, so the lookback
        # query sees only prior state.
        inferred_wake = await infer_wake_if_napping(
            ctx.session, family, kind, event_at,
            logged_by=logger_id, silo=ctx.phone,
        )
        await add_event(
            ctx.session, family, kind, event_at,
            logged_by=logger_id, silo=ctx.phone,
            note=note,
        )

        # A caregiver logging from a group thread gets their own 1:1 silo on
        # the family too, so "text me directly" works with the same log.
        if ctx.is_group and ctx.sender_phone and ctx.sender_phone != ctx.phone:
            await ensure_family_member(ctx.session, family, ctx.sender_phone)

        if total_before == 0:
            log.info(
                "onboarding.first_log",
                family=str(family.id),
                silo=ctx.phone,
                kind=kind,
            )

        events = as_pairs(
            await load_events(ctx.session, family.id, since=now - timedelta(days=HISTORY_DAYS))
        )
        forecast = forecast_next(events, tz, now, birthdate=family.baby_birthdate)
        auto_set = await apply_auto_reminders(
            ctx.session, family, kind, event_at, ctx.phone, forecast, now
        )
        if inferred_wake is not None:
            auto_set += await apply_auto_reminders(
                ctx.session, family, "wake", event_at, ctx.phone, forecast, now
            )

        # Once-ever, code-triggered moments (never model-whim — ONBOARDING.md):
        # the Win-2 forecast reveal (first wake-after-nap OR 3 logged events)
        # and the Win-3 second-caregiver acknowledgment. Never both in one
        # reply — the caregiver moment wins and the reveal waits for a later
        # log. Flags live in family.state; the dict is REASSIGNED so JSONB
        # persists.
        state = dict(family.state or {})
        state_dirty = False
        reveal_now = False
        win3_now = False
        if (
            logger_id not in loggers_before
            and len(loggers_before) == 1
            and not state.get("win3_acked")
        ):
            state["win3_acked"] = now.isoformat()
            state_dirty = True
            win3_now = True
            created = getattr(family, "created_at", None)
            hours = None
            if created is not None:
                if created.tzinfo is None:
                    created = created.replace(tzinfo=UTC)
                hours = round((now - created).total_seconds() / 3600, 1)
            log.info(
                "onboarding.second_caregiver_first_log",
                family=str(family.id),
                logger=logger_id,
                hours_from_start=hours,
            )
        if (
            not win3_now
            and not state.get("forecast_revealed")
            # Early-life only: the reveal is an onboarding payoff. A family
            # already past ~a dozen events (including any that predate this
            # feature) never gets a belated "first" reveal.
            and total_before < 12
            and (
                total_before + 1 >= 3
                or (kind == "wake" and any(k == "nap_start" for k, _ in events))
            )
        ):
            state["forecast_revealed"] = now.isoformat()
            state_dirty = True
            reveal_now = True
            log.info(
                "onboarding.forecast_shown",
                family=str(family.id),
                events=total_before + 1,
            )
        if state_dirty:
            family.state = state
            await ctx.session.flush()

        # Card-on-log: a feed/nap/wake/bedtime update gets the visual status
        # card automatically (user preference: a card on every nap & eating
        # update). Attach the rendered PNG directly so iMessage receives a real
        # image instead of a URL whose Open Graph metadata creates a link card.
        card_attached = kind in CARD_KINDS and await _attach_status_card(ctx)
        if card_attached:
            # A real card supersedes the setup-time EXAMPLE preview: when the
            # first log lands in the same turn as setup, send only the truth.
            ctx.result_images[:] = [
                image
                for image in ctx.result_images
                if image.get("_source") != _EXAMPLE_CARD_IMAGE_SOURCE
            ]

        label = filed_kind or kind.replace("_", " ")
        if card_attached:
            lines = [
                f"Logged: {baby} {label} at {fmt_time(event_at, tz)}.",
                "[The updated status card is attached as an image. Reply with just "
                "ONE short, warm line (e.g. \"Down he goes 💤\" / \"logged ✅\"); "
                "do NOT re-list the times, the card has them.]",
            ]
        else:
            lines = [
                f"Logged: {baby} {label} at {fmt_time(event_at, tz)}.",
                "",
                format_forecast(forecast, tz, baby, now),
            ]
        if filed_kind:
            lines.append(
                f"(No structured kind for '{filed_kind}' — stored as a note, "
                "findable later with baby(action=history, query=...). If it "
                "was really a feed/nap/wake/bedtime, undo and re-log.)"
            )
        if inferred_wake is not None:
            lines.append(
                f"Note: {baby} was still logged as napping, so this {kind.replace('_', ' ')} "
                f"also closed the nap — wake recorded at {fmt_time(event_at, tz)}. Mention "
                "this in one short clause so they can correct the wake time if it was earlier."
            )
        if auto_set:
            lines.append("Auto-set reminders (standing preference): " + "; ".join(auto_set))
            lines.append(
                "Tell the user briefly what was set — do NOT ask whether to set reminders."
            )
        if reveal_now:
            lines.append(
                "[FIRST FORECAST REVEAL — once ever, and it's now: in this "
                "SAME reply, right after the log ack, give the payoff nobody "
                "asked for — the forecast above (the next sleepy window / next "
                "feed) in ONE warm line, keeping its stated uncertainty "
                "wording. Add that you'll quietly flag it ~15 min ahead and "
                "they can say 'stop nudges' anytime. This overrides the "
                "one-short-line card rule for THIS reply only.]"
            )
        if win3_now:
            lines.append(
                f"[SECOND CAREGIVER — this is the first log from a NEW person "
                f"on {baby}'s record. Acknowledge it ONCE, warmly, in this "
                f"reply — e.g. \"Got it — logged. (That's two of you on "
                f"{baby}'s log now — I'll keep everyone's entries straight.)\" "
                f"Never repeat this acknowledgment.]"
            )
        if linked_thread_now:
            lines.append(
                f"[THIS THREAD WAS JUST LINKED to {baby}'s log. If you haven't "
                f"introduced yourself in this group, add ONE line: you keep "
                f"{baby}'s log — anyone here can text feeds/naps/diapers the "
                f"way they'd say it out loud and it all lands in one record; "
                f"you'll stay quiet otherwise 🤫]"
            )
        return "\n".join(lines)

    if action == "forecast":
        events = as_pairs(
            await load_events(ctx.session, family.id, since=now - timedelta(days=HISTORY_DAYS))
        )
        if not events:
            return f"No events logged yet for {baby}."
        return format_forecast(
            forecast_next(events, tz, now, birthdate=family.baby_birthdate),
            tz, baby, now,
        )

    if action == "card":
        # The visual baby-monitor card is delivered as a real image attachment.
        if not await _attach_status_card(ctx):
            return f"No events logged yet for {baby} — nothing to put on a card."
        return (
            f"[{baby}'s status card is attached as an image. Add at most ONE short "
            "friendly line; do NOT re-list the feed/nap times — the card shows them.]"
        )

    if action == "day_card":
        # Whole-day recap card: wake, naps, feeds, bedtime as one image.
        events = as_pairs(
            await load_events(ctx.session, family.id, since=now - timedelta(days=2))
        )
        local_today = now.astimezone(tz).date()
        summary = summarize_day(events, tz, local_today)
        if not (
            summary["feeds"] or summary["naps"] or summary["bedtime"]
            or summary["morning_wake"]
        ):
            return f"Nothing logged yet today for {baby} — no day summary to show."

        from hal_orchestrator.services.baby_card import (
            build_day_summary_data,
            render_day_summary_png,
        )

        data = build_day_summary_data(summary, baby, tz, now)

        async def _render_day() -> bytes:
            return render_day_summary_png(data)

        if not await _attach_card(ctx, _render_day, _DAY_CARD_IMAGE_SOURCE):
            return f"Nothing logged yet today for {baby} — no day summary to show."
        return (
            f"[{baby}'s day summary card is attached as an image. Add at most ONE "
            "short friendly line; do NOT re-list the times — the card shows them.]"
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

        age = _age_str(family.baby_birthdate, now)
        age_part = f" ({age})" if age else ""
        if period in ("today", "yesterday"):
            d = local_today if period == "today" else local_today - timedelta(days=1)
            summary = summarize_day(events, tz, d)
            out = [f"{baby}{age_part} — {period} ({d.strftime('%a %b %-d')}):",
                   format_day_summary(summary, tz, baby)]
            aux_lines = format_day_aux(day_aux(as_triples(events_raw), tz, d), tz)
            if aux_lines:
                out.append(aux_lines)
            if period == "today":
                out += ["", format_forecast(
                    forecast_next(events, tz, now, birthdate=family.baby_birthdate),
                    tz, baby, now,
                )]
                # The one family-thread growth nudge, ever: when this family
                # still logs solo (one silo — no thread, no second caregiver),
                # the first day summary closes with the group-chat P.S.
                # Code-gated so it can never repeat or nag (ONBOARDING.md).
                if not (family.state or {}).get("thread_ps_sent"):
                    from sqlalchemy import func
                    from sqlalchemy import select as sa_select

                    from ag_db.models import HalFamilyMember

                    n_members = (
                        await ctx.session.execute(
                            sa_select(func.count())
                            .select_from(HalFamilyMember)
                            .where(HalFamilyMember.family_id == family.id)
                        )
                    ).scalar_one()
                    if n_members <= 1:
                        st = dict(family.state or {})
                        st["thread_ps_sent"] = now.isoformat()
                        family.state = st
                        await ctx.session.flush()
                        log.info(
                            "onboarding.thread_howto_ps", family=str(family.id)
                        )
                        out.append(
                            "[GROWTH P.S. — once ever, this family logs solo: "
                            "end your reply with exactly this postscript: "
                            "\"P.S. — this log works best as a group chat. Add "
                            "anyone who does feeds or naps — partner, nanny, "
                            "grandma — to a group text with me and everyone "
                            "can log to the same record. Want the 15-second "
                            "how-to?\"]"
                        )
            return "\n".join(out)

        # week: per-day digest + patterns + regression flags
        out = [f"{baby}{age_part} — last 7 days:"]
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
        p = compute_patterns(events, tz, now, birthdate=family.baby_birthdate)
        out.append(
            f"Pattern: naps ~{fmt_duration(int(p['nap_minutes']))}, wake windows "
            f"~{fmt_duration(int(p['wake_window_minutes']))}, feeds every "
            f"~{fmt_duration(int(p['feed_interval_minutes']))}"
        )
        if p["bedtime_minutes"] is not None:
            bm = int(p["bedtime_minutes"])
            out.append(f"Typical bedtime: {bm // 60 % 12 or 12}:{bm % 60:02d} PM")
        week_cut = now - timedelta(days=7)
        aux_counts = Counter(
            kind
            for kind, at, _ in as_triples(events_raw)
            if kind in AUX_KINDS and at >= week_cut
        )
        if aux_counts:
            out.append(
                "Also this week: "
                + ", ".join(
                    f"{kind.replace('_', ' ')} ×{n}"
                    for kind, n in aux_counts.most_common()
                )
            )
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
        from hal_orchestrator.services.baby import fmt_ago

        lines = [f"{baby} — recent events:"]
        for e in events_raw[-20:]:
            local = e.event_at.astimezone(tz)
            note = f" ({e.note})" if e.note else ""
            # Relative time computed in code — the model must never do clock
            # math itself (it narrated a 2-minute-old nap as "2 hours ago").
            lines.append(
                f"- {local.strftime('%a %-I:%M %p')} ({fmt_ago(e.event_at, now)}): "
                f"{e.kind.replace('_', ' ')}{note}"
            )
        return "\n".join(lines)

    if action == "history":
        # Full-log search — "when did he last have tylenol", "how many poops
        # this week", "when was his last bath". recent/stats only cover a few
        # days; this is the lookback path with no horizon.
        kind = (args.get("kind") or "").strip() or None
        query = (args.get("query") or "").strip() or None
        if kind is not None and kind not in EVENT_KINDS:
            # An unknown kind is a concept, not vocabulary ("haircut") — fold
            # it into the text search so lookups never bounce either.
            query = f"{query} {kind}".strip() if query else kind
            kind = None
        since = None
        if args.get("days"):
            try:
                since = now - timedelta(days=max(1, min(int(args["days"]), 400)))
            except (TypeError, ValueError):
                return "Error: days must be a number."
        matches, total = await search_events(
            ctx.session, family.id, kind=kind, query=query, since=since
        )
        scope_bits = [b for b in (
            kind and f"kind={kind}",
            query and f"matching '{query}'",
            args.get("days") and f"last {args['days']} days",
        ) if b]
        scope = f" ({', '.join(scope_bits)})" if scope_bits else ""
        if not matches:
            return f"No events found for {baby}{scope}."
        from hal_orchestrator.services.baby import fmt_ago

        shown = matches[-30:]
        header = f"{baby} — {total} event{'s' if total != 1 else ''}{scope}"
        if total > len(shown):
            header += f", showing the {len(shown)} most recent"
        lines = [header + ":"]
        for e in shown:
            local = e.event_at.astimezone(tz)
            note = f" ({e.note})" if e.note else ""
            lines.append(
                f"- {local.strftime('%a %b %-d, %-I:%M %p')} "
                f"({fmt_ago(e.event_at, now)}): {e.kind.replace('_', ' ')}{note}"
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

    if action == "export":
        # Day-one data portability ("you're never locked in"): the whole log
        # as plain CSV lines the user can keep, paste, or import elsewhere.
        events_raw = await load_events(ctx.session, family.id)
        if not events_raw:
            return f"No events logged yet for {baby} — nothing to export."
        rows = ["date,time,kind,note,logged_by"]
        for e in events_raw[-1000:]:
            local = e.event_at.astimezone(tz)
            note = (e.note or "").replace(",", ";").replace("\n", " ")
            rows.append(
                f"{local:%Y-%m-%d},{local:%H:%M},{e.kind},{note},{e.logged_by or ''}"
            )
        return (
            f"[{baby}'s complete log as CSV ({len(events_raw)} events, "
            "timezone-local). Send the CSV to the user verbatim — it's theirs. "
            "One short line of framing max.]\n" + "\n".join(rows)
        )

    if action == "configure":
        settings = dict(family.settings or {})
        changed: list[str] = []
        if args.get("timezone"):
            tz_arg = str(args["timezone"]).strip()
            try:
                ZoneInfo(tz_arg)
            except Exception:
                return (
                    "Error: timezone must be a valid IANA zone like "
                    "America/Chicago."
                )
            family.timezone = tz_arg
            settings["tz_set"] = True
            changed.append(f"timezone={tz_arg}")
            tz = ZoneInfo(tz_arg)
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
        "Use: log, forecast, stats, card, day_card, recent, history, setup, "
        "configure, undo, export."
    )
