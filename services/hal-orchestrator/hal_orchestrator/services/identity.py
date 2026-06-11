"""Handle normalization and silo keys.

A *silo key* identifies one isolated agent context. Every piece of persistent
state — conversation history, summary, profile, memories, reminders, skills —
is keyed by silo, so one user (or group) can never see another's data.

- 1:1 chats: the sender's normalized handle (E.164 phone, or lowercased email
  for email-based iMessage accounts).
- Group chats: the iMessage group chat id (e.g. "chat6383719372234285...").
  The group is its own silo, shared by its members but walled off from every
  member's personal silo.
"""

from __future__ import annotations

import re

_DIGITS_RE = re.compile(r"\D+")


def is_group_id(handle: str | None) -> bool:
    """True if `handle` looks like an iMessage group chat id (mirrors the
    bridge's is_group_chat heuristic)."""
    if not handle:
        return False
    h = handle.strip()
    if h.startswith("chat"):
        return True
    return not (h.startswith("+") or "@" in h or h.replace("-", "").isdigit())


def normalize_handle(handle: str | None) -> str:
    """Normalize a sender handle to a stable silo key.

    Emails are lowercased; group ids pass through; phone numbers collapse to
    E.164 so "+1 (201) 757-0419", "12017570419" and "+12017570419" all map to
    one silo. Unrecognized shapes pass through stripped, never empty.
    """
    if not handle:
        return ""
    h = handle.strip()
    if "@" in h:
        return h.lower()
    if h.startswith("chat"):
        return h

    digits = _DIGITS_RE.sub("", h)
    if not digits:
        return h
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    if h.startswith("+") or len(digits) > 11:
        return f"+{digits}"
    # Short codes and other oddities: keep digits as-is.
    return digits
