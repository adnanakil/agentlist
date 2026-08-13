# ENG-022 — An opt-out died in a provider failure and left no trace

- id: ENG-022
- from: adnan
- status: open
- priority: P1
- blast: unset
- opened: 2026-08-12

## Request

When the paid family texted "Stop" (2026-08-11 01:54 UTC), the turn ended
status=gemini_failed. Steps show the model correctly called `group_quiet`,
but nothing persisted — no mute in family state, no stopped_at — and the
family received "Sorry, I'm having trouble right now. Please try again." as
the reply to an opt-out. The fallback chain (claude-opus-4-8,
gemini-3.1-pro-preview) did not rescue the turn.

The deterministic STOP handler (shipped 2026-08-12, commit 342f100) should
catch a bare "Stop" before any model call now. Wanted:

1. Verify the deterministic handler would have caught THIS exact message
   (`[+1...]: Stop ` — group message with sender prefix and trailing space)
   — add it and near variants as regression tests if not covered.
2. Ensure a turn that dies mid-flight cannot reply with "try again" boilerplate
   to a message the deterministic layer classifies as an opt-out.
3. Backfill: set stopped_at on the Samuel group silo (chat...8351) to honor the
   2026-08-11 Stop retroactively. Adnan approved at the 2026-08-12 standup.
   This is a flag write, not a deletion. Leave the ad-parent's DM silo alone.

## Acceptance

- [ ] Regression test: group-prefixed "Stop " (trailing space) short-circuits
      deterministically, no model call required
- [ ] A provider-failure turn on an opt-out message never sends "try again"
- [ ] Samuel group silo has stopped_at set; outbox gate verified to drop
      sends to it (test via the test outbox channel, not a real send)
- [ ] Brain lane — expect RED: stage and escalate, do not deploy (the backfill
      command staged in the report for Adnan or run only if triage says GREEN)

## Result

(eng fills this in)

## Addendum (2026-08-12, standup session)

Answer to item 1, from reading routes/message.py:1448-1480 — the deterministic
layer is **1:1 only, by design** (`if not is_group`). The prod group "Stop"
would NOT have been caught even after 342f100; group opt-outs are deliberately
model-mediated (group_quiet). So the real asks are items 2 and 3, plus a
decision: either extend deterministic STOP to groups (with the
one-member-mutes-all tradeoff made explicit) or keep it model-mediated and
make the failure path safe (item 2). New eval scenarios pin both behaviors:
evals/scenarios/prod-optout.yaml (prod-optout-bare-stop-group asserts the
model path muted via group_quiet; prod-optout-dm-stop-deterministic asserts
the 1:1 short-circuit).
