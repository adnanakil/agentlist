"""Tests for the landing CTA and hero (ENG-004, revised by ENG-012/014/015).

History matters here:
- ENG-004 replaced a ↗ navigation arrow with a speech-bubble icon (↗ read as
  "leaves the site" when the button opens Messages).
- ENG-012 (Adnan, option A) removed the bubble again — the label itself now
  reads "Text (number)", which carries the SMS signal — and added a TRAILING
  plain right arrow (→) as a pressable-affordance cue. The diagonal ↗ stays
  banned on SMS CTAs.
- ENG-014 made the hero pastel/light with a rotating last word in the H1.
- ENG-015 moved all landing JS to /static/landing.js because the CSP
  (script-src 'self', no 'unsafe-inline') blocks inline scripts.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services", "hal-orchestrator"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "ag-common"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "ag-db"))

from hal_orchestrator.routes.landing import _LANDING_JS, render_landing

NUMBER = "+15550001234"


def _hero_block(html: str) -> str:
    """Content inside the herocta block (up to the closing </a> of the CTA)."""
    return html.split('id="herocta"')[1].split("</a>")[0]


def _sticky_block(html: str) -> str:
    return html.split('id="stickycta"')[1].split("</div>")[0]


def test_hero_cta_has_trailing_right_arrow():
    """ENG-012 option A: plain → after the label; never the ↗ external-link glyph."""
    html = render_landing(NUMBER)
    block = _hero_block(html)
    assert "→" in block, "trailing right arrow missing from hero CTA"
    assert "↗" not in block, "banned ↗ glyph present in hero CTA (reads as external link)"
    assert 'aria-hidden="true"' in block, "arrow must be decorative (aria-hidden)"


def test_hero_cta_bubble_icon_removed():
    """ENG-012 option A removed the speech-bubble SVG from the CTA pill itself."""
    html = render_landing(NUMBER)
    block = _hero_block(html)
    assert "<svg" not in block, "icon SVG should be gone from the CTA pill (option A)"
    assert "Text" in block, "CTA label must still carry the SMS verb"


def test_sticky_cta_matches_hero_treatment():
    html = render_landing(NUMBER)
    block = _sticky_block(html)
    assert "→" in block, "trailing arrow missing from sticky CTA"
    assert "↗" not in block, "banned ↗ glyph present in sticky CTA"
    assert "<svg" not in block, "bubble SVG should be gone from sticky CTA (option A)"


def test_sms_preview_present_in_hero():
    """The SMS preview bubble (ENG-004) survives option A — only the icon went."""
    html = render_landing(NUMBER)
    block = _hero_block(html)
    assert "cta-preview" in block, "SMS preview div (cta-preview) missing from hero CTA"
    assert "new baby here" in block, "pre-filled message text not visible in SMS preview"


def test_microcopy_present_in_hero():
    html = render_landing(NUMBER)
    assert "Opens your Messages app" in html
    assert "cta-mob-hint" in html


def test_rotating_headline_word():
    """ENG-014: H1 ends 'up with baby's <word>.' — server-renders a real word,
    reserves width, and the JS cycles naps/poops/feeds."""
    html = render_landing(NUMBER)
    assert 'id="rotator"' in html, "rotator span missing from H1"
    assert ">naps.<" in html, "server must render a complete word, not an empty span"
    assert "min-width" in html and "rot-word" in html, "reserved width missing — line would reflow each tick"
    assert "prefers-reduced-motion" in html, "reduced-motion handling missing"
    for w in ("'naps.'", "'poops.'", "'feeds.'"):
        assert w in _LANDING_JS, f"{w} missing from rotator word list"
    assert "'milestones.'" not in _LANDING_JS, "milestones was dropped by Adnan — do not re-add"


def test_hero_phone_is_grid_column_not_background():
    """2026-08-09: the phone is a real <img> in the hero grid. The previous
    object-fit:cover background slid the phone into the headline at aspect
    ratios other than 2:1 (live collision, reported by Adnan). Reverting to a
    cover background reintroduces that bug at some viewport."""
    html = render_landing(NUMBER)
    assert 'class="hero-phone"' in html, "hero phone <img> missing"
    assert "/static/hero-phone.png" in html, "hero phone asset not referenced"
    assert 'class="hero-media"' not in html, "cover-background hero is back (collides)"
    hero = html.split('class="hero"')[1].split("</section>")[0]
    assert "donebottles" not in hero, "stock bottles photo back in the hero"


def test_landing_js_external_not_inline():
    """ENG-015: CSP is script-src 'self' — the page must reference landing.js and
    carry no executable inline script after </head> (JSON-LD in head is data)."""
    html = render_landing(NUMBER)
    assert '<script src="/static/landing.js">' in html
    body = html.split("</head>")[1]
    assert "<script>" not in body, "inline <script> in body will be CSP-blocked and silently dead"


def test_tap_beacon_lives_in_landing_js():
    assert "fetch('/tap'" in _LANDING_JS, "/tap beacon missing from landing.js"
    assert "keepalive:true" in _LANDING_JS


def test_no_preview_when_no_number():
    html = render_landing("")
    assert "coming soon" in html
    assert '<div class="cta-preview">' not in html
    assert 'class="cta-mob-hint"' not in html


def test_sms_link_intact():
    html = render_landing(NUMBER)
    assert "sms:" in html, "sms: link missing"
    assert "new%20baby%20here" in html, "SMS prefill text missing from sms: link"
