# ENG-017 — metrics.py: monitoring probes inflate landing views; Meta spend always $0.00

- id: ENG-017
- from: adnan
- status: open
- priority: P1
- blast: unset
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

- [ ] Scoreboard landing views exclude the monitor UAs above (spot-check: 8/9
      should read ~72, not 1,861)
- [ ] Tap rate recomputed on the clean denominator; note the definition change
- [ ] Per-day meta spend column populated from the Graph API for days ≥ 8/6
- [ ] Naive CPA includes Meta spend
- [ ] No change to the sms_tap event_type filter
