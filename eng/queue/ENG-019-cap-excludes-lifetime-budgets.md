# ENG-019 — the $30/day cap does not see lifetime-budget spend

- id: ENG-019
- from: growth
- status: needs-adnan
- priority: P1
- blast: unset
- opened: 2026-08-12
- experiment: EXP-005

## Request

**Held for Adnan's ruling — this is a policy question before it is a code
change. Do not build it while status is needs-adnan.**

`budget_guard.py` projects the cap from *daily budgets* and excludes
lifetime-budget campaigns by design ("no daily cap — Meta paces"). Meta's
Instagram Post campaign runs on a $66 lifetime budget, so it contributes
$0.00 to the projection. The guard has therefore reported
"OK: within cap — $19.00 / $30.00" on days when real combined spend was:

| day | Google | Meta | combined |
|-----|--------|------|----------|
| 2026-08-07 | $5.43 | $25.58 | **$31.01** |
| 2026-08-10 | $22.46 | $9.11 | **$31.57** |
| 2026-08-11 | $18.45 | $13.84 | **$32.29** |

Three breaches of a rule `growth/CLAUDE.md` calls non-negotiable. The guard
was not wrong by its own definition; it cannot see the money. Actual spend
figures are from the Meta Graph API and Google Ads API, pulled 2026-08-12.

The exposure is bounded now — the Instagram campaign has ~$6.31 left and
Adnan's 2026-08-12 call is to let it exhaust — so this is not urgent today.
It matters the next time any channel runs on a lifetime or pacing-based
budget, which is most Meta objectives.

**The question for Adnan:** should the cap be enforced against *projected
daily budgets* (today's behaviour — cheap, predictive, blind to pacing) or
against *actual spend to date* (accurate, but only catches a breach after
the money is gone)? A third option is both: keep the projection as the
pre-flight check and add a retrospective check that alarms when yesterday's
real combined spend exceeded the cap.

## Acceptance

- [ ] Adnan rules on which definition the cap uses; ticket moves to open
- [ ] Guard reports lifetime/pacing-budget campaigns in the projection under
      the chosen definition, or explains in its output why they are excluded
- [ ] A day whose real combined spend exceeds the cap is surfaced somewhere an
      operator will see it, not silently absorbed

## Result

(eng fills this in)
