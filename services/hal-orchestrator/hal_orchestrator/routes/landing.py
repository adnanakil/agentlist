"""GET / — the tryhal.xyz landing page.

Deliberately minimal: the wordmark, one line, HAL's phone number — tappable
into Messages on iOS/macOS via an sms: link. No signup flow, no JS, no nav.
The number comes from HAL_PUBLIC_NUMBER; unset shows a coming-soon variant.
"""

from __future__ import annotations

import re

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from hal_orchestrator.state import get_settings


def _pretty_number(raw: str) -> str:
    """+16505551234 -> (650) 555-1234; anything unparseable passes through."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return raw


def render_landing(number: str) -> str:
    """Pure renderer. `number` may be '' -> coming-soon variant."""
    pretty = _pretty_number(number)
    sms = re.sub(r"[^\d+]", "", number or "")
    hero = (
        f'<a class="number" href="sms:{sms}&body=hey%20HAL">{pretty}</a>\n'
        '<p class="hint">text anything to get started</p>'
        if number
        else '<p class="number soon">coming soon</p>'
    )
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HAL</title>
<meta name="description" content="HAL is a personal assistant that lives in your texts.">
<style>
  :root {{ color-scheme: dark; }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    background:#0a0a0c; color:#f2f2f4; min-height:100vh; min-height:100dvh;
    display:flex; flex-direction:column; align-items:center; justify-content:center;
    font-family:-apple-system, BlinkMacSystemFont, "SF Pro Display", system-ui, sans-serif;
    text-align:center; padding:24px; gap:0;
  }}
  .logo {{ margin-bottom:22px; line-height:0; }}
  .mark {{
    font-size:15px; font-weight:600; letter-spacing:.42em; text-indent:.42em;
    color:#8b8b93; text-transform:uppercase; margin-bottom:28px;
  }}
  h1 {{
    font-size:clamp(26px, 5.4vw, 44px); font-weight:650; letter-spacing:-.02em;
    line-height:1.15; max-width:22ch; margin-bottom:44px;
  }}
  .number {{
    font-size:clamp(30px, 7.5vw, 58px); font-weight:700; letter-spacing:-.01em;
    color:#f2f2f4; text-decoration:none; font-variant-numeric:tabular-nums;
    border-bottom:2px solid #34c759; padding-bottom:6px;
    transition:color .15s ease, border-color .15s ease;
  }}
  .number:hover {{ color:#34c759; }}
  .number.soon {{ color:#3a3a42; border-color:#3a3a42; }}
  .hint {{ color:#6b6b73; font-size:14px; margin-top:22px; }}
  footer {{ position:fixed; bottom:22px; color:#3a3a42; font-size:12px; letter-spacing:.02em; }}
</style></head>
<body>
  <div class="logo"><svg viewBox="0 0 200 190" width="82" height="78" role="img" aria-label="HAL logo" xmlns="http://www.w3.org/2000/svg"><path d="M65 20 L135 20 A45 45 0 0 1 180 65 L180 85 A45 45 0 0 1 135 130 L95 130 L58 166 L72 130 L65 130 A45 45 0 0 1 20 85 L20 65 A45 45 0 0 1 65 20 Z" fill="none" stroke="#34c759" stroke-width="13" stroke-linejoin="round"/><circle cx="78" cy="80" r="11" fill="#34c759"/><circle cx="122" cy="80" r="11" fill="#34c759"/><path d="M76 104 Q100 124 124 104" fill="none" stroke="#34c759" stroke-width="12" stroke-linecap="round"/></svg></div>
  <div class="mark">HAL</div>
  <h1>A personal assistant that lives in your texts.</h1>
  {hero}
  <footer>tryhal.xyz</footer>
</body></html>"""


def build_landing_router() -> APIRouter:
    router = APIRouter()

    @router.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def landing() -> HTMLResponse:
        return HTMLResponse(render_landing(get_settings().hal_public_number))

    return router
