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
