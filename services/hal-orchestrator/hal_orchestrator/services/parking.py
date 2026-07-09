"""parking — look up NYC parking / camera violations by license plate.

Backed by NYC OpenData's "Open Parking and Camera Violations" dataset
(resource nc67-uf89), which is the same data behind the city's official
lookup/pay site and is refreshed daily. It's keyed by plate + registration
state and carries the summons number, what the ticket was for, and the live
`amount_due` — everything needed to (a) tell the user what they owe and (b)
drive a payment for a specific summons.

Pure-ish and unit-testable: `lookup_violations` does the HTTP; `format_*` and
the parsing helpers have no I/O. The tool wrapper lives in tools/parking.py.
"""

from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import structlog

log = structlog.get_logger()

# NYC OpenData SODA endpoint. No app token needed at our volume (a handful of
# lookups/day); if we ever get rate-limited, set X-App-Token via config.
DATASET_URL = "https://data.cityofnewyork.us/resource/nc67-uf89.json"

# Official NYC payment portal for parking/camera violations. CityPay is the
# current front door (nyc.gov/payonline redirects here). We hand the user this
# plus the exact summons number; the auto-pay phase will drive the flow itself.
# NOTE: the path is case-sensitive — capital "Parking" is the live page;
# lowercase "/parking" 404s. The user lands here and enters the summons/plate
# (search is reCAPTCHA-gated, so we can't deep-link a pre-filled result).
PAY_URL = "https://a836-citypay.nyc.gov/citypay/Parking"

# Money-bearing fields on each row, all delivered as strings.
_MONEY_FIELDS = (
    "fine_amount", "penalty_amount", "interest_amount",
    "reduction_amount", "payment_amount", "amount_due",
)


def normalize_plate(plate: str) -> str:
    """Uppercase, drop spaces/dashes — plates are stored bare (e.g. GKM7541)."""
    return re.sub(r"[^A-Z0-9]", "", (plate or "").upper())


def _money(v: dict, key: str) -> float:
    try:
        return float(str(v.get(key, "") or "0").replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return 0.0


def _issue_dt(v: dict) -> datetime | None:
    """Issue date is 'MM/DD/YYYY'. Used only for sorting/formatting."""
    raw = (v.get("issue_date") or "").strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


async def lookup_violations(
    client: httpx.AsyncClient,
    plate: str,
    state: str = "NY",
    *,
    open_only: bool = True,
    limit: int = 200,
) -> list[dict]:
    """Return this plate's violations (open ones by default), newest first.

    Dedupes by summons number (a summons appears once, but guard anyway) and
    keeps the row with the higher amount_due. Raises httpx.HTTPError on a
    transport/HTTP failure so the caller can render a friendly message.
    """
    p = normalize_plate(plate)
    st = (state or "NY").upper().strip()[:2]
    if not p:
        return []

    resp = await client.get(
        DATASET_URL,
        params={"plate": p, "state": st, "$limit": limit},
        headers={"Accept": "application/json"},
        timeout=25,
    )
    resp.raise_for_status()
    rows = resp.json() or []

    by_summons: dict[str, dict] = {}
    for r in rows:
        if open_only and _money(r, "amount_due") <= 0:
            continue
        key = str(r.get("summons_number") or id(r))
        prev = by_summons.get(key)
        if prev is None or _money(r, "amount_due") > _money(prev, "amount_due"):
            by_summons[key] = r

    out = list(by_summons.values())
    out.sort(key=lambda r: (_issue_dt(r) or datetime.min), reverse=True)
    return out


def total_due(violations: list[dict]) -> float:
    return round(sum(_money(v, "amount_due") for v in violations), 2)


def _fmt_date(v: dict, tz: ZoneInfo) -> str:
    dt = _issue_dt(v)
    return dt.strftime("%b %-d, %Y") if dt else (v.get("issue_date") or "?")


def format_violation(v: dict, tz: ZoneInfo, *, index: int | None = None) -> str:
    """One ticket, human-readable, with the summons number and view link."""
    due = _money(v, "amount_due")
    fine = _money(v, "fine_amount")
    pen = _money(v, "penalty_amount")
    interest = _money(v, "interest_amount")
    head = f"{index}. " if index is not None else ""
    lines = [
        f"{head}{(v.get('violation') or 'Violation').title()} — ${due:,.2f} due",
        f"   Summons #{v.get('summons_number', '?')} · issued {_fmt_date(v, tz)}"
        f" · {v.get('issuing_agency', '').title() or 'NYC'}",
    ]
    breakdown = []
    if fine:
        breakdown.append(f"fine ${fine:,.0f}")
    if pen:
        breakdown.append(f"penalty ${pen:,.0f}")
    if interest:
        breakdown.append(f"interest ${interest:,.2f}")
    if breakdown:
        lines.append("   (" + ", ".join(breakdown) + ")")
    img = (v.get("summons_image") or {}).get("url")
    if img:
        lines.append(f"   View ticket: {img}")
    return "\n".join(lines)


def format_violations(
    violations: list[dict], tz: ZoneInfo, plate: str, state: str = "NY"
) -> str:
    p = normalize_plate(plate)
    if not violations:
        return (
            f"No open parking/camera violations found for {state} plate {p}. "
            "(NYC OpenData; a very recent ticket can take a day or two to appear.)"
        )
    total = total_due(violations)
    n = len(violations)
    header = (
        f"{n} open violation{'s' if n != 1 else ''} for {state} plate {p} — "
        f"${total:,.2f} total due:"
    )
    body = "\n".join(
        format_violation(v, tz, index=i) for i, v in enumerate(violations, 1)
    )
    footer = f"Pay at {PAY_URL} (enter the summons number)."
    return f"{header}\n\n{body}\n\n{footer}"
