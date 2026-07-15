"""Canonical live-location request phrasing.

One pattern shared by the pre-model guard (routes/message.py) and the
structural places enforcement (tools/places.py) so the two can never drift
apart. The Mac bridge keeps a deliberately broader trigger for when to
ATTEMPT a Find My lookup (scripts/hal_findmy_location.py); this is the
enforcement subset: search-style phrasings that anchor at the speaker's
current position. Phrasings with an explicit anchor ("closest subway to
Times Square") must NOT match — forcing the live label onto them would
override an origin the user actually gave.
"""

from __future__ import annotations

import re

LIVE_LOCATION_REQUEST_RE = re.compile(
    r"\b(?:near\s+me|nearby|around\s+me|close\s+to\s+me|from\s+here"
    r"|closest(?:\s+\w+){0,6}?\s+to\s+me)\b",
    re.IGNORECASE,
)

# The words safe to strip when rebuilding a Places query around the live
# label. Kept separate from the detection pattern above: "closest pharmacy
# to me" should DETECT as a live-location turn but only shed "closest" and
# "to me" — stripping the full detection match would eat "pharmacy" too.
LIVE_LOCATION_PHRASE_RE = re.compile(
    r"\b(?:near\s+me|nearby|around\s+me|close\s+to\s+me|from\s+here"
    r"|closest|to\s+me)\b",
    re.IGNORECASE,
)


def requires_live_location(text: str) -> bool:
    """True when the turn asks for a search anchored at the speaker."""
    return bool(LIVE_LOCATION_REQUEST_RE.search(text or ""))
