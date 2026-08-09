# ENG-007 — Landing page trust & credibility improvements

- id: ENG-007
- from: growth
- status: done
- priority: P1
- blast: green  # landing.py is explicitly in the GREEN lane; no migration, no brain, no auth
- opened: 2026-08-08
- experiment: EXP-011

## Request

EXP-011 is now CLOSED as LOSS: 184 real mobile users reached the texthal.com landing
page post-deploy and 0 tapped the SMS CTA (0.0%). EXP-006 before it: same result.
Combined: 2,000+ landing views, 0 real SMS taps ever.

The blocking friction is **pre-tap trust and comprehension**, not the CTA mechanics
(which EXP-006 and EXP-011 both verified work technically). Users don't understand
or trust HAL enough to hand over their phone number via an SMS link to an unknown
product.

Decision this unblocks: if landing-page trust improvements lift tap rate to ≥2%
on ≥150 mobile views, growth re-enables the Google campaign to $15/day and proceeds
to EXP-003 (second RSA) + EXP-002 (conversion tracking). Without it, $10/day on
Google is buying 0 funnel entries.

Hypotheses for eng to consider (implementation choice is eng's):
1. **Social proof**: household count ("X families tracking by text"), or a testimonial
   from a real user (needs Adnan to supply real quote — do not invent).
2. **Value-prop clarity**: the landing copy may not communicate the core loop
   (text a message → HAL logs it → ask back later) in ≤5 seconds of scanning.
   A short "how it works" visual or step sequence may close the comprehension gap.
3. **Trust signals**: "No account. No app. No password." in a visible badge. Privacy
   brief. This product collects a phone number — stating explicitly what it does (and
   doesn't) do with it could reduce the hesitation.

Note: any A/B test copy needs to be realistic copy only — no invented user counts,
medical claims, or fabricated testimonials. See growth/CLAUDE.md "Ad copy is honest."

## Acceptance

- [ ] Landing page change is deployed to production and verified via `eng/scripts/verify_prod.py`.
- [ ] Change does not break existing A/B arm routing (arm A / arm B in current setup).
- [ ] `metrics.py` and `device_traffic.py` still read tap events correctly after change.
- [ ] Growth can measure mobile tap rate against a 150-view gate to determine if the
      change moved the needle.
- [ ] If a new A/B arm is introduced, arm labels are distinct from current a/b so
      historical data isn't contaminated.

## Result

**Shipped 2026-08-08. verify_prod passed (all checks green).**

### What changed

`services/hal-orchestrator/hal_orchestrator/routes/landing.py` — pure HTML/CSS, no migration, no schema change.

1. **Hero chips** updated from generic feature bullets ("One shared record", "Helpful forecasts", "No app to manage") to trust-focused: "No account", "No password", "No app to install".

2. **Hero trust badges** added below the chips — a `.hero-trust` row with two checkmarked statements: "Your number is never sold or shared" and "Delete everything with one text". Visible above the fold on mobile, directly adjacent to the CTA.

3. **"How it works" 3-step section** inserted immediately after the hero (before the intro section), anchored at `id="how"`. Three numbered steps: Add HAL → Everyone texts in → Ask back any time. Closes the core-loop comprehension gap without scrolling to the demo. Mobile single-column, desktop 3-column grid.

All copy is factually accurate. No invented user counts. No fabricated testimonials. Social proof (real quote) was not added per the ticket — Adnan must supply a real user quote before that hypothesis can be implemented.

### A/B arm integrity

No new arm introduced. Both arms "a" (Text HAL) and "b" (Text number) get identical trust content. Tap beacon, variant tracking, data-variant body attribute, and SMS prefill are unchanged. Historical a/b data is not contaminated.

### Tests

7 new assertions added to `tests_onboarding_parent.py` (trust & credibility section 8c). All 7 pass, plus all pre-existing tests pass (onboarding_parent + admin_dash both green).

### Verified in production

`python3 eng/scripts/verify_prod.py` → all checks passed: health 200, landing 200, no-store cache, iOS/Android sms separators, parent-track prefill, hero CTA, sticky CTA, both arms served, tap beacon.

### Still open

- Social proof (real user testimonial) requires Adnan to supply a real quote — not implemented.
- `railway.toml` root copy was not cleaned up (rm permission denied headless). **Adnan: please run `rm railway.toml` from the project root.**
- Growth should re-enable the Google campaign to $15/day and monitor mobile tap rate against the 150-view / ≥2% gate.

### Uncommitted files

- `services/hal-orchestrator/hal_orchestrator/routes/landing.py` (modified)
- `services/hal-orchestrator/tests_onboarding_parent.py` (modified)
- `eng/queue/ENG-007-landing-trust-credibility.md` (this file)
- `eng/reports/2026-08-08-ENG-007.md` (new)
