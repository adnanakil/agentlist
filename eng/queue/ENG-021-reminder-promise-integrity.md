# ENG-021 — HAL says "Done ✅" to reminder requests that can never fire

- id: ENG-021
- from: adnan
- status: open
- priority: P0
- blast: unset
- opened: 2026-08-12

## Request

The first paid family asked on day one: "Remind me every time 10 min ahead of
the next feed." HAL replied "Done — I'll remind you 10 minutes before each
forecasted feed 🍼". Nothing ever fired. They waited five days, feeding every
2-3 hours, then exported their data and texted Stop.

Three stacked causes, all verified in prod data on 2026-08-12:

1. **Wrong tool.** The turn's steps show calls to `current_time` and `baby`
   only — `set_reminder` was never invoked. The request was stored as a
   family routine: {"text": "Nurse Samuel in about 10 minutes", "after":
   "feed", "offset_min": -10}.
2. **Dead switch.** That family's settings carry `auto_reminders: false`, so
   routines can never fire. The founder family has 433 outbox sends and 570+
   reminders — the machinery works; the default killed it for the first real
   customer, and nothing surfaced that the promise was unkeepable.
3. **Settings pollution.** The routines list also contains junk the model
   persisted: entries with text " " and one reading "No new routine".

Sharpest detail: two minutes EARLIER the same family complained about a missed
nudge and HAL apologized: "no reminder was actually pending... I'll only say a
nudge is set after it's successfully scheduled." Then it broke that exact rule
on the next turn.

Outcome wanted: a confirmed nudge either verifiably fires or the family is
told, at ask time, that it cannot. "Done" must be gated on a successfully
persisted, fireable schedule (right tool AND auto_reminders true AND a row that
a scheduler will actually pick up). Whether new families should default
auto_reminders to true is Adnan's product call — put the options in the ticket
result with a recommendation rather than silently flipping it. Also reject
blank/no-op routine writes.

## Acceptance

- [ ] Asking for a recurring pre-feed nudge as a family with auto_reminders
      off produces either a working schedule or an honest "can't do that yet"
      — never a bare "Done"
- [ ] A test asserts the confirmation is emitted only after the schedule row
      exists and is fireable
- [ ] Blank or "no new routine" text can no longer be persisted as a routine
- [ ] auto_reminders default question staged for Adnan with a recommendation
- [ ] reminders-time eval scenarios re-run; no regression vs luna baseline
- [ ] Brain lane — expect RED: stage and escalate, do not deploy

## Result

(eng fills this in)
