# ENG-012 — Make the hero CTA read as a button, with a right-pointing arrow

- id: ENG-012
- from: adnan
- status: open
- priority: P2
- blast: unset
- opened: 2026-08-08

## Request

Adnan: the CTA does not read clearly enough as a button. Make it obviously
pressable and add an arrow pointing right.

### Important constraint — read before changing the icon

ENG-004 deliberately **removed** a `↗` arrow from this button and replaced it
with a speech-bubble icon, because the diagonal arrow signalled "this navigates
off-site" when the button actually opens the Messages app. Do not undo that.

The ask here is a **right-pointing arrow (→)**, which is a different signal:
"proceed", not "external link". The speech bubble should stay — it is what tells
people this opens SMS. Treat this as adding affordance, not swapping the icon
back. If you conclude that a → alongside the speech bubble is visually cluttered,
say so in `## Result` and propose the alternative rather than silently dropping
one.

Also in scope: whatever makes it read as pressable — weight, padding, a clearer
edge, a pressed state. Eng picks the treatment.

### Experiment interaction

EXP-011 (the CTA legibility test) is nominally in flight, but it currently reads
**0 taps on 266 real mobile views**, well past its 150-view gate. Growth is
treating that as answered. Changing the button will end that experiment — that is
accepted, not an accident. Note in `## Result` that EXP-011 was closed by this
change so the ledger stays honest about why the arms stopped.

## Acceptance

- [ ] Hero CTA reads unambiguously as a pressable button
- [ ] A right-pointing arrow is present; the speech-bubble SMS signal is retained
- [ ] Sticky mobile bar and closing CTA stay visually consistent with the hero
- [ ] Tap instrumentation still fires from every CTA after the change
- [ ] `## Result` states that EXP-011 is closed by this change

## Revision 2026-08-08 (Adnan) — arrow goes AFTER the number

Adnan, looking at the new green CTA on the light hero:
"put an arrow -> like that or something after the number"

So: **a right-pointing arrow, trailing, after the phone number**, inside the
pill. Not leading, not replacing the label.

    [  Text (646) 513-1421   →  ]

### The speech bubble — resolve this deliberately, do not just drop it

The original ticket said keep the speech-bubble icon, because ENG-004 added it
on purpose: a `↗` had been signalling "navigates off-site" when the button
actually opens Messages.

That reasoning is weaker now, and eng should decide with it stated out loud:
the button label already reads **"Text (646) 513-1421"** — the verb *Text* plus
a literal phone number is a stronger SMS cue than any icon. The bubble may now
be redundant decoration.

Two acceptable outcomes, both were shown to Adnan:
- **A** — number + trailing arrow, no bubble. Cleanest; the label carries the
  meaning.
- **B** — bubble + number + trailing arrow. Retains ENG-004's explicit signal
  at the cost of a busier pill.

Pick one, state which and why in `## Result`. What is NOT acceptable is
silently losing the SMS signal without noticing the tradeoff.

### Constraints

- Arrow is a plain right arrow (→). **Never `↗`** — that is the external-link
  glyph ENG-004 removed, and re-adding it would repeat a known mistake.
- The arrow is decorative: it must not be announced by screen readers, and the
  accessible name of the button must remain the phone number / "Text HAL".
- Applies to the hero pill, the sticky mobile bar and the closing CTA — keep
  all three consistent.
- Under the new light hero (ENG-014) the pill is solid green with white text;
  the arrow is white. Check contrast on whatever background each instance sits
  on, not just the hero.
- Do not let the arrow wrap to its own line at narrow widths, and do not let it
  push the number to two lines. If the pill cannot fit both on the smallest
  supported width, drop the arrow at that breakpoint rather than breaking the
  label.
- Tap instrumentation must still fire from every CTA afterwards.

## DECIDED 2026-08-08 (Adnan) — build option A. No choice remains.

    [  Text (646) 513-1421   →  ]

**Option A: phone number + trailing right arrow. The speech-bubble icon is
removed from the CTA.** Do not build B. Do not re-open the comparison.

Rationale, so this is not re-litigated later: the label already reads
"Text (646) 513-1421" — the verb plus a real phone number carries the SMS
signal that ENG-004's speech bubble was added to provide. The icon became
redundant once the number itself appeared in the label. ENG-004's underlying
finding is intact and unchallenged: **the diagonal `↗` stays banned**, because
it read as "navigates off-site". A plain `→` is an affordance cue, not a
destination cue.

Everything in the revision above still applies: trailing position, decorative
(hidden from assistive tech, accessible name stays the number), consistent
across hero pill / sticky mobile bar / closing CTA, contrast checked per
background, no wrapping — drop the arrow at any width where the label would
break instead.

Note in `## Result` that this change closes EXP-011, whose arms are ended by
altering the CTA.
