"""Booking-widget unwrap — surface embedded schedule/booking widget URLs.

The 07-13 miss: HAL spent 22 tool calls (2 real browser sessions) on
chelseaforestplay.com/book-a-class and still punted to "call them" — the
schedule lives in a Sawyer embed (`<script src="…hisawyer.com/embed/<token>.js">`)
that `_extract_page_text` strips before the model ever sees it, while the
iframe that script injects (hisawyer.com/<slug>/schedules/widget_calendar) is
a plain GET carrying the whole schedule as inline JSON.

This module detects known booking/schedule widgets in the RAW page HTML and
hands the model the widget's own URL as an appended note on the web_fetch
result. Sawyer token embeds are resolved inline (one small guarded GET of the
embed .js, whose body contains the direct widget URL); if that fetch fails we
fall back to surfacing the embed script URL with instructions. Every surfaced
URL passes the same SSRF guard as the original fetch — a hostile page must not
be able to steer HAL's next fetch at an internal host via a crafted iframe.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

import structlog

log = structlog.get_logger()

# Hosts whose iframes are worth surfacing as-is. Suffix-matched against the
# iframe's hostname (endswith, label-aligned), so subdomains like
# app.acuityscheduling.com or clients.mindbodyonline.com match.
BOOKING_IFRAME_HOSTS = {
    "hisawyer.com": "sawyer",
    "mindbodyonline.com": "mindbody",
    "acuityscheduling.com": "acuity",
    "as.me": "acuity",
    "calendly.com": "calendly",
}

# Sawyer token embed: hisawyer.com/embed/<token>.js — its BODY contains the
# provider's direct widget URL. (The generic sawyer_embed_loader.js does not,
# so it only signals "sawyer is present" and is not worth surfacing itself.)
_SAWYER_TOKEN_EMBED_RE = re.compile(
    r"""<script[^>]+src=['"]([^'"]*hisawyer\.com/embed/[^'"/]+\.js[^'"]*)['"]""",
    re.IGNORECASE,
)

_IFRAME_SRC_RE = re.compile(r"""<iframe[^>]+src=['"]([^'"]+)['"]""", re.IGNORECASE)

# Inside the embed .js body: the direct widget URL for the provider.
_SAWYER_WIDGET_URL_RE = re.compile(
    r"https://www\.hisawyer\.com/[a-z0-9\-]+/schedules(?:/[a-z_]+)?",
    re.IGNORECASE,
)

# A fetched hisawyer.com page (marketplace activity-set, provider profile)
# carries the provider slug in its SSR JSON — HTML-escaped on the marketplace:
#   &quot;provider&quot;:{…,&quot;slug&quot;:&quot;chelsea-forest-play&quot;
# and in /providers/<slug>/… hrefs. From the slug we can hand the model the
# CURRENT schedule URL. This matters because search often lands HAL on a
# marketplace activity listing from a PAST semester (the 07-13 retry miss: a
# Nov'25–Jan'26 listing offered as "the" schedule, no times, wrong ages).
# The provider-object form is tried first: location slugs like
# "214182-chelsea-forest-play" are digit-led, so both patterns anchor on a
# leading letter to skip them.
_SAWYER_PROVIDER_OBJ_SLUG_RE = re.compile(
    r"(?:\"|&quot;)provider(?:\"|&quot;):\{"
    r".{0,300}?"
    r"(?:\"|&quot;)slug(?:\"|&quot;):(?:\"|&quot;)([a-z][a-z0-9-]*)(?:\"|&quot;)",
    re.IGNORECASE | re.DOTALL,
)
_SAWYER_PROVIDERS_PATH_RE = re.compile(
    r"/providers/([a-z][a-z0-9-]*)/", re.IGNORECASE
)
_SLUG_OK_RE = re.compile(r"^[a-z][a-z0-9-]*$")

_MAX_SURFACED = 3


def extract_sawyer_provider_slug(html: str) -> str | None:
    """Provider slug from a hisawyer.com page's SSR HTML, or None."""
    for rx in (_SAWYER_PROVIDER_OBJ_SLUG_RE, _SAWYER_PROVIDERS_PATH_RE):
        m = rx.search(html or "")
        if m:
            slug = m.group(1).lower()
            if _SLUG_OK_RE.match(slug):
                return slug
    return None


def _host_provider(url: str) -> str | None:
    """Provider name when the URL's host is (a subdomain of) a booking host."""
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return None
    for suffix, provider in BOOKING_IFRAME_HOSTS.items():
        if host == suffix or host.endswith("." + suffix):
            return provider
    return None


def detect_booking_widgets(html: str, page_url: str) -> list[dict]:
    """Pure detection over raw HTML → [{provider, url, needs_resolution}].

    `needs_resolution=True` marks a Sawyer token-embed script whose .js body
    must be fetched to learn the actual widget URL.
    """
    hits: list[dict] = []
    seen: set[str] = set()

    for m in _SAWYER_TOKEN_EMBED_RE.finditer(html or ""):
        url = urljoin(page_url, m.group(1))
        if url not in seen:
            seen.add(url)
            hits.append({"provider": "sawyer", "url": url, "needs_resolution": True})

    for m in _IFRAME_SRC_RE.finditer(html or ""):
        url = urljoin(page_url, m.group(1))
        provider = _host_provider(url)
        if provider and url not in seen:
            seen.add(url)
            hits.append({"provider": provider, "url": url, "needs_resolution": False})

    # The fetched page IS a hisawyer.com page (marketplace listing / provider
    # profile): surface the provider's current-schedule URL from its slug.
    # Skip schedule pages themselves — a widget_calendar fetch must not emit a
    # note pointing back at itself.
    if _host_provider(page_url) == "sawyer" and "/schedules" not in urlsplit(page_url).path:
        slug = extract_sawyer_provider_slug(html or "")
        if slug:
            url = f"https://www.hisawyer.com/{slug}/schedules/widget_calendar"
            if url not in seen and url != page_url:
                seen.add(url)
                hits.append(
                    {
                        "provider": "sawyer",
                        "url": url,
                        "needs_resolution": False,
                        "kind": "sawyer_page",
                    }
                )

    return hits


def resolve_sawyer_widget_url(embed_js_body: str) -> str | None:
    """Extract the provider's direct widget URL from a Sawyer embed .js body."""
    m = _SAWYER_WIDGET_URL_RE.search(embed_js_body or "")
    return m.group(0) if m else None


async def _fetch_sawyer_resolution(embed_url: str, ctx) -> str | None:
    """One small guarded GET of the embed .js → direct widget URL (or None)."""
    from hal_orchestrator.services.url_guard import check_url

    reason = await check_url(
        embed_url, allow_private=ctx.settings.allow_private_network_fetch
    )
    if reason:
        return None
    try:
        resp = await ctx.http_client.get(embed_url, timeout=8, follow_redirects=True)
        if resp.status_code != 200:
            return None
        return resolve_sawyer_widget_url(resp.text)
    except Exception as exc:
        log.info("booking_widgets.resolve_failed", url=embed_url[:120], error=str(exc))
        return None


async def booking_widget_note(html: str, page_url: str, ctx) -> str:
    """Note to append to a web_fetch result when the page embeds a booking
    widget; "" when none detected. Never raises — a detection bug must not
    break web_fetch itself."""
    try:
        from hal_orchestrator.services.url_guard import check_url

        hits = detect_booking_widgets(html, page_url)
        if not hits:
            return ""

        embed_lines: list[str] = []
        page_lines: list[str] = []
        surfaced: set[str] = set()
        for hit in hits[:_MAX_SURFACED]:
            target = hit["url"]
            hint = ""
            if hit["needs_resolution"]:
                resolved = await _fetch_sawyer_resolution(target, ctx)
                if resolved:
                    target = resolved
                else:
                    hint = (
                        " (an embed script — fetch it and follow the "
                        "hisawyer.com/<provider>/schedules URL inside)"
                    )
            reason = await check_url(
                target, allow_private=ctx.settings.allow_private_network_fetch
            )
            if reason or target in surfaced:
                continue
            surfaced.add(target)
            if hit.get("kind") == "sawyer_page":
                page_lines.append(f"- {target}{hint}")
            else:
                embed_lines.append(f"- {target}{hint}")

        blocks: list[str] = []
        if embed_lines:
            blocks.append(
                "[BOOKING/SCHEDULE WIDGET DETECTED — this page loads its "
                "schedule inside an embedded widget, so the times are NOT in "
                "the page text above. Fetch the widget URL directly for the "
                "actual schedule:\n" + "\n".join(embed_lines) + "]"
            )
        if page_lines:
            blocks.append(
                "[SAWYER BOOKING PAGE — marketplace activity listings often "
                "show a PAST semester: check the listed dates against today "
                "before citing them, and check the posted age range fits. The "
                "provider's CURRENT schedule is at:\n"
                + "\n".join(page_lines)
                + "]"
            )
        if not blocks:
            return ""
        log.info(
            "booking_widgets.detected",
            page=page_url[:120],
            surfaced=len(surfaced),
        )
        return "\n\n" + "\n\n".join(blocks)
    except Exception:
        log.exception("booking_widgets.note_failed", page=page_url[:120])
        return ""
