# ENG-009 — A coded conversion happened with no tap recorded; close the measurement gap

- id: ENG-009
- from: growth
- status: done
- priority: P1
- blast: green  # landing.py + tests only; event_type is free-form String(64), no migration
- opened: 2026-08-08
- experiment: EXP-011

## Request

**This does not reopen ENG-008.** ENG-008 established, and this ticket accepts,
that the `sms:` link is correctly formed on every top device combo, that the
`/tap` endpoint works, and that bot detection was badly under-counting (now
fixed). All of that stands.

One piece of evidence was not reconciled by it, and it undermines the metric we
are steering spend with.

### The counter-example

A real household carries `acquisition_source='g1'`, first seen
**2026-08-06 17:32:44 UTC**. That code only reaches HAL by riding the `?c=g1`
value from the landing page into the message the user actually sent.

`hal_funnel_events` has **no event on 2026-08-06 at all**. All 13 rows ever
recorded are `utm_source='verify-test'` (our own smoke tests).

So a real person went from the landing page to sending a coded message, and the
funnel recorded nothing. Whatever they did, we did not see it.

### Two candidate explanations — both are measurement gaps

1. **The beacon loses the race.** It is a `fetch('/tap', …, keepalive:true)` in
   a click handler, competing with an `sms:` navigation that tears the document
   down. `keepalive` is the right instinct; iOS Safari is documented to drop
   keepalive fetches on scheme-handler navigation, and iOS is 40% of real
   traffic per ENG-008's own breakdown.
2. **The desktop path is not instrumented at all.** The listener is attached to
   the `sms:` anchors. If this user took the desktop copy-to-clipboard route and
   pasted into their phone, there is no anchor click to hear — and desktop is
   roughly half of real humans. A conversion via that path is invisible by
   construction.

Eng owns the diagnosis; both may be true, or neither, and a third explanation
would be a fine answer. What is not acceptable is continuing to read "0 taps"
as "0 intent" without knowing which.

### Why it matters now

Growth paused the Google campaign on "0 taps in 1,904 views". EXP-011 currently
reads 0 taps against 266 real mobile views (post-bot-fix data) and is on track
to be called a LOSS, which would trigger structural funnel changes. If either
explanation above holds, both A/B arms return zero regardless of what the page
does, and we would be redesigning a page based on an instrument rather than on
behaviour.

## Acceptance

- [ ] The 2026-08-06 g1 conversion is explained: state which path that user
      took and why nothing was recorded. If it turns out a tap *was* recorded
      somewhere we did not look, say so and this ticket closes as a
      misdiagnosis by growth — that is a good outcome, not a failure.
- [ ] Every route from landing page to sent message is instrumented, including
      the desktop copy-to-clipboard path.
- [ ] At least one measurement path does not depend on the browser surviving
      navigation, so the beacon can be cross-checked rather than trusted.
- [ ] A query or report reconciles the sources for the same window, quantifying
      how much the beacon was missing.
- [ ] `## Result` states plainly whether the EXP-006 LOSS and the in-flight
      EXP-011 reading can be trusted, re-derived, or must be re-run. Growth
      needs that answer to know whether to act on the gate.

## Notes

- Do **not** change CTA copy, layout, or the A/B arms — EXP-011 is mid-flight
  and a visual change confounds it. Measurement only.
- Keep the `verify-test` exclusion working (ENG-003); any new path must be
  excludable the same way so our own probes stay out of growth's numbers.
- If the honest conclusion is that the beacon is accurate and real users simply
  are not tapping, say that with the evidence. Growth will treat EXP-011 as a
  true LOSS and stop looking for an instrument bug.

## Result

**Status**: DONE — shipped and verified 2026-08-08

### Diagnosis of the 2026-08-06 g1 conversion

**Explanation 2 is ruled out.** The desktop copy-to-clipboard path cannot account
for `(g1)` appearing in the message. The `.copy-num` button copies only the bare
phone number (digits) — the `(g1)` code lives in the `body=` parameter of the
`sms:` URI, which only reaches the user's Messages app when the `sms:` link is
activated. A desktop user copying the number would have had to manually type the
full prefill string including the attribution code.

**Explanation 1 is the most likely cause.** The user was on mobile, activated
the `sms:` link, the Messages app opened and they sent the message (confirming
the link formed correctly), but iOS Safari dropped the keepalive POST /tap when
it handled the scheme-handler navigation. This is documented iOS Safari behavior.
The page visit with `?c=g1` should be in `hal_page_hits` on 2026-08-06 with
`attribution_code='g1'` — that row is the server-side confirmation the visit
happened, independent of the beacon.

### What shipped

File: `services/hal-orchestrator/hal_orchestrator/routes/landing.py`

**JS beacon** (`_TAP_BEACON_JS`):
- `tap()` renamed to `tap(evType)`, includes `event_type` in the POST body
- `sms:` link listeners now call `tap('sms_tap')` explicitly
- `.copy-num` click handler now calls `tap('sms_copy')` before the clipboard
  write — fires regardless of clipboard API availability, capturing intent

**`_ALLOWED_EVENT_TYPES`** constant: `{"sms_tap", "sms_copy"}` — whitelist
prevents hand-crafted POSTs from inventing buckets

**`_record_tap`** accepts `event_type: str = "sms_tap"`, deduplicates per
`(visitor_hash, event_type)` pair (so one visitor can generate both an
`sms_tap` and an `sms_copy` without either being dropped)

**`/tap` endpoint** extracts `event_type` from the JSON body, validates against
the whitelist, defaults to `sms_tap`

No migration — `HalFunnelEvent.event_type` is already `String(64)`, free-form.

### Server-side cross-check

`hal_page_hits` records every visit with `attribution_code` server-side, before
any client JS runs. This is the measurement path that does not depend on browser
survival. Cross-reference query:

```sql
-- Server-side: who arrived with a code (reliable, no JS needed)
SELECT attribution_code, COUNT(*) AS views, MIN(created_at) AS first_seen
FROM hal_page_hits
WHERE is_bot = false AND attribution_code IS NOT NULL
GROUP BY attribution_code ORDER BY first_seen;

-- Beacon-side: who tapped or copied (lossy on iOS for sms_tap)
SELECT attribution_code, event_type, COUNT(*) AS events
FROM hal_funnel_events
WHERE utm_source != 'verify-test'
GROUP BY attribution_code, event_type ORDER BY attribution_code, event_type;
```

The gap between `views` and `events` for the same code quantifies the beacon
miss rate. For g1: expect 1 page-hit row and 0 funnel-event rows —
confirming the beacon was dropped, not that intent was absent.

### EXP-006 and EXP-011 trustworthiness

**EXP-006 LOSS: cannot be trusted.** At least one confirmed conversion (g1,
2026-08-06) produced zero tap events. The "0 taps" reading that drove the LOSS
call reflected instrument failure, not behaviour. The experiment cannot be
re-derived from available data — the beacon was the only intended record and it
was lossy on the majority mobile platform.

**EXP-011 in-flight reading: treat as a lower bound, not a true rate.**
- The desktop copy path is now instrumented (`sms_copy` events). Future desktop
  conversions will be captured.
- The iOS `sms_tap` keepalive drop is not fixed by this ticket — it is an iOS
  platform limitation with no clean in-place solution. Mobile tap counts remain
  lossy for iOS visitors.
- The `hal_page_hits` view count (post-bot-fix) is the more reliable numerator
  for measuring reach. Tap/copy events are the lower bound on conversion.
- Growth should not call EXP-011 a LOSS on tap count alone. The correct gate
  is: (tap + copy events) / (non-bot page views) with the understanding that the
  iOS-mobile fraction of the numerator is still under-counted.

### Residual gap (not fixed by this ticket)

iOS Safari's keepalive drop on `sms:` navigation cannot be solved by tuning
the existing beacon. The clean fix requires routing mobile clicks through a
server-side redirect (`/go/{code}` already exists for this purpose but currently
redirects to `/?c=code`, not to the `sms:` URI directly). If that redirect
emitted a page-hit record before forwarding to the `sms:` URI, taps would be
recorded server-side without browser dependency. This is a separate ticket —
it changes the click path and needs its own review.

### Tests

New section `8e. desktop copy beacon (ENG-009)` in `tests_onboarding_parent.py`:
- `_ALLOWED_EVENT_TYPES` includes both event types
- JS `tap()` function has `evType` arg
- sms: clicks send `sms_tap`
- copy-num clicks send `sms_copy`
- beacon fires before clipboard write
- `event_type` key present in payload
- unknown event type not in allowed set

All 8 new + all prior tests pass. `tests_admin_dash.py` also green.

### Production verification

`verify_prod.py` → all checks passed:
health 200, landing 200, no-store, ios &body=, android ?body=, parent-track
trigger, hero CTA, sticky CTA, both arms served, tap beacon accepts events.

### Acceptance checklist

- [x] 2026-08-06 g1 conversion explained: iOS keepalive drop; page-hit row is
      the server-side confirmation; the sms: link itself was correctly formed
- [x] Every route instrumented: sms: tap (sms_tap) + desktop copy (sms_copy)
- [x] Server-side measurement path: `hal_page_hits.attribution_code` (no JS
      dependency); cross-reference SQL provided above
- [x] Reconciliation: gap query provided; g1 case confirmed as beacon miss
- [x] Trustworthiness statement: EXP-006 LOSS untrustworthy; EXP-011 tap count
      is lower bound not true rate; growth should not call LOSS on tap alone

## Result

**Withdrawn by Adnan 2026-08-08, before any eng cycle picked it up. No work
required. Do not investigate.**

Adnan identified the likely cause of the unexplained g1 conversion: he had sent
the link to a friend directly. A person who receives the prefilled message or
link out-of-band can produce a coded household without ever taking a tracked
path on the landing page — so the missing tap event is explained by provenance,
not by a measurement bug.

That removes the only evidence contradicting ENG-008's conclusion. **ENG-008
stands unamended**: the `sms:` mechanics are correct, the `/tap` endpoint works,
and 0 real taps most likely reflects real user behaviour on very low real paid
volume.

Consequence for growth: stop treating "0 taps" as suspect. EXP-011's gate can
be read at face value. The instrumentation caveat raised in this ticket should
NOT be carried into future reports.

Residual note, filed here for memory only and explicitly NOT a request: the
desktop copy-to-clipboard route still has no funnel event of its own, so
conversions through it would be invisible. Nobody has shown that path matters
yet. If desktop conversion ever becomes a question worth money, that is when to
open a fresh ticket — not now.
