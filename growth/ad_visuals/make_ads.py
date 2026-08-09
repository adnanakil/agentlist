"""Render iMessage-style ad creatives for HAL.

Reuses the bubble/phone CSS from the texthal.com landing page
(`hal_orchestrator/routes/landing.py`) so ad creative and site stay visually
identical. Conversations below are the ones already shipped on the landing
page — per growth/CLAUDE.md, ad copy shows only what HAL actually does.

Phone geometry is fixed, not content-driven: the screen is always a true
iPhone 19.5:9 (2556x1179), so every creative shows the same device at the same
ratio. Messages are bottom-anchored inside that fixed screen the way a real
chat sits above the input bar; a conversation longer than the screen scrolls
off the top rather than stretching the phone.

Usage:
    uv run --with playwright python growth/ad_visuals/make_ads.py
    uv run --with playwright python growth/ad_visuals/make_ads.py --only handoff --format portrait

Output: growth/ad_visuals/out/<slug>-<format>.png
"""

from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = pathlib.Path(__file__).resolve().parent / "out"
sys.path.insert(0, str(ROOT / "services" / "hal-orchestrator"))

from hal_orchestrator.routes.logo_data import LOGO_DATA_URI  # noqa: E402

# True iPhone display ratio (2556 / 1179). Constant for every render.
SCREEN_RATIO = 2556 / 1179

# Meta placements: (canvas w, canvas h, screen height as fraction of canvas,
# headline scale). Only these are tuned per format — the phone's ratio never
# changes. 1:1 gets a smaller headline so the device still reads at feed size.
FORMATS = {
    "square": (1080, 1080, 0.650, 1.16),
    "portrait": (1080, 1350, 0.620, 1.48),
    "story": (1080, 1920, 0.560, 1.62),
}

# In-phone type is sized relative to the landing page's 330px-wide phone.
BASE_PHONE_W = 330.0
# The landing page sizes bubbles for a 330px thumbnail. In a feed ad the phone
# is the whole subject, so type is scaled up: it fills the fixed-height screen
# (less dead space above a short thread) and stays legible at mobile feed size.
TYPE_BOOST = 1.22

# Pastel phone-wrap backgrounds, straight from the landing page story cards.
BACKDROPS = ["#f5dfe6", "#dfe9f7", "#e6e0f2"]

# (speaker | None for outgoing, text). None => blue right-aligned bubble.
ADS = [
    {
        "slug": "handoff",
        "headline": "Everyone texts.\nHAL remembers.",
        "sub": "The baby log that lives in your family group chat.",
        "time": "3:15",
        "stamp": "Today 3:15 PM",
        "msgs": [
            ("Mom", "4oz at 3:15"),
            ("HAL", "Logged ✅ That's his 4th feed today."),
            (None, "down for a nap 😴"),
            ("HAL", "Logged 💤 He'll likely wake around 5:15 — I'll size his next window when he's up."),
            ("Grandma", "how's his day going?"),
            ("HAL", "3 naps, 5 feeds — last at 3:15. Bedtime's usually around 7:15 💛"),
        ],
    },
    {
        "slug": "recap",
        "headline": "The recap is\nalready done.",
        "sub": "Ask where the day stands. Get the whole picture.",
        "time": "6:42",
        "stamp": "Today 6:42 PM",
        "msgs": [
            ("HAL", "Leo's day at a glance 💛\n5 feeds — last at 6:10 PM\n3 naps · 2h 40m\nLast woke · 4:52 PM"),
            ("HAL", "Bedtime's usually ~7:15. He ran a little light on naps today, so a touch earlier may go down easy."),
            (None, "anything we should watch tonight?"),
            ("HAL", "Nothing unusual in today's log. He'll likely want one more feed near bedtime."),
            (None, "perfect, thank you"),
        ],
    },
    {
        "slug": "morning",
        "headline": "The day comes\nto you.",
        "sub": "Appointments, weather and traffic — before the morning gets noisy.",
        "time": "7:02",
        "stamp": "Today 7:02 AM",
        "msgs": [
            ("HAL", "Good morning ☀️ A few things for today:\n💉 Leo's 6-month vaccines are at 9:20 AM.\n🌧️ Rain is expected from 8–11 AM. Bring the stroller cover.\n🚗 The drive is trending 12 minutes slower. Leave by 8:35."),
            (None, "remind everyone when it's time to leave"),
            ("HAL", "You got it — I'll text the group at 8:30 👍"),
        ],
    },
]

AVATARS = [("M", "#ec6ba8"), ("D", "#5b9cf5"), ("N", "#e8a13c"), ("H", "#1c644c")]


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def status_icons(s: float) -> str:
    """Real iOS status-bar glyphs: cellular bars, wifi, battery — drawn as SVG
    rather than the '● ◒ ▰' stand-ins the landing page uses at thumbnail size."""
    bars = (
        f'<svg width="{17*s:.1f}" height="{11*s:.1f}" viewBox="0 0 17 11">'
        '<rect x="0" y="7.6" width="3" height="3.4" rx="1" fill="#111"/>'
        '<rect x="4.6" y="5.4" width="3" height="5.6" rx="1" fill="#111"/>'
        '<rect x="9.2" y="2.9" width="3" height="8.1" rx="1" fill="#111"/>'
        '<rect x="13.8" y="0" width="3" height="11" rx="1" fill="#111"/>'
        "</svg>"
    )
    wifi = (
        f'<svg width="{16*s:.1f}" height="{11.5*s:.1f}" viewBox="0 0 16 11.5">'
        '<g fill="none" stroke="#111" stroke-width="1.9" stroke-linecap="round">'
        '<path d="M1.3 4.1a10.2 10.2 0 0 1 13.4 0"/>'
        '<path d="M4.1 7a6.3 6.3 0 0 1 7.8 0"/></g>'
        '<circle cx="8" cy="10" r="1.3" fill="#111"/>'
        "</svg>"
    )
    battery = (
        f'<svg width="{26*s:.1f}" height="{12*s:.1f}" viewBox="0 0 26 12">'
        '<rect x="0.6" y="0.6" width="22" height="10.8" rx="3.2" fill="none" '
        'stroke="#111" stroke-opacity=".38" stroke-width="1.1"/>'
        '<rect x="2.2" y="2.2" width="18.8" height="7.6" rx="2" fill="#111"/>'
        '<path d="M24.3 4.2v3.6c1-.35 1.5-.95 1.5-1.8s-.5-1.45-1.5-1.8z" '
        'fill="#111" fill-opacity=".38"/>'
        "</svg>"
    )
    return bars + wifi + battery


def render_html(ad: dict, fmt: str, backdrop: str) -> str:
    w, h, screen_frac, head_scale = FORMATS[fmt]

    # Fixed geometry: screen height from the canvas, width from the true ratio.
    screen_h = h * screen_frac
    screen_w = screen_h / SCREEN_RATIO
    dev = screen_w / BASE_PHONE_W        # device scale (bezel, radius, chrome)
    s = dev * TYPE_BOOST                 # in-phone type scale
    bezel = 9 * dev
    radius = 42 * dev
    hs = (w / 1080.0) * head_scale

    avatars = "".join(
        f'<span class="av" style="background:{c}">{ch}</span>' for ch, c in AVATARS
    )

    bubbles = []
    for speaker, text in ad["msgs"]:
        if speaker is None:
            bubbles.append(f'<div class="m out"><span class="bb">{esc(text)}</span></div>')
        else:
            bubbles.append(
                f'<div class="m in"><span class="lbl">{esc(speaker)}</span>'
                f'<span class="bb">{esc(text)}</span></div>'
            )
    msgs = "\n".join(bubbles)

    headline = esc(ad["headline"]).replace("\n", "<br>")

    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html,body {{ width:{w}px; height:{h}px; }}
  body {{ background:{backdrop}; font-family:'SF Pro Text','Helvetica Neue',Helvetica,Arial,sans-serif;
    -webkit-font-smoothing:antialiased; display:flex; flex-direction:column;
    align-items:center; padding:{58*hs:.0f}px {40*hs:.0f}px {34*hs:.0f}px; }}
  /* Centre the headline+phone group so tall formats (9:16) distribute their
     slack above and below it, keeping content inside the Stories safe area
     instead of stranding a dead gap under the phone. */
  .main {{ flex:1; display:flex; flex-direction:column; align-items:center; justify-content:center; }}

  .headline {{ font-size:{40*hs:.0f}px; line-height:1.04; letter-spacing:-.045em;
    font-weight:600; color:#153f32; text-align:center; }}
  .sub {{ font-size:{15.5*hs:.0f}px; line-height:1.42; color:#47705e; text-align:center;
    margin-top:{14*hs:.0f}px; max-width:{430*hs:.0f}px; }}

  /* Fixed-geometry device: screen is always {SCREEN_RATIO:.3f}:1 (iPhone 19.5:9). */
  .phone {{ background:#111; border-radius:{radius:.1f}px; padding:{bezel:.1f}px;
    margin-top:{34*hs:.0f}px; box-shadow:0 {30*hs:.0f}px {70*hs:.0f}px rgba(21,63,50,.20); }}
  .screen {{ background:#fff; border-radius:{radius-bezel:.1f}px;
    width:{screen_w:.1f}px; height:{screen_h:.1f}px;
    display:flex; flex-direction:column; overflow:hidden; text-align:left; }}

  /* Physical device chrome scales with the device, not the boosted type. */
  .statusbar {{ position:relative; display:flex; justify-content:space-between;
    align-items:center; padding:{13*dev:.1f}px {22*dev:.1f}px {7*dev:.1f}px;
    color:#111; font-size:{13.5*dev:.1f}px; font-weight:640; flex:none; }}
  .statusbar .icons {{ display:flex; align-items:center; gap:{5*dev:.1f}px; }}
  .island {{ position:absolute; left:50%; transform:translateX(-50%); top:{7*dev:.1f}px;
    width:{86*dev:.1f}px; height:{25*dev:.1f}px; background:#111; border-radius:{13*dev:.1f}px; }}

  .chathead {{ text-align:center; padding:{4*s:.1f}px 0 {10*s:.1f}px;
    border-bottom:1px solid #ececee; flex:none; }}
  .avatars {{ display:flex; justify-content:center; margin-bottom:{5*s:.1f}px; }}
  .av {{ width:{25*s:.1f}px; height:{25*s:.1f}px; border-radius:50%; color:#fff;
    font-size:{10*s:.1f}px; font-weight:700; display:flex; align-items:center;
    justify-content:center; margin:0 -{3*s:.1f}px; border:{max(1.5,2*s):.1f}px solid #fff; }}
  .gname {{ color:#111; font-size:{12*s:.1f}px; font-weight:650; }}
  .gname span {{ color:#aaa; }}

  /* Bottom-anchored: the thread sits above the input bar, as in a real chat. */
  .thread {{ flex:1; display:flex; flex-direction:column; justify-content:flex-end;
    overflow:hidden; padding-bottom:{6*s:.1f}px; }}
  .daystamp {{ text-align:center; color:#8e8e93; font-size:{10*s:.1f}px; font-weight:650;
    margin:{11*s:.1f}px 0 {8*s:.1f}px; flex:none; }}
  .m {{ display:flex; flex-direction:column; margin:0 {9*s:.1f}px {8*s:.1f}px; flex:none; }}
  .m .lbl {{ font-size:{9.5*s:.1f}px; color:#8e8e93; margin:0 {11*s:.1f}px {3*s:.1f}px; }}
  .bb {{ max-width:88%; padding:{7*s:.1f}px {11*s:.1f}px; border-radius:{16*s:.1f}px;
    font-size:{12.5*s:.1f}px; line-height:1.38; width:fit-content; white-space:pre-line; }}
  .in {{ align-items:flex-start; }}
  .in .bb {{ background:#e9e9eb; color:#111; border-bottom-left-radius:{5*s:.1f}px; }}
  .out {{ align-items:flex-end; }}
  .out .bb {{ background:#1477f8; color:#fff; border-bottom-right-radius:{5*s:.1f}px; }}

  .inputbar {{ flex:none; display:flex; align-items:center; gap:{7*s:.1f}px;
    padding:{7*s:.1f}px {11*s:.1f}px {9*s:.1f}px; }}
  .plus {{ width:{25*s:.1f}px; height:{25*s:.1f}px; border-radius:50%; background:#e9e9eb;
    color:#8e8e93; font-size:{15*s:.1f}px; line-height:{23*s:.1f}px; text-align:center; flex:none; }}
  .field {{ flex:1; height:{25*s:.1f}px; border:1px solid #e2e2e5; border-radius:{13*s:.1f}px;
    color:#b8b8bd; font-size:{11.5*s:.1f}px; line-height:{23*s:.1f}px; padding:0 {10*s:.1f}px; }}
  .homebar {{ flex:none; width:{112*dev:.1f}px; height:{4*dev:.1f}px; background:#111;
    opacity:.85; border-radius:{2*dev:.1f}px; margin:0 auto {7*dev:.1f}px; }}

  .footer {{ padding-top:{26*hs:.0f}px; display:flex; align-items:center; gap:{12*hs:.0f}px; }}
  .footer img {{ width:{38*hs:.0f}px; height:{38*hs:.0f}px; border-radius:{10*hs:.0f}px; }}
  .footer .url {{ font-size:{19*hs:.0f}px; font-weight:600; letter-spacing:-.02em; color:#153f32; }}
</style></head><body>
  <div class="main">
  <div class="headline">{headline}</div>
  <div class="sub">{esc(ad["sub"])}</div>
  <div class="phone"><div class="screen">
    <div class="statusbar">
      <span>{esc(ad["time"])}</span>
      <div class="island"></div>
      <span class="icons">{status_icons(dev)}</span>
    </div>
    <div class="chathead"><div class="avatars">{avatars}</div><div class="gname">Leo HQ <span>›</span></div></div>
    <div class="thread">
      <div class="daystamp">{esc(ad["stamp"])}</div>
      {msgs}
    </div>
    <div class="inputbar"><div class="plus">+</div><div class="field">iMessage</div></div>
    <div class="homebar"></div>
  </div></div>
  </div>
  <div class="footer"><img src="{LOGO_DATA_URI}"><span class="url">texthal.com</span></div>
</body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="render just this ad slug")
    ap.add_argument("--format", choices=list(FORMATS), help="render just this format")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    ads = [a for a in ADS if not args.only or a["slug"] == args.only]
    fmts = [args.format] if args.format else list(FORMATS)
    if not ads:
        print(f"no ad matching --only {args.only!r}", file=sys.stderr)
        return 1

    written = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for i, ad in enumerate(ads):
            backdrop = BACKDROPS[i % len(BACKDROPS)]
            for fmt in fmts:
                cw, ch = FORMATS[fmt][0], FORMATS[fmt][1]
                page = browser.new_page(viewport={"width": cw, "height": ch}, device_scale_factor=1)
                page.set_content(render_html(ad, fmt, backdrop), wait_until="load")
                # Warn if the thread overflows the fixed screen (top msg clipped).
                clipped = page.evaluate(
                    "() => { const t = document.querySelector('.thread');"
                    " return t.scrollHeight - t.clientHeight; }"
                )
                dest = OUT / f"{ad['slug']}-{fmt}.png"
                page.screenshot(path=str(dest))
                page.close()
                written.append((dest, clipped))
        browser.close()

    for d, clipped in written:
        flag = f"  ⚠ top clipped by {clipped}px" if clipped > 1 else ""
        print(f"{d.relative_to(ROOT)}  ({d.stat().st_size // 1024} KB){flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
