# ENG-001 — How much paid traffic is desktop, where sms: links are dead?

- id: ENG-001
- from: adnan
- status: open
- priority: P1
- blast: unset
- opened: 2026-08-05
- experiment: EXP-006

## Request

The working theory for the low view→household rate was partly "desktop visitors
can't tap SMS links". That is still a theory — nobody has measured it. On
Windows and Linux an `sms:` link has no handler and does nothing; on macOS it
opens Messages. So some fraction of paid clicks land on a page whose only
call to action is inert for them.

We now have the data to answer it: `hal_page_hits` stores `user_agent`,
`utm_source`, and (since 2026-08-05) `variant`, and `hal_funnel_events` stores
taps. Classify hits by device class and report the split and the tap rate for
each.

Answer the decision, not just the number: **if desktop is a meaningful share of
paid clicks and converts far worse, it justifies building a desktop path** (the
obvious candidate is a QR code encoding the prefilled `sms:` URI, so the visitor
scans it with the phone they'd be texting from — no external library, generated
server-side). If desktop is a rounding error, say so and we drop the theory
instead of building for it.

Note the current landing page already gives desktop visitors a copy-to-clipboard
number in the closing section, so "desktop is completely dead" is not the
baseline — measure against what is actually shipped.

## Acceptance

- [ ] Device-class split (mobile / tablet / desktop) of non-bot `/` hits over
      the available window, overall and for `utm_source=google`
- [ ] Tap rate per device class, joined via `visitor_hash`
- [ ] Sample sizes stated plainly; if the window is too small to conclude, say
      that rather than reporting a ratio of single digits as a rate
- [ ] A recommendation with a reason: build the desktop path, or drop the theory
- [ ] The classifier lives in a script under `eng/scripts/` so the answer can be
      re-run later, not a one-off query pasted into a report

## Result

(pending)
