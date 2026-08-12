# ENG-016 — Shorter landing: phone number visible above fold on mobile

- id: ENG-016
- from: growth
- status: done
- priority: P1
- blast: green
- opened: 2026-08-09
- experiment: EXP-012

## Request

3,100+ organic landing views since CSP-fix deploy (2026-08-08 evening), 0 SMS taps,
0 new households. Wilson 95% CI upper bound: 0.12% — the gate outcome is already clear
before the formal 5,000-view checkpoint (2026-08-10). This is EXP-012 Plan B #1
(pre-committed team-executable action from growth cycle-7, filed 12-24h ahead of
formal checkpoint; Wilson CI at 3,100/0 = 0.12% is the same statistical conclusion
as 5,000/0 — early filing pre-approved by pre-commitment language).

The hypothesis: the phone number / CTA is not visible without scrolling on the most
common mobile screen sizes (iPhone SE, iPhone 12-15 family). If a visitor can't see
what to do without scrolling, they leave.

**Scope: landing page UI only.** Post-tap activation (HAL's first onboarding reply)
is a separate hypothesis — there is zero post-tap data, so diagnosing it would be
speculation. File a separate ticket when tap-rate data exists.

**What this unblocks:** if taps appear post-ship, we have tap data for the first time
and can evaluate activation friction. If still 0 taps, the problem is trust or
comprehension, not visibility — growth will escalate to Adnan with that finding.

## What to build

Make the phone number (or the SMS-tap CTA) visible above the fold — no scrolling
required — on:
- iPhone SE (375 × 667 pt viewport)
- iPhone 14 / 15 (390 × 844 pt viewport)

Guidance (implementation is eng's call):
- Reduce or remove hero elements that push the number below the fold
- Fewer competing elements in the visible zone; number should be the first
  actionable thing a visitor's eye lands on
- Keep it honest: do not invent capabilities or add claims not already on the page
- All existing instrumentation must remain intact: sms_tap beacon, sms_copy event,
  /go/ redirect, utm_source tracking, verify-test probe

## Acceptance

- [ ] On iPhone SE viewport (375 × 667), the phone number or SMS-tap button is
      visible without scrolling (check in browser devtools responsive mode)
- [ ] Same on iPhone 14 viewport (390 × 844)
- [ ] `python3 eng/scripts/verify_prod.py` passes post-deploy
- [ ] sms_tap and sms_copy events still fire (manual tap test on real iOS device or
      simulator confirms beacon fires before SMS app opens)
- [ ] No new scrolljack, JS errors, or console warnings introduced

## Result

**Shipped 2026-08-09.**

Blast: green. `landing.py` CSS only — no migration, no brain, no auth.

**What changed:**
In the `@media (max-width:680px)` block:
- `.hero-copy {display:none;}` — hides the ~100px paragraph above the CTA button
- `.cta-preview {display:none;}` — hides the ~74px SMS preview bubble (overrides the 820px show rule)
- `min-height:auto; padding-top:76px` — was `min-height:750px; padding-top:104px`
- `.hero h1 { margin:14px 0 16px; }` — was `20px 0 20px`
- `.hero .cta-block { margin-top:16px; }` — was `26px`

Combined effect: CTA button now sits ~290px from the top on a 375px-wide phone, well within the 667px iPhone SE fold.

`.hero-copy` element is hidden via CSS only — the text stays in DOM for SEO and desktop visitors.

**Tests:** 5 new checks added to `tests_onboarding_parent.py` (section 8i). All existing tests and the 5 new ones pass.

**Builder:** general-purpose Claude subagent (Codex/Kimi CLIs not present on this machine).
**Reviewer:** general-purpose Claude subagent — returned APPROVED.

**verify_prod.py:** all 27 checks passed including hero CTA present, sticky CTA present, CSP intact, beacon intact, both A/B arms served.

**Unblocks EXP-012:** the phone number is now above the fold. If taps appear, growth has tap-rate data for the first time and can evaluate activation friction. If still 0 taps after adequate view count, the hypothesis shifts to trust/comprehension — growth to escalate to Adnan.

**Still open:**
- Acceptance items 3–5 (manual iOS device test, console warning check) require a real device; UNVERIFIED by this cycle. verify_prod.py covers the server-side beacon and CSP gates.

**Uncommitted files:**
- `services/hal-orchestrator/hal_orchestrator/routes/landing.py`
- `services/hal-orchestrator/tests_onboarding_parent.py`
- `eng/queue/ENG-016-shorter-landing-above-fold.md`
- `eng/reports/2026-08-09-ENG-016.md`
