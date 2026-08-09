# ENG-004 — EXP-011: Landing CTA UX — make the SMS action legible

- id: ENG-004
- from: growth
- status: done
- priority: P1
- blast: green
- opened: 2026-08-07
- experiment: EXP-011

## Request

EXP-006 (hero CTA above the fold) closed as LOSS. ENG-002 diagnosed the root
cause: **visitors don't understand what tapping the button will do.** The ↗
arrow implies a web navigation link, not an SMS action. There is no preview of
the pre-filled message, and no microcopy explaining that tapping opens the SMS
app. Real user tap rate: 0 / 1,904 landing views.

Growth's EXP-011 hypothesis: making the two-step SMS action explicit (open SMS
app → press Send) will move mobile tap rate from 0% to ≥2%.

Three specific changes from ENG-002's hypotheses (eng chooses the implementation):

1. **Replace the ↗ arrow with a messaging/phone icon.** The ↗ icon signals
   external link navigation. A speech-bubble, message, or phone icon signals
   "this opens messaging." Apply to the hero CTA pill and the sticky bottom bar.

2. **Add CTA microcopy below the button:** "Opens your Messages app · one text
   to start." One short line. Removes the surprise about what tap will do.

3. **Show a speech-bubble preview of the pre-filled message** before the tap.
   Something like: `"Hi HAL — new baby here 👶"` with a line: "Tap to send →
   HAL replies instantly." This makes the two-step action (tap → send) explicit
   and removes the confusion when Messages opens with text already filled in.

These changes should apply to mobile CTAs (hero pill + sticky bar). Desktop
CTA (copy-to-clipboard) does not need the SMS-specific microcopy.

This unblocks:
- EXP-003 (second RSA / budget raise to $15/day): gated on ≥2% tap rate
- `breastfeeding tracker` keyword add: same gate
- Campaign re-enable: growth will re-enable campaign 24100110386 on deploy

## Acceptance

- [ ] Hero CTA pill uses a messaging/phone icon instead of ↗ (mobile only)
- [ ] Sticky bottom bar uses the same icon change
- [ ] Microcopy "Opens your Messages app · one text to start" visible below the
      button on mobile
- [ ] Pre-filled message preview is visible above or near the CTA on mobile
- [ ] `/tap` events still fire correctly (smoke test: verify-test utm_source)
- [ ] Changes verified in production via `eng/scripts/verify_prod.py`

## Gate (growth will read at 50+ mobile landing views post-deploy)

- ≥2% mobile tap rate AND ≥50 mobile landing views: EXP-011 WIN
  → re-enable campaign, raise budget to $15/day, proceed to EXP-003
- 1-2% mobile tap rate: INCONCLUSIVE → extend gate to 100 mobile views
- <1% mobile tap rate at 50+ views: LOSS → evaluate more structural changes
  (desktop traffic suppression, onboarding copy rewrite, QR code path)

## Result

**Status: needs-adnan — deploy blocked by dirty working tree.**

### What was built

Three changes to `services/hal-orchestrator/hal_orchestrator/routes/landing.py` (GREEN lane):

1. **Message icon**: replaced `↗` with a speech-bubble SVG (`<path d="M20 2H4..."/>`) on the hero CTA, sticky mobile bar, and closing-section CTA. nav_cta left unchanged (it's navigation, not SMS action).

2. **Microcopy**: added `<p class="cta-mob-hint">Opens your Messages app · one text to start.</p>` after the hero CTA button. Hidden on desktop (`display:none`), shown on mobile via `@media (max-width:820px)`.

3. **SMS preview**: added `<div class="cta-preview">` above the hero CTA button showing `"Hi HAL — new baby here 👶"` and "Tap to send · HAL replies instantly". Mobile-only (same 820px gate).

Coming-soon variant (no number set) correctly skips all new elements.

### Tests

- 8 new tests: `tests/test_landing_cta_ux.py` — all pass. Covers icon presence, preview presence, microcopy, mobile-only CSS, tap beacon integrity, no-number variant, SMS link.
- Existing: `services/hal-orchestrator/tests_onboarding_parent.py` — all 22 pass (CTA extraction logic updated to account for new nested preview div).
- `services/hal-orchestrator/tests_admin_dash.py` — all pass (unaffected).

### Review

APPROVED by general-purpose Claude subagent (substituting for kimi:kimi-review — Kimi CLI not present on Hal Mac). Reviewer confirmed: correct f-string escaping, correct mobile-only gating, no XSS vector in SVG, coming-soon branch clean, tap beacon unaffected.

### Deploy blocker — Adnan must act

The working tree has ~230 lines of uncommitted RED-zone changes to HAL's brain that this cycle did NOT write:

```
M  services/hal-orchestrator/hal_orchestrator/services/baby.py    (+107 lines — new event kinds)
M  services/hal-orchestrator/hal_orchestrator/tools/baby.py       (+93 lines — history action)
M  services/hal-orchestrator/hal_orchestrator/routes/message.py   (+36 lines)
M  services/hal-orchestrator/hal_orchestrator/prompts/system.py   (+6 lines)
M  services/hal-orchestrator/hal_orchestrator/tools/memory.py
M  packages/ag-common/ag_common/config.py
M  .env.example
```

`railway up` ships the **working directory**, not git HEAD. Deploying ENG-004 right now would also ship these baby-tracker changes (new event kinds: medicine, bath, play, screen_time, solids, symptom, milestone; new history action) to production without a formal review or migration gate. That violates the dirty-tree rule.

### Commands for Adnan (in order)

**Option A — commit the baby-tracker work first, then deploy:**
```bash
# Step 1: commit (or stash) the baby-tracker changes you want to ship
git add services/hal-orchestrator/hal_orchestrator/services/baby.py \
        services/hal-orchestrator/hal_orchestrator/tools/baby.py \
        services/hal-orchestrator/hal_orchestrator/routes/message.py \
        services/hal-orchestrator/hal_orchestrator/prompts/system.py \
        services/hal-orchestrator/hal_orchestrator/tools/memory.py \
        packages/ag-common/ag_common/config.py
git commit -m "Baby tracker: add medicine/bath/play/screen_time/solids/symptom/milestone events + history lookup"

# Step 2: deploy (landing page UX + baby-tracker changes together)
cp services/hal-orchestrator/railway.toml railway.toml
railway up --service hal-orchestrator --detach
rm railway.toml

# Step 3: verify
python3 eng/scripts/verify_prod.py
```

**Option B — stash the baby-tracker changes, deploy landing only, then pop:**
```bash
git stash -- services/hal-orchestrator/hal_orchestrator/services/baby.py \
             services/hal-orchestrator/hal_orchestrator/tools/baby.py \
             services/hal-orchestrator/hal_orchestrator/routes/message.py \
             services/hal-orchestrator/hal_orchestrator/prompts/system.py \
             services/hal-orchestrator/hal_orchestrator/tools/memory.py \
             packages/ag-common/ag_common/config.py
cp services/hal-orchestrator/railway.toml railway.toml
railway up --service hal-orchestrator --detach
rm railway.toml
python3 eng/scripts/verify_prod.py
git stash pop
```

### Unblocked (on deploy)

- EXP-003 (budget raise to $15/day) — gated on ≥2% mobile tap rate after EXP-011 deploys
- `breastfeeding tracker` keyword add — same gate
- Campaign 24100110386 re-enable — growth acts on it the cycle after deploy + gate reads ≥2%

### Uncommitted files (not committed by this cycle per eng protocol)

- `services/hal-orchestrator/hal_orchestrator/routes/landing.py` (modified)
- `services/hal-orchestrator/tests_onboarding_parent.py` (modified)
- `tests/test_landing_cta_ux.py` (new)

### Deployed — 2026-08-07 evening (standup decision D1, Option A)

- Baby-tracker batch committed as d5f8fd2, ENG-004 as b6cd882 (Adnan's call,
  Option A). Deployed via railway up from a clean tree; new build confirmed
  live (CTA microcopy serving in prod HTML).
- verify_prod: 9/10 pass. The one FAIL ("both hero-CTA arms served — only saw
  none") is a stale checker, not a prod fault: manual probe read body
  data-variant across 12 UA-varied fetches and saw both arms (5xa / 7xb).
  Checker fix filed as ENG-006.
- EXP-011 gate clock runs from this deploy (growth reads at 50+ mobile views).
