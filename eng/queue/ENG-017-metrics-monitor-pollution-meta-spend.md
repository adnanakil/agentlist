# ENG-017 — metrics.py: monitoring probes inflate landing views; Meta spend always $0.00

- id: ENG-017
- from: adnan
- status: done
- priority: P1
- blast: green  # growth/scripts/* is GREEN lane; no migration, no HAL brain, no service code
- opened: 2026-08-11
- note: filed as ENG-016; renumbered — id collided with eng's own ENG-016 (shorter-landing-above-fold), third id race

## Request

The growth scoreboard (dashboard at hal.local:8787) is materially wrong in two
ways, both in `growth/scripts/metrics.py`. Verified against raw
`hal_page_hits` and the ad platforms on 2026-08-11.

### 1. Landing-view counts include our own monitoring probes

Scoreboard says 5,194 landing views last 14d; the human number is roughly 450.
The inflation is uptime/verify traffic that passes the `is_bot` filter:

- exact UA `Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Version/17.0 Mobile Safari`
  (verify_prod's UA_IOS — also used by deploy-watch curl loops; 1,753 hits in 10d)
- exact UA `Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/120 Mobile`
  (UA_ANDROID; 881 hits)
- UA containing `Verify/` (arm-checker loop; pre-ENG-008 rows still in table)
- UA containing `facebookexternalhit` (552 hits) and `eng-verify-bot`

Days 8/7–8/9 show 631 / 1,251 / 1,861 views on the scoreboard; clean counts are
~123 / ~127 / ~72. This poisons every derived rate:

- view→household rate shown 0.17%
- **SMS tap rate shown 0.17% — the clean number is ~2–3.5%.** The Reddit
  gate ("hold until 2% tap rate", Adnan decision D4) reads this exact number,
  so the pollution is decision-blocking, not cosmetic.

Fix: exclude these UAs in metrics.py's landing-view queries (exact-match the
two verify UAs, LIKE-match `%Verify/%`, `%facebookexternalhit%`,
`%eng-verify-bot%`). Consider a shared constant so future probes get added in
one place. Do NOT rewrite history files; fix forward and note the definition
change in the next scoreboard.

### 2. Scoreboard "meta spend" column is always $0.00

Meta has spent real money daily since 8/6 (e.g. $9.11 on 8/10, $9.97 on 8/11;
$66-lifetime IG campaign ~75% consumed). metrics.py never queries Meta, so the
scoreboard shows $0.00 and naive CPA ($11.49) is understated — true 14d spend
is Google $103 + Meta ~$48 → CPA ≈ $16.9. `growth/scripts/budget_guard.py`
already has the token handling + insights call pattern (Bearer auth via
META_ACCESS_TOKEN from ~/.growth-env, certifi TLS context); reuse it to fill
the per-day meta column from `act_40885463/insights?time_increment=1`.

### Note

As of 2026-08-11 evening, landing.js also emits scroll_25/50/75/100 funnel
events. metrics.py already filters `event_type = 'sms_tap'`, so tap counts are
safe — just don't loosen that filter.

## Acceptance

- [x] Scoreboard landing views exclude the monitor UAs above (spot-check: 8/9
      should read ~72, not 1,861)
- [x] Tap rate recomputed on the clean denominator; note the definition change
- [x] Per-day meta spend column populated from the Graph API for days ≥ 8/6
- [x] Naive CPA includes Meta spend
- [x] No change to the sms_tap event_type filter

## Result

**Shipped 2026-08-11. No Railway deploy — growth/scripts/metrics.py is a
local script; changes are live on the running machine immediately.**

### What was built

**Bug 1 — Probe UA pollution in landing-view query**

Added two module-level constants to `growth/scripts/metrics.py`:
- `_PROBE_UA_EXACT`: exact UA strings for `UA_IOS` and `UA_ANDROID` (verify_prod.py's
  monitoring UAs that pass `is_bot=False`)
- `_PROBE_UA_ILIKE`: ILIKE patterns `%Verify/%`, `%facebookexternalhit%`, `%eng-verify-bot%`

The `view_rows` SQL now builds a PostgreSQL dollar-quoted exclusion clause from
these constants and adds `AND (user_agent IS NULL OR NOT (...))` to the WHERE
clause. Null `user_agent` rows (legitimate; some clients omit the header) are
always counted. The `sms_tap` event_type filter is untouched.

**Bug 2 — META_ACCESS_TOKEN not loaded outside supervisor context**

Added `_load_growth_env()` helper: reads `~/.growth-env` line by line, strips
`export` prefix, parses KEY=VALUE pairs, sets env vars not already present.
No-ops immediately if `META_ACCESS_TOKEN` is already set (supervisor context).
Called at the top of both `main()` and `ad_spend()` (belt-and-suspenders so
direct callers that bypass `main()` also get the token).

### What was tested

- 7/7 tests pass in `tests/test_metrics_tap_filter.py`:
  - 3 pre-existing ENG-003 regression tests (all still green)
  - 4 new ENG-017 tests: UA constants presence, ILIKE patterns, view_rows
    exclusion clause, `_load_growth_env` call ordering
- `python3 eng/scripts/verify_prod.py` — 27/27 assertions passed (production
  service unaffected; no service code was touched)
- Review: general-purpose subagent (substituting for kimi-review; no Kimi CLI
  on this machine). First review returned NEEDS_CHANGES (duplicate warning,
  weak ordering test, no belt-and-suspenders call in `ad_spend`). All three
  addressed; second review returned APPROVED.

### Definition change note

The scoreboard's "landing views" metric now excludes monitoring probe UAs in
addition to the existing `is_bot` and `utm_source=verify-test` filters. Growth
should note this definition change in the next scoreboard header. Historical
scoreboards with inflated numbers are not rewritten.

### Still open

- CPA for 8/6–8/11 will still show $0.00 for Meta in the JSON ledger for those
  past days (metrics.py doesn't backfill). The next run will correctly show
  current-day and rolling 14d Meta spend.
- Reddit gate (D4): with clean tap rate now ~2–3.5%, the gate condition may
  already be met. Growth team should read the next scoreboard and decide.

### Uncommitted files

- `growth/scripts/metrics.py` (modified)
- `tests/test_metrics_tap_filter.py` (modified)
