# The eng queue

One markdown file per ticket: `ENG-NNN-short-slug.md`.

The header block is **machine-parsed** by `eng/scripts/queue_check.py` — keep
the `- key: value` shape exactly. Everything below the header is for humans and
agents to read.

```markdown
# ENG-007 — One-line title

- id: ENG-007
- from: growth              # growth | adnan | eng
- status: open              # open | in-progress | done | blocked | needs-adnan
- priority: P1              # P0 (funnel is broken / money burning) | P1 | P2
- blast: unset              # unset until eng triages; then green | red
- opened: 2026-08-05
- experiment: EXP-011       # optional — links to growth/state/experiments.md

## Request

What outcome is wanted, and why. Written by the requester. State the decision
this unblocks, not the implementation — eng picks the implementation.

## Acceptance

- [ ] Checkable conditions. "Tap rate is visible per device class in
      /admin/traffic" beats "add device tracking".

## Result

(eng fills this in: what shipped, what was verified and how, what is still
open. This is the handoff back to the requester.)
```

## Rules

- **Never delete a ticket.** `done` tickets are the team's memory.
- `status: open` is what wakes the team. Anything else is inert.
- One ticket = one outcome. If a request has two independent outcomes, file two.
- Growth files tickets here instead of editing application code (see
  `eng/CLAUDE.md` → Lanes).
- Eng answers in the ticket's `## Result` — the requester reads the outcome
  where they filed the request.
