# ENG-013 — Hero trust badges render a NULL byte: "✓�a0Your number is never sold"

- id: ENG-013
- from: adnan
- status: open
- priority: P1
- blast: unset
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

- [ ] Both hero trust badges read cleanly: a check mark, a space, then the text
- [ ] No NULL byte anywhere in the served HTML/CSS — assert on the response
      bytes, not on the source string
- [ ] Sweep `landing.py` for the same class of bug: any `\0` or CSS escape
      inside an f-string. Fix any others found and say what you found
- [ ] Regression test that would fail if a NULL byte returns to the response
