"""Tests for booking-widget unwrap (services/booking_widgets.py) — pure
detection/resolution logic plus the note assembly with a stubbed ctx.

Run: python3 services/hal-orchestrator/tests_widget_unwrap.py
"""

import asyncio
import os
import sys

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-db"))
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hal_orchestrator.services import booking_widgets as W

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok: {name}")
    else:
        failures.append(name)
        print(f"  FAIL: {name} {detail}")


# Trimmed from the real chelseaforestplay.com/book-a-class page (2026-07-13):
# generic loader + token embed. Only the token embed is worth surfacing.
PAGE = """
<html><body>
<h1>Book a Class</h1>
<script src='https://www.hisawyer.com/uploads/embed/sawyer_embed_loader.js'></script>
<script src='https://www.hisawyer.com/embed/Jm5WCIQzvAdrKB0lnHI94TEM1i49jjw_.js'></script>
<iframe src="https://www.youtube.com/embed/xyz"></iframe>
</body></html>
"""

EMBED_JS = (
    "function SAIFRAME__INIT(){var u='https://www.hisawyer.com/"
    "chelsea-forest-play/schedules/widget_calendar';makeIframe(u);}"
)

WIDGET_URL = "https://www.hisawyer.com/chelsea-forest-play/schedules/widget_calendar"


print("detection:")
hits = W.detect_booking_widgets(PAGE, "https://www.chelseaforestplay.com/book-a-class")
check("one hit (loader + youtube iframe ignored)", len(hits) == 1, f"got {hits}")
check("sawyer token embed, needs resolution",
      hits[0]["provider"] == "sawyer" and hits[0]["needs_resolution"]
      and hits[0]["url"].endswith("Jm5WCIQzvAdrKB0lnHI94TEM1i49jjw_.js"))

iframe_page = """
<iframe src="https://calendly.com/some-studio/intro"></iframe>
<iframe src="https://app.acuityscheduling.com/schedule.php?owner=123"></iframe>
<iframe src="https://evil.example.com/schedule"></iframe>
"""
hits = W.detect_booking_widgets(iframe_page, "https://studio.example.com/")
check("calendly + acuity subdomain detected, unknown host ignored",
      [h["provider"] for h in hits] == ["calendly", "acuity"], f"got {hits}")
check("iframe hits need no resolution", all(not h["needs_resolution"] for h in hits))

rel_page = "<iframe src='/widgets/cal?x=1'></iframe>"
hits = W.detect_booking_widgets(rel_page, "https://www.hisawyer.com/page")
check("relative iframe src resolved against page host",
      hits and hits[0]["url"] == "https://www.hisawyer.com/widgets/cal?x=1", f"got {hits}")

check("no detection on plain page",
      W.detect_booking_widgets("<html><p>hi</p></html>", "https://a.com") == [])

print("sawyer resolution:")
check("widget url extracted from embed js body",
      W.resolve_sawyer_widget_url(EMBED_JS) == WIDGET_URL)
check("no url in unrelated js", W.resolve_sawyer_widget_url("var x = 1;") is None)

# Trimmed from the real hisawyer.com/marketplace/activity-set/1747030 SSR HTML
# (2026-07-13): provider object with the clean slug, plus the digit-led
# LOCATION slug ("214182-chelsea-forest-play") as a decoy that must not win.
MARKETPLACE = (
    "<html><body><div data-react-props=\""
    "&quot;provider&quot;:{&quot;id&quot;:30113,&quot;name&quot;:&quot;Chelsea "
    "Forest Play&quot;,&quot;slug&quot;:&quot;chelsea-forest-play&quot;,"
    "&quot;description&quot;:&quot;kids&quot;}"
    ",&quot;slug&quot;:&quot;214182-chelsea-forest-play&quot;"
    ",&quot;location_page_url&quot;:&quot;/providers/chelsea-forest-play/"
    "214182-chelsea-forest-play&quot;\"></div></body></html>"
)
MKT_URL = "https://www.hisawyer.com/marketplace/activity-set/1747030"

print("sawyer page slug:")
check("slug extracted from marketplace SSR (decoy location slug skipped)",
      W.extract_sawyer_provider_slug(MARKETPLACE) == "chelsea-forest-play")
check("providers-path fallback works",
      W.extract_sawyer_provider_slug(
          "<a href='/providers/chelsea-forest-play/214182-x'>loc</a>"
      ) == "chelsea-forest-play")
check("digit-led path slug rejected",
      W.extract_sawyer_provider_slug("<a href='/providers/214182-x/'>l</a>") is None)
check("malformed provider-object slug rejected",
      W.extract_sawyer_provider_slug(
          '"provider":{"id":1,"slug":"Ev il/../x"}'
      ) is None)

hits = W.detect_booking_widgets(MARKETPLACE, MKT_URL)
check("hisawyer page -> widget_calendar hit tagged sawyer_page",
      len(hits) == 1 and hits[0]["url"] == WIDGET_URL
      and hits[0].get("kind") == "sawyer_page"
      and not hits[0]["needs_resolution"], f"got {hits}")
check("no self-note on a schedules page itself",
      W.detect_booking_widgets(
          MARKETPLACE, "https://www.hisawyer.com/chelsea-forest-play/schedules/widget_calendar"
      ) == [])
check("slug logic only fires on hisawyer pages",
      not any(h.get("kind") == "sawyer_page"
              for h in W.detect_booking_widgets(
                  MARKETPLACE, "https://www.chelseaforestplay.com/book-a-class")))


class _Resp:
    def __init__(self, status_code, text):
        self.status_code, self.text = status_code, text


class _Client:
    def __init__(self, body=EMBED_JS, status=200, raise_exc=False):
        self.body, self.status, self.raise_exc = body, status, raise_exc

    async def get(self, url, **kw):
        if self.raise_exc:
            raise RuntimeError("boom")
        return _Resp(self.status, self.body)


class _Settings:
    allow_private_network_fetch = False


class _Ctx:
    def __init__(self, client):
        self.settings = _Settings()
        self.http_client = client


PAGE_URL = "https://www.chelseaforestplay.com/book-a-class"

print("note assembly:")
note = asyncio.run(W.booking_widget_note(PAGE, PAGE_URL, _Ctx(_Client())))
check("resolved widget url surfaced", WIDGET_URL in note, note)
check("note flags widget explicitly", "WIDGET DETECTED" in note)

note = asyncio.run(W.booking_widget_note(PAGE, PAGE_URL, _Ctx(_Client(raise_exc=True))))
check("resolution failure falls back to embed script url + hint",
      "hisawyer.com/embed/" in note and "follow the" in note, note)

note = asyncio.run(W.booking_widget_note("<p>plain</p>", PAGE_URL, _Ctx(_Client())))
check("no widgets -> empty note", note == "")

note = asyncio.run(W.booking_widget_note(MARKETPLACE, MKT_URL, _Ctx(_Client())))
check("marketplace note carries staleness + age warning and CURRENT url",
      "PAST semester" in note and "age range" in note and WIDGET_URL in note, note)
check("marketplace note uses the sawyer-page header, not the embed header",
      "SAWYER BOOKING PAGE" in note and "WIDGET DETECTED" not in note, note)

# A venue page that both token-embeds Sawyer AND iframes the same widget URL
# must surface it once, not twice.
combo = PAGE + f"<iframe src='{WIDGET_URL}'></iframe>"
note = asyncio.run(W.booking_widget_note(combo, PAGE_URL, _Ctx(_Client())))
check("venue page embedding + iframing same widget -> single surfaced line",
      note.count(WIDGET_URL) == 1, note)

print("ssrf guard:")
from hal_orchestrator.services import url_guard as G

_orig_check = G.check_url


async def _reject_all(url, *, allow_private=False):
    return "blocked by test"


G.check_url = _reject_all
note = asyncio.run(W.booking_widget_note(PAGE, PAGE_URL, _Ctx(_Client())))
G.check_url = _orig_check
check("guard-rejected urls are dropped (empty note)", note == "", note)

# Malicious embed js can't steer resolution off-host: regex only matches
# https://www.hisawyer.com/... so a crafted body yields no resolution at all.
evil = "var u='https://169.254.169.254/latest/meta-data/';"
check("resolution regex is host-pinned", W.resolve_sawyer_widget_url(evil) is None)

print()
if failures:
    print(f"{len(failures)} FAILURES: {failures}")
    sys.exit(1)
print("all checks passed")
