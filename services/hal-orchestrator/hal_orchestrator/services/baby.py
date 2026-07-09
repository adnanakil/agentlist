"""Structured baby tracking — families, events, analytics, auto-reminders.

The family is the one deliberate exception to silo isolation: the parents' 1:1
silos and the family group chat share one event log (see HalFamily). Analytics
are pure functions over (kind, event_at) pairs so they're unit-testable without
a DB.

Event kinds:
  feed       — a feed started
  nap_start  — daytime sleep started
  bedtime    — night sleep started
  wake       — woke up (closes the most recent open nap/night sleep)
  tummy_time | diaper | note — auxiliary, logged but not paired
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ag_db.models import HalBabyEvent, HalFamily, HalFamilyMember, HalReminder

log = structlog.get_logger()

SLEEP_STARTS = {"nap_start", "bedtime"}
EVENT_KINDS = {"feed", "nap_start", "bedtime", "wake", "tummy_time", "diaper", "note"}

# A "nap" longer than this is assumed to be a missed wake log, not real sleep.
MAX_NAP_HOURS = 4
MAX_NIGHT_HOURS = 16

# Sensible 6-month-old defaults, used until the family has enough logged data.
DEFAULT_NAP_MIN = 60
DEFAULT_WAKE_WINDOW_MIN = 135
DEFAULT_FEED_INTERVAL_MIN = 180
DEFAULT_BEDTIME = time(19, 0)
DEFAULT_MORNING_WAKE = time(6, 30)

DEFAULT_SETTINGS = {
    "auto_reminders": True,
    "auto_wind_down": True,
    "auto_feed_prep": True,
    "nap_cap_minutes": 120,
    "routines": [],
}

# Dedupe tags for auto-set reminders (one pending reminder per tag per silo).
TAG_WIND_DOWN = "💤"
TAG_FEED_PREP = "🍼"


# --------------------------------------------------------------------------- #
# Family / event CRUD
# --------------------------------------------------------------------------- #


async def get_family_for_silo(session: AsyncSession, silo: str) -> HalFamily | None:
    stmt = (
        select(HalFamily)
        .join(HalFamilyMember, HalFamilyMember.family_id == HalFamily.id)
        .where(HalFamilyMember.silo == silo)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def create_family(
    session: AsyncSession,
    silo: str,
    baby_name: str,
    timezone_name: str = "America/New_York",
) -> HalFamily:
    family = HalFamily(
        name=baby_name,
        baby_name=baby_name,
        timezone=timezone_name,
        settings=dict(DEFAULT_SETTINGS),
        state={},
    )
    session.add(family)
    await session.flush()
    session.add(HalFamilyMember(family_id=family.id, silo=silo))
    await session.flush()
    log.info("baby.family_created", silo=silo, baby=baby_name)
    return family


async def add_event(
    session: AsyncSession,
    family: HalFamily,
    kind: str,
    event_at: datetime,
    logged_by: str | None,
    silo: str,
    note: str = "",
) -> HalBabyEvent:
    event = HalBabyEvent(
        family_id=family.id,
        kind=kind,
        event_at=event_at,
        logged_by=logged_by,
        silo=silo,
        note=note,
    )
    session.add(event)
    await session.flush()
    log.info("baby.event", family=str(family.id), kind=kind, at=str(event_at))
    return event


async def load_events(
    session: AsyncSession, family_id, since: datetime | None = None
) -> list[HalBabyEvent]:
    stmt = select(HalBabyEvent).where(HalBabyEvent.family_id == family_id)
    if since is not None:
        stmt = stmt.where(HalBabyEvent.event_at >= since)
    stmt = stmt.order_by(HalBabyEvent.event_at.asc())
    return list((await session.execute(stmt)).scalars().all())


async def delete_last_event(session: AsyncSession, family_id) -> HalBabyEvent | None:
    stmt = (
        select(HalBabyEvent)
        .where(HalBabyEvent.family_id == family_id)
        .order_by(HalBabyEvent.created_at.desc())
        .limit(1)
    )
    event = (await session.execute(stmt)).scalar_one_or_none()
    if event is not None:
        await session.delete(event)
        await session.flush()
    return event


# --------------------------------------------------------------------------- #
# Pure analytics (no DB) — operate on [(kind, aware-utc datetime), ...]
# --------------------------------------------------------------------------- #


@dataclass
class Sleep:
    start: datetime
    end: datetime | None  # None = still asleep
    is_night: bool

    @property
    def minutes(self) -> int | None:
        if self.end is None:
            return None
        return int((self.end - self.start).total_seconds() // 60)


def pair_sleeps(events: list[tuple[str, datetime]]) -> list[Sleep]:
    """Pair sleep-start events with the next wake. An unclosed sleep stays open
    only if it's the last one; earlier unclosed ones are dropped (missed log)."""
    sleeps: list[Sleep] = []
    open_sleep: Sleep | None = None
    for kind, at in events:
        if kind in SLEEP_STARTS:
            if open_sleep is not None:
                sleeps.append(open_sleep)  # missed wake; keep with end=None
            open_sleep = Sleep(start=at, end=None, is_night=(kind == "bedtime"))
        elif kind == "wake":
            if open_sleep is not None:
                cap = MAX_NIGHT_HOURS if open_sleep.is_night else MAX_NAP_HOURS
                if at - open_sleep.start <= timedelta(hours=cap):
                    open_sleep.end = at
                sleeps.append(open_sleep)
                open_sleep = None
    if open_sleep is not None:
        sleeps.append(open_sleep)
    # Drop unclosed sleeps except the final one (genuinely still asleep).
    closed = [s for s in sleeps[:-1] if s.end is not None]
    if sleeps:
        closed.append(sleeps[-1])
    return closed


def _local_date(at: datetime, tz: ZoneInfo) -> date:
    return at.astimezone(tz).date()


def summarize_day(
    events: list[tuple[str, datetime]], tz: ZoneInfo, d: date
) -> dict:
    """Summary of one local day: feeds, naps, bedtime, morning wake, night
    sleep that ENDED this morning (i.e. last night's stretch)."""
    sleeps = pair_sleeps(events)
    feeds = [at for kind, at in events if kind == "feed" and _local_date(at, tz) == d]
    naps = [
        s
        for s in sleeps
        if not s.is_night and _local_date(s.start, tz) == d
    ]
    bedtime = next(
        (s.start for s in sleeps if s.is_night and _local_date(s.start, tz) == d), None
    )
    last_night = next(
        (
            s
            for s in reversed(sleeps)
            if s.is_night and s.end is not None and _local_date(s.end, tz) == d
        ),
        None,
    )
    morning_wake = last_night.end if last_night else None
    night_minutes = last_night.minutes if last_night else None
    total_nap_min = sum(s.minutes or 0 for s in naps)
    return {
        "date": d,
        "feeds": feeds,
        "naps": naps,
        "bedtime": bedtime,
        "morning_wake": morning_wake,
        "night_minutes": night_minutes,
        "total_nap_minutes": total_nap_min,
    }


def _median_or_none(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def compute_patterns(
    events: list[tuple[str, datetime]], tz: ZoneInfo, now: datetime, days: int = 7
) -> dict:
    """Medians over the trailing `days` of data, falling back to age-generic
    defaults where the family hasn't logged enough yet."""
    cutoff = now - timedelta(days=days)
    recent = [(k, at) for k, at in events if at >= cutoff]
    sleeps = pair_sleeps(recent)

    nap_lengths = [s.minutes for s in sleeps if not s.is_night and s.minutes]
    night_lengths = [s.minutes for s in sleeps if s.is_night and s.minutes]

    # Wake windows: wake -> next sleep start, same local day, < 6h.
    wake_windows: list[float] = []
    last_wake: datetime | None = None
    for kind, at in recent:
        if kind == "wake":
            last_wake = at
        elif kind in SLEEP_STARTS and last_wake is not None:
            gap = (at - last_wake).total_seconds() / 60
            if 0 < gap <= 360:
                wake_windows.append(gap)
            last_wake = None

    # Feed intervals < 6h.
    feed_times = [at for k, at in recent if k == "feed"]
    feed_intervals = [
        (b - a).total_seconds() / 60
        for a, b in zip(feed_times, feed_times[1:])
        if timedelta(0) < (b - a) <= timedelta(hours=6)
    ]

    # Typical bedtime / morning wake as local minutes-past-midnight.
    bed_minutes = [
        s.start.astimezone(tz).hour * 60 + s.start.astimezone(tz).minute
        for s in sleeps
        if s.is_night
    ]
    morning_minutes = [
        s.end.astimezone(tz).hour * 60 + s.end.astimezone(tz).minute
        for s in sleeps
        if s.is_night and s.end is not None
    ]

    naps_by_day: dict[date, int] = {}
    for s in sleeps:
        if not s.is_night:
            naps_by_day.setdefault(_local_date(s.start, tz), 0)
            naps_by_day[_local_date(s.start, tz)] += 1

    return {
        "nap_minutes": _median_or_none(nap_lengths) or DEFAULT_NAP_MIN,
        "nap_samples": len(nap_lengths),
        "night_minutes": _median_or_none(night_lengths),
        "wake_window_minutes": _median_or_none(wake_windows) or DEFAULT_WAKE_WINDOW_MIN,
        "feed_interval_minutes": _median_or_none(feed_intervals) or DEFAULT_FEED_INTERVAL_MIN,
        "bedtime_minutes": _median_or_none([float(m) for m in bed_minutes]),
        "morning_wake_minutes": _median_or_none([float(m) for m in morning_minutes]),
        "naps_per_day": _median_or_none([float(n) for n in naps_by_day.values()]),
    }


def forecast_next(
    events: list[tuple[str, datetime]], tz: ZoneInfo, now: datetime
) -> dict:
    """Predict next wake / nap / feed / bedtime from the family's own recent
    pattern. Returns aware-utc datetimes (or None)."""
    patterns = compute_patterns(events, tz, now)
    sleeps = pair_sleeps(events)
    open_sleep = sleeps[-1] if sleeps and sleeps[-1].end is None else None

    last_feed = next((at for k, at in reversed(events) if k == "feed"), None)
    next_feed = (
        last_feed + timedelta(minutes=patterns["feed_interval_minutes"])
        if last_feed
        else None
    )

    expected_wake = None
    next_nap = None
    expected_bedtime = None

    local_now = now.astimezone(tz)
    bed_min = patterns["bedtime_minutes"]
    if bed_min is not None:
        bed_local = local_now.replace(
            hour=int(bed_min // 60), minute=int(bed_min % 60), second=0, microsecond=0
        )
    else:
        bed_local = local_now.replace(
            hour=DEFAULT_BEDTIME.hour, minute=DEFAULT_BEDTIME.minute, second=0, microsecond=0
        )
    if bed_local > local_now:
        expected_bedtime = bed_local.astimezone(timezone.utc)

    if open_sleep is not None:
        if open_sleep.is_night:
            wake_min = patterns["morning_wake_minutes"]
            wake_t = (
                time(int(wake_min // 60), int(wake_min % 60))
                if wake_min is not None
                else DEFAULT_MORNING_WAKE
            )
            tomorrow = (local_now + timedelta(days=1)).date()
            expected_wake = datetime.combine(tomorrow, wake_t, tzinfo=tz).astimezone(
                timezone.utc
            )
        else:
            expected_wake = open_sleep.start + timedelta(minutes=patterns["nap_minutes"])
    else:
        last_wake = next((at for k, at in reversed(events) if k == "wake"), None)
        if last_wake is not None:
            candidate = last_wake + timedelta(minutes=patterns["wake_window_minutes"])
            # A nap projected within ~1.5h of typical bedtime isn't realistic —
            # the next sleep is bedtime, not a nap.
            if expected_bedtime is not None and candidate >= expected_bedtime - timedelta(minutes=90):
                next_nap = None
            else:
                next_nap = candidate

    return {
        "state": (
            "night" if (open_sleep and open_sleep.is_night)
            else "napping" if open_sleep
            else "awake"
        ),
        "asleep_since": open_sleep.start if open_sleep else None,
        "expected_wake": expected_wake,
        "next_nap": next_nap,
        "next_feed": next_feed,
        "expected_bedtime": expected_bedtime,
        "patterns": patterns,
    }


def detect_regression(
    events: list[tuple[str, datetime]], tz: ZoneInfo, now: datetime
) -> list[str]:
    """Compare the last 3 days against the prior 7 — flag meaningful drops in
    sleep or rising night fragmentation. Returns human-readable flags."""
    flags: list[str] = []
    recent_cut = now - timedelta(days=3)
    base_cut = now - timedelta(days=10)
    base = [(k, at) for k, at in events if base_cut <= at < recent_cut]
    recent = [(k, at) for k, at in events if at >= recent_cut]
    if len(base) < 8 or len(recent) < 4:
        return flags  # not enough data to call anything a trend

    def daily_sleep(evts: list[tuple[str, datetime]], days: float) -> float:
        total = sum(
            s.minutes or 0 for s in pair_sleeps(evts) if s.minutes is not None
        )
        return total / max(days, 1)

    base_daily = daily_sleep(base, 7)
    recent_daily = daily_sleep(recent, 3)
    if base_daily > 0 and recent_daily < base_daily * 0.85:
        flags.append(
            f"total sleep down ~{int(round((1 - recent_daily / base_daily) * 100))}% "
            f"over the last 3 days vs the prior week"
        )

    def night_wakes(evts: list[tuple[str, datetime]]) -> int:
        n = 0
        for kind, at in evts:
            if kind == "wake":
                h = at.astimezone(tz).hour
                if h >= 21 or h < 5:
                    n += 1
        return n

    base_nw = night_wakes(base) / 7
    recent_nw = night_wakes(recent) / 3
    if recent_nw >= base_nw + 1:
        flags.append("night wake-ups are up vs the prior week")

    return flags


# --------------------------------------------------------------------------- #
# Auto-reminders (proactive, per standing family settings)
# --------------------------------------------------------------------------- #


async def _replace_tagged_reminder(
    session: AsyncSession,
    silo: str,
    tag: str,
    text: str,
    due_at: datetime,
    cancel_if: str | None = None,
) -> None:
    """One pending auto-reminder per tag per silo: replace any unsent one."""
    await session.execute(
        sa_delete(HalReminder).where(
            HalReminder.phone == silo,
            HalReminder.sent == False,  # noqa: E712
            HalReminder.text.startswith(tag),
        )
    )
    session.add(
        HalReminder(phone=silo, text=text, due_at=due_at, cancel_if=cancel_if)
    )
    await session.flush()


async def apply_auto_reminders(
    session: AsyncSession,
    family: HalFamily,
    kind: str,
    event_at: datetime,
    silo: str,
    forecast: dict,
    now: datetime,
) -> list[str]:
    """Set standing-preference reminders for a just-logged event. Returns
    human-readable descriptions of what was set (for the tool result)."""
    settings = {**DEFAULT_SETTINGS, **(family.settings or {})}
    if not settings.get("auto_reminders"):
        return []

    tz = ZoneInfo(family.timezone)
    baby = family.baby_name
    set_msgs: list[str] = []

    def fmt(at: datetime) -> str:
        return at.astimezone(tz).strftime("%-I:%M %p")

    # Event-triggered routines (e.g. tummy time 30 min after each feed).
    # Every auto-reminder carries a cancel_if so the fire-time model gate
    # ALWAYS re-judges it against live state — a routine without one fired
    # unconditionally, which is how "Tummy time" pinged the group minutes
    # after bedtime was logged. Relevance is the model's call, not a rule.
    for routine in settings.get("routines", []):
        if routine.get("after") != kind:
            continue
        due = event_at + timedelta(minutes=int(routine.get("offset_min", 30)))
        if due <= now:
            continue
        text = routine.get("text") or f"{baby} routine"
        cancel_if = (
            f"{baby} is asleep (napping or down for the night), or "
            f"'{text}' already happened, or anything logged/said since makes "
            f"this awake-time routine moot or unwanted right now"
        )
        await _replace_tagged_reminder(session, silo, text[:20], text, due, cancel_if)
        set_msgs.append(f"{text} at {fmt(due)}")

    # Wind-down ahead of the predicted next nap.
    if kind == "wake" and settings.get("auto_wind_down") and forecast.get("next_nap"):
        due = forecast["next_nap"] - timedelta(minutes=15)
        if due > now:
            text = (
                f"{TAG_WIND_DOWN} Start winding {baby} down — next nap looks "
                f"like ~{fmt(forecast['next_nap'])}"
            )
            cancel_if = (
                f"{baby} is already asleep (down for a nap or the night), or he "
                f"already woke again so the next nap is no longer ~{fmt(forecast['next_nap'])}"
            )
            await _replace_tagged_reminder(
                session, silo, TAG_WIND_DOWN, text, due, cancel_if
            )
            set_msgs.append(f"wind-down at {fmt(due)}")

    # Bottle prep ahead of the predicted next feed.
    if kind == "feed" and settings.get("auto_feed_prep") and forecast.get("next_feed"):
        due = forecast["next_feed"] - timedelta(minutes=15)
        if due > now:
            text = (
                f"{TAG_FEED_PREP} Bottle prep — {baby}'s next feed is "
                f"around {fmt(forecast['next_feed'])}"
            )
            cancel_if = (
                f"{baby} has already been fed since this was set, or the next "
                f"feed is no longer around {fmt(forecast['next_feed'])}"
            )
            await _replace_tagged_reminder(
                session, silo, TAG_FEED_PREP, text, due, cancel_if
            )
            set_msgs.append(f"bottle prep at {fmt(due)}")

    return set_msgs


# --------------------------------------------------------------------------- #
# Formatting (shared by the baby tool and the digest skill)
# --------------------------------------------------------------------------- #


def as_pairs(events: list[HalBabyEvent]) -> list[tuple[str, datetime]]:
    return [(e.kind, e.event_at) for e in events]


def fmt_time(at: datetime | None, tz: ZoneInfo) -> str:
    if at is None:
        return "?"
    return at.astimezone(tz).strftime("%-I:%M %p")


def fmt_duration(minutes: int | None) -> str:
    if minutes is None:
        return "ongoing"
    h, m = divmod(int(minutes), 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


def fmt_ago(at: datetime | None, now: datetime) -> str:
    """Relative time ('2m ago' / 'in 43m') computed in CODE, not by the model.
    Models reliably misdo clock arithmetic (a nap logged 2 minutes ago got
    narrated as 'about 2 hours ago'), so every clock time the baby tool emits
    carries this annotation and the prompt tells the model to quote it."""
    if at is None:
        return ""
    minutes = round((now - at).total_seconds() / 60)
    if abs(minutes) < 1:
        return "just now"
    word = "{} ago" if minutes > 0 else "in {}"
    return word.format(fmt_duration(abs(minutes)))


def format_day_summary(summary: dict, tz: ZoneInfo, baby: str) -> str:
    lines: list[str] = []
    if summary["morning_wake"]:
        line = f"Up at {fmt_time(summary['morning_wake'], tz)}"
        if summary["night_minutes"]:
            line += f" after {fmt_duration(summary['night_minutes'])} overnight"
        lines.append(line)
    naps = summary["naps"]
    if naps:
        nap_bits = ", ".join(
            f"{fmt_time(s.start, tz)} ({fmt_duration(s.minutes)})" for s in naps
        )
        lines.append(
            f"Naps: {len(naps)} — {nap_bits} (total {fmt_duration(summary['total_nap_minutes'])})"
        )
    else:
        lines.append("Naps: none logged")
    feeds = summary["feeds"]
    if feeds:
        lines.append(
            f"Feeds: {len(feeds)} — " + ", ".join(fmt_time(f, tz) for f in feeds)
        )
    else:
        lines.append("Feeds: none logged")
    if summary["bedtime"]:
        lines.append(f"Down for the night at {fmt_time(summary['bedtime'], tz)}")
    return "\n".join(lines)


def format_forecast(
    forecast: dict, tz: ZoneInfo, baby: str, now: datetime | None = None
) -> str:
    # Every clock time gets a code-computed relative ("2:33 PM — 2m ago") when
    # `now` is provided, so the model quotes relatives instead of doing clock
    # math itself (see fmt_ago).
    def _t(at) -> str:
        base = fmt_time(at, tz)
        rel = fmt_ago(at, now) if now is not None else ""
        return f"{base} — {rel}" if rel else base

    lines: list[str] = []
    state = forecast["state"]
    if state in ("napping", "night"):
        what = "down for the night" if state == "night" else "napping"
        lines.append(f"{baby} is {what} (since {_t(forecast['asleep_since'])})")
        if forecast["expected_wake"]:
            lines.append(f"Expected wake: ~{_t(forecast['expected_wake'])}")
    else:
        lines.append(f"{baby} is awake")
        if forecast["next_nap"]:
            lines.append(f"Next nap: ~{_t(forecast['next_nap'])}")
        elif forecast["expected_bedtime"]:
            lines.append(
                f"Next sleep is bedtime: ~{_t(forecast['expected_bedtime'])}"
            )
    if forecast["next_feed"]:
        lines.append(f"Next feed: ~{_t(forecast['next_feed'])}")
    if forecast["expected_bedtime"] and forecast["state"] != "night":
        lines.append(f"Bedtime: ~{_t(forecast['expected_bedtime'])}")
    p = forecast["patterns"]
    if p["nap_samples"] >= 3:
        lines.append(
            f"(based on his own last-7-day pattern: naps ~{fmt_duration(int(p['nap_minutes']))}, "
            f"wake windows ~{fmt_duration(int(p['wake_window_minutes']))}, "
            f"feeds every ~{fmt_duration(int(p['feed_interval_minutes']))})"
        )
    return "\n".join(lines)
