# ruff: noqa: E501 -- embedded HTML/CSS stays readable as authored markup.
"""GET / — the texthal.com landing page.

The beachhead front door (BEACHHEAD.md): the household baby-schedule pitch.
One page, minimal JS (tap beacon only), no signup flow — the demo IS the pitch: a mocked family
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

import asyncio
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)

import ag_db.session as db_session
from ag_db.models import HalFunnelEvent
from sqlalchemy import func, select

from hal_orchestrator.middleware.page_hits import (
    LANDING_VARIANTS,
    landing_variant,
    visitor_hash,
)

log = structlog.get_logger()

from hal_orchestrator.routes.logo_data import LOGO_DATA_URI
from hal_orchestrator.state import get_settings

# The prefill is ALSO the parent-track selector: "new baby here" is the literal
# trigger in prompts/system.py (_PARENT_PREFILL_RX) and the only branch that
# strips + records the "(<code>)" attribution suffix. Never drop that phrase.
SMS_PREFILL = "Hi HAL — new baby here 👶 What can you do?"

# Android wants "?body=" (RFC 5724); iOS/macOS want "&body=". The separator is
# chosen server-side from the request UA so the markup is already right without
# JS — "/" is no-store, so per-UA markup can't be cached across visitors.
_ANDROID_UA_RX = re.compile(r"android", re.IGNORECASE)


def sms_separator(user_agent: str | None) -> str:
    return "?" if _ANDROID_UA_RX.search(user_agent or "") else "&"


# Minimal inline JS. Four jobs, all conversion-critical, all fail-open:
#   1. Belt-and-braces for the separator above: if the markup somehow reached an
#      Android device carrying the iOS form, rewrite it client-side. A no-op when
#      the server already got it right.
#   2. Keepalive tap beacon before the native SMS app steals the tab.
#   3. Sticky mobile bar hides only while the hero CTA is already on screen —
#      CSS shows the bar by default, so a JS failure leaves the CTA visible.
#   4. Desktop has no working sms: handler on Windows/Linux, so the number
#      becomes a copy-to-clipboard button there instead of a dead link.
# Served as /static/landing.js (NOT inlined): the CSP is default-src 'none'
# with script-src 'self', so inline <script> blocks never execute (ENG-015 —
# the beacon was silently dead for days because of exactly that).
_LANDING_JS = """
(function(){
  var links=document.querySelectorAll('a[href^="sms:"]');
  if(/android/i.test(navigator.userAgent||'')){
    links.forEach(function(a){a.href=a.href.replace('&body=','?body=');});
  }
  var goLinks=document.querySelectorAll('a[href^="/go/"]');
  if(goLinks.length){
    var gp=new URLSearchParams(window.location.search),pts=[];
    ['utm_source','utm_medium','utm_campaign'].forEach(function(k){var v=gp.get(k);if(v)pts.push(k+'='+encodeURIComponent(v));});
    if(pts.length){var goQs='?'+pts.join('&');goLinks.forEach(function(a){a.href=a.href+goQs;});}
  }
  function tap(evType){
    var p=new URLSearchParams(window.location.search);
    fetch('/tap',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({event_type:evType||'sms_tap',code:p.get('c'),
        utm_source:p.get('utm_source'),utm_medium:p.get('utm_medium'),
        utm_campaign:p.get('utm_campaign'),
        variant:document.body.getAttribute('data-variant')}),
      keepalive:true}).catch(function(){});
  }
  links.forEach(function(a){a.addEventListener('click',function(){tap('sms_tap');});});

  var bar=document.getElementById('stickycta'), hero=document.getElementById('herocta');
  if(bar&&hero&&'IntersectionObserver' in window){
    new IntersectionObserver(function(e){
      bar.classList.toggle('is-hidden', e[0].isIntersecting);
    },{threshold:.35}).observe(hero);
  }

  try{
    if(!window.matchMedia('(pointer:coarse)').matches){
      document.documentElement.classList.add('desk');
    }
  }catch(err){}
  document.querySelectorAll('.copy-num').forEach(function(b){
    b.addEventListener('click',function(){
      if(!document.documentElement.classList.contains('desk')) return;
      tap('sms_copy');
      var n=b.getAttribute('data-num')||'', prev=b.textContent;
      if(!navigator.clipboard) return;
      navigator.clipboard.writeText(n).then(function(){
        b.textContent='Copied \\u2713';
        setTimeout(function(){b.textContent=prev;},2000);
      }).catch(function(){});
    });
  });

  var rw=document.getElementById('rotator');
  if(rw){
    var reduce=false;
    try{reduce=window.matchMedia('(prefers-reduced-motion: reduce)').matches;}catch(e){}
    if(!reduce){
      var words=['naps.','poops.','feeds.'], wi=0;
      setInterval(function(){
        wi=(wi+1)%words.length;
        rw.classList.add('rot-out');
        setTimeout(function(){rw.textContent=words[wi];rw.classList.remove('rot-out');},240);
      },2200);
    }
  }

  // Scroll-depth beacons (2026-08-11): answers "do visitors scroll at all?".
  // Quartiles fire once per pageload; event types are whitelisted server-side.
  var sSent={};
  function sDepth(){
    var h=document.documentElement;
    var total=h.scrollHeight-window.innerHeight;
    if(total<=0) return 1;
    return (window.pageYOffset||h.scrollTop||0)/total;
  }
  window.addEventListener('scroll',function(){
    var d=sDepth();
    [[.25,'scroll_25'],[.5,'scroll_50'],[.75,'scroll_75'],[.97,'scroll_100']].forEach(function(q){
      if(d>=q[0]&&!sSent[q[1]]){sSent[q[1]]=1;tap(q[1]);}
    });
  },{passive:true});
})();
"""
_CODE_RX = re.compile(r"^[A-Za-z0-9_-]{2,32}$")
_BOTTLES_IMAGE = Path(__file__).parent.parent / "static" / "donebottles.png"
_HERO_IMAGE = Path(__file__).parent.parent / "static" / "hero-conversation.png"
_HERO_PHONE_IMAGE = Path(__file__).parent.parent / "static" / "hero-phone.png"


def _pretty_number(raw: str) -> str:
    """+16505551234 -> (650) 555-1234; anything unparseable passes through."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return raw


def _cta_label(pretty: str, variant: str) -> str:
    """The A/B'd primary-CTA copy: brand name vs. the literal number."""
    return f"Text {pretty}" if variant == "b" else "Text HAL"


def _qr_svg(data: str) -> str:
    """Server-side QR code as an inline SVG string. Returns '' if qrcode is unavailable."""
    try:
        import qrcode  # type: ignore[import]
    except ImportError:
        return ""
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L, border=4)
    qr.add_data(data)
    qr.make(fit=True)
    modules = qr.modules
    n = len(modules)
    rects: list[str] = []
    for row_i, row in enumerate(modules):
        c_start: int | None = None
        for col_i, dark in enumerate(row):
            if dark and c_start is None:
                c_start = col_i
            elif not dark and c_start is not None:
                rects.append(
                    f'<rect x="{c_start}" y="{row_i}" width="{col_i - c_start}" height="1"/>'
                )
                c_start = None
        if c_start is not None:
            rects.append(f'<rect x="{c_start}" y="{row_i}" width="{n - c_start}" height="1"/>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n} {n}"'
        f' role="img" aria-label="QR code — scan with your phone to open Messages">'
        f'<rect width="{n}" height="{n}" fill="#fff"/>'
        + "".join(rects)
        + "</svg>"
    )


def render_landing(
    number: str,
    code: str | None = None,
    variant: str = "a",
    user_agent: str | None = None,
) -> str:
    """Render the landing page with an optional SMS attribution code.

    `variant` picks the primary-CTA copy (see middleware.page_hits.landing_variant)
    and is echoed into <body data-variant> so the tap beacon reports what was
    actually on screen rather than re-deriving it. `user_agent` only selects the
    sms: body separator; it is never stored here.
    """
    pretty = _pretty_number(number)
    sms = re.sub(r"[^\d+]", "", number or "")
    body = SMS_PREFILL + (f" ({code})" if code else "")
    if code and sms:
        sms_href = f"/go/{code}"
    else:
        sms_href = f"sms:{sms}{sms_separator(user_agent)}body={quote(body)}"
    label = _cta_label(pretty, variant)

    # QR code for desktop visitors. The /go/ path records a server-side sms_tap
    # on scan — same mechanism as the mobile CTA (ENG-010). A "qr" suffix on the
    # attribution code makes QR-originated starts separable in the funnel from
    # mobile taps that share the same campaign code.
    qr_attr_code = (code[:30] + "qr") if code else "qr"
    _qr_html = _qr_svg(f"https://www.texthal.com/go/{qr_attr_code}") if number and sms else ""
    qr_block = (
        f'<div class="qr-desk-block" data-qr-url="/go/{qr_attr_code}">'
        f'<div class="qr-img">{_qr_html}</div>'
        f'<div class="qr-copy">'
        f'<p class="qr-label">Scan from your phone to open Messages</p>'
        f'<p class="qr-num">{pretty}</p>'
        f'</div></div>'
    ) if _qr_html else ""

    # Three CTAs: hero (above the fold), sticky mobile bar, and the closing
    # section. Paid traffic lands on the hero and mostly never scrolls. The hero
    # and sticky bar carry the A/B copy and NO number line — a second line under
    # the button crowded the hero and buried the button it was explaining. The
    # closing section stays constant and is the one place the number is always
    # spelled out, which is also where a desktop visitor can copy it.
    hero_cta = (
        f'<div class="cta-block" id="herocta">'
        f'<div class="cta-preview"><span class="sms-bubble">"Hi HAL — new baby here 👶"</span><p class="sms-preview-hint">Tap to send · HAL replies instantly</p></div>'
        f'<div class="cta-row">'
        f'<a class="number primary-cta cta-lg" href="{sms_href}">'
        f'<span>{label}</span><span class="cta-arrow" aria-hidden="true">→</span></a>'
        f'{qr_block}'
        f'</div>'
        f'<p class="cta-mob-hint">Opens your Messages app · one text to start.</p>'
        f'</div>'
        if number
        else '<p class="number soon">coming soon</p>'
    )
    cta = (
        f'<div class="cta-block"><a class="number primary-cta" href="{sms_href}">'
        '<span>Text HAL</span><span class="cta-arrow" aria-hidden="true">→</span></a>'
        f'<p class="hint"><button type="button" class="copy-num" data-num="{sms}">{pretty}</button>'
        '<span class="hint-mob"> · no app, nothing to install</span>'
        '<span class="hint-desk"> · text from your phone (tap to copy)</span></p></div>'
        if number
        else '<p class="number soon">coming soon</p>'
    )
    sticky_cta = (
        f'<div class="sticky-cta" id="stickycta"><a class="sticky-btn" href="{sms_href}">'
        f'<span>{label}</span><span aria-hidden="true">→</span></a></div>'
        if number
        else ""
    )
    body_class = (
        f' class="has-sticky" data-variant="{variant}"'
        if number
        else f' data-variant="{variant}"'
    )
    nav_cta = (
        f'<a class="nav-cta" href="{sms_href}">Text HAL <span aria-hidden="true">→</span></a>'
        if number
        else '<a class="nav-cta" href="#start">Coming soon</a>'
    )

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#f5f4ee">
<title>HAL — the baby log that lives in your group chat</title>
<meta name="description" content="Your whole household on one baby schedule. Parents, nanny, grandma text feeds and naps to the family thread — HAL keeps one record, forecasts the next nap, and recaps the day. No app.">
<meta name="application-name" content="HAL">
<meta property="og:site_name" content="HAL">
<meta property="og:title" content="HAL — the baby log that lives in your group chat">
<meta property="og:description" content="One calm, shared baby log for the whole household. Just text.">
<meta property="og:type" content="website">
<meta property="og:url" content="https://www.texthal.com/">
<link rel="canonical" href="https://www.texthal.com/">
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"WebSite","name":"HAL","alternateName":"texthal.com","url":"https://www.texthal.com/"}}</script>
<style>
  :root {{
    color-scheme: light;
    --ink:#202124; --muted:#5f6368; --paper:#f6f5f1; --white:#fff;
    --green:#153f32; --green-soft:#dff4e8; --green-bright:#b9f8d3;
    --blue:#1b6ef3; --blue-soft:#e4eefc; --lilac:#eee3ff;
    --peach:#ffebe3; --line:rgba(32,33,36,.14);
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html {{ scroll-behavior:smooth; background:var(--paper); }}
  body {{
    background:var(--paper); color:var(--ink); min-height:100vh;
    font-family:"Helvetica Neue", Helvetica, Arial, system-ui, sans-serif;
    -webkit-font-smoothing:antialiased; overflow-x:hidden;
  }}
  a {{ color:inherit; }}
  .site-nav {{
    height:76px; padding:0 clamp(20px, 4vw, 64px); display:flex;
    align-items:center; justify-content:space-between; position:absolute;
    inset:0 0 auto; z-index:10; color:var(--ink);
  }}
  .brand {{ display:flex; align-items:center; gap:11px; text-decoration:none;
    font-size:18px; font-weight:650; letter-spacing:-.02em; }}
  .brand img {{ width:36px; height:36px; border-radius:10px; display:block; }}
  .nav-links {{ display:flex; align-items:center; gap:34px; font-size:14px; font-weight:600; }}
  .nav-links > a:not(.nav-cta) {{ color:var(--ink); text-decoration:none; opacity:.82; }}
  .nav-links > a:not(.nav-cta):hover {{ opacity:1; }}
  .nav-cta {{ background:var(--green); color:#fff; border-radius:999px;
    padding:11px 17px; text-decoration:none; display:inline-flex; gap:9px; align-items:center; }}

  /* Hero is a real two-column grid: text | phone <img>. It was previously a
     full-bleed background image with the phone baked in at 69% across — at
     aspect ratios other than 2:1, object-fit:cover slid the phone left into
     the headline (Adnan hit the collision live on 2026-08-09). Layout in the
     grid means overlap is impossible at any viewport. The pastel gradient the
     image carried is now plain CSS; text colours keep their ENG-014 AA picks. */
  .hero {{
    min-height:920px; position:relative; display:grid; place-items:center;
    color:var(--green); overflow:hidden; padding:130px 24px 90px;
    background:
      radial-gradient(70% 100% at 74% 42%, rgba(255,255,255,.55) 0%,
        rgba(255,255,255,.18) 45%, rgba(255,255,255,0) 75%),
      linear-gradient(105deg, #efe2ea 0%, #ece1ef 30%, #e4e6f5 62%, #dfe9f7 100%);
  }}
  .hero::after {{
    content:""; position:absolute; left:0; right:0; bottom:0; height:38%; z-index:0;
    background:linear-gradient(0deg, rgba(206,190,214,.30), rgba(206,190,214,0));
  }}
  .hero-inner {{ width:min(1280px, 100%); position:relative; z-index:1; text-align:left;
    display:grid; grid-template-columns:minmax(0,1fr) clamp(280px, 26vw, 380px);
    gap:clamp(32px, 4vw, 72px); align-items:center; }}
  .hero-phone {{ max-width:100%; max-height:min(74vh, 690px); width:auto; height:auto;
    justify-self:end;
    filter:drop-shadow(0 34px 60px rgba(86,60,102,.30)) drop-shadow(0 8px 18px rgba(86,60,102,.16)); }}
  .eyebrow {{ font-size:13px; font-weight:700; letter-spacing:.11em; text-transform:uppercase; }}
  .hero .eyebrow {{ color:#48685a; }}
  .hero h1 {{
    max-width:980px; margin:26px 0 28px; font-size:clamp(48px, 5.6vw, 80px);
    line-height:.96; letter-spacing:-.025em; font-weight:500;
  }}
  .hero h1 .h1-l2 {{ display:block; }}
  .nw {{ white-space:nowrap; }}
  .rot-word {{ display:inline-block; min-width:5.6ch; text-align:left; color:#128a47;
    transition:opacity .24s ease, transform .24s ease; }}
  .rot-word.rot-out {{ opacity:0; transform:translateY(10px); }}
  @media (prefers-reduced-motion:reduce) {{ .rot-word {{ transition:none; }} }}
  .hero-copy {{ max-width:590px; margin:0; font-size:clamp(18px, 2vw, 24px);
    line-height:1.45; letter-spacing:-.015em; color:#41584c; }}
  .hero .cta-block {{ margin-top:38px; }}
  .hero-chips {{ display:flex; flex-wrap:wrap; justify-content:flex-start; gap:10px; margin-top:30px; }}
  .chip {{ padding:10px 15px; border-radius:999px; font-size:13px; font-weight:650;
    border:1px solid rgba(32,33,36,.08); }}
  .chip:nth-child(1) {{ background:#e8fffc; color:#02756e; }}
  .chip:nth-child(2) {{ background:#f7e9ff; color:#5a2f90; }}
  .chip:nth-child(3) {{ background:#e5f6ff; color:#004f66; }}
  .scroll-cue {{ position:absolute; bottom:32px; left:clamp(20px, 4vw, 64px);
    z-index:2; display:flex; gap:12px; align-items:center; font-size:13px; color:#4d6c5d; }}
  .scroll-cue::before {{ content:"↓"; border:1px solid rgba(21,63,50,.32); width:35px;
    height:35px; border-radius:50%; display:grid; place-items:center; }}

  .section {{ padding:clamp(80px, 11vw, 160px) clamp(20px, 4vw, 64px); }}
  .section-inner {{ width:min(1280px, 100%); margin:0 auto; }}
  .intro {{ background:var(--paper); }}
  .intro-grid {{ display:grid; grid-template-columns:minmax(0, .8fr) minmax(0, 1.2fr);
    gap:clamp(48px, 10vw, 150px); align-items:start; }}
  .kicker {{ color:var(--blue); font-size:14px; font-weight:700; letter-spacing:.08em;
    text-transform:uppercase; margin-bottom:22px; }}
  .display {{ font-size:clamp(40px, 5.7vw, 82px); line-height:.98; letter-spacing:-.025em; font-weight:500; }}
  .intro-copy {{ font-size:clamp(22px, 3vw, 39px); line-height:1.18; letter-spacing:-.04em;
    max-width:720px; color:#3c4043; }}
  .intro-copy strong {{ color:var(--green); font-weight:600; }}

  .demo-stage {{ background:var(--green-soft); padding-top:100px; padding-bottom:100px; }}
  .demo-header {{ display:flex; justify-content:space-between; gap:40px; align-items:end;
    margin-bottom:64px; }}
  .demo-header h2 {{ max-width:750px; }}
  .demo-header p {{ max-width:360px; font-size:18px; line-height:1.5; color:#315646; }}
  .phone-row {{ display:grid; grid-template-columns:repeat(3, 1fr); gap:18px; align-items:start; }}
  .story-card {{ min-width:0; }}
  .phone-wrap {{ border-radius:40px; padding:clamp(16px, 2vw, 28px); min-height:660px;
    display:flex; align-items:center; justify-content:center; overflow:hidden; }}
  .story-card:nth-child(1) .phone-wrap {{ background:#f5dfe6; }}
  .story-card:nth-child(2) .phone-wrap {{ background:var(--blue-soft); }}
  .story-card:nth-child(3) .phone-wrap {{ background:var(--lilac); }}
  .phone {{ background:#111; border-radius:42px; padding:9px; width:min(100%, 330px);
    box-shadow:0 30px 70px rgba(21,63,50,.18); }}
  .screen {{ background:#fff; border-radius:34px; padding:12px 11px 20px; text-align:left;
    min-height:570px; overflow:hidden; }}
  .statusbar {{ display:flex; justify-content:space-between; align-items:center;
    padding:3px 12px 9px; color:#111; font-size:12px; font-weight:700; }}
  .status-icons {{ letter-spacing:1px; font-size:10px; }}
  .chathead {{ text-align:center; padding-bottom:10px; border-bottom:1px solid #ececee; }}
  .avatars {{ display:flex; justify-content:center; margin-bottom:5px; }}
  .av {{ width:25px; height:25px; border-radius:50%; color:#fff; font-size:10px; font-weight:700;
    display:flex; align-items:center; justify-content:center; margin:0 -3px; border:2px solid #fff; }}
  .chathead .gname {{ color:#111; font-size:12px; font-weight:650; }}
  .chathead .gname span {{ color:#aaa; }}
  .daystamp {{ text-align:center; color:#8e8e93; font-size:10px; font-weight:650; margin:11px 0 8px; }}
  .m {{ display:flex; flex-direction:column; margin:0 5px 8px; }}
  .m .lbl {{ font-size:9.5px; color:#8e8e93; margin:0 11px 3px; }}
  .bb {{ max-width:88%; padding:7px 11px; border-radius:16px; font-size:12.5px;
    line-height:1.38; width:fit-content; white-space:pre-line; }}
  .in {{ align-items:flex-start; }} .in .bb {{ background:#e9e9eb; color:#111; border-bottom-left-radius:5px; }}
  .out {{ align-items:flex-end; }} .out .bb {{ background:#1477f8; color:#fff; border-bottom-right-radius:5px; }}
  .receipt {{ font-size:9.5px; color:#8e8e93; margin:3px 11px 0; align-self:flex-end; }}
  .story-copy {{ padding:26px 8px 8px; }}
  .story-num {{ font-size:12px; font-weight:700; color:#47705e; margin-bottom:10px; }}
  .story-copy h3 {{ font-size:clamp(24px, 2.4vw, 36px); line-height:1.08; letter-spacing:-.04em;
    font-weight:550; margin-bottom:12px; }}
  .story-copy p {{ color:#476052; font-size:16px; line-height:1.5; }}

  .feature {{ background:#fff; }}
  .feature-grid {{ display:grid; grid-template-columns:1fr 1fr; min-height:720px; border-radius:44px;
    overflow:hidden; background:var(--blue-soft); }}
  .feature-copy {{ padding:clamp(50px, 8vw, 110px); display:flex; flex-direction:column;
    justify-content:center; align-items:flex-start; }}
  .feature-copy h2 {{ margin-bottom:28px; max-width:700px; }}
  .feature-copy p {{ font-size:clamp(18px, 2vw, 25px); line-height:1.5; letter-spacing:-.02em;
    color:#3c526b; max-width:590px; }}
  .feature-visual {{ position:relative; min-height:650px; background:linear-gradient(150deg,#d5e8fb,#eef4fc); overflow:hidden; }}
  .orbit {{ position:absolute; width:560px; height:560px; border-radius:50%; border:1px solid rgba(27,110,243,.19);
    top:50%; left:50%; transform:translate(-50%,-50%); }}
  .orbit::before, .orbit::after {{ content:""; position:absolute; border-radius:50%; border:1px solid rgba(27,110,243,.19); inset:70px; }}
  .orbit::after {{ inset:150px; background:#fff; box-shadow:0 30px 80px rgba(27,110,243,.12); }}
  .orbit-center {{ position:absolute; z-index:2; inset:50%; transform:translate(-50%,-50%); width:110px; height:110px;
    background:var(--green); color:var(--green-bright); border-radius:31px; display:grid; place-items:center;
    font-size:28px; font-weight:750; box-shadow:0 20px 45px rgba(21,63,50,.28); }}
  .orbit-item {{ position:absolute; z-index:3; background:#fff; border-radius:999px; padding:13px 18px;
    box-shadow:0 12px 30px rgba(32,33,36,.1); font-size:14px; font-weight:650; }}
  .oi-1 {{ top:21%; left:17%; }} .oi-2 {{ top:30%; right:10%; }}
  .oi-3 {{ bottom:25%; left:10%; }} .oi-4 {{ bottom:15%; right:17%; }}

  .values {{ background:var(--paper); }}
  .value-head {{ display:grid; grid-template-columns:1fr 1fr; gap:60px; align-items:end; margin-bottom:72px; }}
  .value-head p {{ max-width:560px; font-size:20px; line-height:1.55; color:var(--muted); }}
  .value-cards {{ display:grid; grid-template-columns:repeat(2,1fr); gap:18px; }}
  .value-card {{ min-height:330px; border-radius:34px; padding:38px; display:flex; flex-direction:column;
    justify-content:space-between; }}
  .value-card:nth-child(1) {{ background:#e7f5dd; }} .value-card:nth-child(2) {{ background:#ffebe8; }}
  .value-card:nth-child(3) {{ background:#eddcff; }} .value-card:nth-child(4) {{ background:#deeff4; }}
  .value-icon {{ width:54px; height:54px; border:1px solid rgba(32,33,36,.2); border-radius:50%; display:grid;
    place-items:center; font-size:22px; }}
  .value-card h3 {{ font-size:clamp(27px, 3vw, 43px); line-height:1.05; letter-spacing:-.045em;
    font-weight:550; max-width:450px; margin-bottom:14px; }}
  .value-card p {{ font-size:16px; line-height:1.55; color:#4c5150; max-width:500px; }}

  .privacy-panel {{ background:var(--green); color:#fff; border-radius:44px; padding:clamp(52px, 8vw, 110px);
    display:grid; grid-template-columns:.8fr 1.2fr; gap:70px; align-items:center; }}
  .shield {{ width:150px; aspect-ratio:1; border-radius:50%; background:var(--green-bright); color:var(--green);
    display:grid; place-items:center; font-size:58px; }}
  .privacy-panel .kicker {{ color:var(--green-bright); }}
  .privacy-panel h2 {{ font-size:clamp(40px, 5.5vw, 76px); line-height:1; letter-spacing:-.025em;
    font-weight:500; margin-bottom:28px; }}
  .privacy-panel p {{ color:#d8ecdf; font-size:19px; line-height:1.55; max-width:680px; }}
  .privacy-list {{ display:grid; gap:13px; margin-top:28px; list-style:none; color:#fff; font-size:16px; }}
  .privacy-list li::before {{ content:"✓"; color:var(--green-bright); margin-right:12px; }}

  .faq {{ background:#fff; }}
  .faq-grid {{ display:grid; grid-template-columns:.7fr 1.3fr; gap:clamp(50px, 9vw, 130px); }}
  .faq-list {{ border-top:1px solid var(--line); }}
  details {{ border-bottom:1px solid var(--line); padding:25px 0; }}
  summary {{ cursor:pointer; list-style:none; display:flex; align-items:center; justify-content:space-between;
    gap:24px; font-size:19px; font-weight:550; }}
  summary::-webkit-details-marker {{ display:none; }}
  summary::after {{ content:"+"; font-size:28px; font-weight:300; }}
  details[open] summary::after {{ content:"−"; }}
  details p {{ color:var(--muted); line-height:1.65; max-width:650px; padding:18px 50px 0 0; }}

  .final-cta {{ background:var(--blue); color:#fff; text-align:center; position:relative; overflow:hidden; }}
  .final-cta::before {{ content:""; position:absolute; width:620px; height:620px; border-radius:50%;
    background:#90f4ea; opacity:.18; top:-420px; left:calc(50% - 310px); }}
  .final-cta .section-inner {{ position:relative; }}
  .final-cta h2 {{ font-size:clamp(52px, 8vw, 112px); line-height:.92; letter-spacing:-.025em;
    font-weight:500; max-width:900px; margin:0 auto 38px; }}
  .primary-cta {{ display:inline-flex; align-items:center; gap:32px; background:var(--ink); color:#fff;
    padding:18px 20px 18px 27px; border-radius:999px; text-decoration:none; font-size:18px; font-weight:650;
    box-shadow:0 12px 30px rgba(0,0,0,.18); transition:transform .18s ease, background .18s ease; }}
  .primary-cta:hover {{ transform:translateY(-2px); background:#000; }}
  .cta-arrow {{ width:34px; height:34px; border-radius:50%; background:#fff; color:#111; display:grid; place-items:center; }}
  .cta-lg {{ font-size:21px; padding:21px 22px 21px 34px; gap:38px; }}
  .cta-lg .cta-arrow {{ width:40px; height:40px; font-size:19px; }}
  .number.soon {{ display:inline-block; font-size:24px; font-weight:650; border-radius:999px; background:rgba(255,255,255,.16); padding:18px 28px; }}
  .hint {{ color:rgba(255,255,255,.78); margin-top:15px; font-size:14px; }}

  /* Hero CTA — solid brand green on the light hero. #178a4c on white text is
     ~3.9:1, passing AA for this large bold label. */
  .hero .primary-cta {{ background:#178a4c; color:#fff;
    box-shadow:0 14px 34px rgba(86,60,102,.24); }}
  .hero .primary-cta:hover {{ background:#0f7a3f; }}
  .hero .cta-arrow {{ background:#fff; color:#128a47; }}
  .hero .hint {{ color:#4c6b5c; }}

  .copy-num {{ background:none; border:0; padding:0; font:inherit; color:inherit; }}
  .hint-desk {{ display:none; }}
  html.desk .copy-num {{ cursor:pointer; text-decoration:underline; text-underline-offset:3px; }}
  html.desk .hint-mob {{ display:none; }}
  html.desk .hint-desk {{ display:inline; }}

  /* Sticky mobile CTA. Shown by CSS (fail-open) and hidden by JS only while the
     hero CTA is already in view. Everything below the fold still has one tap. */
  .sticky-cta {{ display:none; position:fixed; left:0; right:0; bottom:0; z-index:30;
    padding:10px 14px calc(10px + env(safe-area-inset-bottom, 0px));
    background:rgba(11,40,32,.97); border-top:1px solid rgba(255,255,255,.14);
    transition:transform .24s ease; }}
  .sticky-cta.is-hidden {{ transform:translateY(115%); }}
  .sticky-btn {{ display:flex; align-items:center; justify-content:center; gap:11px;
    background:var(--green-bright); color:var(--green); border-radius:999px;
    padding:16px 18px; font-size:17px; font-weight:700; letter-spacing:-.01em;
    text-decoration:none; }}

  .cta-preview {{ display:none; margin-bottom:16px; }}
  .sms-bubble {{ display:inline-block; background:#fff; border:1px solid rgba(21,63,50,.16); border-radius:18px 18px 18px 5px; padding:9px 15px; font-size:14px; color:#2f4a3e; font-style:italic; box-shadow:0 4px 14px rgba(86,60,102,.10); }}
  .sms-preview-hint {{ font-size:12px; color:#54725f; margin-top:6px; }}
  .cta-mob-hint {{ display:none; font-size:13px; color:#4c6b5c; margin-top:10px; }}

  footer {{ background:#fff; padding:40px clamp(20px, 4vw, 64px); }}
  .footer-inner {{ width:min(1280px,100%); margin:0 auto; display:flex; align-items:center;
    justify-content:space-between; gap:25px; color:#5f6368; font-size:13px; }}
  .footer-brand {{ color:var(--ink); font-weight:700; font-size:18px; }}
  .footer-links {{ display:flex; flex-wrap:wrap; gap:24px; }}
  .footer-links a {{ color:inherit; text-decoration:none; }}
  a:focus-visible, summary:focus-visible {{ outline:3px solid #90f4ea; outline-offset:4px; }}

  @media (max-width:980px) {{
    .hero {{ min-height:800px; }}
    /* Stack: text (CTA stays above the fold), phone below at product-shot size. */
    .hero-inner {{ grid-template-columns:1fr; gap:44px; }}
    .hero-phone {{ justify-self:center; max-height:460px; }}
    .intro-grid, .value-head, .privacy-panel, .faq-grid {{ grid-template-columns:1fr; }}
    .phone-row {{ grid-template-columns:1fr; gap:54px; }}
    .phone-wrap {{ min-height:620px; }}
    .demo-header {{ align-items:start; flex-direction:column; }}
    .feature-grid {{ grid-template-columns:1fr; }}
    .feature-visual {{ min-height:560px; order:-1; }}
    .privacy-panel {{ gap:45px; }}
  }}
  @media (max-width:820px) {{
    .sticky-cta {{ display:block; }}
    body.has-sticky {{ padding-bottom:92px; }}
    .cta-preview {{ display:block; }}
    .cta-mob-hint {{ display:block; }}
  }}
  @media (max-width:680px) {{
    .site-nav {{ height:68px; }} .nav-links > a:not(.nav-cta) {{ display:none; }}
    .nav-cta {{ padding:9px 14px; }}
    .hero {{ min-height:750px; padding-top:104px; }}
    /* Tighter hero rhythm so the CTA clears the fold on a 667px-tall phone. */
    .hero h1 {{ margin:20px 0 20px; }}
    .hero .cta-block {{ margin-top:26px; }}
    .hero-chips {{ margin-top:24px; }}
    .cta-lg {{ font-size:19px; padding:18px 19px 18px 28px; gap:26px; }}
    .cta-lg .cta-arrow {{ width:36px; height:36px; font-size:17px; }}
    .hero-inner {{ gap:36px; }}
    .hero-phone {{ max-height:420px; }}
    .hero h1 {{ font-size:clamp(44px, 13vw, 80px); }}
    .scroll-cue {{ display:none; }}
    .intro-grid {{ gap:36px; }}
    .demo-header {{ margin-bottom:40px; }}
    .phone-wrap {{ min-height:570px; border-radius:28px; padding:16px; }}
    .feature-grid, .privacy-panel {{ border-radius:28px; }}
    .feature-visual {{ min-height:460px; }}
    .orbit {{ width:410px; height:410px; }} .orbit::before {{ inset:50px; }} .orbit::after {{ inset:115px; }}
    .orbit-center {{ width:82px; height:82px; border-radius:24px; font-size:22px; }}
    .orbit-item {{ font-size:12px; padding:10px 13px; }}
    .oi-1 {{ left:6%; }} .oi-2 {{ right:3%; }} .oi-3 {{ left:2%; }} .oi-4 {{ right:6%; }}
    .value-cards {{ grid-template-columns:1fr; }} .value-card {{ min-height:290px; padding:30px; }}
    .shield {{ width:108px; font-size:42px; }}
    .footer-inner {{ align-items:flex-start; flex-direction:column; }}
  }}
  @media (prefers-reduced-motion:reduce) {{ html {{ scroll-behavior:auto; }}
    .primary-cta, .sticky-cta {{ transition:none; }} }}

  /* Desktop QR block — hidden on mobile, shown when JS adds .desk to <html>.
     Sits to the RIGHT of the CTA button (Adnan, 2026-08-11), sized down so the
     button stays the loudest thing in the row. */
  .cta-row {{ display:flex; align-items:center; gap:34px; flex-wrap:wrap; }}
  .qr-desk-block {{ display:none; }}
  html.desk .qr-desk-block {{ display:flex; align-items:center; gap:13px; }}
  .qr-img svg {{ width:104px; height:104px; flex-shrink:0; border-radius:8px; display:block; }}
  .qr-copy {{ display:flex; flex-direction:column; justify-content:center; max-width:190px; }}
  .qr-label {{ font-size:12px; color:#48685a; margin-bottom:6px; font-weight:500; line-height:1.35; }}
  .qr-num {{ font-size:15px; font-weight:650; color:var(--green); letter-spacing:-.01em; }}

  /* Trust badges under the hero CTA chips */
  .hero-trust {{ display:flex; flex-wrap:wrap; gap:6px 20px; margin-top:16px; }}
  .trust-badge {{ font-size:13px; color:#3f6553; font-weight:600; letter-spacing:-.01em; }}
  .trust-badge::before {{ content:"✓\u00a0"; color:#128a47; }}

  /* How it works — 3-step strip immediately below the hero */
  .how-steps {{ background:#fff; padding:60px clamp(20px, 4vw, 64px); border-bottom:1px solid var(--line); }}
  .how-steps-inner {{ width:min(1280px, 100%); margin:0 auto; }}
  .how-steps-label {{ font-size:13px; font-weight:700; letter-spacing:.1em; text-transform:uppercase;
    color:var(--muted); margin-bottom:40px; }}
  .steps-row {{ display:grid; grid-template-columns:repeat(3,1fr); gap:32px; }}
  .step-item {{ display:flex; flex-direction:column; gap:14px; }}
  .step-num {{ width:38px; height:38px; border-radius:50%; background:var(--green); color:var(--green-bright);
    font-size:14px; font-weight:700; display:grid; place-items:center; flex-shrink:0; }}
  .step-item h3 {{ font-size:clamp(19px, 2.1vw, 27px); font-weight:550; letter-spacing:-.035em;
    line-height:1.1; }}
  .step-item p {{ font-size:15px; color:var(--muted); line-height:1.55; max-width:380px; }}
  @media (max-width:680px) {{
    .steps-row {{ grid-template-columns:1fr; gap:28px; }}
    .how-steps {{ padding:48px clamp(20px, 4vw, 64px); }}
  }}
</style></head>
<body{body_class}>
  <nav class="site-nav" aria-label="Main navigation">
    <a class="brand" href="#top"><img src="{LOGO_DATA_URI}" alt=""><span>HAL</span></a>
    <div class="nav-links">
      <a href="#how">How it works</a><a href="#privacy">Privacy</a>{nav_cta}
    </div>
  </nav>

  <main id="top">
    <section class="hero">
      <div class="hero-inner">
        <div class="hero-text">
          <p class="eyebrow">HAL — the baby log that lives in your group chat.</p>
          <h1>A calmer way to keep <span class="h1-l2">up with <span class="nw">baby's <span id="rotator" class="rot-word">naps.</span></span></span></h1>
          <p class="hero-copy">HAL turns the family group chat into one reliable baby schedule—without asking anyone to learn another app.</p>
          {hero_cta}
          <div class="hero-chips" aria-label="Trust highlights">
            <span class="chip">No account</span><span class="chip">No password</span><span class="chip">No app to install</span>
          </div>
          <div class="hero-trust" aria-label="Privacy assurance">
            <span class="trust-badge">Your number is never sold or shared</span>
            <span class="trust-badge">Delete everything with one text</span>
          </div>
        </div>
        <img class="hero-phone" src="/static/hero-phone.png"
          alt="Family group chat where HAL logs a feed and a nap and answers Grandma"
          fetchpriority="high">
      </div>
      <div class="scroll-cue" aria-hidden="true">See how HAL helps</div>
    </section>

    <section class="how-steps" id="how" aria-labelledby="how-steps-label">
      <div class="how-steps-inner">
        <p class="how-steps-label" id="how-steps-label">How it works</p>
        <div class="steps-row">
          <div class="step-item">
            <div class="step-num" aria-hidden="true">1</div>
            <h3>Add HAL to the family thread</h3>
            <p>One text to start — no sign-up form, no download, no new accounts for anyone.</p>
          </div>
          <div class="step-item">
            <div class="step-num" aria-hidden="true">2</div>
            <h3>Everyone texts in naturally</h3>
            <p>Feeds, naps, notes — HAL understands plain language and keeps one shared record the whole household can trust.</p>
          </div>
          <div class="step-item">
            <div class="step-num" aria-hidden="true">3</div>
            <h3>Ask back any time</h3>
            <p>"What's the schedule today?" HAL has the full picture and tells you what is likely next from your baby's own rhythm.</p>
          </div>
        </div>
      </div>
    </section>

    <section class="section intro" aria-labelledby="intro-title">
      <div class="section-inner intro-grid">
        <div><p class="kicker">Made for real households</p><h2 class="display" id="intro-title">Everyone texts. HAL remembers.</h2></div>
        <p class="intro-copy">Parents, nanny, grandma—everyone logs feeds and naps the way they already talk. <strong>HAL keeps one record straight</strong>, quietly does the schedule math, and tells the family what is likely next.</p>
      </div>
    </section>

    <section class="section demo-stage" aria-labelledby="demo-title">
      <div class="section-inner">
        <div class="demo-header"><h2 class="display" id="demo-title">One thread. Three calmer moments.</h2><p>Everything here is a real part of HAL: shared logging, day summaries, and useful heads-ups.</p></div>
        <div class="phone-row">
          <article class="story-card">
            <div class="phone-wrap"><div class="phone"><div class="screen">
              <div class="statusbar"><span>3:15</span><span class="status-icons">● ◒ ▰</span></div>
              <div class="chathead"><div class="avatars"><span class="av" style="background:#ec6ba8">M</span><span class="av" style="background:#5b9cf5">D</span><span class="av" style="background:#e8a13c">N</span><span class="av" style="background:#1c644c">H</span></div><div class="gname">Leo HQ <span>›</span></div></div>
              <div class="daystamp">Today 3:15 PM</div>
              <div class="m in"><span class="lbl">Mom</span><span class="bb">4oz at 3:15</span></div>
              <div class="m in"><span class="lbl">HAL</span><span class="bb">Logged ✅ That's his 4th feed today.</span></div>
              <div class="m out"><span class="bb">down for a nap 😴</span></div>
              <div class="m in"><span class="lbl">HAL</span><span class="bb">Logged 💤 He'll likely wake around 5:15 — I'll size his next window when he's up.</span></div>
              <div class="m in"><span class="lbl">Grandma</span><span class="bb">how's his day going?</span></div>
              <div class="m in"><span class="lbl">HAL</span><span class="bb">3 naps, 5 feeds — last at 3:15. Bedtime's usually around 7:15 💛</span></div>
            </div></div></div>
            <div class="story-copy"><p class="story-num">01 · LOG TOGETHER</p><h3>Everyone stays in sync.</h3><p>Whoever is on duty just texts the thread. Handoffs stop feeling like a briefing.</p></div>
          </article>

          <article class="story-card">
            <div class="phone-wrap"><div class="phone"><div class="screen">
              <div class="statusbar"><span>6:42</span><span class="status-icons">● ◒ ▰</span></div>
              <div class="chathead"><div class="avatars"><span class="av" style="background:#ec6ba8">M</span><span class="av" style="background:#5b9cf5">D</span><span class="av" style="background:#e8a13c">N</span><span class="av" style="background:#1c644c">H</span></div><div class="gname">Leo HQ <span>›</span></div></div>
              <div class="daystamp">Today 6:42 PM</div>
              <div class="m in"><span class="lbl">HAL</span><span class="bb">Leo's day at a glance 💛\n\n5 feeds — last at 6:10 PM\n3 naps · 2h 40m\nLast woke · 4:52 PM\n\nBedtime's usually ~7:15. He ran a little light on naps today, so a touch earlier may go down easy.</span></div>
              <div class="m out"><span class="bb">anything we should watch tonight?</span></div>
              <div class="m in"><span class="lbl">HAL</span><span class="bb">Nothing unusual in today's log. He'll likely want one more feed near bedtime.</span></div>
              <div class="m out"><span class="bb">perfect, thank you</span><span class="receipt">Delivered</span></div>
            </div></div></div>
            <div class="story-copy"><p class="story-num">02 · SEE THE DAY</p><h3>The recap is already done.</h3><p>Ask where the day stands and get the whole picture—feeds, naps, and what is likely next.</p></div>
          </article>

          <article class="story-card">
            <div class="phone-wrap"><div class="phone"><div class="screen">
              <div class="statusbar"><span>7:02</span><span class="status-icons">● ◒ ▰</span></div>
              <div class="chathead"><div class="avatars"><span class="av" style="background:#ec6ba8">M</span><span class="av" style="background:#5b9cf5">D</span><span class="av" style="background:#e8a13c">N</span><span class="av" style="background:#1c644c">H</span></div><div class="gname">Leo HQ <span>›</span></div></div>
              <div class="daystamp">Today 7:02 AM</div>
              <div class="m in"><span class="lbl">HAL</span><span class="bb">Good morning ☀️ A few things for today:\n\n💉 Leo's 6-month vaccines are at 9:20 AM.\n\n🌧️ Rain is expected from 8–11 AM. Bring the stroller cover.\n\n🚗 The drive is trending 12 minutes slower. Leave by 8:35.</span></div>
              <div class="m out"><span class="bb">remind everyone when it's time to leave</span></div>
              <div class="m in"><span class="lbl">HAL</span><span class="bb">You got it — I'll text the group at 8:30 👍</span></div>
              <div class="m out"><span class="receipt">Read 7:03 AM</span></div>
            </div></div></div>
            <div class="story-copy"><p class="story-num">03 · STAY AHEAD</p><h3>The day comes to you.</h3><p>Appointments, weather, and the drive show up together—before the morning gets noisy.</p></div>
          </article>
        </div>
      </div>
    </section>

    <section class="section feature" aria-labelledby="one-place-title">
      <div class="section-inner feature-grid">
        <div class="feature-copy"><p class="kicker">The household, connected</p><h2 class="display" id="one-place-title">Bring the whole day into one place.</h2><p>No shared passwords. No per-seat fees. No “did you put it in the app?” HAL follows the conversation and keeps the useful parts organized.</p></div>
        <div class="feature-visual" aria-label="HAL connects parents, caregivers, schedules, and daily baby logs">
          <div class="orbit"></div><div class="orbit-center">HAL</div>
          <span class="orbit-item oi-1">Mom · 4oz 🍼</span><span class="orbit-item oi-2">Nanny · nap 😴</span><span class="orbit-item oi-3">Calendar · 9:20</span><span class="orbit-item oi-4">Grandma · recap?</span>
        </div>
      </div>
    </section>

    <section class="section values" aria-labelledby="values-title">
      <div class="section-inner">
        <div class="value-head"><div><p class="kicker">Built for the 3 AM version of you</p><h2 class="display" id="values-title">Less managing. More knowing.</h2></div><p>HAL lives where the family already talks and turns small updates into a clear picture everyone can use.</p></div>
        <div class="value-cards">
          <article class="value-card"><div class="value-icon" aria-hidden="true">↗</div><div><h3>Natural in. Useful out.</h3><p>“4oz at 3:15” is enough. HAL understands the update and keeps the day current.</p></div></article>
          <article class="value-card"><div class="value-icon" aria-hidden="true">◷</div><div><h3>It quietly does the math.</h3><p>Get the next likely nap window, sized to your baby's own rhythm and shared with honest uncertainty.</p></div></article>
          <article class="value-card"><div class="value-icon" aria-hidden="true">◎</div><div><h3>No app. Ever.</h3><p>One thumb, one text, screen off. There is nothing new for the household to download or maintain.</p></div></article>
          <article class="value-card"><div class="value-icon" aria-hidden="true">⌁</div><div><h3>Yours, and disposable.</h3><p>Say “export” for your full log. Say “forget me” and everything is permanently deleted.</p></div></article>
        </div>
      </div>
    </section>

    <section class="section" id="privacy" aria-labelledby="privacy-title">
      <div class="section-inner privacy-panel">
        <div class="shield" aria-hidden="true">✓</div>
        <div><p class="kicker">Personal, private, in your control</p><h2 id="privacy-title">Your family’s data stays yours.</h2><p>HAL is designed around a simple promise: your household information should help your household—and nobody else. Your family's data is never sold, never ads, and never used to train anything.</p>
          <ul class="privacy-list"><li>Never sold, never ads</li><li>Never used to train anything</li><li>Export or permanently delete it by text</li></ul>
        </div>
      </div>
    </section>

    <section class="section faq" aria-labelledby="faq-title">
      <div class="section-inner faq-grid">
        <div><p class="kicker">Good to know</p><h2 class="display" id="faq-title">Questions, answered.</h2></div>
        <div class="faq-list">
          <details><summary>Do we all need to install something?</summary><p>No. HAL works over text. Add HAL to the family thread and everyone can participate from the messaging app already on their phone.</p></details>
          <details><summary>What can HAL keep track of?</summary><p>HAL can log feeds, naps, wake-ups, and other baby-day updates, summarize the day, and estimate what is likely next from your baby's own recent rhythm.</p></details>
          <details><summary>Can I get my data back?</summary><p>Yes. Text “export” and HAL will prepare the log as a file. Text “forget me” to permanently delete the household's stored data.</p></details>
          <details><summary>Is HAL medical advice?</summary><p>No. HAL is a household coordination and logging assistant, not a medical service. For health concerns, contact your pediatrician or another qualified professional.</p></details>
        </div>
      </div>
    </section>

    <section class="section final-cta" id="start" aria-labelledby="start-title">
      <div class="section-inner"><p class="eyebrow">Start with one text</p><h2 id="start-title">A calmer family rhythm is already in the chat.</h2>{cta}</div>
    </section>
  </main>

  <footer><div class="footer-inner"><span class="footer-brand">HAL</span><span>© 2026 HAL</span><div class="footer-links"><a href="/privacy">Privacy Policy</a><a href="/terms">Terms of Service</a></div></div></footer>
  {sticky_cta}
<script src="/static/landing.js"></script>
</body></html>"""


def _client_id(request: Request) -> tuple[str, str]:
    """(ip, user_agent) — Railway's edge proxy puts the real client in XFF."""
    fwd = request.headers.get("x-forwarded-for", "")
    ip = fwd.split(",")[0].strip() or (request.client.host if request.client else "")
    return ip, request.headers.get("user-agent", "")


_SCROLL_EVENTS = {"scroll_25", "scroll_50", "scroll_75", "scroll_100"}
_ALLOWED_EVENT_TYPES = {"sms_tap", "sms_copy"} | _SCROLL_EVENTS


async def _record_tap(
    code: str | None,
    utm_source: str | None,
    utm_medium: str | None,
    utm_campaign: str | None,
    visitor_hash: str,
    variant: str | None = None,
    event_type: str = "sms_tap",
) -> None:
    factory = db_session._session_factory
    if factory is None:
        return
    try:
        async with factory() as session:
            # Dedup: skip if this visitor already fired this event in the last 60 seconds.
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=60)
            recent = await session.scalar(
                select(func.count()).where(
                    HalFunnelEvent.event_type == event_type,
                    HalFunnelEvent.visitor_hash == visitor_hash,
                    HalFunnelEvent.created_at > cutoff,
                )
            )
            if recent:
                return
            session.add(
                HalFunnelEvent(
                    event_type=event_type,
                    attribution_code=code,
                    utm_source=utm_source,
                    utm_medium=utm_medium,
                    utm_campaign=utm_campaign,
                    visitor_hash=visitor_hash,
                    variant=variant,
                )
            )
            await session.commit()
    except Exception:
        log.exception("funnel_event.record_failed", event_type=event_type)


def build_landing_router() -> APIRouter:
    router = APIRouter()

    @router.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def landing(request: Request, c: str | None = None) -> HTMLResponse:
        code = c if c and _CODE_RX.match(c) else None
        ip, ua = _client_id(request)
        variant = landing_variant(visitor_hash(ip, ua))
        return HTMLResponse(
            render_landing(
                get_settings().hal_public_number,
                code=code,
                variant=variant,
                user_agent=ua,
            ),
            # The two arms differ in the HTML itself, so a cached copy would
            # serve one arm to everyone downstream of the cache.
            headers={"Cache-Control": "private, no-store"},
        )

    @router.post("/tap", include_in_schema=False, status_code=204)
    async def sms_tap(request: Request) -> Response:
        try:
            data = await request.json()
        except Exception:
            data = {}
        ip, ua = _client_id(request)

        def _str_field(key: str, max_len: int) -> str | None:
            v = data.get(key) if isinstance(data, dict) else None
            return (str(v)[:max_len] or None) if isinstance(v, str) else None

        code = _str_field("code", 64)
        if code and not _CODE_RX.match(code):
            code = None
        # Trust the beacon's variant (it is what was rendered) but only as one
        # of the known arms, so a hand-crafted POST can't invent buckets.
        variant = _str_field("variant", 8)
        if variant not in LANDING_VARIANTS:
            variant = None
        # Validate event_type against the whitelist so hand-crafted POSTs
        # can't invent new buckets.
        raw_event_type = _str_field("event_type", 32)
        event_type = raw_event_type if raw_event_type in _ALLOWED_EVENT_TYPES else "sms_tap"
        asyncio.get_running_loop().create_task(
            _record_tap(
                code=code,
                utm_source=_str_field("utm_source", 255),
                utm_medium=_str_field("utm_medium", 255),
                utm_campaign=_str_field("utm_campaign", 255),
                visitor_hash=visitor_hash(ip, ua),
                variant=variant,
                event_type=event_type,
            )
        )
        return Response(status_code=204)

    # Attribution tap recording: texthal.com/go/<code> records a server-side
    # sms_tap before opening Messages, bypassing iOS Safari's keepalive drop.
    # HTTP 302 redirects to sms: are blocked by iOS since iOS 8; this page
    # uses meta-refresh + a visible button (inline JS is CSP-blocked, ENG-015).
    @router.get("/go/{code}", include_in_schema=False)
    async def go(
        code: str,
        request: Request,
        utm_source: str | None = None,
        utm_medium: str | None = None,
        utm_campaign: str | None = None,
    ) -> Response:
        if not _CODE_RX.match(code):
            return RedirectResponse("/", status_code=302)

        ip, ua = _client_id(request)
        vh = visitor_hash(ip, ua)

        settings = get_settings()
        raw_number = settings.hal_public_number
        sms_raw = re.sub(r"[^\d+]", "", raw_number or "")
        sms_uri: str | None = None
        if sms_raw:
            body_text = SMS_PREFILL + f" ({code})"
            sms_uri = f"sms:{sms_raw}{sms_separator(ua)}body={quote(body_text)}"

        asyncio.get_running_loop().create_task(
            _record_tap(
                code=code,
                utm_source=utm_source,
                utm_medium=utm_medium,
                utm_campaign=utm_campaign,
                visitor_hash=vh,
                variant=None,
                event_type="sms_tap",
            )
        )

        if not sms_uri:
            return RedirectResponse("/", status_code=302)

        esc = sms_uri.replace("&", "&amp;").replace('"', "%22")
        page = (
            "<!doctype html><html><head>"
            '<meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta http-equiv="refresh" content="0;url={esc}">'
            "<title>Opening Messages\u2026</title>"
            "<style>body{font-family:system-ui,sans-serif;display:flex;flex-direction:column;"
            "align-items:center;justify-content:center;min-height:100vh;margin:0;"
            "background:#f6f5f1;color:#202124;text-align:center;padding:24px;}"
            "</style></head><body>"
            "<p style='font-size:18px;margin-bottom:20px'>Opening Messages\u2026</p>"
            f'<a href="{esc}" style="display:inline-block;background:#153f32;color:#b9f8d3;'
            "padding:16px 28px;border-radius:999px;text-decoration:none;font-size:17px;"
            "font-weight:700\">Tap to open Messages</a>"
            "<p style='margin-top:20px;font-size:14px;color:#5f6368'>"
            '<a href="/" style="color:#1b6ef3">Back to HAL</a></p>'
            "</body></html>"
        )
        return HTMLResponse(page, headers={"Cache-Control": "no-store"})

    @router.get("/static/donebottles.png", include_in_schema=False)
    async def bottles_image() -> FileResponse:
        return FileResponse(
            _BOTTLES_IMAGE,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @router.get("/static/hero-conversation.png", include_in_schema=False)
    async def hero_image() -> FileResponse:
        return FileResponse(
            _HERO_IMAGE,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @router.get("/static/hero-phone.png", include_in_schema=False)
    async def hero_phone_image() -> FileResponse:
        # Transparent phone-only cut (growth/ad_visuals/make_hero.py). The hero
        # lays it out as a grid column; the full hero-conversation.png remains
        # served above for social/ads reuse but the page no longer loads it.
        return FileResponse(
            _HERO_PHONE_IMAGE,
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @router.get("/static/landing.js", include_in_schema=False)
    async def landing_js() -> PlainTextResponse:
        # External file, not inline: the CSP is script-src 'self' with no
        # 'unsafe-inline' (ENG-015). Short max-age so deploys propagate fast.
        return PlainTextResponse(
            _LANDING_JS,
            media_type="application/javascript",
            headers={"Cache-Control": "public, max-age=300"},
        )

    @router.get("/robots.txt", include_in_schema=False)
    async def robots() -> PlainTextResponse:
        return PlainTextResponse(
            "User-agent: *\nAllow: /\nSitemap: https://www.texthal.com/sitemap.xml\n"
        )

    @router.get("/sitemap.xml", include_in_schema=False)
    async def sitemap() -> PlainTextResponse:
        pages = ["", "privacy", "terms"]
        urls = "\n".join(
            f"  <url><loc>https://www.texthal.com/{p}</loc></url>" for p in pages
        )
        return PlainTextResponse(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{urls}\n</urlset>\n",
            media_type="application/xml",
        )

    return router
