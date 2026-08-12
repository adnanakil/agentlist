# ENG-018 — budget_guard.py cannot verify the cap when run by hand

- id: ENG-018
- from: adnan
- status: open
- priority: P1
- blast: unset
- opened: 2026-08-12
- experiment: EXP-000

## Request

`growth/scripts/budget_guard.py` reads `META_ACCESS_TOKEN` straight from the
process environment. Outside the supervisor (which sources `~/.growth-env`),
the variable is absent, so the guard prints
"Meta spend UNKNOWN — cap cannot be verified (META_ACCESS_TOKEN not set)"
and exits 1 — even though the token is sitting in `~/.growth-env` on the same
machine.

ENG-017 solved exactly this for `metrics.py` by adding `_load_growth_env()`.
The guard never got the same treatment. Consequence: every operator who runs
the guard directly — the standup protocol explicitly asks for this — gets a
false "cap cannot be verified" and a non-zero exit. Every 2026-08-11 ledger
entry records that false block as if it were a real one.

The decision this unblocks: an operator running the guard by hand should be
able to trust its verdict without knowing to source a dotfile first.

Reuse `_load_growth_env()` from `metrics.py` rather than writing a second
copy — one loader, imported by both.

## Acceptance

- [ ] `~/.growth-venv/bin/python3 growth/scripts/budget_guard.py` run from a
      bare shell (no env sourced) prints the real Meta figures and exits 0
- [ ] The env loader exists in exactly one place; `budget_guard.py` imports it
- [ ] A genuinely missing or expired token still fails loudly — this ticket
      removes a false negative, it must not create a false positive
- [ ] Existing `tests/test_metrics_tap_filter.py` still passes

## Result

(eng fills this in)
