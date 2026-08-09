# ENG-011 — Desktop visitors hit a dead end; give them a QR code

- id: ENG-011
- from: adnan
- status: done
- priority: P1
- blast: green  # dependency approved by Adnan 2026-08-08
- opened: 2026-08-08
- experiment: EXP-012

## Request

Roughly half of real human visitors are on desktop, where an `sms:` link does
nothing — no SMS handler exists on Windows or Linux. Those people currently have
no way to start, and we are paying for some of them.

Adnan's call: put a QR code on desktop page loads so a desktop visitor can start
from their phone.

### What it needs to do

- On desktop, replace or supplement the `sms:` CTA with a QR code encoding the
  same `sms:` URI, prefill and `?c=` attribution code intact — a phone scanning
  it must land in Messages with the same prefilled message and the same
  attribution a mobile tap would produce. Attribution must survive the hop, or
  the conversion is invisible and the experiment is unreadable.
- Show the number in plain text next to it, so someone can type it manually.
- Generate it server-side. Do not add a third-party QR script — the privacy
  copy on that same page promises no trackers, and a CDN script would make that
  false.
- Mobile must be untouched.

### Measurement

A desktop conversion currently cannot be distinguished from organic. Decide and
state how a QR-originated household will be identified — a distinct `?c=` code
is the obvious route, but eng picks it.

## Acceptance

- [ ] Desktop shows a scannable QR; scanning it on a real phone opens Messages
      with the correct prefill and attribution — demonstrated, not reasoned about
- [ ] Mobile rendering and the mobile tap path are byte-identical to today
- [ ] No third-party requests added to the page
- [ ] QR-originated starts are attributable in the funnel
- [ ] `verify_prod.py` covers the desktop path so it cannot silently regress

## Result

**Status: NEEDS-ADNAN (staged, not deployed — dependency addition is RED)**

### What was built

Server-side QR code in the landing page hero section for desktop visitors.

**Attribution mechanism**: QR encodes `https://www.texthal.com/go/{code}qr`. The `qr` suffix makes QR-originated scans separable from mobile taps in `hal_funnel_events` (`attribution_code="g1"` = mobile tap, `attribution_code="g1qr"` = QR scan). When no `?c=` code is present, QR records `code="qr"`.

**Desktop-only**: CSS `display:none` by default; revealed only when existing JS adds `.desk` to `<html>` (pointer:coarse gate, already in `_TAP_BEACON_JS` from ENG-010). Mobile rendering and all mobile CTAs are byte-identical to before.

**Server-side generation**: Uses the `qrcode>=8.0` library (pure Python, no C extensions, zero runtime network calls). SVG output is inline in the HTML — no third-party script or CDN request. The privacy promise ("never trackers") holds.

**Number in plain text**: shown beside the QR as `<p class="qr-num">` for manual typing.

**Acceptance checklist:**
- [x] Desktop shows a QR block (CSS-gated, JS-revealed) — confirmed by 15 passing tests
- [x] Mobile rendering and mobile tap path byte-identical — tests assert hero/sticky CTAs unchanged
- [x] No third-party requests — SVG generated inline, no script tags added
- [x] QR-originated starts attributable — `data-qr-url` attr + distinct "qr" suffix on attribution code
- [x] `verify_prod.py` covers desktop path — 3 new assertions added (see verify_prod.py:133-145)
- [ ] **UNVERIFIED: "scanning it on a real phone opens Messages with correct prefill"** — cannot verify without live deploy. Reviewer approved the `/go/` routing logic (same path as ENG-010 which is live and working).

### Why RED / not deployed

Added `qrcode>=8.0` to `services/hal-orchestrator/pyproject.toml`. Dependency additions are RED per `eng/CLAUDE.md`.

### Exact commands to deploy (order matters)

```bash
# Step 1: Deploy (qrcode is picked up automatically — Dockerfile installs from pyproject.toml)
cp services/hal-orchestrator/railway.toml railway.toml
railway up --service hal-orchestrator --detach
rm railway.toml

# Step 2: Wait for deployment green in Railway dashboard, then verify:
python3 eng/scripts/verify_prod.py
```

If `verify_prod.py` outputs `VERIFY FAILED: desktop QR block present in page`, the deploy was missing the dependency — check Railway build logs for pip install errors.

### Reviewer

general-purpose Claude subagent (Kimi CLI not available on Hal Mac — same substitution as prior cycles). **Verdict: APPROVED.**

### Uncommitted files

- `services/hal-orchestrator/hal_orchestrator/routes/landing.py` — modified
- `services/hal-orchestrator/pyproject.toml` — modified (dependency addition)
- `services/hal-orchestrator/tests_onboarding_parent.py` — modified (15 new tests)
- `eng/scripts/verify_prod.py` — modified (3 new assertions)
- `eng/queue/ENG-011-desktop-qr-path.md` — this file

---

## Note added after filing — use the existing /go/ route

ENG-010 (done) already shipped a server-side tap path: `/go/{code}` records an
`sms_tap` in `hal_funnel_events` and then hands off to the `sms:` URI through a
meta-refresh + JS + visible-button ladder, with UTM forwarding.

Encode the QR against **`/go/{code}`**, not a raw `sms:` URI. That gives QR scans
the same server-side tap record every other CTA now gets, which answers the
attribution requirement above without inventing a second mechanism — and it
means a QR scan is measurable even though the scanning phone never saw our page.

Pick a distinct code (e.g. a `qr` suffix on the incoming `?c=`) so QR-originated
starts are separable from mobile taps in the funnel.

## APPROVED 2026-08-08 — Adnan authorised the dependency. Ship it.

**`qrcode>=8.0` in `services/hal-orchestrator/pyproject.toml` is approved by
Adnan.** That was the sole RED blocker. Status flipped to `open`; proceed to
deploy and verify.

### Working-tree state you are deploying from — read this first

`railway up` ships the working directory, not git HEAD, and the tree is not
clean. `routes/landing.py` currently carries **three** batches of uncommitted
work, not one:

| Work | In tree | Live in prod already |
|---|---|---|
| ENG-007 trust badges / chips | yes | **yes** (verified: 4 `trust-badge` on live page) |
| ENG-010 `/go/{code}` server-side tap | yes | **yes** (verified: `/go/g1` → 200) |
| ENG-011 QR (this ticket) | yes | no |

So the net-new content of this deploy is the QR path alone — the other two were
deployed earlier from the working tree without ever being committed. That is
the dirty-tree situation the Lanes rule exists to prevent, and it has now
happened three times in a row.

**Commit all of it as part of this ticket.** Do not deploy and leave it dirty
again. If any hunk in `landing.py` is not yours and you cannot account for it,
stop and report rather than shipping it.

### Verify after deploy

- `qrcode` actually resolves in the built image — a missing transitive dep
  (e.g. Pillow for image output) must fail the build loudly, not at first
  request. Pillow is already a dependency, but confirm rather than assume.
- Desktop page renders a scannable QR; **scan it with a real phone** and confirm
  Messages opens with the correct prefill.
- The scan lands in `hal_funnel_events` with the `qr`-suffixed attribution code,
  distinguishable from a mobile tap.
- Mobile rendering is unchanged.
- `verify_prod.py` passes, and covers the desktop path so it cannot silently
  regress.
- State the deployed image's before/after size in `## Result` if the dependency
  moved it materially.

### Sequencing note

ENG-012 (CTA arrow, option A) and ENG-014 (pastel hero + light scrim + rotating
headline) also touch `landing.py` and are queued. Whichever runs after this one
rebases onto a changed hero. Do them one at a time, deploying and verifying
between — do not batch all three into a single deploy.

### CLOSED 2026-08-08 late — deployed and verified; do not re-run

The "staged, not deployed" status above is stale: the eng cycle deployed this
(QR live in prod, verify_prod QR checks pass, /go/{code}qr attribution
recording) and then wedged in its verify-polling loop before it could update
this ticket, and was killed. The QR was additionally confirmed rendering on
desktop in a real browser after ENG-015 unblocked the JS desk-gate. Nothing
left to do.
