# HAL — Parent Onboarding Experience (2026-07)

*Design doc for the beachhead front door (see BEACHHEAD.md). Builds on the
existing onboarding v2 machinery (`prompts/system.py` step machine, ask decay,
group warm-start, `first_win.py`, trial-brief state machine) rather than
replacing it. The generic track stays for non-parent users; this adds a
**parent track** that the front door funnels into.*

---

## The job

Onboarding has exactly three wins to deliver, in order:

1. **Win 1 — first log, under 2 minutes.** They text a feed; it's logged and
   acknowledged. The setup IS the product. (Time-to-first-win today is
   measured in onboarding *questions*; for parents it must be measured in
   seconds-to-first-log.)
2. **Win 2 — the payoff, same day.** After a few events HAL gives something
   back nobody asked for but everyone wants: the next-nap window and, that
   evening, the day's digest. The demo is the pitch (same principle as the
   trial brief).
3. **Win 3 — the household, within 72 hours.** A second caregiver logs.
   This is the activation metric from BEACHHEAD.md (2+ caregivers logging
   within 72h) and the moat. Everything in the flow bends toward it.

Anti-goals, straight from GOALS.md and the convo mining: no forms, no
feature dumps, one question at a time, never nag (ask caps), never fake
"logged ✅" (write-verified is a launch blocker), and proactive sends stay
rare and impeccable.

**The one-line mental model: the user doesn't set HAL up; HAL sets itself up
around the first thing they text it.**

---

## What changes vs. onboarding v2

> **2026-07-29 update:** the generic track is now a guided path too:
> name → **little-one probe** ("do we have a little one we're keeping an
> eye on? 👶", ONE ask, never re-raised after a no; a yes sets up the baby
> log right there) → **city** (timezone + home in one ask, framed as
> weather/events) → Google. home/work are no longer asked — the enricher
> learns them. Each step is CHAINED into the previous reply (the name ack
> asks the little-one question, the probe answer asks the city, the city
> save closes with the calendar offer) so no reply dead-ends. Both tracks
> now finish with the single optional Google-calendar offer — the parent
> track included, superseding the "no Google in parent onboarding" row
> below. The v2 column is kept for history.

| v2 (generic) | Parent track |
|---|---|
| name → timezone → home → work → Google → trial brief | name → **baby (name + age)** → timezone-via-city → **first log** → *(earned)* family thread → trial brief |
| First win = Google OAuth scan | First win = first log ack; second win = **forecast reveal** after ~3 events / first nap |
| Google offered at step 5 | Google **removed from onboarding entirely** — offered contextually, week 2+, or when they mention a pediatrician appt / "what's on my calendar" |
| home + work asked | work never asked; home folded into "what city are you in" (timezone + weather in one) |
| Solo user assumed | **The household is the unit.** Second-caregiver step is a first-class part of the flow |

Everything else is reused: ask decay caps, `compute_onboarding_progress`
funnel events, group warm-start + name pre-fill, trial-brief state machine
(armed → asked → off-if-silent), value-first "answer their actual message
first" rule.

**Track selection.** New silo → parent track when any of: the first message
matches baby intent (feed/nap/diaper/week-old/"just had a baby"/a time+oz
pattern), the sms body carries the parent prefill or a probe/referral code
(below), or the user says so when asked. Otherwise generic track. Stored as
`profile.onboarding_track`; a generic-track user who later mentions a baby
gets the baby steps woven in from wherever they are (tracks converge, never
restart).

---

## Entry paths (design each, in priority order)

### Path A — cold 1:1 from the landing page / Reddit

Landing page (`landing.py`) gets the beachhead hero. Same minimal structure,
new copy:

- H1: **"The baby log that lives in your group chat."**
- Sub: "Text feeds, naps, diapers the way you'd text your partner. HAL keeps
  one record for everyone — parents, nanny, grandma. No app."
- sms body prefill changes from `hey HAL` to `Hi HAL — new baby here 👶`
  (this is also the track selector).
- One privacy line above the footer, verbatim: "Your family's data stays
  yours — never sold, never ads, never used to train anything. Text
  'forget me' and it's gone."
- Probe/referral attribution: `/?c=<code>` variants set the sms body to
  `Hi HAL — new baby here 👶 (<code>)`; HAL strips and records the code as
  `acquisition_source` on the profile. One landing page, per-channel links —
  no extra infra.

**The script (first three beats):**

> **User:** Hi HAL — new baby here 👶
>
> **HAL:** Congrats 🎉 I'm HAL — I keep your baby's log in your texts. No
> app: when a feed or nap happens, just text it to me like you'd text your
> partner ("4oz at 3:15", "down for a nap"). I keep one record and start
> spotting the patterns.
> Who am I keeping the log for — name and how old?

> **User:** Leo, 7 weeks
>
> **HAL:** Leo it is 💙 Seven weeks — the thick of it. What city are you in,
> so his days and nights land right?
> *(saves baby via create_family; infers tz from city; asks nothing else)*

> **User:** Brooklyn
>
> **HAL:** Set. That's the whole setup — text me the next feed or nap as it
> happens and I'll take it from there. If it's easier, tell me what's
> already happened today and I'll backfill.

Three questions total (their name gets woven in naturally on a later turn —
it is NOT allowed to delay the first log; ask cap 1 during day 0). If their
first message is already a loggable event ("she ate at 2:30"), **log it
first, confirm, then do the intro** — value-first rule, unchanged.

**Win 1 ack (every early log, first ~5 events):** confirm + echo the
parse so trust forms: "Logged — 4oz at 3:15. That's his 5th feed today."
Ambiguous times get a confirm-back, never a guess (the 5:05 saga rule).

**Win 2 — the forecast reveal (code-triggered, not model-whim):** after the
first wake-following-a-nap, or 3 logged events, whichever first:

> **HAL:** Based on his morning, his next sleepy window looks like
> ~1:20–1:50. I'll quietly flag it 15 min ahead — say "stop nudges" anytime.

And at ~8pm local, the first **evening digest** (existing digest path,
enumerate-before-count enforced). The digest closes with the single most
important growth line in the product:

> "P.S. — this log works best as a group chat. Add anyone who does feeds or
> naps — partner, nanny, grandma — to a group text with me and everyone can
> log to the same record. Want the 15-second how-to?"

### Path B — the family thread (second caregiver; the activation moment)

How it works, told as one message when they say yes (or on day 1 if no
second caregiver has appeared — **one nudge ever**, then drop it):

> **HAL:** Easiest way: open your existing family thread → tap the names at
> the top → Add Contact → add me (this number). Or start a fresh group with
> me + whoever helps with Leo. The moment I'm in, everyone's texts land in
> one log — nobody else installs or signs up for anything.

When HAL lands in a group containing a known parent (existing group-detect +
warm-start machinery), the in-group intro is ONE line, then silence unless
addressed (tact gate unchanged):

> **HAL:** Hi — I'm HAL, I keep Leo's log for [Name]. Anyone here can text
> feeds/naps/diapers the way you'd say it out loud and I'll keep one record.
> I'll stay quiet otherwise 🤫

Mechanics: link the group silo to the existing `HalFamily` (add
`HalFamilyMember` rows as members speak — membership means "spoke there,"
per the one-way valve). First log from a NEW member triggers Win 3
acknowledgment **in the thread, once**: "Got it — logged. (That's two of
you on Leo's log now — I'll keep everyone's entries straight.)"

### Path C — the nanny / grandparent

They never onboard. That's the feature. The moment they're ADDED to the
family thread, HAL welcomes them in ONE line and asks their name — the
natural hospitality moment, once ever, code-triggered off the bridge's
member-add event (never in muted or dormant threads):

> **HAL:** Welcome 👋 I'm HAL — I keep Leo's log in this thread. Text
> feeds, naps, diapers the way you'd say them out loud and they all land in
> one record. What should I call you?

Beyond that, nothing is required of them: HAL DMs nothing, asks nothing
else. Their 1:1 warm-start (existing D1 invite, rate-limited once-ever)
fires only after a *meaningful* interaction and reads:

> **HAL:** Hi, it's HAL from Leo's family chat. You can text me here too —
> anything you log lands on the same record, and I can tell you where his
> day stands when you come on shift ("morning brief" / "where's his day
> at?"). Nothing to install, and your texts with me stay private.

Name capture for caregivers: the add-time welcome above asks once,
in-thread; pre-fill from group context where possible. Never re-ask (the
Joyce name-nag cost three weeks of goodwill — the welcome is the ONE ask,
hard cap).

**The handoff brief** (P1 feature from BEACHHEAD.md) is what makes this
persona love HAL: "Joyce texted 'here' — He woke at 6:15, ate 7oz at 7,
aim for a nap around 9:40."

### Path D — referred household

Referral code in the sms body (Path A mechanics). The only difference:
HAL opens warm — "Ah, the Bazzys sent you 💙" — and both households get the
free month when the new one activates (2 caregivers logging), not on signup.
Reuses the usage-cap/billing machinery.

---

## The membership boundary (who knows what, when the roster changes)

The governing rule: **in a group, HAL speaks only from what the whole
current room has seen.** iMessage never shows a newly added member the
messages from before they joined — HAL matches that line exactly.

- **On member-add** (bridge forwards chat.db's `item_type=1` events): the
  thread's working knowledge CUTS at that moment — conversation + rolling
  summary cleared, archive recall floored at the epoch for anyone who
  wasn't in the room before it. Structural, not prompt-enforced.
- **What crosses the boundary: typed, shared-by-design structures only** —
  the family baby log (feeds, naps, names). Free text NEVER crosses
  automatically. Whitelist by structure, never blacklist by pattern — a
  redaction filter would eventually miss the nanny-pay discussion; a
  structural cut cannot.
- **The valve**: a longer-tenured member keeps full recall — "HAL, catch
  Rosa up" works because the *asker* is entitled to the context and chooses
  to re-share it, exactly like pasting a screenshot. HAL never volunteers
  pre-epoch content on its own or to a newer member's ask. Floors are
  per-member and permanent: someone who joined at cut N never gains pre-N
  recall from a later cut. Known tradeoff: entitlement is spoke-only
  (iMessage rosters can't be enumerated), so a lurker who never spoke before
  a cut is floored like a newcomer — the valve covers them.
- **On member-remove**: access revocation. A caregiver whose log access came
  via the thread loses it the moment they're removed — parents manage access
  with the one gesture they already know (group membership), no settings
  page. The onboarding parents are never auto-revoked.
- **Caveat to document for parents**: baby-log event *notes* are free text
  inside a shared structure — they're household-visible like the rest of
  the log. Don't put private asides in a log note.

## Capacity gating (bridge-safe intake)

Until FEATURE_PLAN A1 lands, intake is capped in code, not vibes:
`max_active_households` setting checked at new-silo creation. Over cap, HAL
itself is the waitlist — no web build:

> **HAL:** I'm at capacity right now (I run family-by-family so the log
> never drops). You're #4 — I'll text you the moment a spot opens, usually
> under a week. If you were referred, tell me who and I'll bump you.

Waitlisted silos: store phone + timestamp + source; when a slot opens, HAL
texts the head of the line and the parent-track flow starts fresh. Scarcity
here is honest (the bridge IS the constraint) and reads as care. Admin
override via existing admin route.

---

## The first week (cadence contract)

Proactive sends during onboarding are the highest-risk surface (heartbeat
spam is the #1 churn risk in production data). The week-one contract:

| Day | HAL-initiated sends (max) |
|---|---|
| D0 | forecast reveal (1) + evening digest (1) |
| D1 | morning brief **trial** (existing armed→asked machinery, parent flavor: Leo's night + today's shape + weather) (1) + evening digest (1) |
| D2 | evening digest (1) + family-thread nudge iff still solo (1, once ever) |
| D3–7 | digests + committed brief only; ONE contextual capability reveal max all week (e.g., they mention a TikTok → fact-check + "I can keep doing that") |

Nothing else. No re-engagement pings ever (non-negotiable). Every proactive
send obeys the global min-interval gate. If the user goes silent for 48h+,
HAL sends nothing — the digest simply waits for the next log ("nothing new →
send nothing").

Google: never during week one unless the user asks for calendar/email.
Contextual triggers that earn the offer later: "what's on my calendar," a
mentioned pediatrician appointment ("want me to watch your calendar for
these? one-time connect, I never send anything as you"), or the week-2
brief. The OAuth first-win (`first_win.py`) stays exactly as is when it
does fire.

Payment: invisible during onboarding (beta = free founding-family). The
paywall moment, when it comes, follows the habit — after D30 and 2+
caregivers active — and is one message with the household framing ("$9/mo
covers everyone on Leo's log — Joyce and grandma included, always").

---

## Edge cases (scripted, not improvised)

- **First message is a question, not a log** ("is 4oz normal for 7 weeks?"):
  answer it excellently (with the call-the-nurse-line boundary), THEN the
  intro. Never "let me set you up first."
- **Ambiguous terse log** ("at 505 before bedtime"): confirm-back, one line,
  never guess. (Convo-mining Theme B.)
- **Backfill dump** ("today: ate 7, 10, 1, naps 9-10 and 12-1:30"): parse
  all, echo the full list once, count enumerated = count claimed.
- **Twins / second child**: `HalFamily` is single-baby today. Script the
  honest answer ("I can only keep one log per family right now — [name]'s?
  Twins support is close") and log the request as friction. Don't fake it.
- **Android partner**: "Group texts with me need iMessage today — Android
  support is coming. Meanwhile anything you or I log, [partner] can get as
  a nightly recap I text them directly." (Solo-degraded, not dead-ended;
  SMS fallback is FEATURE_PLAN A2.)
- **Older kid / out of ICP**: serve them on the generic track, warmly. The
  front door is niched; the product isn't.
- **Privacy question**: the C3 verbatim paragraph + "text 'forget me' and
  everything's deleted." Must be word-perfect, not improvised.
- **"Stop" / overwhelmed**: one message: digests off, logging still works,
  "say 'digest on' anytime." Tracking-anxiety positioning (BEACHHEAD.md):
  HAL is how you track *less* — never guilt, never streaks, and if they
  say they're stopping tracking, agree that's healthy.
- **Huckleberry refugee** ("can I import?"): "Not yet — but start texting
  and I'll have his rhythm within a day or two. Export works from day one
  (say 'export') so you're never locked in." Log import demand as friction.
- **gemini_failed on turn one**: slash-command-grade retry/fallback; a new
  user must NEVER meet "I'm having trouble right now" as message #2.

---

## Instrumentation (extends `compute_onboarding_progress`)

New funnel events on the existing `onboarding_events` timeline +
FEATURE_PLAN E rows: `track_selected(parent|generic)`, `acquisition_source`,
`baby_created`, `first_log` (stamp minutes-from-first-message — the #1
onboarding KPI, target median < 10 min), `forecast_shown`, `digest_sent_d0`,
`thread_howto_sent`, `family_thread_joined`, `second_caregiver_first_log`
(stamp hours-from-start — activation, target < 72h for ≥50%),
`caregiver_dm_started`, `brief_trial_{armed,asked,committed,expired}`,
`waitlisted`, `waitlist_converted`. Weekly cohort table in the admin digest:
started → first_log → D1 → thread → activated → D7 → D30.

## Implementation map (small, mostly prompt + glue)

1. `prompts/system.py`: parent-track branch in `next_onboarding_step` /
   `_onboarding_block` (new facts: `baby`, `city`; drop `home`/`work`/
   `google` from the parent path; day-0 name ask-cap = 1). Reuse decay.
2. Track detection + `onboarding_track` + `acquisition_source` on profile
   (`profiles.py`), sms-body code parsing in `routes/message.py`.
3. Forecast-reveal + digest-P.S. triggers in the baby write path
   (`services/baby.py` already computes `forecast_next`; fire on the
   code-side condition, through the outbox, respecting send gates).
4. Family-thread linking: group-silo → `HalFamily` join + Win-3 ack
   (builds on `group_catalog` warm-start + `get_family_for_silo`).
5. Landing hero + `?c=` variants (`routes/landing.py`, pure-renderer change).
6. Capacity gate + waitlist rows + admin override.
7. Parent flavor for the trial brief prompt (`services/helpful.py`).
8. Tests: `tests_onboarding_parent.py` mirroring `tests_onboarding_v2.py`
   (track selection, 3-question cap, forecast trigger, nudge once-ever,
   waitlist FIFO, Android/twins scripts present); extend `eval_first_win` /
   `eval_hal_behavior` with day-0 parent scenarios (first message = log,
   = question, = backfill dump; terse-ambiguity confirm-back).
9. Launch blockers inherited from BEACHHEAD.md P0: write-verified logging,
   digest count correctness, C3 privacy answer + forget-me.

**Sequencing:** 1–3 + 9 are the week-one build (the solo experience must be
perfect first); 4 + 7 the week after (household); 5–6 with the landing-page
switch; 8 alongside throughout.

---

## The test (GOALS.md §"test for any new feature")

Fewer taps to done: yes — setup collapses into the first log. Fits better
next week: yes — forecasts and briefs sharpen with data. Respects the room:
yes — one-ever nudges, silent in groups, no re-engagement. Ship it with
fewer messages: yes — week-one send budget is explicit and small.
