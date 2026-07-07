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


def render_card_png(data: dict) -> bytes:
    """Draw the card. Returns PNG bytes."""
    from PIL import Image, ImageDraw, ImageFont

    def fnt(path, sz):
        return ImageFont.truetype(path, sz)

    now_dt = _parse(data.get("now"))

    def is_past(s):
        d = _parse(s)
        return bool(d and now_dt and d < now_dt)

    img = Image.new("RGB", (W, H), BG_TOP)
    dr = ImageDraw.Draw(img)
    for y in range(H):
        f = y / H
        dr.line([(0, y), (W, y)], fill=(
            int(BG_TOP[0] + (250 - BG_TOP[0]) * f),
            int(BG_TOP[1] + (248 - BG_TOP[1]) * f),
            int(BG_TOP[2] + (255 - BG_TOP[2]) * f)))
    M = 36
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([M + 6, M + 14, W - M + 6, H - M + 14], 44, fill=(90, 78, 120, 55))
    img = Image.alpha_composite(img.convert("RGBA"), sh).convert("RGB")
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([M, M, W - M, H - M], 44, fill=CARD)
    cx0, cx1 = M + 44, W - M - 44

    def bottle(cx, cy, c, s=1.15):
        w = int(15 * s)
        d.rounded_rectangle([cx - w, cy - 2, cx + w, cy + int(38 * s)], int(9 * s), fill=c)
        d.rounded_rectangle([cx - int(8 * s), cy - int(14 * s), cx + int(8 * s), cy + 2], int(4 * s), fill=c)
        d.rounded_rectangle([cx - int(5 * s), cy - int(24 * s), cx + int(5 * s), cy - int(12 * s)], int(3 * s), fill=c)
        d.line([(cx - w + 3, cy + int(12 * s)), (cx + w - 3, cy + int(12 * s))], fill=CARD, width=3)
        d.line([(cx - w + 3, cy + int(22 * s)), (cx + w - 3, cy + int(22 * s))], fill=CARD, width=3)

    def moon(cx, cy, c, r=24):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c)
        d.ellipse([cx - r + int(r * 0.55), cy - r - 2, cx + r + int(r * 0.55), cy + r - 2], fill=CARD)

    def sun(cx, cy, c, r=16):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c)
        for a in range(0, 360, 45):
            dx, dy = math.cos(math.radians(a)), math.sin(math.radians(a))
            d.line([(cx + dx * (r + 5), cy + dy * (r + 5)), (cx + dx * (r + 12), cy + dy * (r + 12))], fill=c, width=5)

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


# --------------------------------------------------------------------------- #
# Hosted-URL delivery. The live iMessage send path is text-only (it drives a
# phone; it can't attach a file), so the card is also served at a public,
# HMAC-signed URL that HAL drops into the reply — iMessage renders it inline.
# The `t` (timestamp) cache-busts so each send fetches a fresh render instead
# of iMessage reusing a cached preview for the same URL.
# --------------------------------------------------------------------------- #


def _sign(silo: str, secret: str) -> str:
    return hmac.new(secret.encode(), silo.encode(), hashlib.sha256).hexdigest()[:32]


def card_url(base_url: str, silo: str, secret: str) -> str:
    s = base64.urlsafe_b64encode(silo.encode()).decode().rstrip("=")
    return f"{base_url.rstrip('/')}/card.png?s={s}&sig={_sign(silo, secret)}&t={int(time.time())}"


def verify_card_token(s: str, sig: str, secret: str) -> str | None:
    """Return the silo if the signature is valid, else None. Prevents anyone
    from rendering an arbitrary silo's card by guessing the URL."""
    try:
        pad = "=" * (-len(s) % 4)
        silo = base64.urlsafe_b64decode(s + pad).decode()
    except Exception:
        return None
    return silo if hmac.compare_digest(_sign(silo, secret), sig or "") else None


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
