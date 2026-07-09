# HAL Conversation Mining Report
_Data through 2026-07-05. Source: prod Postgres (hal_messages, hal_turns, hal_friction_events, hal_feature_backlog, hal_playbook, hal_watches, hal_reminders). Read-only._

## Scope of what was read
- **2 primary silos read in full**: `+12017570419` (Adnan, the 1:1 — 685 msgs, 263 user turns, Jun 11–Jul 5) and `chat783794800760957500` (family baby-log group — 681 msgs, sampled morning/evening + all failure windows).
- **4 secondary silos read in full**: `chat494659226205048821` (Adnan+Seth lunch), `chat957723300680920907` (two-families North Fork), `+15555550100` (test/broadcast), `+16508239042` (Joyce/nanny 1:1), `chat837207703426444750` (WC tickets group).
- All 47 graded partial/failed turns, all 54 friction events, full backlog + playbook.

**Grade distribution**: 559 handled, 279 na, 35 partial, 12 failed. Failure categories: bad_judgment 29, infra_error 11, external_block 3, then singletons. The self-grading + internal critic loop is genuinely working (25 critic_catch events caught hallucinations *before* they shipped — see Delight section). Most of the pain is not in the graded failures; it's in high-frequency annoyances the grader doesn't flag.

---

## Executive summary — top 10 opportunities (impact × frequency)

1. **Proactive "heartbeat" cadence is spammy — the single biggest churn risk.** The heartbeat fires ~every 15 min. Even when nothing changed, it frequently *sends* near-duplicate messages instead of staying silent. Worst case: **~15 near-identical "leave by 3:30pm / bring a poncho" sends between 11am–1pm on match day** (`+12017570419`, 06-27), and **~15 near-identical "beautiful evening, stroller walk to Little Island" sends inside 15 minutes** (`+15555550100`, 06-29 21:55–22:11). There are **31 "already flagged…" messages** — sends whose entire content is HAL noting it already told you. This is a *cadence + gating* problem, distinct from (and beyond) the repetitive-summaries content-dedup rule already in flight. NEW angles below.

2. **HAL says "logged ✅" but the event silently didn't persist.** The 07-01 digest opens: *"Patched — 5 events hadn't saved (morning feed, the 11:30 wake, the 12:28 feed, and the whole 4:00 PM nap)."* HAL had confirmed each in real time. This is a silent **write failure**, not just HAL forgetting to call the tool. Separately, several terse updates got **no acknowledgment at all** (07-04 23:58, 07-05 12:55/14:16 — silent). 5 graded partials in the last week are silent-logging.

3. **TikTok/video fact-check is the #1 use case AND the #1 delight driver — but fragile.** **74 user messages** contain a TikTok/YouTube link (~28% of all user turns). Users love it and go deep. When the browser hits a captcha/login wall it fails or punts. This is the feature to make bulletproof and to invest in richer output.

4. **Weather tool was down ~4 consecutive days (Jul 1–3), not just intermittent.** HAL repeatedly told the user to *"peek outside before the stroller walk"* — violating its own new anti-punt rule — instead of consistently web-searching. 5 messages reference the outage.

5. **Current-time reasoning in proactive/countdown contexts is unreliable** (NEW angle beyond reminder-timezone work). "The match started at 5pm and it's now 4:06pm — you should already be inside" (self-contradicting, 06-27 graded partial); user corrected an alarmist countdown with *"I'm on east coast time so it's only 1120"*; sous-vide timers: *"Dude, you said take the steak out at 525, it's not 525 yet."*

6. **Live/priced data quoted from a stale cache erodes trust** (NEW). HAL quoted World Cup ticket prices *"from a price tracker last updated June 6"*; user caught it: *"Where are you seeing these prices? I'm seeing 2000 minimum."*

7. **Group over-participation + energy mismatch** (NEW evidence for restraint work). Seth: *"Ok please chill. You are a bit too enthusiastic, doesn't match my energy well this morning."* and *"Hap keep it to yourself, you're helping but not invited to this lunch."* Adnan says *"Stfu hal"* three separate times across chats. Distinct from interjection-frequency: it's *per-person tone* + not knowing when humans have already converged.

8. **Onboarding friction: Google-connect + repeated info-nagging** (NEW). User issued Connect Google → Disconnect → Connect **4+ times in 30 min** (07-04); the earlier raw OAuth URL was almost certainly un-tappable in iMessage (the short `/connect` link is a recent fix — evidence supports it). HAL also nagged Joyce for her name across 3 messages over 3 weeks.

9. **Stuck-pivot punts read as broken when repeated verbatim.** *"I dug into that but couldn't pin it down — can you give me one more detail?"* appears **back-to-back, identical** (06-21 ticket search; 06-25 lunch pivot). Even with the playbook fix, the identical double-send is the tell.

10. **Infra/model failures leak raw errors and blank out slash-commands.** `gemini_failed` blanked `/morning-brief` twice (06-16, 06-18). Users saw *"Sorry, I'm having trouble right now,"* *"I ran into too many steps,"* and *"The research agent choked."*

---

## Per-theme findings with evidence

### Theme A — Proactivity cadence & de-duplication (highest impact)
The proactive engine is HAL's best and worst feature. When it surfaces the right thing at the right time it's magic (Care.com applicant triage, ticket-transfer confirmations, "Shuka cancellation deadline is at 3pm today," Anthropic API suspension). But the firing *cadence* overwhelms the signal.

**NEW angles not covered by the repetitive-summaries content rule:**
- **Cadence, not just content.** Even a perfect "diff against last summary" leaves the heartbeat *evaluating* every ~15 min and often sending. Need a **global minimum interval between actual sends** (e.g. no non-urgent proactive send within N hours of the last one) and a hard "nothing genuinely new → send nothing" gate. Four `stuck` friction events fired on back-to-back heartbeats in 45 min (06-18 17:27–18:13), confirming the ~15-min beat.
- **Single-item over-nagging with escalation.** The World Cup pool deadline was nagged **~10 times with escalating urgency** — "LAST CALL — 28 minutes!", "13 MINUTES! …do it RIGHT NOW", then "Sorry for the heavy nagging this morning" (06-28). The user **still missed it** and asked for picks 2h later. Escalating nags for one actionable item cause banner-blindness. Cap re-nags per item (e.g. 2), then stop.
- **Morning-brief / first-heartbeat overlap.** Almost every `/morning-brief` at 12:00 UTC is followed 1–3 min later by a heartbeat repeating the same items ("Already flagged X in the morning brief I just sent at 8:00 AM"). Suppress the first heartbeat if a brief just went out.
- **Contradictory state across rapid sends.** In the 15-message evening burst (`+15555550100`), some sends say "no rain tonight," others "rain moving in around 7:30 PM (70%)," others "7:10 PM" — within 2 minutes. The heartbeat isn't reading its own prior output.

Quantified: 31 "already flagged" sends, 14 correct "…" silences (so the silence path exists — it just isn't the default often enough).

### Theme B — Baby logging reliability (highest-frequency feature: 174 "logged" confirmations)
The nap/feed/wake loop with schedule forecasting is the daily killer feature, and multi-parent coordination (Adnan + Joyce corrections) mostly works. But:
- **Silent write failures**: 07-01 digest "5 events hadn't saved" despite live "logged ✅" confirmations. The digest's reconciliation is a good safety net but it's *masking* a persistence bug. Fix: confirm the tool write succeeded before claiming "logged"; alert on write failure.
- **Duplicate writes**: same digest flagged a 4:50p **and** 4:59p feed — "looks like a duplicate."
- **Silent absorption of terse updates**: multi-event message 07-04 23:58 ("Baby at At 615 pm and slept at 7. Note he was awake…ate at 1 am and 4 am") got **no reply**; 07-05 12:55 & 14:16 also silent. The new "always acknowledge a reported update" playbook rule is the right instinct — evidence shows it's still leaking.
- **Terse-message parsing flip-flops**: the "5:05 saga" (06-22) — HAL misread Joyce's correction "At 505 before bedtime," logged a feed, then re-corrected twice. Ambiguous terse logs need a confirm-back rather than a guess.
- **Digest counting**: 07-03 digest says "Feeds: 7" but lists **6** times; 07-05 says "Feeds: 9 total" with no enumeration. The enumerate-before-count rule exists but isn't holding on the digest path.
- **Standout delight in the same feature**: the 07-01 overtired-meltdown crisis — HAL ran the medical checklist (temp, ear infection, hair-tourniquet), backed the parents' instinct to call the nurse, and said *"I've got the log covered — don't worry about updating me while you're out. Go take care of him."* This is the trust peak of the whole dataset. Protect this behavior.

### Theme C — Fact-check / research (the love + the fragility)
74 fact-check requests; the depth is a retention engine — Adnan repeatedly rabbit-holes (Girard→Thiel→Gilgamesh; Oh-My-God particle→black-hole cosmology; Herculaneum scrolls). Evidence of love: he keeps asking follow-ups ("How did Christ expose the sacrificial?", "So what is it and where is it coming from"). Double-down ideas:
- **Reliability**: captcha/login-wall failures (already backlogged as `social_media_extractor`). Real evidence: 06-12 The Atlantic post blocked; 06-11 TikTok → `gemini_failed`.
- **Format**: walls of text are *tolerated here* (this user wants depth) but a consistent skimmable header — a one-line verdict badge (✅ True / ⚠️ Mixed / ❌ False) followed by the claim-by-claim breakdown — is already emerging organically and could be standardized. When HAL couldn't fetch the video it still delivered value from the title/description ("Couldn't pull the transcript, but from the description…") — good graceful degradation to keep.

### Theme D — Time & data freshness (NEW angles)
- **Current-time discipline must extend past reminders** to: heartbeat "you should already be inside" logic, event countdowns (match day), and **cooking timers** (the sous-vide session had 3 time-confusion corrections in a row, ending in "Dude…"). Same `current_time`-before-any-relative-claim rule, applied to these surfaces.
- **Freshness caveats on quoted numbers**: ticket prices from a 3-week-old tracker shipped as current. Either fetch live or label the as-of date. (Complements the fabricated-data playbook rule, which covers invented numbers but not *stale* ones.)

### Theme E — Group behavior (NEW evidence for the restraint effort)
- **Per-person energy calibration**: Seth explicitly wants low-key; the North Fork friend group *loves* HAL's banter ("C-anal Street!" gets laughs; baby-photo one-liners like "wait are you my person??" are adored). Same HAL, opposite optimal register. Tone should be per-participant, not per-silo.
- **Know when to stop closing**: in the Seth lunch chat HAL asked "Lock it in for 12:20?" / "good to lock that in?" repeatedly while the humans were still converging → "Stfu hal." Once participants are actively hashing out logistics themselves, HAL should go quiet unless asked.
- **Good boundaries to keep**: HAL correctly refused to leak Adnan's email/1:1 info into the group ("I keep 1:1 info private"), and offered iOS-parseable event text when calendar-write was unavailable. Those are wins.

### Theme F — Unmet capability requests (from users, verbatim)
- **Booking/reservations**: "ok just book the 8pm one for me" — HAL can only hand off a link (backlog: reservation tool). High-signal.
- **Send MMS/photo to a contact by name**: "Send this to nanny" — HAL had no number and no contacts lookup (backlog: MMS).
- **Read shared iCloud Notes**: "Hal can you read this [icloud.com/notes]" — Apple blocks it; workaround is paste-text.
- **Create calendar events / invites**: read-only calendar; Seth wanted a real invite. Workaround (iOS-parseable text) is decent but users want the real thing.
- **Live sports without looping**: "Is there a Fifa game today?" → `too many steps` (backlog: sports API). Note the **score-alert watch actually fired correctly** ("Goal! Someone just scored…") — the watch primitive works; the ad-hoc web-search loop is what blows up.

### Theme G — Reliability / infra
- `gemini_failed` clusters blanked `/morning-brief` (06-16, 06-18) and greetings ("hi" → "trouble right now"). Slash-commands especially should retry/fallback so they never return empty.
- Raw error-string leaks to users: "I ran into too many steps," "The research agent choked," "Sorry, I'm having trouble right now."

---

## Quick wins (prompt / playbook level)
1. **Heartbeat gate**: "If nothing is materially new since your last sent message in this silo, send nothing (output the silent token). Never send a message whose content is only that you already flagged something." (Kills the 31 "already flagged" sends.)
2. **Re-nag cap**: "For a single actionable item, send at most 2 proactive nudges total, then stop until the user engages." (Kills the escalating pool-deadline spam.)
3. **Suppress post-brief heartbeat**: "If a morning brief or digest was sent in the last hour, do not run a heartbeat send."
4. **Confirm-before-claim on writes**: "Never say 'logged'/'reminder set' until the tool returns success; if it fails, say so and retry." (Backs the existing baby_tool rule with the write-failure case.)
5. **Freshness caveat**: "When quoting prices, scores, or availability, either fetch live or state the as-of timestamp; never present cached market data as current."
6. **Current-time for countdowns & timers**, not just reminders (extend the temporal_awareness rule's surfaces).
7. **De-duplicate the stuck-punt**: never send the identical "couldn't pin it down, one more detail?" twice in a row — if the first didn't unstick it, change approach or actually re-run the search.
8. **Per-person tone note**: persist "Seth prefers low-key/brief" style and apply in that participant's presence (aligns with the tone-feedback task).

## Code features (bigger lifts)
1. **Heartbeat scheduler redesign**: global min-interval between non-urgent sends + urgency tiering + "diff against last *sent* message, not last summary." This is the highest-ROI code change in the dataset.
2. **Baby-log write path**: transactional write with success check + idempotency (dedupe near-identical events like 4:50/4:59) + a "reconcile on digest" that *reports* the bug rather than silently patching.
3. **Weather tool hardening** (already backlogged) — but the evidence is a *multi-day hard outage*, so prioritize the secondary-provider failover + cache, not just retry.
4. **Social-video extractor** (backlogged) — this is the #1 use case (74 hits); worth doing well.
5. **Reservation + MMS/contacts tools** (backlogged) — repeated verbatim asks.
6. **Reminder storage is silo-mis-scoped**: all 242 reminders are stored `is_group=f` under `+12017570419`, even the baby-log reminders that originate in the family group chat, and the group Seth-lunch reminder never persisted at all (graded partial: "I dropped the ball on actually creating it"). Group-context reminders need to persist and fire in-group. (Related to the reminder work already underway — flag as the concrete failing case.)

---

## Sketchy things visible in the transcripts (bugs)
- **Internal status strings leaked as user-visible messages**: "Sent ✓", "Brief sent ✓", "Sent ✓" appear as assistant messages in `+15555550100` (06-29 22:10–22:11).
- **Phishing risk**: HAL relayed a "Stripe Security Alert" email **and its login link verbatim** without any caution flag (07-03 13:07, graded partial). Same pattern with a Google account-recovery alert. Proactive relays of security emails should add a "verify independently, don't tap links from a text" caveat.
- **Contradictory forecasts within minutes** (rain on/off, `+15555550100`).
- **Duplicate feed log** (4:50p + 4:59p, 07-01).
- **Digest count ≠ enumerated items** ("7 feeds," lists 6; 07-03).
- **Self-contradicting time math** shipped to user: "started at 5pm and it's now 4:06pm — you should already be inside" (06-27).
- **Watches offered but not created**: HAL offered a FIFA face-value ticket-drop watch and "I'll text you the moment either team scores"; only **one** watch row exists in the entire DB (the score alert, which did fire). Offers of proactive monitoring mostly don't materialize into watch rows.

## Double-down signals (what users love)
- **Deep intellectual companionship** on fact-checks and rabbit-holes — the strongest retention driver. (Girard/Thiel, cosmology, Herculaneum, epigenetics.)
- **Nap/feed-aware itinerary math** — "get there awake, nap on the walk home" threading is the standout practical feature.
- **Crisis co-parenting** (07-01 meltdown) — calm, medically literate, and it explicitly took logging off the parents' plate.
- **The "Surprise me — make my day better 🎁" prompt** (3×) drew genuinely delightful curated "gems" — a repeatable delight primitive.
- **Group banter** in the friend chat — HAL is a beloved character there ("C-anal Street!", baby-photo one-liners get "Loved" reactions).
- **The internal critic** silently caught ~25 hallucinations/time-inconsistencies before send (fabricated precipitation, hallucinated doctor visits, over-long wake windows, omitted auto-reminders). Keep and lean on it.

_Report file: `/private/tmp/claude-501/-Users-adnanakil-Project-agentlist/f22a609a-1225-4c2c-acef-1b6bb20cb1e1/scratchpad/convo-mining-report.md`_
