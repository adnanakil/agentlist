# ruff: noqa: E501 -- embedded HTML/CSS stays readable as authored markup.
"""GET /guides and /guides/{slug} — SEO content pages.

The search-intent layer of the site (nap schedules by age + practical guides);
content lives in routes/guide_content.py, this module is the shell. Same
constraints as the landing page: server-rendered, zero JS (the CSP would block
inline scripts anyway), light theme matching the landing brand.

Each page carries Article + BreadcrumbList JSON-LD and a CTA that routes
through the landing page with a per-guide `?c=` attribution code, so guide
-driven signups surface in acquisition_source like any other channel.
"""

from __future__ import annotations

import json

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

from hal_orchestrator.routes.guide_content import DISCLAIMER, GUIDES, GUIDES_BY_SLUG
from hal_orchestrator.routes.logo_data import LOGO_DATA_URI

_BASE = "https://www.texthal.com"

_CSS = """
  :root { color-scheme: light; --ink:#202124; --muted:#5f6368; --paper:#f6f5f1;
    --green:#153f32; --green-mid:#128a47; --green-soft:#dff4e8;
    --line:rgba(32,33,36,.14); }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:var(--paper); color:var(--ink);
    font-family:"Helvetica Neue", Helvetica, Arial, system-ui, sans-serif;
    -webkit-font-smoothing:antialiased; font-size:17px; line-height:1.65; }
  a { color:var(--green-mid); }
  .site-nav { height:72px; padding:0 clamp(20px, 4vw, 64px); display:flex;
    align-items:center; justify-content:space-between; border-bottom:1px solid var(--line); }
  .brand { display:flex; align-items:center; gap:11px; text-decoration:none;
    font-size:18px; font-weight:650; letter-spacing:-.02em; color:var(--ink); }
  .brand img { width:32px; height:32px; border-radius:9px; display:block; }
  .nav-links { display:flex; align-items:center; gap:26px; font-size:14px; font-weight:600; }
  .nav-links > a:not(.nav-cta) { color:var(--ink); text-decoration:none; opacity:.82; }
  .nav-cta { background:var(--green); color:#fff; border-radius:999px;
    padding:10px 16px; text-decoration:none; }
  .wrap { max-width:760px; margin:0 auto; padding:40px 22px 90px; }
  .crumbs { font-size:13px; color:var(--muted); margin-bottom:26px; }
  .crumbs a { color:var(--muted); }
  h1 { font-size:clamp(30px, 5vw, 42px); line-height:1.12; letter-spacing:-.02em;
    font-weight:600; color:var(--green); margin-bottom:14px; }
  .byline { font-size:14px; color:var(--muted); margin-bottom:34px;
    padding-bottom:22px; border-bottom:1px solid var(--line); }
  article h2 { font-size:24px; letter-spacing:-.015em; font-weight:600;
    color:var(--green); margin:38px 0 12px; }
  article p { margin:0 0 16px; }
  article ul, article ol { margin:0 0 16px 22px; }
  article li { margin-bottom:8px; }
  .tablewrap { overflow-x:auto; margin:0 0 16px; }
  article table { border-collapse:collapse; width:100%; background:#fff;
    border:1px solid var(--line); border-radius:10px; overflow:hidden; font-size:15px; }
  article th, article td { text-align:left; padding:10px 14px; border-bottom:1px solid var(--line); }
  article th { background:var(--green-soft); color:var(--green); font-weight:650; }
  article tr:last-child td { border-bottom:none; }
  .cta { background:var(--green-soft); border-radius:16px; padding:26px;
    margin:42px 0; }
  .cta h2 { margin-top:0; }
  .cta a.btn { display:inline-block; background:var(--green); color:#fff;
    border-radius:999px; padding:12px 20px; text-decoration:none; font-weight:600;
    margin-top:6px; }
  .sources { margin-top:44px; padding-top:20px; border-top:1px solid var(--line);
    font-size:14px; color:var(--muted); }
  .sources h2 { font-size:16px; margin:0 0 10px; color:var(--ink); }
  .sources ul { margin-left:20px; }
  .disclaimer { margin-top:22px; font-size:13px; color:var(--muted); }
  .related { margin-top:34px; }
  .related h2 { font-size:18px; color:var(--green); margin-bottom:10px; }
  .related ul { margin-left:20px; }
  .calc { background:#fff; border:1px solid var(--line); border-radius:16px;
    padding:24px; margin:10px 0 26px; }
  .calc label { display:block; font-weight:650; font-size:15px; margin:14px 0 6px; }
  .calc label:first-child { margin-top:0; }
  .calc-hint { font-weight:400; color:var(--muted); font-size:13px; }
  .calc input { font:inherit; padding:10px 12px; border:1px solid var(--line);
    border-radius:10px; width:100%; max-width:280px; background:var(--paper); }
  .calc-out { margin-top:18px; padding:16px 18px; background:var(--green-soft);
    border-radius:12px; }
  .calc-out p { margin:0 0 10px; } .calc-out p:last-child { margin-bottom:0; }
  .calc-note { font-size:13px; color:var(--muted); }
  .guide-list { list-style:none; margin:0; }
  .guide-list li { margin:0 0 18px; background:#fff; border:1px solid var(--line);
    border-radius:12px; padding:18px 20px; }
  .guide-list a { font-size:18px; font-weight:600; color:var(--green); text-decoration:none; }
  .guide-list p { margin:6px 0 0; font-size:15px; color:var(--muted); }
  .group-title { font-size:14px; font-weight:700; letter-spacing:.08em;
    text-transform:uppercase; color:var(--muted); margin:34px 0 14px; }
  footer { border-top:1px solid var(--line); padding:26px clamp(20px, 4vw, 64px);
    display:flex; flex-wrap:wrap; gap:18px; justify-content:space-between;
    font-size:14px; color:var(--muted); }
  footer a { color:inherit; text-decoration:none; margin-right:18px; }
"""


def _shell(
    *,
    title: str,
    description: str,
    canonical: str,
    structured_data: str,
    body: str,
) -> str:
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#f5f4ee">
<title>{title}</title>
<meta name="description" content="{description}">
<meta property="og:site_name" content="HAL">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:type" content="article">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="{_BASE}/static/og-card.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{title}">
<meta name="twitter:image" content="{_BASE}/static/og-card.png">
<link rel="canonical" href="{canonical}">
<link rel="icon" type="image/png" sizes="200x200" href="/static/logo.png">
<link rel="apple-touch-icon" href="/static/logo.png">
<script type="application/ld+json">{structured_data}</script>
<style>{_CSS}</style></head>
<body>
  <nav class="site-nav" aria-label="Main navigation">
    <a class="brand" href="/"><img src="{LOGO_DATA_URI}" alt=""><span>HAL</span></a>
    <div class="nav-links"><a href="/guides">Guides</a><a class="nav-cta" href="/">Text HAL →</a></div>
  </nav>
{body}
  <footer><span>© 2026 HAL</span><span><a href="/guides">Guides</a><a href="/privacy">Privacy Policy</a><a href="/terms">Terms of Service</a></span></footer>
</body></html>"""


def _fmt_date(iso: str) -> str:
    y, m, d = iso.split("-")
    months = [
        "January", "February", "March", "April", "May", "June", "July",
        "August", "September", "October", "November", "December",
    ]
    return f"{months[int(m) - 1]} {int(d)}, {y}"


def _render_guide(g: dict) -> str:
    url = f"{_BASE}/guides/{g['slug']}"
    structured_data = json.dumps(
        {
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@type": "Article",
                    "headline": g["title"],
                    "description": g["description"],
                    "url": url,
                    "datePublished": g["updated"],
                    "dateModified": g["updated"],
                    "image": f"{_BASE}/static/og-card.png",
                    "author": {"@type": "Organization", "name": "HAL", "url": f"{_BASE}/"},
                    "publisher": {"@id": f"{_BASE}/#org"},
                },
                {
                    "@type": "BreadcrumbList",
                    "itemListElement": [
                        {"@type": "ListItem", "position": 1, "name": "HAL", "item": f"{_BASE}/"},
                        {"@type": "ListItem", "position": 2, "name": "Guides", "item": f"{_BASE}/guides"},
                        {"@type": "ListItem", "position": 3, "name": g["title"], "item": url},
                    ],
                },
            ],
        }
    )

    related_items = "".join(
        f'<li><a href="/guides/{s}">{GUIDES_BY_SLUG[s]["title"]}</a></li>'
        for s in g.get("related", ())
        if s in GUIDES_BY_SLUG
    )
    related = (
        f'<div class="related"><h2>Related guides</h2><ul>{related_items}</ul></div>'
        if related_items
        else ""
    )
    sources = "".join(
        f'<li><a href="{href}" rel="noopener">{label}</a></li>'
        for label, href in g.get("sources", ())
    )

    # Wide tables scroll inside their own container on small screens.
    body_html = g["body"].replace("<table>", '<div class="tablewrap"><table>').replace(
        "</table>", "</table></div>"
    )

    body = f"""
  <main class="wrap">
    <nav class="crumbs" aria-label="Breadcrumb"><a href="/">HAL</a> › <a href="/guides">Guides</a> › {g["title"]}</nav>
    <article>
      <h1>{g["title"]}</h1>
      <p class="byline">By the HAL team · Updated {_fmt_date(g["updated"])}</p>
      {body_html}
      <div class="cta">
        <h2>Keep the schedule without keeping a spreadsheet</h2>
        <p>HAL tracks naps, feeds, and bedtime by text in your family group chat — no app, and every caregiver stays on today's actual timing.</p>
        <a class="btn" href="/?c={g["code"]}">Meet HAL →</a>
      </div>
      {related}
      <div class="sources"><h2>Sources</h2><ul>{sources}</ul>
        <p class="disclaimer">{DISCLAIMER}</p>
      </div>
    </article>
  </main>"""

    return _shell(
        title=f"{g['page_title']} — HAL",
        description=g["description"],
        canonical=url,
        structured_data=structured_data,
        body=body,
    )


def _render_index() -> str:
    structured_data = json.dumps(
        {
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@type": "CollectionPage",
                    "name": "Baby sleep & routine guides",
                    "url": f"{_BASE}/guides",
                    "description": "Practical, sourced guides to baby nap schedules, wake windows, and keeping every caregiver on one consistent routine.",
                },
                {
                    "@type": "BreadcrumbList",
                    "itemListElement": [
                        {"@type": "ListItem", "position": 1, "name": "HAL", "item": f"{_BASE}/"},
                        {"@type": "ListItem", "position": 2, "name": "Guides", "item": f"{_BASE}/guides"},
                    ],
                },
            ],
        }
    )

    groups: dict[str, list[dict]] = {}
    for g in GUIDES:
        groups.setdefault(g["category"], []).append(g)
    sections = "".join(
        f'<p class="group-title">{cat}</p><ul class="guide-list">'
        + "".join(
            f'<li><a href="/guides/{g["slug"]}">{g["title"]}</a><p>{g["teaser"]}</p></li>'
            for g in items
        )
        + "</ul>"
        for cat, items in groups.items()
    )
    sections += (
        '<p class="group-title">Tools</p><ul class="guide-list">'
        f'<li><a href="/guides/{CALCULATOR_SLUG}">Wake window calculator</a>'
        "<p>Age in, next-nap window out — free, no signup.</p></li></ul>"
    )

    body = f"""
  <main class="wrap">
    <nav class="crumbs" aria-label="Breadcrumb"><a href="/">HAL</a> › Guides</nav>
    <h1>Baby sleep &amp; routine guides</h1>
    <p class="byline">Practical, sourced answers on naps, wake windows, and keeping every caregiver on one consistent routine.</p>
    {sections}
  </main>"""

    return _shell(
        title="Baby Sleep & Routine Guides — HAL",
        description="Practical, sourced guides to baby nap schedules, wake windows by age, nap transitions, and keeping every caregiver on one consistent routine.",
        canonical=f"{_BASE}/guides",
        structured_data=structured_data,
        body=body,
    )


CALCULATOR_SLUG = "wake-window-calculator"

# Bands mirror the verified chart in guide_content wake-windows-by-age —
# keep the two in sync when either changes. Minutes.
_CALC_JS = """\
(function () {
  var BANDS = [
    { maxM: 1,  label: "0\\u20134 weeks",   lo: 30,  hi: 60,  naps: "4\\u20136+ (irregular)" },
    { maxM: 3,  label: "1\\u20133 months",  lo: 60,  hi: 90,  naps: "4\\u20135" },
    { maxM: 4,  label: "3\\u20134 months",  lo: 75,  hi: 120, naps: "3\\u20134" },
    { maxM: 6,  label: "5\\u20136 months",  lo: 120, hi: 180, naps: "3" },
    { maxM: 9,  label: "7\\u20139 months",  lo: 150, hi: 210, naps: "2\\u20133 \\u2192 2" },
    { maxM: 12, label: "10\\u201312 months", lo: 180, hi: 240, naps: "2" },
    { maxM: 18, label: "13\\u201318 months", lo: 180, hi: 300, naps: "2 \\u2192 1" },
    { maxM: 24, label: "18\\u201324 months", lo: 240, hi: 360, naps: "1" }
  ];
  function band(months) {
    for (var i = 0; i < BANDS.length; i++) if (months <= BANDS[i].maxM) return BANDS[i];
    return BANDS[BANDS.length - 1];
  }
  function fmtDur(min) {
    if (min < 120) return min + " min";
    var h = min / 60;
    return (h % 1 ? h.toFixed(1) : h) + " h";
  }
  function fmtTime(d) {
    var h = d.getHours(), m = d.getMinutes(), ap = h >= 12 ? "PM" : "AM";
    h = h % 12 || 12;
    return h + ":" + (m < 10 ? "0" : "") + m + " " + ap;
  }
  var age = document.getElementById("calc-age");
  var wake = document.getElementById("calc-wake");
  var out = document.getElementById("calc-out");
  function render() {
    var months = parseFloat(age.value);
    if (isNaN(months) || months < 0 || months > 30) { out.hidden = true; return; }
    if (months > 24) months = 24;
    var b = band(months);
    var html = "<p><strong>" + b.label + ":</strong> typical wake window about <strong>" +
      fmtDur(b.lo) + "\\u2013" + fmtDur(b.hi) + "</strong>, usually <strong>" +
      b.naps + " naps</strong> a day.</p>";
    if (wake.value) {
      var p = wake.value.split(":");
      var d1 = new Date(); d1.setHours(+p[0], +p[1], 0, 0);
      var lo = new Date(d1.getTime() + b.lo * 60000);
      var hi = new Date(d1.getTime() + b.hi * 60000);
      html += "<p>Woke at " + fmtTime(d1) + " \\u2192 next sleep is likely between <strong>" +
        fmtTime(lo) + "</strong> and <strong>" + fmtTime(hi) + "</strong>. Start winding down a little before the early end.</p>";
    }
    html += "<p class=\\"calc-note\\">Ranges are sleep-consultant convention \\u2014 your baby\\u2019s own recent pattern beats the chart. Shorter end after a short nap; longer end before bedtime.</p>";
    out.innerHTML = html; out.hidden = false;
  }
  age.addEventListener("input", render);
  wake.addEventListener("input", render);
})();
"""


def _render_calculator() -> str:
    url = f"{_BASE}/guides/{CALCULATOR_SLUG}"
    structured_data = json.dumps(
        {
            "@context": "https://schema.org",
            "@graph": [
                {
                    "@type": "WebApplication",
                    "name": "Wake Window Calculator",
                    "url": url,
                    "applicationCategory": "LifestyleApplication",
                    "operatingSystem": "Any (web)",
                    "description": "Free wake-window calculator: enter your baby's age (and last wake-up) to get the typical wake window, nap count, and next-nap time range.",
                    "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"},
                    "publisher": {"@id": f"{_BASE}/#org"},
                },
                {
                    "@type": "BreadcrumbList",
                    "itemListElement": [
                        {"@type": "ListItem", "position": 1, "name": "HAL", "item": f"{_BASE}/"},
                        {"@type": "ListItem", "position": 2, "name": "Guides", "item": f"{_BASE}/guides"},
                        {"@type": "ListItem", "position": 3, "name": "Wake Window Calculator", "item": url},
                    ],
                },
            ],
        }
    )
    body = f"""
  <main class="wrap">
    <nav class="crumbs" aria-label="Breadcrumb"><a href="/">HAL</a> › <a href="/guides">Guides</a> › Wake window calculator</nav>
    <article>
      <h1>Wake window calculator</h1>
      <p class="byline">Enter your baby's age — and, if you like, when they last woke — to get the typical wake window and next-nap time range.</p>
      <div class="calc">
        <label for="calc-age">Baby's age in months <span class="calc-hint">(0 = under 4 weeks; 4.5 = four and a half months)</span></label>
        <input id="calc-age" type="number" min="0" max="30" step="0.5" inputmode="decimal" placeholder="e.g. 6">
        <label for="calc-wake">Last wake-up time <span class="calc-hint">(optional)</span></label>
        <input id="calc-wake" type="time">
        <div id="calc-out" class="calc-out" hidden></div>
      </div>
      <noscript><p>The interactive calculator needs JavaScript — but the full chart below works without it.</p></noscript>
      <h2>The chart behind the calculator</h2>
      <p>The ranges come from the consensus across major wake-window charts — see the full <a href="/guides/wake-windows-by-age">wake windows by age guide</a> for the complete table, how to use the ranges, and the honest note on where these numbers come from (they're sleep-consultant convention, not medical guidance).</p>
      <h2>What the calculator can't know</h2>
      <p>It knows the chart; it doesn't know your baby. A short nap shrinks the next window. A big morning stretches it. Growth spurts, teeth, and daycare days bend everything. That's the actual reason we built HAL: it estimates the next nap from <em>your baby's own recent rhythm</em>, not a static chart — and it lives in the family group chat, so whoever is holding the baby sees it.</p>
      <div class="cta">
        <h2>The calculator that updates itself</h2>
        <p>Text "woke 2:40" in your family thread and HAL answers "when's her next nap?" from her actual pattern — no app, nothing to install.</p>
        <a class="btn" href="/?c=g-calc">Meet HAL →</a>
      </div>
      <div class="sources"><h2>Sources</h2>
        <ul>
          <li><a href="https://health.clevelandclinic.org/wake-windows-by-age" rel="noopener">Cleveland Clinic — Wake Windows by Age (pediatrician-reviewed)</a></li>
          <li><a href="https://aasm.org/resources/pdf/pediatricsleepdurationconsensus.pdf" rel="noopener">American Academy of Sleep Medicine — Recommended Amount of Sleep for Pediatric Populations</a></li>
          <li><a href="https://drcraigcanapari.com/do-wake-windows-help-kids-nap-better/" rel="noopener">Dr. Craig Canapari, Yale Pediatric Sleep Center — Do Wake Windows Help Kids Nap Better?</a></li>
        </ul>
        <p class="disclaimer">{DISCLAIMER}</p>
      </div>
    </article>
  </main>
  <script src="/static/wake-calc.js"></script>"""
    return _shell(
        title="Wake Window Calculator: Naps & Next Sleep by Age — HAL",
        description="Free wake-window calculator — enter your baby's age and last wake-up to get the typical wake window, nap count, and the time range for the next nap.",
        canonical=url,
        structured_data=structured_data,
        body=body,
    )


def build_guides_router() -> APIRouter:
    router = APIRouter()

    # Rendered once at startup: content is static per deploy.
    index_html = _render_index()
    pages = {g["slug"]: _render_guide(g) for g in GUIDES}
    pages[CALCULATOR_SLUG] = _render_calculator()
    cache = {"Cache-Control": "public, max-age=3600"}

    @router.get("/guides", include_in_schema=False)
    async def guides_index() -> HTMLResponse:
        return HTMLResponse(index_html, headers=cache)

    @router.get("/static/wake-calc.js", include_in_schema=False)
    async def wake_calc_js() -> PlainTextResponse:
        # External file, not inline: the CSP is script-src 'self' (see
        # middleware/security_headers.py) — inline <script> is blocked.
        return PlainTextResponse(
            _CALC_JS,
            media_type="application/javascript",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @router.get("/guides/{slug}", include_in_schema=False)
    async def guide_page(slug: str):
        html = pages.get(slug)
        if html is None:
            return RedirectResponse("/guides", status_code=302)
        return HTMLResponse(html, headers=cache)

    return router
