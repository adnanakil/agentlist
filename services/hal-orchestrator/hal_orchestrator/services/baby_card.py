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
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

_FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
_BOLD = str(_FONT_DIR / "DejaVuSans-Bold.ttf")
_REG = str(_FONT_DIR / "DejaVuSans.ttf")

# palette
BG_TOP = (255, 241, 230); CARD = (255, 255, 255); INK = (44, 42, 56)
SUB = (150, 147, 163); FEED = (38, 150, 168); SLEEP = (114, 103, 214)
NIGHT = (72, 76, 120); CHIP = (245, 242, 251); LINE = (236, 233, 243)
ROW_BG = (252, 251, 254)
W, H = 680, 880


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


# Shared drawing helpers — both the status card and the day-summary card use
# the same canvas frame and icon set so they read as one family of cards.


def _fnt(path, sz):
    from PIL import ImageFont

    return ImageFont.truetype(path, sz)


def _card_canvas(w: int, h: int):
    """Gradient background + drop shadow + white rounded card. Returns draw."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (w, h), BG_TOP)
    dr = ImageDraw.Draw(img)
    for y in range(h):
        f = y / h
        dr.line([(0, y), (w, y)], fill=(
            int(BG_TOP[0] + (250 - BG_TOP[0]) * f),
            int(BG_TOP[1] + (248 - BG_TOP[1]) * f),
            int(BG_TOP[2] + (255 - BG_TOP[2]) * f)))
    m = 36
    sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle(
        [m + 6, m + 14, w - m + 6, h - m + 14], 44, fill=(90, 78, 120, 55)
    )
    img = Image.alpha_composite(img.convert("RGBA"), sh).convert("RGB")
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([m, m, w - m, h - m], 44, fill=CARD)
    return img, d


def _bottle(d, cx, cy, c, s=1.15):
    w = int(15 * s)
    d.rounded_rectangle([cx - w, cy - 2, cx + w, cy + int(38 * s)], int(9 * s), fill=c)
    d.rounded_rectangle([cx - int(8 * s), cy - int(14 * s), cx + int(8 * s), cy + 2], int(4 * s), fill=c)
    d.rounded_rectangle([cx - int(5 * s), cy - int(24 * s), cx + int(5 * s), cy - int(12 * s)], int(3 * s), fill=c)
    d.line([(cx - w + 3, cy + int(12 * s)), (cx + w - 3, cy + int(12 * s))], fill=CARD, width=3)
    d.line([(cx - w + 3, cy + int(22 * s)), (cx + w - 3, cy + int(22 * s))], fill=CARD, width=3)


def _moon(d, cx, cy, c, r=24):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c)
    d.ellipse([cx - r + int(r * 0.55), cy - r - 2, cx + r + int(r * 0.55), cy + r - 2], fill=CARD)


def _sun(d, cx, cy, c, r=16):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c)
    for a in range(0, 360, 45):
        dx, dy = math.cos(math.radians(a)), math.sin(math.radians(a))
        d.line([(cx + dx * (r + 5), cy + dy * (r + 5)), (cx + dx * (r + 12), cy + dy * (r + 12))], fill=c, width=5)


def render_card_png(data: dict) -> bytes:
    """Draw the card. Returns PNG bytes."""

    def fnt(path, sz):
        return _fnt(path, sz)

    now_dt = _parse(data.get("now"))

    def is_past(s):
        d = _parse(s)
        return bool(d and now_dt and d < now_dt)

    img, d = _card_canvas(W, H)
    M = 36
    cx0, cx1 = M + 44, W - M - 44

    def bottle(cx, cy, c, s=1.15):
        _bottle(d, cx, cy, c, s)

    def moon(cx, cy, c, r=24):
        _moon(d, cx, cy, c, r)

    def sun(cx, cy, c, r=16):
        _sun(d, cx, cy, c, r)

    d.text((cx0, M + 42), data["baby"], font=fnt(_BOLD, 58), fill=INK)
    d.text((cx0, M + 116), f"baby monitor · as of {data['now']}", font=fnt(_REG, 25), fill=SUB)

    state = data["state"]
    hy = M + 178
    col = {"napping": SLEEP, "night": NIGHT, "awake": FEED}.get(state, FEED)
    d.rounded_rectangle([cx0, hy, cx1, hy + 100], 28, fill=CHIP)
    if state in ("napping", "night"):
        moon(cx0 + 52, hy + 50, col, r=26)
    else:
        sun(cx0 + 52, hy + 50, col, r=17)
    label = {"napping": "Napping", "night": "Down for the night", "awake": "Awake"}.get(state, "Awake")
    hs = f"since {data['asleep_since']}" if state in ("napping", "night") and data.get("asleep_since") else "in the wake window"
    d.text((cx0 + 112, hy + 22), label, font=fnt(_BOLD, 34), fill=INK)
    d.text((cx0 + 112, hy + 66), hs, font=fnt(_REG, 24), fill=SUB)

    def row(y, icon, c, title, last_lbl, last_v, next_lbl, next_v, dim=False):
        d.rounded_rectangle([cx0, y, cx1, y + 156], 28, fill=ROW_BG, outline=LINE, width=2)
        if icon == "bottle":
            bottle(cx0 + 52, y + 62, c)
        else:
            moon(cx0 + 52, y + 62, c, r=24)
        d.text((cx0 + 104, y + 26), title, font=fnt(_BOLD, 30), fill=INK)
        d.text((cx0 + 104, y + 80), last_lbl, font=fnt(_REG, 20), fill=SUB)
        d.text((cx0 + 104, y + 106), last_v or "—", font=fnt(_BOLD, 29), fill=INK)
        nc = SUB if dim else c
        d.text((cx1 - 22, y + 80), next_lbl, font=fnt(_REG, 20), fill=nc, anchor="ra")
        d.text((cx1 - 22, y + 106), next_v or "—", font=fnt(_BOLD, 29), fill=nc, anchor="ra")

    fy = hy + 124
    feed_lbl = "Feed due" if is_past(data.get("next_feed")) else "Next feed"
    row(fy, "bottle", FEED, "Feeds", "Last fed", data["last_feed"], feed_lbl, data["next_feed"])

    sy = fy + 176
    if state in ("napping", "night"):
        wv = data.get("expected_wake")
        if not wv or is_past(wv):
            row(sy, "moon", SLEEP, "Sleep", "Down at", data.get("asleep_since"), "Waking", "soon", dim=True)
        else:
            row(sy, "moon", SLEEP, "Sleep", "Down at", data.get("asleep_since"), "Wake ~", wv)
    else:
        row(sy, "moon", SLEEP, "Sleep", "Last woke", data.get("last_nap_end"), "Next nap", data.get("next_nap"))

    gy = sy + 180
    d.line([(cx0, gy), (cx1, gy)], fill=LINE, width=2)
    moon(cx0 + 18, gy + 34, NIGHT, r=15)
    d.text((cx0 + 48, gy + 16), f"Bedtime tonight ~ {data.get('expected_bedtime') or '—'}", font=fnt(_BOLD, 27), fill=NIGHT)

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
    """Draw the whole-day recap card. Height grows with the number of naps and
    feeds logged; same visual language as the status card."""
    naps = data.get("naps") or []
    feeds = data.get("feeds") or []
    # Feed times flow in a 2-column grid to keep long days compact.
    feed_lines = max(1, (len(feeds) + 1) // 2)

    M = 36
    gap = 20
    wake_h = 156
    naps_h = 88 + max(1, len(naps)) * 46 + 18
    feeds_h = 88 + feed_lines * 46 + 18
    footer_h = 96
    h = M + 178 + wake_h + gap + naps_h + gap + feeds_h + 24 + footer_h + M

    img, d = _card_canvas(W, h)
    cx0, cx1 = M + 44, W - M - 44

    d.text((cx0, M + 42), data["baby"], font=_fnt(_BOLD, 58), fill=INK)
    d.text(
        (cx0, M + 116),
        f"today's recap · {data['date_label']}",
        font=_fnt(_REG, 25), fill=SUB,
    )

    # Morning — wake time + last night's stretch
    y = M + 178
    d.rounded_rectangle([cx0, y, cx1, y + wake_h], 28, fill=ROW_BG, outline=LINE, width=2)
    _sun(d, cx0 + 52, y + 62, FEED, r=17)
    d.text((cx0 + 104, y + 26), "Morning", font=_fnt(_BOLD, 30), fill=INK)
    d.text((cx0 + 104, y + 80), "Woke up", font=_fnt(_REG, 20), fill=SUB)
    d.text((cx0 + 104, y + 106), data.get("morning_wake") or "—", font=_fnt(_BOLD, 29), fill=INK)
    d.text((cx1 - 22, y + 80), "Overnight", font=_fnt(_REG, 20), fill=NIGHT, anchor="ra")
    d.text(
        (cx1 - 22, y + 106), data.get("night_duration") or "—",
        font=_fnt(_BOLD, 29), fill=NIGHT, anchor="ra",
    )

    # Naps — one line per nap: start time left, duration right
    y += wake_h + gap
    d.rounded_rectangle([cx0, y, cx1, y + naps_h], 28, fill=ROW_BG, outline=LINE, width=2)
    _moon(d, cx0 + 52, y + 56, SLEEP, r=24)
    title = f"Naps · {len(naps)}" if naps else "Naps"
    d.text((cx0 + 104, y + 30), title, font=_fnt(_BOLD, 30), fill=INK)
    if data.get("total_nap"):
        d.text(
            (cx1 - 22, y + 38), f"total {data['total_nap']}",
            font=_fnt(_REG, 22), fill=SLEEP, anchor="ra",
        )
    ly = y + 88
    if naps:
        for nap in naps:
            d.text((cx0 + 104, ly), nap["start"], font=_fnt(_BOLD, 29), fill=INK)
            d.text((cx1 - 22, ly), nap["duration"], font=_fnt(_BOLD, 29), fill=SLEEP, anchor="ra")
            ly += 46
    else:
        d.text((cx0 + 104, ly), "—", font=_fnt(_BOLD, 29), fill=SUB)

    # Feeds — 2-column grid of times
    y += naps_h + gap
    d.rounded_rectangle([cx0, y, cx1, y + feeds_h], 28, fill=ROW_BG, outline=LINE, width=2)
    _bottle(d, cx0 + 52, y + 44, FEED)
    title = f"Feeds · {data.get('feed_count') or 0}" if feeds else "Feeds"
    d.text((cx0 + 104, y + 30), title, font=_fnt(_BOLD, 30), fill=INK)
    ly = y + 88
    if feeds:
        col_x = (cx0 + 104, cx0 + 104 + 210)
        for i, t in enumerate(feeds):
            d.text((col_x[i % 2], ly), t, font=_fnt(_BOLD, 29), fill=INK)
            if i % 2 == 1:
                ly += 46
    else:
        d.text((cx0 + 104, ly), "—", font=_fnt(_BOLD, 29), fill=SUB)

    # Bedtime footer
    y += feeds_h + 24
    d.line([(cx0, y), (cx1, y)], fill=LINE, width=2)
    _moon(d, cx0 + 18, y + 34, NIGHT, r=15)
    d.text(
        (cx0 + 48, y + 16),
        f"Bedtime ~ {data.get('bedtime') or '—'}",
        font=_fnt(_BOLD, 27), fill=NIGHT,
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
        as_pairs, forecast_next, get_family_for_silo, load_events, pair_sleeps,
    )
    from datetime import timedelta

    family = await get_family_for_silo(session, silo)
    if family is None:
        return None
    tz = ZoneInfo(family.timezone)
    now = datetime.now(timezone.utc)
    events = as_pairs(await load_events(session, family.id, since=now - timedelta(days=2)))
    if not events:
        return None
    forecast = forecast_next(events, tz, now)
    last_feed = next((at for k, at in reversed(events) if k == "feed"), None)
    sleeps = pair_sleeps(events)
    last_nap = next((s for s in reversed(sleeps) if s.end is not None and not s.is_night), None)
    data = build_card_data(
        forecast, last_feed, last_nap.end if last_nap else None,
        family.baby_name, tz, now,
    )
    return render_card_png(data)
