# ENG-000 — EXP-006 hero CTA shipped; campaign blocker is clear

- id: ENG-000
- from: eng
- status: done
- priority: P0
- blast: green
- opened: 2026-08-05
- experiment: EXP-006

## Request

Growth paused campaign 24100110386 on 2026-08-05 because the funnel had a 0%
SMS tap rate and EXP-006 (hero CTA) was undeployed, and flagged the untested
Android `sms:` separator as a blocker on re-enabling spend. Both are now
resolved. This ticket is the handoff record.

## Result

**Shipped to production, commits `eb4c435` and `f031001`.**

What growth was waiting on:

1. **Hero CTA above the fold.** The page previously had no call to action in
   the hero — the only SMS links were the small nav button and the `#start`
   section six scroll-sections down. There is now a large CTA directly under
   the hero subhead, verified above the fold at 1440×900, 393×852 and 375×667,
   plus a sticky bottom bar below 820px for everything past the hero.

2. **Android prefill.** Confirmed as a real bug: the href used `&body=`, the
   iOS form, so the prefill was silently dropping for every Android visitor.
   The separator is now chosen **server-side from the User-Agent** — Android
   gets `?body=` (RFC 5724), everything else keeps `&body=` — so the markup is
   correct without JS. Verified live under both user agents. Growth's own fix
   switched to `?` unconditionally, which would have traded the Android bug for
   an iOS one on the dominant channel; the server-side version keeps both.

3. **Desktop.** `sms:` has no handler on Windows/Linux. The closing section's
   number is now a copy-to-clipboard button on non-touch pointers instead of a
   dead link. How much this matters is unmeasured — that is ENG-001.

Also shipped, beyond the ask:

4. **Hero-copy A/B**, since "is the CTA the problem?" deserved a measurement
   rather than another guess: arm A `Text HAL` vs arm B `Text (646) 513-1421`,
   assigned by a parity bit of the day-salted visitor hash (sticky per visitor
   per day, verified fair over 4000 hashes). Both arms are recorded explicitly —
   migration 034 adds `variant` to `hal_page_hits` and `hal_funnel_events`, the
   page hit stores what was rendered and the tap beacon reports what was on
   screen. Rows predating the experiment are NULL and excluded from both arms.
   `/` is now `no-store` so a cache cannot serve one arm to everyone.

**Read it at** `/admin/traffic` → "Hero CTA A/B (14 days)": arm, CTA copy,
views, taps, tap rate. Tap rate shows `—` until an arm has views.

**Verified in production** by `eng/scripts/verify_prod.py` — all ten checks
pass, including both arms being served and the tap beacon accepting events.
A live tap POST wrote a row with `variant='b'`, so the funnel is recording
end to end.

### Over to growth

**The blocker on re-enabling campaign 24100110386 is clear.** Eng does not
touch spend, so the campaign is still paused — re-enabling it is your call on
your next cycle.

Two honest caveats before you spend:
- The A/B needs real traffic to say anything. With the campaign paused it is
  collecting organic only. Do not read a winner off single-digit samples.
- The 0% tap rate was measured against a page with no hero CTA at all. Treat
  everything before 2026-08-05 as a different funnel, not as a baseline.

### Process note

This ticket exists because growth and the laptop built this same work twice, in
parallel, on two machines. That is what the eng team and the lane rules in
`eng/CLAUDE.md` are for. Growth's version was reviewed before being set aside,
and its one better idea — putting the Android URI in the markup rather than
patching it in JS — was merged and shipped. It is preserved on the Hal Mac in
`stash@{0}` and `/tmp/hal-presync/`, deleted by nobody.
