"""Render a baby status card (last/next feed + nap) to a PNG.

A visual "baby monitor" HAL can text back: current state, last & next feed,
last & next sleep, tonight's bedtime — all from the family's own logged events
and learned patterns (services/baby.py). Delivered as an iMessage image
attachment via ctx.result_images.

Pure rendering (Pillow) with a bundled DejaVu font so it works in the slim
Docker image. `build_card_data` turns the forecast into the display dict;
`render_card_png` draws it. Kept separate so the data shaping is unit-testable
without Pillow.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

_FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
_BOLD = str(_FONT_DIR / "DejaVuSans-Bold.ttf")
_REG = str(_FONT_DIR / "DejaVuSans.ttf")

# Minimal HAL palette: a white canvas, dark ink, and one brand accent.
CARD = (255, 255, 255)
INK = (25, 35, 31)
SUB = (105, 116, 110)
ACCENT = (28, 100, 76)
SOFT = (232, 241, 237)
LINE = (225, 231, 227)
EMOJI_YELLOW = (255, 205, 72)
EMOJI_INK = (91, 65, 35)
EMOJI_BLUE = (55, 112, 214)
W, H = 680, 760


def build_card_data(forecast: dict, last_feed, last_nap_end, baby: str, tz, now: datetime) -> dict:
    """Shape the baby forecast into the card's display fields (time strings in
    tz). Pure — no Pillow. `forecast` is services.baby.forecast_next output."""
    from hal_orchestrator.services.baby import fmt_time

    def t(x):
        return fmt_time(x, tz) if x else None

    return {
        "baby": baby,
        "now": t(now),
        "state": forecast.get("state", "awake"),
        "asleep_since": t(forecast.get("asleep_since")),
        "last_feed": t(last_feed),
        "next_feed": t(forecast.get("next_feed")),
        "expected_wake": t(forecast.get("expected_wake")),
        "next_nap": t(forecast.get("next_nap")),
        "last_nap_end": t(last_nap_end),
        "expected_bedtime": t(forecast.get("expected_bedtime")),
    }


def _parse(s: str | None):
    try:
        return datetime.strptime(s, "%I:%M %p")
    except (TypeError, ValueError):
        return None


def _clock_past(now_str: str | None, s: str | None) -> bool:
    """True when clock time `s` reads as already-passed relative to `now_str`.

    Clock strings carry no date, so they wrap: a reading more than 12h "ago"
    means the time is actually TOMORROW — a 6:30 AM expected wake rendered at
    7:40 PM must NOT collapse to "Soon", and a 2:30 AM next feed rendered at
    11:50 PM must NOT flip to "FEED DUE". PURE."""
    now_dt, d = _parse(now_str), _parse(s)
    if not (now_dt and d):
        return False
    delta_min = (now_dt - d).total_seconds() / 60
    return 0 < delta_min <= 12 * 60


# Shared drawing helpers — both cards use the same restrained frame and type.


def _fnt(path, sz):
    from PIL import ImageFont

    return ImageFont.truetype(path, sz)


def _card_canvas(w: int, h: int):
    """Pure white attachment canvas. Returns image + draw."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (w, h), CARD)
    d = ImageDraw.Draw(img)
    return img, d


def _status_emoji(d, cx: int, cy: int, sleeping: bool) -> None:
    """Draw a compact emoji that works without a color-emoji system font.
    Vector-drawn with PIL primitives on purpose: the slim image's
    Pillow/DejaVu stack can't rasterize color-emoji fonts, and Apple's emoji
    font isn't redistributable — this needs no assets at all."""
    r = 18
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=EMOJI_YELLOW)
    if sleeping:
        d.line([(cx - 11, cy - 1), (cx - 5, cy - 1)], fill=EMOJI_INK, width=3)
        d.line([(cx + 4, cy - 1), (cx + 10, cy - 1)], fill=EMOJI_INK, width=3)
        d.ellipse([cx - 3, cy + 6, cx + 3, cy + 12], fill=EMOJI_INK)
        d.text(
            (cx + 10, cy - 29), "Z", font=_fnt(_BOLD, 16), fill=EMOJI_BLUE
        )
    else:
        d.ellipse([cx - 9, cy - 6, cx - 5, cy - 2], fill=EMOJI_INK)
        d.ellipse([cx + 5, cy - 6, cx + 9, cy - 2], fill=EMOJI_INK)
        d.arc(
            [cx - 10, cy - 1, cx + 10, cy + 12],
            start=12, end=168, fill=EMOJI_INK, width=3,
        )


def render_card_png(data: dict) -> bytes:
    """Draw a minimal, glanceable current-status card. Returns PNG bytes."""

    def fnt(path, sz):
        return _fnt(path, sz)

    def is_past(s):
        return _clock_past(data.get("now"), s)

    img, d = _card_canvas(W, H)
    x0, x1 = 66, W - 66

    # Quiet product label, then the baby's name and timestamp.
    d.text((x0, 58), "HAL · BABY STATUS", font=fnt(_BOLD, 18), fill=ACCENT)
    d.text((x0, 91), data["baby"], font=fnt(_BOLD, 50), fill=INK)
    d.text(
        (x1, 111), f"AS OF {data['now']}",
        font=fnt(_BOLD, 17), fill=SUB, anchor="ra",
    )
    d.line([(x0, 166), (x1, 166)], fill=LINE, width=2)

    state = data.get("state", "awake")
    sleeping = state in ("napping", "night")
    state_label = {
        "napping": "Napping",
        "night": "Down for the night",
        "awake": "Awake",
    }.get(state, "Awake")
    state_detail = (
        f"Since {data['asleep_since']}" if sleeping and data.get("asleep_since")
        else "In the wake window"
    )
    _status_emoji(d, x0 + 18, 216, sleeping)
    d.text((x0 + 58, 194), state_label, font=fnt(_BOLD, 39), fill=INK)
    d.text((x0 + 58, 244), state_detail, font=fnt(_REG, 22), fill=SUB)

    # Put the most actionable sleep transition in one clear focal block.
    if sleeping:
        next_label = "EXPECTED WAKE"
        next_value = data.get("expected_wake")
        if not next_value or is_past(next_value):
            next_value = "Soon"
    else:
        next_label = "NEXT NAP"
        next_value = data.get("next_nap") or "No estimate yet"
    fy = 302
    d.rounded_rectangle([x0, fy, x1, fy + 116], 24, fill=SOFT)
    d.text((x0 + 26, fy + 21), next_label, font=fnt(_BOLD, 17), fill=ACCENT)
    d.text((x0 + 26, fy + 51), next_value, font=fnt(_BOLD, 36), fill=INK)

    # Secondary timing details sit in a simple two-by-two grid.
    mid = 340
    grid_y = 470
    d.line([(mid, grid_y), (mid, grid_y + 168)], fill=LINE, width=2)
    d.line([(x0, grid_y + 84), (x1, grid_y + 84)], fill=LINE, width=2)

    def metric(x, y, label, value, accent=False):
        d.text((x, y), label, font=fnt(_BOLD, 16), fill=SUB)
        d.text(
            (x, y + 28), value or "—", font=fnt(_BOLD, 29),
            fill=ACCENT if accent else INK,
        )

    feed_label = "FEED DUE" if is_past(data.get("next_feed")) else "NEXT FEED"
    metric(x0, grid_y, "LAST FEED", data.get("last_feed"))
    metric(mid + 28, grid_y, feed_label, data.get("next_feed"), accent=True)
    sleep_label = "SLEEP START" if sleeping else "LAST WAKE"
    sleep_value = data.get("asleep_since") if sleeping else data.get("last_nap_end")
    metric(x0, grid_y + 102, sleep_label, sleep_value)
    metric(mid + 28, grid_y + 102, "BEDTIME", data.get("expected_bedtime"))

    d.text(
        (x0, H - 64), f"Based on {data['baby']}’s recent rhythm",
        font=fnt(_REG, 18), fill=SUB,
    )

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def build_day_summary_data(summary: dict, baby: str, tz, now: datetime) -> dict:
    """Shape services.baby.summarize_day output into the day card's display
    fields (time strings in tz). Pure — no Pillow."""
    from hal_orchestrator.services.baby import fmt_duration, fmt_time

    day = summary.get("date") or now.astimezone(tz).date()
    naps = [
        {"start": fmt_time(s.start, tz), "duration": fmt_duration(s.minutes)}
        for s in summary.get("naps") or []
    ]
    feeds = [fmt_time(at, tz) for at in summary.get("feeds") or []]
    return {
        "baby": baby,
        "date_label": day.strftime("%A, %B %-d"),
        "morning_wake": (
            fmt_time(summary["morning_wake"], tz) if summary.get("morning_wake") else None
        ),
        "night_duration": (
            fmt_duration(summary["night_minutes"]) if summary.get("night_minutes") else None
        ),
        "naps": naps,
        "total_nap": fmt_duration(summary.get("total_nap_minutes") or 0) if naps else None,
        "feeds": feeds,
        "feed_count": len(feeds),
        "bedtime": fmt_time(summary["bedtime"], tz) if summary.get("bedtime") else None,
    }


def render_day_summary_png(data: dict) -> bytes:
    """Draw a minimal whole-day recap with sleep as a simple timeline."""
    naps = data.get("naps") or []
    feeds = data.get("feeds") or []
    feed_lines = max(1, (len(feeds) + 2) // 3)

    # The canvas grows only as the plain-text timelines grow.
    naps_start = 504
    naps_rows_h = max(1, len(naps)) * 48
    feeds_top = naps_start + naps_rows_h + 34
    feeds_items = feeds_top + 68
    feeds_rows_h = feed_lines * 46
    bedtime_top = feeds_items + feeds_rows_h + 24
    h = bedtime_top + 110
    img, d = _card_canvas(W, h)
    x0, x1 = 66, W - 66

    d.text((x0, 58), "HAL · DAILY RECAP", font=_fnt(_BOLD, 18), fill=ACCENT)
    d.text((x0, 91), f"{data['baby']}’s day", font=_fnt(_BOLD, 50), fill=INK)
    d.text(
        (x0, 151), data["date_label"], font=_fnt(_REG, 22), fill=SUB,
    )
    d.line([(x0, 194), (x1, 194)], fill=LINE, width=2)

    # Three top-line facts replace the previous stack of summary panels.
    col_w = (x1 - x0) / 3
    stats = [
        ("OVERNIGHT", data.get("night_duration") or "—"),
        ("NAPS", str(len(naps))),
        ("FEEDS", str(data.get("feed_count") or 0)),
    ]
    for i, (label, value) in enumerate(stats):
        x = int(x0 + i * col_w)
        if i:
            d.line([(x - 18, 225), (x - 18, 298)], fill=LINE, width=2)
        d.text((x, 225), label, font=_fnt(_BOLD, 16), fill=SUB)
        d.text((x, 255), value, font=_fnt(_BOLD, 34), fill=INK)
    d.line([(x0, 320), (x1, 320)], fill=LINE, width=2)

    # Sleep timeline: wake first, then each nap with its duration.
    d.text((x0, 355), "SLEEP", font=_fnt(_BOLD, 18), fill=ACCENT)
    d.text((x0, 397), "Morning wake", font=_fnt(_REG, 21), fill=SUB)
    d.text(
        (x1, 393), data.get("morning_wake") or "—",
        font=_fnt(_BOLD, 29), fill=INK, anchor="ra",
    )
    d.text((x0, 457), "NAPS", font=_fnt(_BOLD, 16), fill=SUB)
    if data.get("total_nap"):
        d.text(
            (x1, 457), f"{data['total_nap']} TOTAL",
            font=_fnt(_BOLD, 16), fill=ACCENT, anchor="ra",
        )
    ly = naps_start
    if naps:
        for i, nap in enumerate(naps, start=1):
            d.text((x0, ly), f"Nap {i}", font=_fnt(_REG, 20), fill=SUB)
            d.text((x0 + 112, ly - 3), nap["start"], font=_fnt(_BOLD, 27), fill=INK)
            d.text((x1, ly - 3), nap["duration"], font=_fnt(_BOLD, 27), fill=ACCENT, anchor="ra")
            ly += 48
    else:
        d.text((x0, ly), "No naps logged", font=_fnt(_REG, 21), fill=SUB)

    # Feed times are a compact three-column list.
    d.line([(x0, feeds_top), (x1, feeds_top)], fill=LINE, width=2)
    d.text((x0, feeds_top + 27), "FEEDS", font=_fnt(_BOLD, 18), fill=ACCENT)
    if feeds:
        col_x = (x0, x0 + 184, x0 + 368)
        for i, t in enumerate(feeds):
            row = i // 3
            d.text(
                (col_x[i % 3], feeds_items + row * 46),
                t, font=_fnt(_BOLD, 26), fill=INK,
            )
    else:
        d.text((x0, feeds_items), "No feeds logged", font=_fnt(_REG, 21), fill=SUB)

    # One clean closing line for bedtime.
    d.line([(x0, bedtime_top), (x1, bedtime_top)], fill=LINE, width=2)
    d.text((x0, bedtime_top + 34), "BEDTIME", font=_fnt(_BOLD, 17), fill=SUB)
    d.text(
        (x1, bedtime_top + 27), data.get("bedtime") or "—",
        font=_fnt(_BOLD, 31), fill=INK, anchor="ra",
    )

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# Legacy hosted-URL delivery. New replies attach the rendered PNG directly via
# ctx.result_images. Keep signed URLs working for previously sent messages and
# other callers of the public card route. The `t` timestamp cache-busts renders.
# --------------------------------------------------------------------------- #


def _sign(silo: str, expires: int, secret: str) -> str:
    payload = f"hal-card-v1\n{silo}\n{expires}".encode()
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()[:32]


def card_url(
    base_url: str, silo: str, secret: str, ttl_seconds: int = 15 * 60
) -> str:
    s = base64.urlsafe_b64encode(silo.encode()).decode().rstrip("=")
    now = int(time.time())
    expires = now + max(60, ttl_seconds)
    sig = _sign(silo, expires, secret)
    return f"{base_url.rstrip('/')}/card.png?s={s}&e={expires}&sig={sig}&t={now}"


def verify_card_token(s: str, sig: str, expires: int, secret: str) -> str | None:
    """Return the silo if the signature is valid, else None. Prevents anyone
    from rendering an arbitrary silo's card by guessing the URL."""
    try:
        if expires < int(time.time()):
            return None
        pad = "=" * (-len(s) % 4)
        silo = base64.urlsafe_b64decode(s + pad).decode()
    except Exception:
        return None
    expected = _sign(silo, expires, secret)
    return silo if hmac.compare_digest(expected, sig or "") else None


async def render_for_silo(session, silo: str) -> bytes | None:
    """Compute the forecast for a family silo and render its card. None if the
    silo has no family / no events."""
    from hal_orchestrator.services.baby import (
        as_pairs,
        forecast_next,
        get_family_for_silo,
        load_events,
        pair_sleeps,
    )
    family = await get_family_for_silo(session, silo)
    if family is None:
        return None
    tz = ZoneInfo(family.timezone)
    now = datetime.now(UTC)
    events = as_pairs(await load_events(session, family.id, since=now - timedelta(days=2)))
    if not events:
        return None
    forecast = forecast_next(events, tz, now, birthdate=family.baby_birthdate)
    last_feed = next((at for k, at in reversed(events) if k == "feed"), None)
    sleeps = pair_sleeps(events)
    last_nap = next((s for s in reversed(sleeps) if s.end is not None and not s.is_night), None)
    data = build_card_data(
        forecast, last_feed, last_nap.end if last_nap else None,
        family.baby_name, tz, now,
    )
    return render_card_png(data)
