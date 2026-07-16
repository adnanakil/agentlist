"""Read a consenting iMessage user's location from Find My on HAL's Mac.

This module is copied next to the stdlib-only iMessage bridge. It maps an
inbound phone/email handle to the matching Find My display name using Apple's
local sharing roster, then asks the narrowly permissioned helper app to read
that person's visible location label. Location values are returned to the
caller only; this module never logs them or persists them.

Compatible with the bridge's Python 3.8 runtime.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unicodedata
from contextlib import suppress
from datetime import datetime, timezone

FRIEND_CACHE = os.path.expanduser(
    "~/Library/Caches/com.apple.findmy.fmfcore/FriendCacheData.data"
)
HELPER_APP = os.path.expanduser("~/.hal/HalFindMyHelper.app")
OVERRIDE_MAP = os.path.expanduser("~/.hal/findmy_location_map.json")
# The helper polls the Find My detail pane for up to ~6s after selecting the
# person (the pin callout renders asynchronously), on top of app activation
# and person-match retries — a failing lookup can legitimately take ~13s.
LOOKUP_TIMEOUT_SECONDS = 18
CACHE_TTL_SECONDS = 90

# "how far/long" only counts within one sentence and only with a self-anchor
# ("from here", "take me", ...) so "how far is Rome from Paris? let me know"
# doesn't trigger a lookup. "directions to X" implies origin = the speaker;
# "directions from JFK" names its own origin and must not.
_LOCATION_RE = re.compile(
    r"\b(?:where am i|my (?:current )?location|near me|nearby|closest|from here|"
    r"around me|close to me|"
    r"how (?:long|far)\b[^.?!\n]*\b(?:from here|to me|am i|take me)|"
    r"directions? to)\b",
    re.IGNORECASE,
)
_LOCATION_UI_ARTIFACT_RE = re.compile(
    r"(?:^|\b)(?:heading|bearing|compass|map scale)\s*:.*\bdegrees?\b",
    re.IGNORECASE,
)
# Find My chrome that can slip through as a "label" (belt-and-suspenders with
# the helper's own scorer): a button is never a location.
_LOCATION_UI_CONTROL_RE = re.compile(
    r"^(?:show (?:in )?3d|show map|show 2d|satellite|hybrid|play sound"
    r"|mark as lost|remove this device|erase this device|notify when found"
    r"|directions|add label|edit label|zoom (?:in|out))$",
    re.IGNORECASE,
)
_cache = {}
_cache_lock = threading.Lock()
# Lookups run one at a time: `open -n` spawns a fresh helper instance per
# call, and concurrent instances would fight over the same Find My window.
# Serializing also makes the timeout kill below safe — the only helper alive
# is the one that just hung.
_helper_lock = threading.Lock()


def location_relevant(text):
    """True only when an inbound turn clearly benefits from live location."""
    return bool(_LOCATION_RE.search(text or ""))


def _handle_keys(value):
    value = (value or "").strip().lower()
    for prefix in ("tel:", "mailto:", "sms:", "imessage:"):
        if value.startswith(prefix):
            value = value[len(prefix):]
            break
    keys = set()
    if "@" in value:
        keys.add(value)
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) >= 7:
        keys.add(digits)
        keys.add(digits[-10:])
    if value:
        keys.add(value)
    return keys


def _safe_json(path, max_bytes=1_000_000):
    try:
        if os.path.getsize(path) > max_bytes:
            return {}
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _override_name(handle):
    config = _safe_json(OVERRIDE_MAP, max_bytes=100_000)
    mappings = config.get("handles") or {}
    if not isinstance(mappings, dict):
        return None
    wanted = _handle_keys(handle)
    for candidate, display_name in mappings.items():
        if wanted.intersection(_handle_keys(candidate)) and isinstance(display_name, str):
            cleaned = display_name.strip()
            if cleaned:
                return cleaned[:200]
    return None


def find_display_name(handle, roster_path=FRIEND_CACHE):
    """Map the bridge sender handle to a person visible in Find My."""
    override = _override_name(handle)
    if override:
        return override

    data = _safe_json(roster_path)
    following = data.get("following") or []
    contacts = data.get("contacts") or {}
    if not isinstance(following, list) or not isinstance(contacts, dict):
        return None
    wanted = _handle_keys(handle)
    for relationship in following:
        if not isinstance(relationship, dict):
            continue
        candidates = []
        for field in (
            "invitationFromHandles",
            # The handle that ACCEPTED the share often differs from the one the
            # invite came from (multi-line users): a share created from the
            # user's primary number can be accepted by the number they text
            # HAL from. Both must map to the same person.
            "invitationAcceptedHandles",
            "invitationFromHandle",
            "invitationSentToHandle",
            "id",
        ):
            raw = relationship.get(field)
            candidates.extend(raw if isinstance(raw, list) else [raw])
        if not any(wanted.intersection(_handle_keys(candidate)) for candidate in candidates):
            continue
        contact = contacts.get(str(relationship.get("id"))) or {}
        display_name = contact.get("displayName") if isinstance(contact, dict) else None
        if isinstance(display_name, str) and display_name.strip():
            return display_name.strip()[:200]
    return None


def _clean_text(value, limit):
    if not isinstance(value, str):
        return None
    # Find My address labels carry invisible directionality marks (U+200E)
    # that survive str.split(); drop all Unicode format chars (category Cf).
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Cf")
    cleaned = " ".join(value.split()).strip()
    return cleaned[:limit] if cleaned else None


def _clean_location_label(value):
    """Reject map controls that Accessibility can expose as address-like text."""
    label = _clean_text(value, 300)
    if not label:
        return None
    if _LOCATION_UI_ARTIFACT_RE.search(label) or _LOCATION_UI_CONTROL_RE.match(label):
        return None
    return label


def _kill_stale_helper():
    """Killing `open -W` on timeout does not kill the helper instance it
    launched — without this the orphan keeps driving Find My and can write
    its output after the caller has given up."""
    with suppress(Exception):
        subprocess.run(
            ["pkill", "-f", "HalFindMyHelper.app"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )


def _run_helper(display_name):
    if not os.path.isdir(HELPER_APP):
        return {"status": "helper_unavailable"}
    # The helper writes its own 0600 file inside a private (0700) scratch dir.
    # Removing the whole dir afterwards means even a helper that outlived the
    # timeout has no surviving path to recreate, so no location JSON can
    # linger on disk.
    output_dir = tempfile.mkdtemp(prefix="hal-findmy-")
    output_path = os.path.join(output_dir, "location.json")
    try:
        with _helper_lock:
            try:
                subprocess.run(
                    [
                        "open",
                        "-W",
                        "-n",
                        HELPER_APP,
                        "--args",
                        "lookup",
                        display_name,
                        "--output",
                        output_path,
                    ],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=LOOKUP_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired:
                _kill_stale_helper()
                return {"status": "helper_timeout"}
            result = _safe_json(output_path, max_bytes=50_000)
            return result or {"status": "helper_no_response"}
    finally:
        shutil.rmtree(output_dir, ignore_errors=True)


def lookup_location(handle):
    """Return a bridge-safe current-location dict, or an unavailable status."""
    cache_key = next(iter(sorted(_handle_keys(handle))), "")
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(cache_key)
        if cached and now - cached[0] <= CACHE_TTL_SECONDS:
            return dict(cached[1])

    display_name = find_display_name(handle)
    if not display_name:
        return {"status": "person_not_mapped", "source": "find_my"}
    raw = _run_helper(display_name)
    status = _clean_text(raw.get("status"), 80) or "helper_error"
    if status != "ok":
        return {"status": status, "source": "find_my"}
    label = _clean_location_label(raw.get("label"))
    if not label:
        return {"status": "location_label_unavailable", "source": "find_my"}

    result = {
        "status": "ok",
        "label": label,
        "updated": _clean_text(raw.get("updated"), 80),
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "source": "find_my",
    }
    if isinstance(raw.get("approximate"), bool):
        result["approximate"] = raw["approximate"]
    with _cache_lock:
        # Expired entries are dead weight (and stale locations) — drop them so
        # the cache stays bounded over a long-lived bridge process.
        for stale_key in [
            key
            for key, (stamp, _) in _cache.items()
            if now - stamp > CACHE_TTL_SECONDS
        ]:
            del _cache[stale_key]
        _cache[cache_key] = (now, dict(result))
    return result
