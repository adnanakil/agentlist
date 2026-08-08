# ENG-006 — verify_prod: hero-arm detection stale after ENG-004 markup

- id: ENG-006
- from: growth
- status: open
- priority: P2
- blast: green
- opened: 2026-08-07

## Request

verify_prod.py detects the hero A/B arms by grabbing the first <span> inside
the id="herocta" block. ENG-004 added <div class="cta-preview"><span
class="sms-bubble"> above the button, so the first span is now the SMS preview
and the first </div> closes cta-preview before the label span — the arms set
comes back empty and the check FAILs even though prod is splitting correctly
(verified manually 2026-08-07: body data-variant showed both arms, 5xa/7xb
across 12 UA-varied fetches).

Fix: read data-variant="([ab])" from the <body> tag instead of span-scraping —
it is stable and purpose-built for reporting (the tap beacon uses it). Keep the
24-fetch UA variation and the >=2 arms assertion.

## Acceptance

- [ ] verify_prod passes 10/10 against current production
- [ ] the check still fails when only one arm is served (fixture or reasoning)
