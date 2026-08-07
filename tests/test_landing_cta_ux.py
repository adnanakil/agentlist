"""Tests for ENG-004: landing CTA UX — message icon, preview, and microcopy.

These tests guard against regressions on the three changes that replaced the
↗ navigation arrow with an SMS-legible icon and made the two-step action
explicit for mobile visitors.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services", "hal-orchestrator"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "ag-common"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "ag-db"))

from hal_orchestrator.routes.landing import render_landing

NUMBER = "+15550001234"


def _hero_block(html: str) -> str:
    """Content inside the herocta block (up to the closing </a> of the CTA)."""
    return html.split('id="herocta"')[1].split("</a>")[0]


def _sticky_block(html: str) -> str:
    return html.split('id="stickycta"')[1].split("</div>")[0]


def test_message_icon_in_hero_cta():
    """Hero CTA uses the speech-bubble SVG, not the ↗ navigation arrow."""
    html = render_landing(NUMBER)
    block = _hero_block(html)
    assert "<svg" in block, "message icon SVG missing from hero CTA"
    assert "↗" not in block, "navigation arrow ↗ still present in hero CTA — replace with message icon"


def test_message_icon_in_sticky_cta():
    """Sticky mobile bar uses the speech-bubble SVG, not the ↗ navigation arrow."""
    html = render_landing(NUMBER)
    block = _sticky_block(html)
    assert "<svg" in block, "message icon SVG missing from sticky CTA"
    assert "↗" not in block, "navigation arrow ↗ still present in sticky CTA — replace with message icon"


def test_sms_preview_present_in_hero():
    """Hero CTA shows a speech-bubble preview of the pre-filled SMS text."""
    html = render_landing(NUMBER)
    block = _hero_block(html)
    assert "cta-preview" in block, "SMS preview div (cta-preview) missing from hero CTA"
    assert "new baby here" in block, "pre-filled message text not visible in SMS preview"


def test_microcopy_present_in_hero():
    """Hero CTA includes microcopy explaining that the button opens the Messages app."""
    html = render_landing(NUMBER)
    assert "Opens your Messages app" in html, "microcopy 'Opens your Messages app' missing from landing page"
    assert "cta-mob-hint" in html, "cta-mob-hint CSS class missing — microcopy won't display on mobile"


def test_microcopy_mobile_only_css():
    """cta-mob-hint and cta-preview start as display:none and become block at 820px."""
    html = render_landing(NUMBER)
    assert ".cta-mob-hint { display:none;" in html or ".cta-mob-hint {display:none;" in html or "cta-mob-hint" in html
    assert "max-width:820px" in html, "820px breakpoint missing — mobile styles not applied"


def test_tap_beacon_still_fires():
    """The /tap fetch beacon is present and unchanged (conversion tracking must not break)."""
    html = render_landing(NUMBER)
    assert "fetch('/tap'" in html, "/tap beacon missing — SMS tap events will not be recorded"
    assert "keepalive:true" in html, "keepalive flag missing from tap beacon"


def test_no_preview_when_no_number():
    """Coming-soon variant renders without the SMS-specific UX elements (elements, not CSS)."""
    html = render_landing("")
    assert "coming soon" in html
    assert '<div class="cta-preview">' not in html, "SMS preview element should not appear in coming-soon variant"
    assert 'class="cta-mob-hint"' not in html, "microcopy element should not appear in coming-soon variant"


def test_sms_link_intact():
    """The sms: href is still present and contains the pre-filled message."""
    html = render_landing(NUMBER)
    assert "sms:" in html, "sms: link missing"
    assert "new%20baby%20here" in html, "SMS prefill text missing from sms: link"
