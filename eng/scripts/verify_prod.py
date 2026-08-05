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

import sys
import urllib.error
import urllib.request

BASE = "https://www.texthal.com"
UA_IOS = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Version/17.0 Mobile Safari"
UA_ANDROID = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/120 Mobile"
TIMEOUT = 20

failures: list[str] = []
notes: list[str] = []


def get(path: str = "/", ua: str = UA_IOS) -> tuple[int, str, dict]:
    req = urllib.request.Request(BASE + path, headers={"User-Agent": ua})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
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
arms = set()
for i in range(24):
    _, html, _ = get("/", f"{UA_IOS} Verify/{i}")
    if 'id="herocta"' not in html:
        continue
    block = html.split('id="herocta"', 1)[1].split("</div>", 1)[0]
    if "<span>" in block:
        arms.add(block.split("<span>", 1)[1].split("</span>", 1)[0])
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
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        check("tap beacon accepts events", r.status == 204, f"got {r.status}")
except Exception as e:
    check("tap beacon accepts events", False, str(e))

for n in notes:
    print(f"  note: {n}")

if failures:
    print(f"\nVERIFY FAILED: {len(failures)} — {', '.join(failures)}")
    sys.exit(1)
print("\nverify_prod: all checks passed")
