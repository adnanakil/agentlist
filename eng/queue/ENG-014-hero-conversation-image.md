# ENG-014 — Swap the hero photo for HAL's own conversation

- id: ENG-014
- from: adnan
- status: open
- priority: P1
- blast: unset
- opened: 2026-08-08

## Request

The landing hero currently shows a stock photo of two baby bottles
(`/static/donebottles.png`). It says nothing about what HAL does. Adnan's call:
replace it with one of our iMessage-conversation visuals, so the first thing a
visitor sees is the product working.

**The asset already exists and is committed**:
`services/hal-orchestrator/hal_orchestrator/static/hero-conversation.png`
(2400x1200). It was rendered by `growth/ad_visuals/make_hero.py`, which reuses
the phone chrome and bubble CSS from `make_ads.py`, so hero, ad creatives and
the on-page demo are visibly the same product.

The asset was built specifically for this slot, not cropped from an ad:
- The subject sits at ~69% horizontally, so it clears the `.hero::before`
  gradient (94% opaque at 0%, 35% at 59%, 8% at 82%) instead of being buried.
- The left third is deliberately quiet — it is covered by the overlay anyway
  and must not compete with the headline.
- Warm light falls from the right so the white phone separates from the green.

A composite check against the real gradient was done before filing; the phone
clears the headline block and the bubbles stay legible. But that was an offline
approximation — **verify in the real page at real breakpoints**, which is the
part eng owns.

## Acceptance

- [ ] Hero uses `hero-conversation.png`; the bottles image is no longer
      referenced by the hero
- [ ] Headline, subhead and CTA remain fully legible over it at desktop,
      tablet and mobile widths — check the existing `object-position` overrides
      at the 502 and 527 breakpoints, which were tuned for the old photo and are
      very likely wrong for this one
- [ ] The phone/conversation is still recognisable at mobile widths, or the
      `object-position` is retuned until it is. If it cannot be made to work on
      narrow screens, say so rather than shipping something unreadable
- [ ] `alt` stays empty (decorative) — the conversation is duplicated in the
      demo section below, so it is not new information for a screen reader
- [ ] Page weight does not regress badly: the PNG is ~1.2 MB, larger than the
      photo it replaces, and it is `fetchpriority="high"` on the critical path.
      Compress or convert (WebP with PNG fallback) as you see fit; state the
      before/after byte size in `## Result`
- [ ] `/static/donebottles.png` route and file: leave them in place unless you
      confirm nothing else references them. Do not delete assets — that needs
      Adnan

## Notes

- `make_hero.py` regenerates the asset, but it needs Playwright browsers, which
  are not installed on the Hal Mac. Treat the committed PNG as the source of
  truth; if the image needs changing, that is a growth request, not an eng fix.
