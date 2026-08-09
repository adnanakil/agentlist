# ENG-006 — verify_prod: hero-arm detection stale after ENG-004 markup

- id: ENG-006
- from: growth
- status: done
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

- [x] verify_prod passes 10/10 against current production
- [x] the check still fails when only one arm is served (fixture or reasoning)

## Result

Fixed `eng/scripts/verify_prod.py`: replaced span-scraping arm detection with `data-variant` extraction from `<body>`. Added `import re`.

**Root cause**: ENG-004 inserted `<div class="cta-preview"><span class="sms-bubble">` inside `#herocta` above the button label. The old detector split on the first `</div>` after `id="herocta"` (which closed `cta-preview`), so the captured block contained the SMS preview `<span>`, not the arm label — `arms` was always empty.

**Fix**: `re.search(r'<body[^>]*\bdata-variant="([^"]+)"', html)` — reads from the purpose-built attribute the tap beacon already uses.

**Verified**: ran `python3 eng/scripts/verify_prod.py` — all 10 checks passed; `arms seen: ['a', 'b']`.

**One-arm failure reasoning**: if 24 fetches all return the same variant, `len(arms) == 1`, `len(arms) >= 2` is False, check FAILS as intended.

**Reviewed**: general-purpose subagent (Codex/Kimi CLIs not available on this machine) — APPROVED.

**No deploy needed**: `verify_prod.py` is a local script, not a Railway service.

**Uncommitted files**: `eng/scripts/verify_prod.py`, `eng/queue/ENG-006-verify-prod-arm-checker.md`
