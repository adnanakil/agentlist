"""Post-deploy smoke checks against live texthal.com. Stdlib only.

Run after EVERY deploy. Exit 0 = production behaves; non-zero = something the
cycle just shipped is broken and the report must lead with BLOCKED.

These are deliberately behavioural, not "did it return 200" — the failure this
guards against is a deploy that serves a page which no longer converts. Each
assertion below corresponds to something that has actually broken or nearly
broken in production:

  health           service is up at all
  landing 200      the page renders
  no-store         the A/B arms can't be cached across visitors
  both arms        the hero-CTA experiment is actually splitting traffic
  ios separator    "&body=" — the form iOS accepts (dominant channel)
  android separator"?body=" — RFC 5724; silently broke Android prefill before
  prefill intact    "new baby here" is the parent-track trigger AND the only
                    branch that records the paid attribution code
  tap beacon       /tap accepts the funnel event growth measures with
"""

from __future__ import annotations

import re
import ssl
import sys
import urllib.error
import urllib.request

BASE = "https://www.texthal.com"
UA_IOS = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Version/17.0 Mobile Safari"
UA_ANDROID = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/120 Mobile"
TIMEOUT = 20

failures: list[str] = []
notes: list[str] = []


def _ssl_context() -> ssl.SSLContext:
    """Verified TLS that also works on the Hal Mac.

    The python.org macOS build ships without a usable system root store, so a
    default context there fails every request with CERTIFICATE_VERIFY_FAILED —
    which would look exactly like "the deploy broke production". Load certifi's
    roots on top when available (it is already a transitive dependency). Never
    disable verification: a verifier that trusts anything verifies nothing.
    """
    ctx = ssl.create_default_context()
    try:
        import certifi

        ctx.load_verify_locations(certifi.where())
    except Exception:
        pass
    return ctx


SSL_CTX = _ssl_context()


def get(path: str = "/", ua: str = UA_IOS) -> tuple[int, str, dict]:
    req = urllib.request.Request(BASE + path, headers={"User-Agent": ua})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=SSL_CTX) as r:
            return r.status, r.read().decode("utf-8", "replace"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, "", dict(e.headers or {})
    except Exception as e:  # network/DNS/TLS — report, don't crash
        return 0, f"__error__ {e}", {}


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}{(' — ' + detail) if detail and not ok else ''}")
    if not ok:
        failures.append(name)


print(f"verify_prod: {BASE}")

status, _, _ = get("/health")
check("health 200", status == 200, f"got {status}")

status, ios_html, headers = get("/", UA_IOS)
check("landing 200", status == 200, f"got {status}")
check(
    "landing is no-store (A/B arms uncacheable)",
    "no-store" in headers.get("Cache-Control", "").lower(),
    f"Cache-Control={headers.get('Cache-Control')!r}",
)

if status == 200:
    check("ios gets &body=", "&body=" in ios_html, "iOS prefill separator wrong")
    check(
        "sms prefill carries the parent-track trigger",
        "new%20baby%20here" in ios_html,
        "prefill no longer selects the parent track / records attribution",
    )
    check("hero CTA present above the fold", 'id="herocta"' in ios_html)
    check("sticky mobile CTA present", 'id="stickycta"' in ios_html)

_, android_html, _ = get("/", UA_ANDROID)
check("android gets ?body=", "?body=" in android_html, "Android prefill silently breaks")

# Both A/B arms must be reachable. Assignment is per-visitor-hash, so vary the
# UA until both appear; a stuck arm means the experiment is not splitting.
# Read data-variant from <body> — stable, purpose-built for reporting. The old
# span-scraping broke when ENG-004 added a <span class="sms-bubble"> above the
# button label, making the first span the preview, not the arm label.
arms = set()
for i in range(24):
    _, html, _ = get("/", f"{UA_IOS} Verify/{i}")
    m = re.search(r'<body[^>]*\bdata-variant="([^"]+)"', html)
    if m:
        arms.add(m.group(1))
check("both hero-CTA arms served", len(arms) >= 2, f"only saw {sorted(arms) or 'none'}")
if arms:
    notes.append(f"arms seen: {sorted(arms)}")

# Tap beacon: utm_source=verify-test is excluded from the funnel dashboards, so
# this probe cannot pollute growth's numbers.
req = urllib.request.Request(
    BASE + "/tap",
    data=b'{"variant":"a","utm_source":"verify-test"}',
    headers={"Content-Type": "application/json", "User-Agent": "eng-verify-bot"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=SSL_CTX) as r:
        check("tap beacon accepts events", r.status == 204, f"got {r.status}")
except Exception as e:
    check("tap beacon accepts events", False, str(e))

# Desktop QR code block — should be present in any page load (CSS hides it on
# mobile; JS reveals it on desktop). If qrcode is not deployed, this fails.
_, desktop_html, _ = get("/", UA_IOS)  # UA doesn't affect QR presence (CSS-gated)
if desktop_html:
    has_qr = 'class="qr-desk-block"' in desktop_html
    check("desktop QR block present in page", has_qr,
          "QR block missing — qrcode dep not installed or qr_svg returned empty")
    if has_qr:
        _qr_section = desktop_html.split('class="qr-desk-block"')[1].split("</div></div>")[0]
        check("QR data-qr-url encodes /go/ path (attribution-safe)",
              'data-qr-url="/go/' in desktop_html,
              "QR block present but data-qr-url missing /go/ path")
        check("QR block SVG embedded inline", "<svg" in _qr_section)

# /go/{code} — server-side tap recording for iOS. Sends utm_source=verify-test
# so this probe is excluded from funnel dashboards.
go_req = urllib.request.Request(
    BASE + "/go/verify-test?utm_source=verify-test",
    headers={"User-Agent": UA_IOS},
)
try:
    with urllib.request.urlopen(go_req, timeout=TIMEOUT, context=SSL_CTX) as r:
        go_html = r.read().decode("utf-8", "replace")
        check("/go/{code} returns 200 (tap recorded server-side)", r.status == 200,
              f"got {r.status}")
        check("/go/{code} page contains sms: URI", "sms:" in go_html,
              "redirect page missing sms: URI")
        check("/go/{code} is no-store", "no-store" in dict(r.headers).get("Cache-Control", "").lower())
except urllib.error.HTTPError as e:
    check("/go/{code} returns 200 (tap recorded server-side)", False, f"HTTP {e.code}")
    check("/go/{code} page contains sms: URI", False, "request failed")
    check("/go/{code} is no-store", False, "request failed")
except Exception as e:
    check("/go/{code} returns 200 (tap recorded server-side)", False, str(e))
    check("/go/{code} page contains sms: URI", False, "request failed")
    check("/go/{code} is no-store", False, "request failed")

# Landing JS must actually be EXECUTABLE, not merely present (ENG-015: the CSP
# silently blocked every inline script for days and nothing caught it). We
# cannot run JS from here, so assert the two facts that together make it run:
# the CSP explicitly permits same-origin scripts, and the page loads its JS
# from a same-origin file that really serves.
csp = headers.get("Content-Security-Policy", "")
check("CSP permits same-origin scripts (script-src 'self')",
      "script-src 'self'" in csp, f"CSP={csp!r}")
check("CSP permits beacon POSTs (connect-src 'self')",
      "connect-src 'self'" in csp, f"CSP={csp!r}")
check("landing references /static/landing.js",
      '<script src="/static/landing.js">' in ios_html)
check("no executable inline script in body (would be CSP-dead)",
      "<script>" not in ios_html.split("</head>", 1)[-1],
      "inline <script> found after </head> — it will never run under this CSP")
js_status, js_body, js_headers = get("/static/landing.js")
check("/static/landing.js serves 200", js_status == 200, f"got {js_status}")
check("landing.js is javascript",
      "javascript" in js_headers.get("Content-Type", ""),
      f"Content-Type={js_headers.get('Content-Type')!r}")
check("landing.js carries the desk gate + tap beacon + rotator",
      "desk" in js_body and "fetch('/tap'" in js_body and "rotator" in js_body)

# ENG-014 hero: conversation image + rotating headline word, server-rendered.
check("hero uses the conversation image",
      "/static/hero-conversation.png" in ios_html)
hero_img_status, _, _ = get("/static/hero-conversation.png")
check("hero image serves 200", hero_img_status == 200, f"got {hero_img_status}")
check("H1 rotator span present with a real word",
      'id="rotator"' in ios_html and ">naps.<" in ios_html)

for n in notes:
    print(f"  note: {n}")

if failures:
    print(f"\nVERIFY FAILED: {len(failures)} — {', '.join(failures)}")
    sys.exit(1)
print("\nverify_prod: all checks passed")
