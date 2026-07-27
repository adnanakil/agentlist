# HAL — Community Marketing Plan (2026-07)

*Operationalizes BEACHHEAD.md's go-to-market: value-first, founder-led help
in the places families already ask for it. Companion tooling:
`scripts/forum_scout.py` (daily thread discovery) and the `?c=` attribution
codes wired through the landing page → `acquisition_source`.*

---

## The rules (non-negotiable, before anything else)

1. **Disclose, every single time.** Any message that mentions HAL carries
   the founder line in your own words ("I built this because we kept losing
   the thread on feeds"). No exceptions, no "someone told me about," no
   second accounts. This is FTC territory and — more importantly — the
   entire brand.
2. **Never AI-written posts or comments.** Parenting mods delete AI text on
   sight and ban for it; one ban in this vertical is near-unrecoverable.
   Everything below is an OUTLINE — the words are always yours.
3. **The answer must stand alone.** Help fully first; the reply has to be
   worth upvoting even if HAL didn't exist. Mention HAL only when the
   question is literally about the thing HAL does.
4. **Ratio: ≤1 product mention per 5–6 genuine contributions.** Never the
   same mention across subs in the same week.
5. **Discovery is automated; participation never is.** forum_scout finds
   threads. It will never post, vote, or DM — and neither does any other
   automation.
6. **Never pitch in pain.** Grief, NICU, medical emergencies, PPD crises:
   help like a human or stay out.
7. **Kill criteria** (from BEACHHEAD): any venue that bans or warns → stop
   there entirely. Any paid probe >$40/activated household → kill.

---

## The weekly engine (30–60 min/day founder time)

| When | What |
|---|---|
| Every morning (10 min) | `uv run python scripts/forum_scout.py` → pick 1–3 threads where you can genuinely help |
| Daily (20–30 min) | Write 2–4 real answers in your own words. Most mention nothing. |
| Tue + Thu (10 min) | One partnership outreach email (list below) |
| Friday (10 min) | Scorecard: contributions, mentions, text-started per `?c=` code, first_log conversions (admin digest) |
| Week 6–8, once | The r/daddit founder story post (see below) — only after the account has real history |

Account prep (start now, runs in the background): one human account, aging
toward 60+ days and 200+ karma from ordinary participation before any
founder post. Join Park Slope Parents + 2–3 FB groups now — their 30-day
genuine-membership clocks start on join.

---

## The use-case answer library

The same eight questions recur weekly. For each: the genuinely helpful
answer (outline — write it in your words), and whether a disclosed HAL
mention even belongs.

### 1. "What tracking app can BOTH parents use?" (app-recs)
- The real answer: whatever you pick, the failure mode is sync — shared
  logins get logged out, per-seat pricing punishes the second parent, and
  the non-installing caregiver never logs. Recommend picking for the
  *household*, not the phone: shared access should be free and instant.
- HAL mention: appropriate WITH disclosure — this is exactly the question
  HAL answers ("we text feeds to our family thread and it keeps one log —
  I built it after the shared-password thing broke us").

### 2. "How do I sync the log with our nanny?" (nanny-sync)
- The real answer: the nanny will not install an app, and she's right not
  to. Paper works. A pinned note works. The system that survives is the one
  that lives where you already talk — your text thread.
- HAL mention: appropriate with disclosure; this is the wedge persona.
  Honest caveat if asked: group logging needs iMessage today.

### 3. 3am logging misery (3am-logging)
- The real answer: lower the bar. Nobody needs oz-perfect records at 3am —
  a two-word note beats an abandoned app. Track less, in the easiest place.
- HAL mention: usually skip. If the thread is explicitly about app
  friction at night, one line with disclosure.

### 4. Huckleberry price / sync / anxiety (huckleberry)
- The real answer: name what's actually good about it (SweetSpot is real),
  then the honest costs: per-family pricing quirks, the shared-login hack,
  and the dashboard-staring anxiety loop. Permission to quit: your baby, not
  the graph, is the source of truth.
- HAL mention: only if they ask for alternatives; never dunk on the
  competitor — the anxiety framing matters more than the feature list.

### 5. "When did you stop tracking everything?" (tracking-anxiety)
- The real answer: earlier than you think, and it's healthy. Whatever
  tracking remains should be ambient — said out loud, not dashboarded.
- HAL mention: almost never. This thread type is where the category's
  backlash lives; be the person who agrees tracking less is good. (This IS
  HAL's positioning — "the way to track less" — but let the thread breathe.)

### 6. Wake-window confusion (wake-windows)
- The real answer: age-normed ranges (share the table — 0–4wk ~45min,
  5–8wk ~60, 9–12wk ~75, 3–4mo ~90…), plus: your baby's own trailing
  pattern beats any chart within a week of notes.
- HAL mention: rarely; the table is the gift. Disclosure if asked how you
  track the pattern.

### 7. Mental load / "dad can't see the schedule" (mental-load)
- The real answer: the fix is structural, not motivational — the schedule
  has to live where BOTH of you already look. Anything that requires the
  other parent to open a special app recreates the load.
- HAL mention: occasionally, with disclosure, when tools are asked for.

### 8. Nanny→parent handoff ("how was his day?") (nanny-sync)
- The real answer: the handoff brief pattern — last feed, last wake, next
  likely nap — takes 15 seconds when it's written where everyone can see
  it, and zero seconds when something keeps it for you.
- HAL mention: appropriate with disclosure in r/Nanny and r/NannyEmployers
  where "holy grail system" threads literally ask for this.

### The r/daddit story post (week 6–8, once)
Shape: personal-pain narrative with data — "our nanny, my wife and I kept
losing the thread on feeds, so the baby log became a group chat with a
number we text; here's what 6 weeks of that looked like" — screenshots of
the real thread (family-approved), the numbers, what broke along the way.
Name-as-footnote, no link in the post body, founder status in the first
paragraph. Post only from the aged account; answer every comment for 48h.

---

## Venue playbook

*Rules verified 2026-07-19 (sidebars/wikis via mirror + archive snapshots). Re-check any venue before its first founder post — rules drift.*

- **r/NewParents (522k members)**
  <https://www.reddit.com/r/NewParents/wiki/rulesfaq>
  Rule 5 (live wiki, fetched today via mirror of reddit.com/r/NewParents/wiki/rulesfaq): "No Self-Promotion/Advertising/Surveys — Do not make posts to generate followers for your Youtube channel or your blog. These will be removed and continued postings will result in a permanent ban. We are not allowing academic survey posts at this time." Rule 3: "No Spam — Spam will be removed and users placed on a permanent ban," and the wiki adds "Spam will be removed. This applies to posts or comments which are obviously advertising, including blog posts" — note it covers COMMENTS too. Rule 2 (No Soliciting) also carries a permanent ban.
  *Angle:* Comments-only, and sparingly. Answer feeding/sleep/logistics questions on the merits; mention HAL only if someone explicitly asks how to share a log across caregivers, with the I-built-this disclosure, and keep it well under Reddit's 10% self-promo norm — the spam rule reaches comments and the penalty is a permaban. Never make a HAL post here.
- **r/beyondthebump (806k members)**
  <http://web.archive.org/web/20260601080428/https://www.reddit.com/r/beyondthebump/>
  Rule 1 (rules widget, Wayback snapshot June 1, 2026; matches live wiki fetched today): "No Advertisements, AI Content, Market Research, or Spam — This is not the place to ask for donations or advertise your personal blogs/services. Spam, market research, or AI content will be removed and you may be banned. Do not post links to your personal site." Rule 4: "No Polls or Surveys ... without prior permission from the Moderators." Note the explicit "AI content" ban — sensitive territory for an AI assistant product.
  *Angle:* Comments-only with disclosure when directly asked; no posts, no links to hal's site ("do not post links to your personal site" is explicit). A 'how our family split night shifts' story post that name-drops HAL would read as market research/advertising under Rule 1. The only mod-permission route (Rule 4) covers polls/surveys, not products — not useful here.
- **r/daddit (2.0m members)**
  <https://www.reddit.com/r/daddit/wiki/rules>
  Wiki rules page (live, fetched today): "No Self Promotion or Solicitation. Do not post promotions/links to any product or service you created or are selling, to include apps or other tools. ... Do not solicit responses to surveys, votes, etc, regardless of purpose." Apps are named explicitly. Separate lane for CONTENT creators (wiki/blogs, live): blogs/podcasts/YouTube can be mod-listed on the content wiki after genuine participation ("no more than 10% of your posts/comments should be self-promotion"), then may "promote themselves through posts sparingly" as text posts with "a clear expression that the poster is the author." Also: "No AI Posts" (AI-composed posts removed).
  *Angle:* Best genuine-participation venue for a dad founder — but the whitelist route covers content (blogs/podcasts/YouTube), not apps, and the product rule names "apps" explicitly. Lane: participate as a real NYC dad, comments-only for HAL mentions when asked, always disclosed. Optional: modmail asking whether a disclosed built-this-for-my-family story post would fly (mods reserve discretion), or start genuine dad content (e.g. a newborn-logistics blog/podcast) and earn a wiki listing the legitimate way.
- **r/Nanny (93k members)**
  <http://web.archive.org/web/20260619021451/https://www.reddit.com/r/Nanny/>
  Rule 7 (rules widget, Wayback snapshot June 19, 2026): "No Spam/Job Ads/Surveys/Self Promotion/Affiliate Links — Any posts deemed as spam ... will be removed. This includes affiliate links or promotion of your own products or services. General product recommendations are permitted. Posting surveys or research projects is not permitted. AI generated content is also considered spam and will be removed." Rule 5 adds "Usage of AI responses as a source will result in post or comment removal." Relevant context: the sub's own FAQ answers "What app do you use to keep track of feedings, diaper changes, etc?" with a list (Huckleberry, Daily Nanny, Baby Connect, Baby Tracker, Daily Connect...).
  *Angle:* Comments-only, and treat own-product mentions as off-limits even disclosed — Rule 7 bans "promotion of your own products" while allowing GENERAL product recs, i.e. HAL should enter this sub through other users recommending it, not the founder. The founder can still answer employer-side questions genuinely (flair as NP). Longer play: once real nannies use HAL, its natural home is that FAQ app list — a polite modmail suggestion, never a post. Watch the two AI-content tripwires.
- **r/NannyEmployers (16k members)**
  <http://web.archive.org/web/20250728210556/https://www.reddit.com/r/NannyEmployers/>
  Only five rules as of the newest available snapshot (Wayback July 28, 2025 — the freshest archive; re-verify in-app): 1 be respectful, 2 no doxxing, 3 no medical advice, 4 no legal advice, 5 respect post flair ("nanny parents only" flair). NO explicit self-promotion/advertising rule, and no wiki exists. Live sub description (fetched today): "a space for all employers of a nanny or au pair to discuss, kvetch and get opinions"; primarily a parents' space; anonymous posting available via mod DM.
  *Angle:* The most natural venue on the list: the founder IS a nanny employer, so a disclosed "here's how we keep our nanny, grandma and us on one feeding log" contribution is on-topic and no written rule forbids it. Still: rules snapshot is a year old and it's a small mod-discretion sub — verify current rules in-app and modmail first before anything post-shaped; comments answering coordination questions are the safe default.
- **r/sleeptrain (170k members) — BAN RISK, stay out as founder**
  <http://web.archive.org/web/20250725084055/https://www.reddit.com/r/sleeptrain/>
  Rule 7 (rules widget, Wayback July 25, 2025 — newest archive available): "No Self-Promotion — Promotion of blogs, surveys, chat bots, or other materials/services is not allowed. We welcome the advice and expertise of sleep consultants. Unapproved advertising, spam, giveaways, AMAs, and comments containing self-promotion will be removed. This includes solicitation of DMs. We ask that all sleep consultants and bloggers update their flair to identify themselves. Due to an influx of self-promotion, mods will likely ban first time offenders that do not follow the rules." Live sidebar (fetched today): "As a general practice we do not reverse bans" — and mods run their own paid sleep-plan service, dreamie.rest. The word "Unapproved" implies a mod pre-approval route exists (modmail + identifying flair), but it is aimed at credentialed sleep consultants.
  *Angle:* Stay out as a founder. "Chat bots" is named in the ban, first offense likely = ban, bans aren't reversed, and the mod team has a competing commercial product — a pre-approval request for an AI baby log is a long shot with real downside (account ban travels via ban-evasion enforcement). If ever attempted: modmail pre-approval + flair FIRST, zero mentions before written approval. Reading the sub for product insight is fine; promo participation is not.
- **r/Mommit (2.7m members) — stay out entirely (moms-only bars a dad founder)**
  <http://web.archive.org/web/20260531230036/https://www.reddit.com/r/Mommit/>
  Rule 1 (rules widget, Wayback May 31, 2026): "No blogs, surveys or promotional posts — Blogs and surveys are not welcomed at this time. Promotional posts, market research and solicitations are also not allowed." Rule 2: "Moms only — ... whether commenting, or posting." The monthly promo sticky question: the LIVE sidebar (fetched today) still says "NO blogs or surveys outside the stickied monthly blog/survey post" and "Want to share a blog? Please link it in our monthly blog thread" — but a search of the sub's recent history turns up NO monthly blog/survey thread (nothing since at least 2024), and the current structured Rule 1's "not welcomed at this time" language supersedes it. The sticky is defunct legacy sidebar text.
  *Angle:* Stay out. Two independent bars: (1) the founder is a dad and Rule 2 prohibits him from commenting OR posting at all — any participation is a removal/ban risk regardless of disclosure or value; (2) even for a mom teammate, promotional posts are flatly banned and the monthly blog/survey sticky no longer runs. If HAL ever has a mom co-founder/teammate, she could participate genuinely, but there is still no promo lane here.
- **r/workingmoms (164k members) — stay out (founder-move explicitly banned + not a working mom)**
  <http://web.archive.org/web/20250713222445/https://www.reddit.com/r/workingmoms/>
  Rules widget (Wayback July 13, 2025 — newest archive available; re-verify in-app): Rule 5: "Posts may cover any topic regarding parenting/work but responses must be from working moms." Rule 7: "No surveys/research requests please. This includes for work, for school, for an article/research. ... No asking if working moms are interesting [sic] in what you are trying to make or sell." Rule 8: "No blogs, solicitation, selling, or spam please."
  *Angle:* Stay out. Rule 7 is nearly a description of the founder-validation post ("asking if working moms are interested in what you are trying to make or sell") and Rule 5 restricts responses to working moms, so a dad founder has no compliant way to even comment. As with Mommit, a working-mom teammate could participate genuinely, but with zero promo lane.
- **Park Slope Parents (paid lane exists — best NYC placement buy)**
  <https://www.parkslopeparents.com/Advertise-with-PSP/place-a-commercial-post-on-our-list-serve.html>
  Verified live on parkslopeparents.com (fetched today). Paid options: (1) Commercial Posts on the Advice List email digest (11,000+ Brooklyn parents daily, tagged [CP] in subject): $75/post standard ($50 Brooklyn 501c3, $60 other 501c3; 10-packs $450/$550 for nonprofits), up to 40 lines/1,500 chars, 2 images + attachment, sendable on your schedule over 18 months. (2) Run-of-site banners, (3) Category banners over the Recommendations section, (4) logo on your Recommendations listing, (5) Dedicated email blasts (one advertiser/week, 5,000+ members), (6) Newsletter sponsorship (18,000+ recipients, 64–76% open rates) — banner/email pricing via advertising@parkslopeparents.com. Conduct rules for businesses on the member lists: you MAY "reply to a post individually" when a member asks for a specific service, but may not "troll the list for names of people to spam"; repeated unwelcome responses are treated as abuse and jeopardize membership.
  *Angle:* Paid placement + earned recommendations — this is the one venue with an official, welcomed founder lane. Concrete play: (a) $75 Commercial Post (or a 5-pack) written as the founder's own story; (b) get HAL a Recommendations-section listing so member word-of-mouth has somewhere to land; (c) as a paid member and actual Park Slope-adjacent dad, individually reply when someone asks the list for baby-tracking/caregiver-coordination recs — explicitly permitted, with disclosure. Skip mass-messaging; that's their abuse definition.
- **NYC parents & nannies Facebook groups (rules unverifiable from outside — treat as no-promo until admins approve)**
  <https://www.facebook.com/groups/2126168947622586/>
  All relevant groups are PRIVATE, and their rules/pinned posts are invisible without membership — I could confirm existence and size but not rule text, so no rule can honestly be quoted. Found: "The Parents & Nannies of New York City!" (~5.2K members, purpose "to connect families with nannies and nannies with families" — i.e. a hiring board), "Manhattan Moms and Nannies-NYC", "Williamsburg Brooklyn Parents & Nannies", UES Mommas (~28K, private), Brooklyn Baby Hui (~4K, private), plus PSP's own FB group (~8.3K, tied to paid PSP membership). Public directories (Tinybeans, Mommy Poppins, SmartSitting) confirm admin-gated entry and pre-screened posts as the norm but document no promo policies.
  *Angle:* Join as a real NYC dad (answer the screening questions honestly), read each group's pinned rules from inside, then MESSAGE ADMINS for explicit permission before any HAL mention — many NYC parent groups run designated vendor/promo days or small-biz threads, but that must be confirmed per group. Until then: comments-only genuine help, zero product mentions. Extra caution in the parents-and-nannies matching groups: they're job boards, a product pitch there reads as spam and admins remove-and-ban fast; undisclosed or fake-account participation would also violate Facebook group norms and the founder's own disclosure principle.

## Day-one threads (live now)

*Researched live 2026-07-19 (14 threads; r/NannyEmployers had nothing usable this week — all pay disputes). Refresh daily with `scripts/forum_scout.py`. Every angle below leads with the genuine advice; mention flags are per-thread.*

- **Is the mental load of a newborn supposed to be this heavy? (r/NewParents, ~27d old, 175 pts, 110 comments)**
  <https://www.reddit.com/r/NewParents/comments/1ucohjv/is_the_mental_load_of_a_newborn_supposed_to_be/>
  OP is drowning in mental tracking — 'When did they last eat? How many ounces? Which side did I nurse on last?' — and says even when her partner takes a shift her mind races with everything she must remember to tell them. She explicitly asks: 'Are there any actual systems or apps you use to manage all this mental clutter?' Top comments push back on over-tracking (some say it fed their PPA), so lead with permission to drop non-essential metrics. Near the 1-month age limit but the single best product-question fit found.
  *Angle:* The fix is moving the list out of one parent's head into a shared external record both partners write to — any shared log plus a standing handoff note kills the 'memory dump between shifts' problem; only track what changes a decision. Disclosed HAL mention appropriate (OP asked for apps): one line at the end, 'I built a thing for exactly this, disclosure.'
- **Which apps did you help the most throughout? (r/newborns, ~8d old, 6 comments)**
  <https://www.reddit.com/r/newborns/comments/1utklj3/which_apps_did_you_help_the_most_throughout/>
  Direct app-recommendation request: which apps (Huckleberry etc.) actually helped in the newborn phase through year one. Thread is small and still answerable; current replies are a spreadsheet user, a Huckleberry-glancer, and one app plug — OP is following up asking what apps got wrong/missed, which is an open door.
  *Angle:* Honest by-stage rundown: weeks 0–8 the feed/diaper log matters most (it's what the pediatrician asks about) and any free tool works; sleep-prediction features are averages, not oracles; the real test is whether both caregivers actually keep the log up. Disclosed HAL mention fully appropriate here — 'I built one that lives in iMessage so everyone actually uses it; I'm the founder.'
- **Siri Shortcuts for baby logging and newborn tech pearls (r/daddit, ~9d old, 8 comments)**
  <https://www.reddit.com/r/daddit/comments/1usr0an/siri_shortcuts_for_baby_logging_and_newborn_tech/>
  Dad of 2 built voice-prompted Siri Shortcuts that timestamp diapers/feeds into a CSV shared with his wife — hands-free, no extra login. His first child was failure-to-thrive, so the tracking has real medical stakes for him. One commenter scolded him for over-tracking; he explained why it matters. This is HAL's exact thesis (capture must be frictionless and shared) arrived at independently.
  *Angle:* Builder-to-builder: validate the insight that hands-free capture into a shared record is the whole game, add what you learned (grandma/nanny can't run his Shortcut — text-based capture covers every caregiver; daily totals matter more than raw rows for weight-gain tracking). 'I went down the same rabbit hole and ended up building X — I'm the founder' disclosure lands naturally and is very appropriate here.
- **Parents & Nannies: What's your holy grail digital calendar for syncing schedules? (r/Nanny, ~7d old, 30 comments)**
  <https://www.reddit.com/r/Nanny/comments/1uucmie/parents_nannies_whats_your_holy_grail_digital/>
  Dual-income parents asking how to sync chaotic camp schedules and daily task lists with their nanny without frantic verbal handoffs or giving the nanny access to their Google family group. OP posted an update saying they bought an 'Everblog' calendar, but the thread is active with parents and nannies swapping systems (Skylight, paper wall calendar, color-coding). Kids are older (camps/chores), not newborns.
  *Angle:* Concrete system advice: a dedicated shared calendar the nanny is invited to directly (separate from the family Google group) plus one written daily-log ritual beats any single gadget; the failure mode is systems only one side updates. HAL mention only tangential (it's a baby log, not a calendar/chore tool) — lean no, or at most one disclosed aside if the newborn-log topic comes up in replies.
- **When did you stop tracking your baby's diapers, naps, feeds, etc.? (r/beyondthebump, ~25d old, 10 pts, 165 comments)**
  <https://www.reddit.com/r/beyondthebump/comments/1uecwca/when_did_you_stop_tracking_your_babys_dispers/>
  The canonical 'when did you stop tracking' thread: 7-week-old is huge, thriving, sleeping 8–10h; OP asks whether stopping tracking this young is neglectful. Big active comment section split between 'never tracked, you don't need to' and 'tracking eased my anxiety.' Near the age limit but the highest-volume version of this recurring question this month.
  *Angle:* With weight gain established, diapers normal, and pediatrician happy, tracking is officially optional — keep only what feeds an actual decision (e.g., last-feed time on a sticky note), drop the rest guilt-free. Thread tilts anti-tracking, so a product mention is mostly unnecessary; at most a disclosed founder observation that tracking should cost nothing or not be done at all. Lean advice-only.
- **Maybe I don't understand schedules at all… (r/sleeptrain, ~4d old, 12 comments)**
  <https://www.reddit.com/r/sleeptrain/comments/1uxmhlw/maybe_i_dont_understand_schedules_at_all/>
  Classic Huckleberry complaint: 'I wonder if Huckleberry screwed me bc we followed it religiously but things never got better, so I need to take control into my own hands.' Parent is confused about wake windows vs the app's SweetSpot predictions and wants to understand schedules from first principles.
  *Angle:* Explain that app sweet-spots are population averages, not measurements of your baby — show how to derive real wake windows from one week of their own data (time-awake before naps that went well vs badly) and treat predictions as hypotheses. Advice-only: HAL doesn't do sleep prediction, so no mention — answering the Huckleberry frustration well IS the value here.
- **Napper App — when do you even start sleep tracking? (r/sleeptrain, ~9h old, 3 comments)**
  <https://www.reddit.com/r/sleeptrain/comments/1v0uhrk/napper_app/>
  Expectant first-time mum, due soon, was recommended the Napper app and asks whether there's a certain age to start sleep tracking (8 weeks?) or any use in tracking right away. Freshest thread on the list — posted hours ago, barely answered.
  *Angle:* Genuinely useful staging: newborn sleep has no rhythm to predict until ~8 weeks, so sleep-prediction apps add nothing early — but a simple feed/diaper log from day one is worth it because that's what the pediatrician asks about at every visit. A soft disclosed HAL mention is defensible (she's asking what to set up before birth), but keep it one line after the real answer.
- **Tracking naps — helpful or just anxiety? (r/newborns, ~28d old, 11 comments)**
  <https://www.reddit.com/r/newborns/comments/1uc6qfh/tracking_naps/>
  OP asks whether people find Huckleberry nap-tracking actually helpful — her friends all track, she just puts baby down when she seems tired and gave up tracking feeds. Right at the month boundary; include only if commenting soon.
  *Angle:* Cue-following is completely legitimate; tracking earns its keep in exactly two cases — troubleshooting a specific problem, or handing the baby to another caregiver who needs to know when the last nap/feed was. Mention HAL only inside that second point, one disclosed line, or skip entirely.
- **Shifts are great...until they aren't (r/NewParents, ~3d old, 67 pts, 96 comments; duplicate 'Shift care backfiring' in r/newborns)**
  <https://www.reddit.com/r/NewParents/comments/1uym17n/shifts_are_greatuntil_they_arent/>
  Couple running a night/day shift system ('based on the app we use to track everything') hits a wall as dad returns to work at 2 months: baby only does long stretches on a parent, mom can't sleep. Asking for suggestions on restructuring. Cross-posted to r/newborns as 1uylub0 (~3d, 10 comments).
  *Angle:* Practical shift-system advice from a dad who lived it: split the night into two hard blocks with the off-parent in a separate room and earplugs, protect one 4–5h anchor stretch for mom, and use the log to spot which stretch is most reliably long before assigning shifts. They already track — no product mention needed; advice-only.
- **Trapped in the living room!! (r/newborns, ~22d old, 36 pts, 96 comments)**
  <https://www.reddit.com/r/newborns/comments/1uhh6k9/trapped_in_the_living_room/>
  First-time parents doing sleep shifts have effectively stopped living in their own home — one sleeps behind a closed door, the other camps in the living room with the bassinet. High-engagement peer-support thread about escaping the shift-sleeping trap.
  *Angle:* Been-there advice on graduating out of shift sleeping (moving bassinet to the bedroom in stages, consolidating night feeds, when it's safe to trust a monitor) and reassurance that the arrangement is a phase. Advice-only — any product mention would be tone-deaf in a commiseration thread.
- **Advice for parents who miss half of bedtimes every week? (r/beyondthebump, ~1d old, 1 comment)**
  <https://www.reddit.com/r/beyondthebump/comments/1v0jfrr/advice_for_parents_who_miss_half_of_bedtimes/>
  Both parents now work evenings 3 nights/week so the nanny does bedtime; 10-month-old has started waking screaming on nanny-bedtime nights, and OP is guilt-ridden, worried about attachment damage. Nanny-parent handoff household, but the emotional center is guilt, not logistics. Nearly unanswered.
  *Angle:* Reassure with evidence (separation anxiety peaks 9–12 months; consistent, warm nanny bedtimes with the identical routine/script — same book, same song — close the gap; no research supports lasting harm from 3 nanny bedtimes/week). NO product mention — this is a guilt/attachment thread and a promo would be tone-deaf; pure help builds standing in the sub.
- **How do I know my 4 month old is doing ok in daycare? (r/workingmoms, ~5d old, 31 comments)**
  <https://www.reddit.com/r/workingmoms/comments/1uwnr50/how_do_i_know_my_4_month_old_is_doing_ok_in/>
  Mom back at work can't tell how her 18-week-old is actually doing at daycare — eating and napping poorly, and she has no visibility into his day. The caregiver-information-gap pattern, in daycare form.
  *Angle:* Tell her exactly what to ask the center for: which app they use (Brightwheel/Procare/Tadpoles all push per-feed and per-nap entries to parents), a daily report as a licensing-level expectation, and what a normal 2–4 week adjustment curve looks like. No HAL mention — daycares run their own systems; this is relationship-building help only.
- **At what point did you get your baby on a more predictable 'schedule'? (r/NewParents, ~25d old, 19 pts, 99 comments)**
  <https://www.reddit.com/r/NewParents/comments/1ueu6bq/at_what_point_did_you_get_your_baby_on_a_more/>
  Parent of a 6-week-old deliberately avoiding all baby apps ('would just add unneeded stress') asks when predictable schedules emerged for others. Big thread, still gets replies. OP is explicitly anti-app.
  *Angle:* Straight answer: real schedules self-assemble around 3–4 months when circadian rhythm matures; before that the only pattern worth nudging is day/night distinction (light, activity, boring night feeds). Absolutely no product mention — OP rejected apps; a good app-free answer from a founder is exactly the kind of participation that earns trust in the sub.
- **Anyone tried a baby monitor with sleep tracking and did it actually help? (r/newborns, ~18d old, 8 comments)**
  <https://www.reddit.com/r/newborns/comments/1ukstga/anyone_tried_a_baby_monitor_with_sleep_tracking/>
  Parent of a 4-week-old running on no sleep is considering monitors that analyze overnight sleep patterns and wants to know if the breakdowns are actually useful. Hardware-adjacent version of the tracking question.
  *Angle:* Honest take: at 4 weeks there's no sleep architecture worth analyzing and monitor 'sleep scores' mostly manufacture anxiety — a basic video monitor plus knowing wake-window norms beats a $300 analytics camera; revisit at 4–6 months if troubleshooting. Advice-only; HAL is not a monitor, no mention.

## Partnership outreach (NYC beachhead-within-the-beachhead)

The offer: free founding-family months for their clients + a `?c=` referral
code; both households get a free month when a referred family activates
(2 caregivers logging within 72h). Outreach is a personal, three-sentence
email from Adnan — who you are, why their clients specifically, the offer.
No mail-merge blasts; two per week, warm and specific.

*17 prospects verified 2026-07-19 (sites fetched, NYC service area confirmed). Two outreach emails a week, Tue/Thu, personally written.*

- **Well Supported Family — night nurse / newborn care agency (Brooklyn + Manhattan)**
  <https://www.wellsupportedfamily.com/brooklyn-ny-postpartum-doulas/>
  Certified Newborn Care Specialists and postpartum doulas doing overnight and 24/7 care across Brooklyn (explicitly Park Slope, Williamsburg, Crown Heights) and Manhattan — their whole business is the exact multi-caregiver handoff moment HAL exists for: an NCS leaves at 7am and the parents need to know what happened overnight. Contact: info@wellsupportedfamily.com, site inquiry form, IG @wellsupportedfamily.
  *Angle:* Your NCSs hand a night of feeds and wake-ups to groggy parents every morning — I'm a Brooklyn dad who built HAL, a baby log that lives in the family's iMessage thread, and I'd love to give your client families founding-family access so the overnight log is already in the chat when your specialist walks out the door.
- **Happy Family After — overnight doula & NCS agency (Manhattan)**
  <https://happyfamilyafter.com/locations/postpartum-care-for-manhattan-families/>
  Overnight and live-in postpartum doulas and newborn care specialists across Manhattan neighborhoods (UES, Chelsea, Tribeca, Village) plus NJ; they even run professional-development webinars for caregivers, so they think in terms of tools for their staff. Contact: info@happyfamilyafter.com, (732) 301-4131, contact form, IG @happyfamilyafter.
  *Angle:* You place live-in and overnight doulas into households where three adults are tag-teaming one newborn — I built HAL (a shared baby log that runs inside the family group chat, no app) for my own family, and a referral code for your placements would mean every caregiver on the rotation logs to one record from day one.
- **Nestling Care — night nurse agency (Manhattan + Brooklyn)**
  <https://www.getnestling.com/night-nurse-nyc>
  Background-checked, CPR-certified night nurses serving UES, Tribeca, Prospect Heights and Brooklyn, with twins/preemie specialization — multiples households are the heaviest multi-caregiver logging case there is. Very reachable: hello@getnestling.com, WhatsApp +1 (917) 304-7334, IG @get_nestling, contact form.
  *Angle:* For your twins and preemie families, feed tracking across a night nurse plus two parents is chaos in three different apps — I'm an NYC dad who built HAL to put the whole log in the family's existing group chat, and I'd love to offer your client roster free founding-family spots.
- **Moonstone Babies — overnight newborn care + doulas + IBCLC (Brooklyn/Manhattan/Queens)**
  <https://www.moonstonebabies.com/baby-night-nurse-in-nyc>
  Full-stack perinatal shop — overnight night doulas, postpartum doulas, and in-house IBCLC lactation consulting across Brooklyn, Manhattan, Queens and the Hamptons — so one partnership touches both the night-shift handoff and the feed-log-for-the-lactation-consult use case. Contact: site inquiry form (asks for due date / baby's age) and contact page.
  *Angle:* Your night doulas and your IBCLC both live off the same feeding log the parents are too tired to keep — I built HAL, a baby log that lives in the family's group chat, and gifting it to your clients would hand your team a clean overnight record at every visit.
- **Lullaby Baby Nurses — baby nurse agency (Manhattan + metro)**
  <https://lullabybabynurses.com/>
  Long-running baby nurse and night-nanny agency serving Manhattan, Westchester, Long Island and beyond, with specialty care for multiples, NICU grads and colicky babies — high-touch households that already employ round-the-clock caregivers. Contact: phones 212-804-7741 / 914-882-6641 and contact form at lullabybabynurses.com/contact/.
  *Angle:* Your baby nurses run weeks-long 24/7 rotations where the day book is still literally paper in a lot of homes — I'm a dad who built HAL to make the family group chat itself the baby log, and I'd love your nurses to try it free with a founding family or two.
- **NYC Birth Village Doulas — postpartum doula collective (NYC-wide)**
  <https://www.nycbirthvillage.com/>
  Vetted collective offering daytime and overnight postpartum doulas, lactation visits, and 0-4-month postpartum support groups; already plugged into Carrot/Progyny/Maven employer benefits, so they understand a partner-perk motion. Contact: hello@nycbirthvillage.com, contact form, IG @nycbirthvillage.
  *Angle:* Between your overnight doulas, your lactation visits, and your 0-4 month groups you meet families at every point where the log falls apart — I built HAL, the baby log that lives in the group chat, and founding-family codes for your clients would make your doulas' handoff notes land where the parents already are: iMessage.
- **Baby Caravan — birth & postpartum doula collective (NYC)**
  <https://www.babycaravan.com/>
  Established NYC doula collective matching families to birth, daytime and overnight postpartum doulas; Maven/Carrot-approved, which signals openness to partnership programs. Contact: contact form at babycaravan.com/contact, IG @babycaravan.
  *Angle:* You match families with overnight doulas whose first question each evening is 'how did today go?' — I'm an NYC dad who built HAL so the answer already lives in the family's group chat, and I'd love to include a free founding-family offer in your client welcome materials.
- **Brooklyn Birth Collective — doula + lactation team (Brooklyn)**
  <https://www.brooklynbirthcollective.com/>
  Team of doulas providing birth and postpartum support, childbirth education, and lactation services throughout NYC from a Brooklyn base — a community-rooted collective whose postpartum clients are exactly HAL's household. Contact: contact form at brooklynbirthcollective.com/contact plus a scheduling page.
  *Angle:* Your postpartum and lactation clients are juggling doula shifts, partner shifts, and grandma shifts — I built HAL, a baby log that runs in the family's existing iMessage thread, and I'd love to gift founding-family access through your collective so every caregiver writes to one record.
- **Essential Postpartum — postpartum doula team (Brooklyn, Manhattan, LIC)**
  <https://www.essentialpostpartum.com/our-team>
  Nine-doula team doing overnight and daytime postpartum care plus meal support across Brooklyn (they market Park Slope, Williamsburg, Greenpoint specifically), Manhattan, LIC and Queens — neighborhood-perfect for HAL's beachhead. Contact: contact form at essentialpostpartum.com/contact.
  *Angle:* Nine doulas rotating through Park Slope and Williamsburg homes means nine versions of handoff notes — I'm a local dad who built HAL to make the family group chat the single baby log, and your team could hand each new client a founding-family code as part of their welcome.
- **City Lactation — IBCLC group practice (Brooklyn, Manhattan, Queens)**
  <https://citylactation.com/>
  Ten-IBCLC practice doing home visits across Brooklyn (Williamsburg, Park Slope, Greenpoint per their team pages), Manhattan and Queens, in-network with Aetna/Cigna/UHC/Anthem — every consult starts with 'walk me through the last few days of feeds,' which is precisely the record HAL produces. Contact: hello@citylactation.com, 917-830-3153 (text OK).
  *Angle:* Every home visit starts with reconstructing the feed history from a sleep-deprived parent's memory — I built HAL, a baby log that lives in the family's group chat, and if your IBCLCs' clients had it, the last 72 hours of feeds would be one scroll away; happy to set your practice up with referral codes.
- **Shamina Rao / Brooklyn Lactation — IBCLC + Park Slope support group**
  <https://www.shaminarao.com/lactation>
  IBCLC doing in-home visits across Brooklyn, office visits in Windsor Terrace, and a bi-weekly support group in Park Slope — the support group alone is a room full of exactly HAL's founding families, in the beachhead neighborhood. Contact: inquiry form on site, IG @shaminarao.
  *Angle:* Your Park Slope group is full of parents trading tips on tracking feeds between partners and nannies — I'm a Park Slope-area dad who built HAL, a baby log that lives in the group chat, and I'd love to offer your group and home-visit clients free founding-family access (and get your honest IBCLC take on the feed log).
- **NYC Birth + Baby (Danielle Jackson) — IBCLC, classes & doula services (Manhattan/Brooklyn)**
  <https://nycbirthandbaby.com/lactation-consultant/>
  RN + IBCLC offering in-home lactation visits across Manhattan, Brooklyn and Queens plus private baby-care classes and birth doula work — she teaches new parents their systems for the fourth trimester, the ideal moment to introduce a shared log. Contact: info@nycbirthandbaby.com, 646-328-1933, online booking.
  *Angle:* You teach parents their newborn-care systems before the baby comes — I built HAL, the baby log that lives in the family's group chat, and it could be the tracking system you hand them in class, with a referral code so your families get founding-family status free.
- **Manhattan Birth — UWS lactation, childbirth ed & doula matching**
  <https://manhattanbirth.com/about-us/frequently-asked-questions/>
  Upper West Side hub combining childbirth education cohorts, lactation consultations in their UWS office, and a vetted find-a-doula platform — a single UWS partner that reaches expecting families right before the multi-caregiver scramble begins. Contact: support@manhattanbirth.com, contact form, IG @ManhattanBirth.
  *Angle:* Your Complete Childbirth cohorts graduate straight into the newborn haze where partner, doula and grandma all need to know when the last feed was — I'm an NYC dad who built HAL to keep that log in the family group chat, and your UWS cohorts would be perfect founding families.
- **Love You Forever Photo — in-home newborn photographer (Park Slope/Cobble Hill)**
  <https://loveyouforeverphoto.com/park-slope-newborn-photographer/>
  In-home studio-lighting newborn sessions marketed specifically to Park Slope, Cobble Hill, Carroll Gardens and Boerum Hill — photographers are inside HAL's target homes in weeks 1-3 and their client-gift bag is a natural referral-code channel. Contact: contact form at loveyouforeverphoto.com/contact/, 516-405-1206, IG @loveyouforeverphoto.
  *Angle:* You're in Park Slope living rooms during week two, when the feed schedule is chaos around your session — I'm a local dad who built HAL, a baby log that lives in the family's group chat, and a founding-family gift code in your client welcome kit would be a genuinely useful add-on to your sessions.
- **Danielle Terenzio — newborn & family photographer (Carroll Gardens/Park Slope/Williamsburg)**
  <https://www.danielleterenziofamily.com>
  Lifestyle newborn and family photographer explicitly covering Carroll Gardens, Park Slope, Cobble Hill, Brooklyn Heights and Williamsburg with in-home newborn sessions — same right-moment access, hyper-local to the beachhead. Contact: danielle@danielleterenziofamily.com, contact form, IG @danielleterenziofamily.
  *Angle:* Your in-home newborn sessions put you with brand-new Brooklyn families at their most sleep-deprived — I built HAL (a baby log that runs in the family's iMessage thread) for my own newborn, and I'd love to give your clients founding-family access as a session gift, with a code so you see the referrals.
- **Park Slope Parents — parent community organization (Brownstone Brooklyn)**
  <https://www.parkslopeparents.com/Local-Organizations/other-parenting-groups.html>
  The canonical Brownstone Brooklyn parents' organization: paid membership, 100+ specialty groups including in-person baby groups, nanny-hiring guides, and a heavily-used recommendations culture — a single relationship here reaches thousands of exactly-right households, and their nanny resources pages are a natural fit for a shared nanny/parent log. Contact: contact form on site, IG @parkslopeparents.
  *Angle:* PSP's baby groups and nanny guides are where Park Slope families figure out multi-caregiver logistics — I'm a member-neighborhood dad who built HAL, a baby log that lives in the group chat with the nanny, and I'd love to offer PSP members founding-family access and contribute an honest write-up on caregiver handoffs.
- **The Moms Groups (Renee Sullivan) — new-moms group organizer (Manhattan + Brooklyn)**
  <https://ce173.infusionsoft.app/app/page/newmomsgroup>
  Running facilitated six-week new-moms cohorts since 2008 across the East Side, West Side, Murray Hill, Brooklyn, Astoria and NJ (Fall 2026 registration live; many sections already full) — ten-mom cohorts of babies under six months are dense clusters of founding families, and Renee personally curates resources for them. Contact: Renee at 917-578-3733 and the program-coordinator email posted on the page; sign-up form on site. Note: site is a Keap landing page that loops for some fetchers, so lead with the phone number.
  *Angle:* Your six-week cohorts are ten moms all hitting the same 'who logged the last feed?' wall at the same time — I'm an NYC dad who built HAL, a baby log that lives in the family group chat, and I'd love to offer each cohort founding-family codes (and come answer questions honestly as the builder, not a pitch).

---

## Attribution codes (`?c=` registry)

`texthal.com/?c=<code>` puts the code in the sms prefill; HAL strips it and
records `acquisition_source` on the profile. Reddit rules mostly forbid
links — there, the product is mentioned by NAME only and attribution is
organic (that's fine; the funnel still shows `track_selected` volume).

| Code | Channel |
|---|---|
| `daddit` | the one r/daddit story post (profile link only) |
| `psp` | Park Slope Parents placement |
| `fbnanny` | Parents & Nannies of NYC (when biz-thread rules allow) |
| `doula-<name>` | each doula/night-nurse partner |
| `ibclc-<name>` | each lactation partner |
| `photo-<name>` | each newborn photographer |
| `nd-<zip>` | Nextdoor sponsorship probes |
| `pod-<show>` | podcast host-reads |
| `ig-<handle>` | nano-creator posts |

Weekly rollup (until the cohort dashboard lands): count
`onboarding.track_selected` events by `source` in the Railway logs, and
`acquisition_source` on profiles vs `first_log` / `second_caregiver_first_log`.

## Measurement

- **North star:** activated households (2+ caregivers logging within 72h),
  target ≥50% of new households; week 6 = 25, week 12 = 100 (bridge-capped).
- Per-channel: text-started → first_log → thread → activated; kill any paid
  probe >$40/activated household.
- Friday scorecard from: forum contributions (manual tally), funnel events
  (admin digest), `?c=` code counts.

## What we never do

Undisclosed promotion. Second accounts or personas. AI-written posts or
comments. Automated posting/voting/DMs. Fake reviews or seeded testimonials.
Pitching into grief or medical crisis threads. Competitor dunking. Paying
for placement that isn't labeled as such by the venue's own norms.
