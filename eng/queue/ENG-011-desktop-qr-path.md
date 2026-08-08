# ENG-011 — Desktop visitors hit a dead end; give them a QR code

- id: ENG-011
- from: adnan
- status: open
- priority: P1
- blast: unset
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
