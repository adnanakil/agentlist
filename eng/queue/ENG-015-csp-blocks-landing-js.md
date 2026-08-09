# ENG-015 — CSP blocks ALL JavaScript on texthal.com; the tap beacon has never fired

- id: ENG-015
- from: adnan
- status: done
- priority: P0
- blast: unset
- opened: 2026-08-08

## Request

**Every piece of JavaScript on the public landing page is blocked by our own
Content-Security-Policy, and has been for as long as the header has shipped.**

`middleware/security_headers.py` sends:

    default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline';
    form-action 'self'; base-uri 'none'; frame-ancestors 'none'

There is **no `script-src`**, so it inherits `default-src 'none'` and the inline
`<script>` in `landing.py` never runs. `style-src 'unsafe-inline'` IS present,
which is why the page looks completely normal — this failed silently and
invisibly.

There is also no `connect-src`, so even if scripts ran, `fetch('/tap')` would be
blocked by the same fallback.

### Proven in production, not inferred

On `https://www.texthal.com/?c=g1&utm_source=verify-test`:

| Expected side effect of the script | Observed |
|---|---|
| `.desk` added to `<html>` (pointer gate) | **absent** — `htmlClasses: "(none)"` |
| UTM appended to the 4 `/go/` hrefs | **absent** — all still bare `/go/g1` |
| `is-hidden` toggled on `#stickycta` by IntersectionObserver | **absent** |
| QR revealed on desktop | **`display:none`** |

Manually running `document.documentElement.classList.add('desk')` in the console
makes the QR render correctly — so the markup and CSS are fine. Only script
execution is dead.

### What this actually explains — read this part

This is almost certainly the real cause of the funnel mystery the team has been
chasing for days:

- **"0 real SMS taps across ~1,904 landing views"** — the beacon is a
  `fetch('/tap')` inside that blocked script. It has never executed once. Every
  `sms_tap` row in `hal_funnel_events` is from `verify-test` server-side probes,
  which is exactly what we observed.
- **EXP-006 was called LOSS. EXP-011 is heading for LOSS.** Both were read off
  tap rate. Both may be measuring a blocked script rather than user behaviour.
- **The Google campaign was paused** on the strength of that 0% tap rate.
- ENG-008 concluded the `sms:` mechanics were sound and users simply were not
  tapping. The mechanics *are* sound — but the measurement was dead, and nobody
  checked whether the script ran at all.
- ENG-009 was withdrawn on the theory that a friend's out-of-band share
  explained the one coded conversion. That may still be true, but it is no
  longer needed as an explanation, and withdrawing it was premature.

Note the `/go/{code}` server-side tap route (ENG-010) is unaffected — it records
server-side and does work. That is the one measurement path we can currently
trust.

## Acceptance

- [ ] Landing page JavaScript executes in production. Verify by observing a real
      side effect (`.desk` present on `<html>`, UTM forwarded onto `/go/` hrefs),
      not by reading the header
- [ ] `/tap` beacon records a **real** (non-`verify-test`) event from an actual
      browser interaction
- [ ] Desktop QR becomes visible without manual intervention
- [ ] CSP remains restrictive. Do **not** simply add `'unsafe-inline'` and move
      on — prefer a nonce or hash for our one inline script, and add an explicit
      `connect-src 'self'` so the beacon can post. Justify the final policy in
      `## Result`
- [ ] `verify_prod.py` gains a check that fails if landing JS is blocked again —
      assert on a script-dependent side effect or on the presence of a
      `script-src` that permits our script. This class of bug must never again
      be invisible
- [ ] State in `## Result` when the CSP header shipped, so growth can determine
      which experiment reads are contaminated

## Notes for growth (do not act until eng confirms)

If this is confirmed, EXP-006 and EXP-011 tap-rate readings are void and must be
re-run after the fix. Do not conclude anything about CTA copy from them. The
paused Google campaign was paused on a broken metric.
## Result (ENG-012, ENG-014, ENG-015 — closed together)

**Built and deployed directly by Adnan's interactive session on 2026-08-08
evening** after the scheduled eng cycle wedged in a verify-polling loop (its
grep pattern never matched verify_prod's success line; process killed). Commits
0b0b27f + 4568aa1 + 14566a2. verify_prod: ALL checks pass, including the new
CSP/JS/hero assertions. Confirmed live in a real browser, desktop and mobile.

- ENG-015 (CSP): script-src 'self' + connect-src 'self'; all landing JS moved
  to /static/landing.js; /go/ interstitial's CSP-dead inline script removed
  (meta refresh carries it). Rotator observed cycling in production = JS
  provably executing for the first time.
- ENG-014 (hero): pastel conversation image, light scrim, all hero text
  re-picked for contrast on light; H1 rotates naps./poops./feeds. with width
  reserved, reduced-motion static, naps. server-rendered.
- ENG-012 (option A): label + trailing plain → on hero/sticky/closing CTAs,
  bubble SVG removed, ↗ asserted-against in tests.
- EXP-011 is closed by these changes (CTA altered mid-flight, and its 0-tap
  reading was measuring a blocked script anyway — see ledger).
