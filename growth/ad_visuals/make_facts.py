"""Instagram fact-card series: pastel typographic posts, one infant fact each.

Same visual family as make_ads.py (pastel backdrops, SF Pro, brand green), but
no phone — a big statement instead (Adnan, 2026-08-11). Facts are deliberately
well-established, range-phrased developmental knowledge: no medical advice, no
invented statistics or citations (honesty rule in growth/CLAUDE.md).

    uv run --with playwright python growth/ad_visuals/make_facts.py

Output: growth/ad_visuals/out/facts/fact-01..10.png (1080x1350, IG 4:5)
"""
from __future__ import annotations

import pathlib
import sys

OUT = pathlib.Path(__file__).resolve().parent / "out" / "facts"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from make_ads import BACKDROPS  # noqa: E402

W, H = 1080, 1350

# (emoji, fact-html) — <b> wraps the hook, rendered in brand green.
FACTS = [
    ("😴", "Newborns sleep <b>14–17 hours</b> a day — just almost never more than a few at a time."),
    ("🍒", "On day one, a newborn's stomach is about the size of <b>a cherry</b>."),
    ("🦴", "Babies are born with about <b>300 bones</b>. Adults have 206 — many fuse as they grow."),
    ("💬", "A newborn can recognize <b>their mother's voice</b> from the very first day."),
    ("📈", "Most babies <b>double their birth weight</b> by around 5 months — and triple it by their first birthday."),
    ("👀", "A newborn sees sharpest at <b>8–12 inches</b> — about the distance to the face feeding them."),
    ("💧", "Newborns cry <b>without tears</b> at first. Real tears usually arrive after a few weeks."),
    ("🥕", "Babies <b>taste what mom eats</b> before birth — flavors reach the amniotic fluid."),
    ("🍼", "A newborn feeds <b>8–12 times a day</b>. That's 70+ feeds a week to keep track of."),
    ("🧠", "A baby's brain <b>nearly doubles in size</b> in the first year."),
]


def card_html(emoji: str, fact: str, backdrop: str) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html,body {{ width:{W}px; height:{H}px; overflow:hidden; }}
  body {{
    font-family:'SF Pro Display','SF Pro Text','Helvetica Neue',Helvetica,Arial,sans-serif;
    -webkit-font-smoothing:antialiased;
    background:
      radial-gradient(80% 60% at 50% 30%, rgba(255,255,255,.5) 0%, rgba(255,255,255,0) 70%),
      {backdrop};
    display:flex; flex-direction:column; padding:96px 92px 84px;
    color:#20332a;
  }}
  .eyebrow {{ font-size:26px; font-weight:700; letter-spacing:.14em;
    color:#48685a; text-transform:uppercase; }}
  .emoji {{ font-size:120px; margin:64px 0 8px; line-height:1;
    font-family:'Apple Color Emoji','SF Pro Display',sans-serif; }}
  .fact {{ flex:1; display:flex; align-items:center; }}
  .fact p {{ font-size:76px; line-height:1.16; letter-spacing:-.022em; font-weight:600; }}
  .fact b {{ color:#128a47; font-weight:650; }}
  .foot {{ display:flex; align-items:center; gap:18px; border-top:2px solid rgba(32,51,42,.14);
    padding-top:34px; }}
  .mark {{ width:58px; height:58px; border-radius:15px; background:#33c463;
    color:#fff; font-size:24px; font-weight:700; display:flex; align-items:center;
    justify-content:center; letter-spacing:-.01em; }}
  .foot .t1 {{ font-size:25px; font-weight:650; }}
  .foot .t2 {{ font-size:22px; color:#48685a; }}
  .foot .site {{ margin-left:auto; font-size:24px; font-weight:650; color:#128a47; }}
</style></head><body>
  <div class="eyebrow">Tiny human facts</div>
  <div class="emoji">{emoji}</div>
  <div class="fact"><p>{fact}</p></div>
  <div class="foot">
    <div class="mark">hal</div>
    <div><div class="t1">HAL</div><div class="t2">the baby log in your group chat</div></div>
    <div class="site">texthal.com</div>
  </div>
</body></html>"""


def main() -> int:
    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        for i, (emoji, fact) in enumerate(FACTS, 1):
            page.set_content(card_html(emoji, fact, BACKDROPS[(i - 1) % len(BACKDROPS)]),
                             wait_until="load")
            overflow = page.evaluate(
                "() => document.body.scrollHeight > window.innerHeight"
            )
            dest = OUT / f"fact-{i:02d}.png"
            page.screenshot(path=str(dest))
            flag = "  OVERFLOW!" if overflow else ""
            print(f"{dest.name}  ({dest.stat().st_size // 1024} KB){flag}")
        page.close()
        b.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
