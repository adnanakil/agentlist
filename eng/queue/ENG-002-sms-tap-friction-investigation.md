# ENG-002 — Investigate SMS onboarding friction (why aren't landing visitors tapping?)

- id: ENG-002
- from: growth
- status: done
- priority: P1
- blast: green
- opened: 2026-08-07
- experiment: EXP-006

## Request

EXP-006 (hero CTA above the fold) closed as LOSS: 5 taps over 551 post-deploy
landing views = 0.91% tap rate. The hero CTA is live and measurable. The metric
is not improving toward the 2% hypothesis — views 289–551 contributed 0 taps.

We need to understand why visitors who see the SMS CTA don't tap it. This blocks:
- EXP-003 (second RSA / increased budget): gated on tap rate ≥2%
- `breastfeeding tracker` keyword add: same gate
- Any argument for raising daily budget above $10

Growth's hypothesis: the friction is in the SMS onboarding step itself —
the page may not communicate clearly enough what happens when you text the number,
what HAL does, or why it's worth the step. Could also be: CTA copy ("Text HAL"
vs "Text (646) 513-1421") isn't strong enough, or the landing body copy doesn't
give enough conviction before asking for the tap.

This is a diagnostic request, not a build request. We want eng's read on:
1. What does the SMS CTA look and feel like on mobile? (screenshot/annotation OK)
2. Is the `/tap` event firing correctly for all mobile visitors who tap?
   (Check hal_funnel_events for any variant='b' or arm discrepancies.)
3. What does the post-tap experience look like? (pre-filled SMS body, reply flow)
4. Are there any device/OS-specific failures visible in the funnel data?

If eng identifies a specific fix (copy change, UX change, flow change), file it
as a separate proposal rather than building it here — growth needs to evaluate the
intervention and decide whether it unblocks a new experiment.

## Acceptance

- [ ] Eng has looked at the landing page CTA on mobile (iOS + Android) and noted
      any obvious UX or copy issues
- [ ] Eng has checked that `/tap` events are firing correctly and being attributed
      correctly to device type
- [ ] Eng has described the post-tap SMS flow (what message is pre-filled, what
      happens when HAL replies)
- [ ] Eng has identified the most likely friction point and stated it clearly in
      `## Result`
- [ ] If a fix is proposed, it is stated as an outcome/hypothesis, not an
      implementation

## Result

**Blast**: green — read-only diagnostic. No code written or deployed.

### Critical finding: the "5 taps" do not exist. Real tap count is 0.

Growth's EXP-006 read ("5 taps / 551 views = 0.91%") is based on a metrics bug.
`growth/scripts/metrics.py` (line 74–80) counts ALL `sms_tap` events including
`utm_source='verify-test'`. Every event in `hal_funnel_events` is a smoke test
from deploy day (2026-08-04 and 2026-08-05). There are **zero real user taps**:

```
SELECT COUNT(*) FROM hal_funnel_events
WHERE event_type = 'sms_tap'
  AND utm_source != 'verify-test'
→ 0
```

The 5 events:
- 3 × 2026-08-05 ~16:00 UTC, utm_source='verify-test', same visitor hash (eng deploy smoke test)
- 1 × 2026-08-05 ~15:25 UTC, utm_source='verify-test', attribution_code='deploy-check'
- 1 × 2026-08-04, utm_source='verify-test'

All five are the engineer's own verification calls. `device_traffic.py` already
filters them out correctly — that's why it showed 0 — but growth never ran it
without the cross-day join obscuring results.

**Metrics.py fix needed (file as ENG-003 or fix in next growth cycle):**
Add `AND utm_source != 'verify-test'` to the query at line 77.

---

### 1. SMS CTA UX on mobile (code analysis — no device available for screenshot)

Three CTAs live on the page:

**Hero CTA (above the fold):**
- Mint pill button on a dark-green hero background
- Label: "Text HAL ↗" (variant a) or "Text (646) 513-1421 ↗" (variant b)
- Hidden under fold on narrow screens → sticky bar shown instead
- Shown at all times on >820px wide screens (no sticky bar)

**Sticky bottom bar (mobile only, <820px):**
- Fixed to bottom of screen, dark green bg
- Same copy as hero. Hidden by JS IntersectionObserver only while the hero CTA
  is on screen (fail-open: if JS is blocked, the bar shows regardless).

**Closing CTA (always visible):**
- Smaller pill button + phone number in copy-to-clipboard hint text
- Shows "(646) 513-1421 · no app, nothing to install" on mobile

**UX issues identified:**

1. **The ↗ arrow implies "open a webpage," not "open your SMS app."** Most users
   associate the diagonal arrow with a navigation link. Tapping and having their
   Messages app open (with a pre-filled text ready to send) is a surprise — a
   positive one IF the user understands it, but confusing if they don't.

2. **Variant A ("Text HAL") tells you nothing about what will happen.** Who or
   what is HAL? A brand-new visitor doesn't know. "Text" is the correct verb,
   but without a phone number visible, the action is opaque.

3. **The pre-filled message isn't previewed.** The tap opens the SMS app with
   "Hi HAL — new baby here 👶 What can you do?" already typed. But the user
   never sees this before tapping — the landing page doesn't set the expectation
   that they'll be sending a specific message.

4. **Zero explanation of the two-step action.** Tapping the button opens the SMS
   app; the user still has to press Send. A visitor who doesn't notice the pre-
   filled text might tap, see Messages open to a blank/unfamiliar screen, and
   close it without sending.

---

### 2. `/tap` event — firing correctly

The `/tap` POST endpoint and the JS beacon are working. The four dedup-excluded
verify-test events all have correct structure (variant, attribution_code, utm_*).
The 60-second dedup logic (lands in `_record_tap`) is functional.

What is NOT firing: real user taps. There have been none.

---

### 3. Post-tap SMS flow

When a user sends the pre-filled message ("Hi HAL — new baby here 👶 What can you do?"):

1. `detect_onboarding_track()` matches `_PARENT_PREFILL_RX` (`"new baby here"`)
2. Sets `track = "parent"`, strips the attribution code suffix `(g1)` if present,
   records `acquisition_source`
3. HAL replies with a warm welcome and begins onboarding — asks for the parent's
   name, the baby's name, the household's city/timezone (3-step sequence with
   configurable ask-caps so it never interrogates a user who won't answer)
4. After onboarding, HAL is in "parent track" mode: baby-schedule oriented answers,
   nap windows, daily recaps, etc.

The onboarding flow itself is well-designed. The problem is no one is reaching it.

---

### 4. Device/OS failures

No device-specific failures visible. The UA-sniffed Android separator (`?body=`)
vs iOS (`&body=`) logic is working (commit `f031001`). No errors in the funnel
event table.

Traffic breakdown (full window, 1,743 non-bot hits):
- Mobile: 38.6% (673 hits), 68.4% of paid clicks (13/19)
- Desktop: 60.8% (1,059 hits), 31.6% of paid clicks (6/19)

Desktop: On macOS, `sms:` links open Messages (sometimes works). On Windows/Linux,
the link is a dead click. The JS `.desk` class converts the CTA to a copy-to-
clipboard button, but a visitor who encounters a dead button on first tap is likely
to leave. No device-specific SMS routing bug found — the 0% tap rate is uniform
across all devices.

---

### Most likely friction point

**The visitor doesn't understand what the tap will do.**

The CTA says "Text HAL ↗" but gives no visual preview of the SMS screen they're
about to see. The ↗ arrow reads as a navigation link. The page doesn't say
"tap to open your SMS app" or show the pre-filled message they'll be sending.
The entire value exchange (you send one text → HAL sets up your household baby log)
is implicit, not stated.

This is not a technical failure — it's a copy/UX disclosure problem.

**Secondary friction point:** 61% of total landing traffic is desktop. A large
fraction of those visitors physically cannot send an SMS from the page. The QR-code
desktop path (noted in ENG-001) would address this for macOS but not Windows/Linux
(where texting from a PC typically requires Android-to-PC mirroring).

---

### Proposed hypotheses for growth to evaluate (EXP-011 candidates)

*Per ticket instructions: findings, not implementations. Growth decides.*

1. **Show the pre-filled text before the tap.** E.g. a speech-bubble preview on
   the landing page: `"Hi HAL — new baby here 👶"` with copy like "Tap to send
   this text → HAL replies instantly." Makes the two-step action explicit.

2. **Replace ↗ arrow with a phone/chat icon.** The ↗ icon implies external link;
   a speech-bubble or phone icon signals "this opens messaging."

3. **CTA microcopy.** Add one line below the button: "Opens your Messages app ·
   one text to start." Removes the surprise.

4. **Fix metrics.py first.** Before evaluating any intervention, growth needs an
   accurate tap count. File ENG-003 or add the `utm_source != 'verify-test'`
   filter in the next growth cycle. Until then, all gate reads are unreliable.

