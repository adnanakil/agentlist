"""Render the texthal.com hero background: HAL's conversation on a phone.

Replaces the stock bottles photo. The hero is a full-bleed `object-fit:cover`
image with a green gradient laid over it — opaque (94%) on the left where the
headline sits, fading to ~8% past 82% across. So the subject must sit in the
RIGHT third or it disappears under the overlay, and the left third must be
quiet because it is covered anyway.

Reuses the phone chrome and bubble styling from make_ads.py so the hero, the
ad creatives, and the landing page demo are visibly the same product.

    uv run --with playwright python growth/ad_visuals/make_hero.py

Output: growth/ad_visuals/out/hero-conversation.png (2400x1200)
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = pathlib.Path(__file__).resolve().parent / "out"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from make_ads import SCREEN_RATIO, status_icons, esc  # noqa: E402

W, H = 2400, 1200

# The conversation that shows the handoff in three beats: a caregiver logs,
# HAL confirms and predicts, someone else asks and gets a straight answer.
MSGS = [
    ("Mom", "4oz at 3:15"),
    ("HAL", "Logged ✅ That's his 4th feed today."),
    (None, "down for a nap 😴"),
    ("HAL", "Logged 💤 He'll likely wake around 5:15."),
    ("Grandma", "how's his day going?"),
    ("HAL", "3 naps, 5 feeds — last at 3:15. Bedtime's usually around 7:15 💛"),
]

AVATARS = [("M", "#ec6ba8"), ("D", "#5b9cf5"), ("N", "#e8a13c"), ("H", "#1c644c")]

# Phone sized to sit comfortably in the right third at 2400x1200.
SCREEN_H = 980.0
SCREEN_W = SCREEN_H / SCREEN_RATIO
DEV = SCREEN_W / 330.0
S = DEV * 1.24


def build_html() -> str:
    avatars = "".join(
        f'<span class="av" style="background:{c}">{ch}</span>' for ch, c in AVATARS
    )
    bubbles = []
    for who, text in MSGS:
        if who is None:
            bubbles.append(f'<div class="m out"><span class="bb">{esc(text)}</span></div>')
        else:
            bubbles.append(
                f'<div class="m in"><span class="lbl">{esc(who)}</span>'
                f'<span class="bb">{esc(text)}</span></div>'
            )
    msgs = "\n".join(bubbles)

    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html,body {{ width:{W}px; height:{H}px; overflow:hidden; }}
  body {{
    font-family:'SF Pro Text','Helvetica Neue',Helvetica,Arial,sans-serif;
    -webkit-font-smoothing:antialiased;
    background:
      radial-gradient(120% 90% at 12% 45%, #2a4f42 0%, #22443a 40%, #1b3a31 100%);
    position:relative;
  }}
  /* Warm light from the right so the phone reads against the green overlay,
     echoing the daylight in the photo this replaces. */
  .warm {{
    position:absolute; inset:0;
    background:
      radial-gradient(75% 105% at 78% 40%, rgba(232,205,168,.55) 0%,
                      rgba(206,178,142,.26) 38%, rgba(20,52,42,0) 72%);
  }}
  .floor {{
    position:absolute; left:0; right:0; bottom:0; height:34%;
    background:linear-gradient(0deg, rgba(10,32,26,.55), rgba(10,32,26,0));
  }}

  /* Subject sits right-of-centre: under object-position 66-70% and clear of
     the gradient that covers the left 34%. */
  .stage {{
    position:absolute; top:50%; left:69%; transform:translate(-50%,-50%) rotate(-3deg);
  }}
  .phone {{
    background:#111; border-radius:{42*DEV:.0f}px; padding:{9*DEV:.0f}px;
    box-shadow:0 {46*DEV:.0f}px {96*DEV:.0f}px rgba(6,22,18,.5),
               0 {8*DEV:.0f}px {20*DEV:.0f}px rgba(6,22,18,.35);
  }}
  .screen {{
    background:#fff; border-radius:{33*DEV:.0f}px;
    width:{SCREEN_W:.0f}px; height:{SCREEN_H:.0f}px;
    display:flex; flex-direction:column; overflow:hidden; text-align:left;
  }}

  .statusbar {{ position:relative; display:flex; justify-content:space-between;
    align-items:center; padding:{13*DEV:.0f}px {22*DEV:.0f}px {7*DEV:.0f}px;
    color:#111; font-size:{13.5*DEV:.0f}px; font-weight:640; flex:none; }}
  .statusbar .icons {{ display:flex; align-items:center; gap:{5*DEV:.0f}px; }}
  .island {{ position:absolute; left:50%; transform:translateX(-50%); top:{7*DEV:.0f}px;
    width:{86*DEV:.0f}px; height:{25*DEV:.0f}px; background:#111;
    border-radius:{13*DEV:.0f}px; }}

  .chathead {{ text-align:center; padding:{4*DEV:.0f}px 0 {10*DEV:.0f}px;
    border-bottom:1px solid #ececee; flex:none; }}
  .avatars {{ display:flex; justify-content:center; margin-bottom:{5*DEV:.0f}px; }}
  .av {{ width:{25*DEV:.0f}px; height:{25*DEV:.0f}px; border-radius:50%; color:#fff;
    font-size:{10*DEV:.0f}px; font-weight:700; display:flex; align-items:center;
    justify-content:center; margin:0 -{3*DEV:.0f}px; border:{2*DEV:.0f}px solid #fff; }}
  .gname {{ color:#111; font-size:{12*DEV:.0f}px; font-weight:650; }}
  .gname span {{ color:#aaa; }}

  .thread {{ flex:1; display:flex; flex-direction:column; justify-content:flex-end;
    overflow:hidden; padding-bottom:{6*S:.0f}px; }}
  .daystamp {{ text-align:center; color:#8e8e93; font-size:{10*S:.0f}px;
    font-weight:650; margin:{11*S:.0f}px 0 {8*S:.0f}px; flex:none; }}
  .m {{ display:flex; flex-direction:column; margin:0 {9*S:.0f}px {8*S:.0f}px; flex:none; }}
  .m .lbl {{ font-size:{9.5*S:.0f}px; color:#8e8e93; margin:0 {11*S:.0f}px {3*S:.0f}px; }}
  .bb {{ max-width:88%; padding:{7*S:.0f}px {11*S:.0f}px; border-radius:{16*S:.0f}px;
    font-size:{12.5*S:.0f}px; line-height:1.38; width:fit-content; white-space:pre-line; }}
  .in {{ align-items:flex-start; }}
  .in .bb {{ background:#e9e9eb; color:#111; border-bottom-left-radius:{5*S:.0f}px; }}
  .out {{ align-items:flex-end; }}
  .out .bb {{ background:#1477f8; color:#fff; border-bottom-right-radius:{5*S:.0f}px; }}

  .inputbar {{ flex:none; display:flex; align-items:center; gap:{7*S:.0f}px;
    padding:{7*S:.0f}px {11*S:.0f}px {9*S:.0f}px; }}
  .plus {{ width:{25*S:.0f}px; height:{25*S:.0f}px; border-radius:50%; background:#e9e9eb;
    color:#8e8e93; font-size:{15*S:.0f}px; line-height:{23*S:.0f}px; text-align:center;
    flex:none; }}
  .field {{ flex:1; height:{25*S:.0f}px; border:1px solid #e2e2e5;
    border-radius:{13*S:.0f}px; color:#b8b8bd; font-size:{11.5*S:.0f}px;
    line-height:{23*S:.0f}px; padding:0 {10*S:.0f}px; }}
  .homebar {{ flex:none; width:{112*DEV:.0f}px; height:{4*DEV:.0f}px; background:#111;
    opacity:.85; border-radius:{2*DEV:.0f}px; margin:0 auto {7*DEV:.0f}px; }}
</style></head><body>
  <div class="warm"></div>
  <div class="floor"></div>
  <div class="stage">
    <div class="phone"><div class="screen">
      <div class="statusbar">
        <span>3:15</span><div class="island"></div>
        <span class="icons">{status_icons(DEV)}</span>
      </div>
      <div class="chathead">
        <div class="avatars">{avatars}</div>
        <div class="gname">Leo HQ <span>›</span></div>
      </div>
      <div class="thread">
        <div class="daystamp">Today 3:15 PM</div>
        {msgs}
      </div>
      <div class="inputbar"><div class="plus">+</div><div class="field">iMessage</div></div>
      <div class="homebar"></div>
    </div></div>
  </div>
</body></html>"""


def main() -> int:
    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / "hero-conversation.png"
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        page.set_content(build_html(), wait_until="load")
        clipped = page.evaluate(
            "() => { const t = document.querySelector('.thread');"
            " return t.scrollHeight - t.clientHeight; }"
        )
        page.screenshot(path=str(dest))
        page.close()
        b.close()
    if clipped > 1:
        print(f"WARNING: thread overflows by {clipped}px — top message is cut off")
    print(f"{dest.relative_to(ROOT)}  ({dest.stat().st_size // 1024} KB, {W}x{H})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
