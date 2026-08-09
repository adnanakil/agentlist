# ENG-014 — Swap the hero photo for HAL's own conversation

- id: ENG-014
- from: adnan
- status: done
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

## Revision 2026-08-08 (Adnan) — pastel, upright, and a rotating last word

The asset has been **replaced in place** (same path, same filename). It is now:
- Pastel, using the same palette as the Instagram creatives
  (`#f5dfe6 / #dfe9f7 / #e6e0f2`, blended), so hero and paid social match
- **Upright — no rotation.** Do not re-add a tilt
- 927 KB, down from 1.2 MB

### The overlay has to change with it, and that is the real work here

A composite against the current `.hero::before` was checked before filing.
**The pastel does not survive it.** The gradient is
`rgba(14,49,39, .94 → .82 → .35 → .08)` — tuned for the dark photo it replaces.
Over a pastel image the right side reads as muddy grey-lavender, nothing like
the Instagram creatives, and the point of the change is lost.

Getting the intended look means inverting the hero's treatment:
- Scrim becomes light rather than dark green — roughly
  `rgba(249,244,247, .86 → .72 → .28 → .04 → 0)`, same stop positions
- Headline and subhead flip to dark ink (`#153f32`), rotating word in green
- CTA pill becomes solid brand green with white text (it currently relies on
  being light-on-dark)
- Eyebrow, trust chips and the trust badges under the CTA all need their colours
  rechecked — several are currently pale-on-dark and will vanish on light

Eng picks the exact values; the two composites Adnan approved are the target.
**Contrast is not optional**: every text element over the new scrim must still
pass WCAG AA (4.5:1 for body, 3:1 for large text). If a colour cannot hit that,
change the colour rather than shipping it.

### Headline: rotate the last word

Current: "A calmer way to keep up with baby."
New: **"A calmer way to keep up with baby's ‹word›."** where ‹word› cycles:

    naps → feeds → poops → milestones

- Cycle on a timer (~2s per word reads well; eng may tune), looping
- Animate the swap — a short fade or slide. It should feel calm, not flashy;
  the whole brand promise is "calmer"
- The rotating word takes the accent colour, the rest stays ink
- **Reserve the width** of the longest word ("milestones") so the line does not
  reflow and shove the subhead and CTA around on every tick. Layout shift here
  would be worse than no animation at all
- **Respect `prefers-reduced-motion`**: when set, do not animate — render one
  word statically. This is non-negotiable, not a nice-to-have
- Server-render a real word (not an empty span) so the headline is complete
  with JS disabled and for crawlers
- Keep it one `<h1>`; do not split into multiple headings

### Acceptance additions

- [ ] Pastel hero renders with a light scrim; the phone and its bubbles are
      clearly legible, and the pastel actually reads as pastel
- [ ] All hero text passes WCAG AA against the new background
- [ ] Headline cycles naps → feeds → poops → milestones, with no layout shift
- [ ] `prefers-reduced-motion` disables the animation
- [ ] Headline is complete and sensible with JS off

## Revision 2 — 2026-08-08 (Adnan): supersedes the rotator spec above

Two corrections. **These override the previous revision; build to these.**

### 1. Line break — the rotating word stays on line 2

    line 1:  A calmer way to keep
    line 2:  up with baby's ‹word›.

The rotating word must sit on the **same line** as "up with baby's", not wrap to
a third line. Two lines total. The previous three-line composite is void.

### 2. Word list — drop "milestones"

    naps → poops → feeds

"milestones" is removed. This is what keeps the headline inside its space: the
remaining words are 4-5 characters, so the reserved slot is narrow and the line
length barely moves. Do not re-add a long word later without rechecking the
break.

### What this simplifies

Reserved width is now just the widest of `poops.` / `feeds.` — a small,
predictable box (outlined in the approved composite). The earlier concern about
the line reflowing on every tick largely goes away, but **still reserve the
width**; do not let the period or the following whitespace jitter.

Everything else from the previous revision stands unchanged: light scrim,
dark ink text, green CTA, WCAG AA on every hero element, `prefers-reduced-motion`
renders one word statically, and the headline must be complete with JS off.

### Watch the narrow breakpoints

Two lines at desktop will not stay two lines on mobile. Pick the mobile break
deliberately and keep the rotating word adjacent to "baby's" — a word alone on
its own line, cycling, will look like a bug rather than a flourish. If that
cannot be achieved at some width, render the word statically there and say so.
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
