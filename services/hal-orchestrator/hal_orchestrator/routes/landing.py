"""GET / — the tryhal.xyz landing page.

The beachhead front door (BEACHHEAD.md): the household baby-schedule pitch.
One page, no JS, no signup flow — the demo IS the pitch: a mocked family
thread showing mom/nanny/grandma logging to one record, the schedule math
HAL gives back, and one tappable number. The sms prefill doubles as the
parent-track selector ("Hi HAL — new baby here 👶", see ONBOARDING.md);
`?c=<code>` appends a per-channel attribution code that HAL strips and
records as acquisition_source. The number comes from HAL_PUBLIC_NUMBER;
unset shows a coming-soon variant.

Everything shown is real product behavior: shared log, next-nap window with
honest uncertainty, day recap on request, export, forget-me. Never mock a
feature that doesn't exist.
"""

from __future__ import annotations

import re
from urllib.parse import quote

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from hal_orchestrator.routes.logo_data import LOGO_DATA_URI
from hal_orchestrator.state import get_settings

SMS_PREFILL = "Hi HAL — new baby here 👶"
_CODE_RX = re.compile(r"^[A-Za-z0-9_-]{2,32}$")


def _pretty_number(raw: str) -> str:
    """+16505551234 -> (650) 555-1234; anything unparseable passes through."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return raw


def render_landing(number: str, code: str | None = None) -> str:
    """Pure renderer. `number` may be '' -> coming-soon variant. `code` is an
    already-validated attribution code appended to the sms prefill."""
    pretty = _pretty_number(number)
    sms = re.sub(r"[^\d+]", "", number or "")
    body = SMS_PREFILL + (f" ({code})" if code else "")
    cta = (
        f'<a class="number" href="sms:{sms}&body={quote(body)}">{pretty}</a>\n'
        '<p class="hint">text me to get started — no app, nothing to install</p>'
        if number
        else '<p class="number soon">coming soon</p>'
    )
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HAL — the baby log that lives in your group chat</title>
<meta name="description" content="Your whole household on one baby schedule. Parents, nanny, grandma text feeds and naps to the family thread — HAL keeps one record, forecasts the next nap, and recaps the day. No app.">
<style>
  :root {{ color-scheme: dark; }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    background:#1B4D3E; color:#B9F8D3; min-height:100vh;
    display:flex; flex-direction:column; align-items:center;
    font-family:-apple-system, BlinkMacSystemFont, "SF Pro Display", system-ui, sans-serif;
    text-align:center; padding:48px 24px 32px;
  }}
  .logo {{ width:84px; height:84px; border-radius:19px; overflow:hidden;
           margin-bottom:20px; box-shadow:0 6px 28px rgba(0,0,0,.45); }}
  .logo img {{ width:100%; height:100%; object-fit:cover; display:block; }}
  .mark {{
    font-size:14px; font-weight:600; letter-spacing:.42em; text-indent:.42em;
    color:#8b8b93; text-transform:uppercase; margin-bottom:26px;
  }}
  h1 {{
    font-size:clamp(27px, 5.6vw, 46px); font-weight:650; letter-spacing:-.02em;
    line-height:1.12; max-width:20ch; margin-bottom:16px;
  }}
  .sub {{
    color:#8fd7b0; font-size:clamp(15px, 2.6vw, 18px); line-height:1.55;
    max-width:46ch; margin-bottom:36px;
  }}

  /* The demo IS the pitch: the family thread, everyone logging. */
  .chat {{
    width:100%; max-width:420px; text-align:left; margin:0 auto 40px;
    background:#123529; border:1px solid #2a5d4b; border-radius:22px;
    padding:18px 14px 16px; box-shadow:0 10px 34px rgba(0,0,0,.35);
  }}
  .chat-title {{
    text-align:center; color:#6f9d85; font-size:12px; font-weight:600;
    letter-spacing:.06em; margin-bottom:12px;
  }}
  .msg {{ display:flex; flex-direction:column; margin-bottom:10px; }}
  .msg .who {{ font-size:11px; color:#6f9d85; margin:0 10px 3px; }}
  .bubble {{
    max-width:82%; padding:8px 13px; border-radius:18px;
    font-size:15px; line-height:1.4; width:fit-content;
  }}
  .them {{ align-items:flex-start; }}
  .them .bubble {{ background:#26493c; color:#d9f7e6; border-bottom-left-radius:6px; }}
  .hal {{ align-items:flex-end; }}
  .hal .who {{ align-self:flex-end; }}
  .hal .bubble {{ background:#34c759; color:#03301c; border-bottom-right-radius:6px; }}

  .number {{
    font-size:clamp(30px, 7.5vw, 56px); font-weight:700; letter-spacing:-.01em;
    color:#B9F8D3; text-decoration:none; font-variant-numeric:tabular-nums;
    border-bottom:2px solid #34c759; padding-bottom:6px;
    transition:color .15s ease, border-color .15s ease;
  }}
  .number:hover {{ color:#34c759; }}
  .number.soon {{ color:#3a3a42; border-color:#3a3a42; }}
  .hint {{ color:#ffffff; font-size:14px; margin-top:20px; }}

  .cards {{
    display:grid; grid-template-columns:1fr; gap:14px;
    width:100%; max-width:640px; margin:52px auto 0; text-align:left;
  }}
  @media (min-width:600px) {{ .cards {{ grid-template-columns:1fr 1fr; }} }}
  .card {{
    background:#123529; border:1px solid #2a5d4b; border-radius:16px;
    padding:18px 18px 16px;
  }}
  .card h2 {{ font-size:16px; font-weight:650; margin-bottom:7px; color:#B9F8D3; }}
  .card p {{ font-size:14px; line-height:1.55; color:#8fd7b0; }}

  .privacy {{
    color:#6f9d85; font-size:13px; line-height:1.55; max-width:52ch;
    margin-top:44px;
  }}
  footer {{ margin-top:30px; color:#6b6b73; font-size:13px; letter-spacing:.02em; }}
  footer a {{ color:#8b8b93; text-decoration:none; }}
  footer a:hover {{ color:#34c759; }}
</style></head>
<body>
  <div class="logo"><img src="{LOGO_DATA_URI}" alt="HAL logo"></div>
  <div class="mark">HAL</div>
  <h1>The baby log that lives in your group chat.</h1>
  <p class="sub">Your whole household on one schedule. Parents, nanny,
  grandma — everyone texts feeds and naps the way they'd say them out loud,
  and HAL keeps one record straight. No app.</p>

  <div class="chat" aria-label="Example family thread">
    <div class="chat-title">Leo HQ — mom, dad, nanny &amp; HAL</div>
    <div class="msg them"><span class="who">Mom · 3:15 PM</span>
      <span class="bubble">4oz at 3:15</span></div>
    <div class="msg hal"><span class="who">HAL</span>
      <span class="bubble">Logged ✅ That's his 4th feed today.</span></div>
    <div class="msg them"><span class="who">Nanny · 4:02 PM</span>
      <span class="bubble">down for a nap 😴</span></div>
    <div class="msg hal"><span class="who">HAL</span>
      <span class="bubble">Logged 💤 Next sleepy window after he wakes looks
      like ~5:20–5:50 — I'll quietly flag it 15 min ahead.</span></div>
    <div class="msg them"><span class="who">Grandma · 6:30 PM</span>
      <span class="bubble">how's his day going?</span></div>
    <div class="msg hal"><span class="who">HAL</span>
      <span class="bubble">3 naps (2h 40m total), 5 feeds — last at 6:10.
      Bedtime's usually around 7:15 💛</span></div>
  </div>

  {cta}

  <div class="cards">
    <div class="card">
      <h2>One schedule, whole household</h2>
      <p>Whoever's on duty just texts the thread — parents, nanny, grandma.
      No shared passwords, no per-seat fees, no "did you put it in the
      app?" Handoffs stop being a briefing.</p>
    </div>
    <div class="card">
      <h2>It quietly does the math</h2>
      <p>The next nap window, sized to your baby's own rhythm. Ask "where's
      his day at?" when you come on shift and get the whole picture — feeds,
      naps, what's likely next.</p>
    </div>
    <div class="card">
      <h2>No app. Ever.</h2>
      <p>Log the 3am feed with one thumb from the thread you already have
      open. No bright screen, no login, no timer that dies. If you can text,
      you're set up.</p>
    </div>
    <div class="card">
      <h2>Yours, and disposable</h2>
      <p>Say "export" and the whole log is yours as a file, any time. Say
      "forget me" and everything is permanently deleted. No lock-in, no
      ads, ever.</p>
    </div>
  </div>

  <p class="privacy">Your family's data stays yours — never sold, never ads,
  never used to train anything. Text 'forget me' and it's gone.</p>
  <footer><a href="/privacy">Privacy Policy</a> · <a href="/terms">Terms of Service</a></footer>
</body></html>"""


def build_landing_router() -> APIRouter:
    router = APIRouter()

    @router.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def landing(c: str | None = None) -> HTMLResponse:
        code = c if c and _CODE_RX.match(c) else None
        return HTMLResponse(
            render_landing(get_settings().hal_public_number, code=code)
        )

    return router
