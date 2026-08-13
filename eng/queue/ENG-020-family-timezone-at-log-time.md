# ENG-020 — Logged event times ignore the family timezone the system already has

- id: ENG-020
- from: adnan
- status: in-progress
- priority: P0
- blast: unset
- opened: 2026-08-12

## Request

The first paid family (baby Samuel, San Diego) had `timezone:
America/Los_Angeles` and `tz_set: true` in hal_families from minute one —
onboarding captured it correctly. They still spent four days correcting times:
"The time is wrong it's currently 11:13AM in San Diego" (day 1), "The timing
is confusing can you recheck", "The time is off again", "Remember that
we're in San Diego. Pacific standard time", "Remember we are PST" (final
morning). They churned on 2026-08-11.

Root cause is visible in HAL's own reply on 08-10: "The 5:10 AM header
converted to 2:10 AM Pacific" — inbound messages arrive stamped in the bridge
Mac's local time (Eastern), and the MODEL is expected to convert header time to
family time on every turn. It repeatedly logged header times as local,
producing entries 3 hours off. This is the family-tz bug from the beachhead
review, now with a churned paying customer attached.

Outcome wanted: event timestamps written to the log are family-local without
relying on per-turn model arithmetic. Convert in the pipeline (present the
model family-local time, or convert at write), not in the prompt.

## Acceptance

- [ ] A feed logged from a family with tz_set=true records family-local time
      even when the inbound header is in another timezone
- [ ] A regression test covers a PST family texting through the ET bridge
- [ ] Relevant eval scenarios (baby-logging / reminders-time) re-run; no
      regression vs the 2026-07-13 luna baseline
- [ ] Brain lane — expect RED: stage the diff and escalate, do not deploy

## Result

(eng fills this in)
