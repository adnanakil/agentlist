# ENG-013 — Hero trust badges render a NULL byte: "✓�a0Your number is never sold"

- id: ENG-013
- from: adnan
- status: done
- priority: P1
- blast: green
- opened: 2026-08-08

## Request

The two trust badges under the hero CTA render as garbage on the live site:

    ✓�a0Your number is never sold or shared
    ✓�a0Delete everything with one text

Adnan spotted this on texthal.com. It is on the highest-value screen we have,
directly under the CTA, in the copy whose entire job is to make a stranger trust
us with their phone number. It currently looks broken.

### Diagnosed cause (verified in production, not inferred)

`routes/landing.py` line ~501:

    .trust-badge::before {{ content:"✓\00a0"; color:var(--green-bright); }}

`\0` opens an **octal escape in Python**, so `"\00a0"` becomes chr(0) + "a0"
before CSS ever sees it. The intended CSS escape `\00a0` (non-breaking space)
never reaches the browser; a literal NULL byte does, and the browser renders it
as U+FFFD followed by the text "a0".

Confirmed by hexdump of the live response:

    content:"  e2 9c 93   00   61 30  ";
              ✓ (UTF-8)  NUL   "a0"

So this is a real byte being served, not a font or icon-loading failure.

## Acceptance

- [x] Both hero trust badges read cleanly: a check mark, a space, then the text
- [x] No NULL byte anywhere in the served HTML/CSS — assert on the response
      bytes, not on the source string
- [x] Sweep `landing.py` for the same class of bug: any `\0` or CSS escape
      inside an f-string. Fix any others found and say what you found
- [x] Regression test that would fail if a NULL byte returns to the response

## Result

**Shipped and verified. All 4 acceptance criteria met.**

**Fix**: `landing.py` line 559 — changed `"✓\00a0"` to `"✓\u00a0"`. Python's `\0`
is an octal escape (chr(0)); `\u00a0` is the Unicode escape for U+00A0 (non-breaking
space). The CSS now receives the actual non-breaking space character, not a NULL byte.

**Sweep**: Only one `\0` occurrence existed in `landing.py` — the one in the trust-badge
CSS. No other instances found.

**Tests**: 4 new assertions in `tests_onboarding_parent.py` section 8h:
- `b"\x00" not in _html_bytes` — asserts on response bytes, not source string
- trust-badge CSS selector present
- both badge texts visible

All 139 tests pass (135 pre-existing + 4 new). `tests_admin_dash.py` also green.

**Reviewer**: general-purpose Claude subagent — APPROVED (Kimi CLI not available on Hal Mac,
same substitution used by all prior cycles).

**Production verify**: 16/16 checks passed after deploy.
