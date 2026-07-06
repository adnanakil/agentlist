# HAL Feature Plan — Growth to Real Users

**Date:** 2026-07-05 · **Horizon:** next 4–6 weeks · **Direction:** make HAL viable for strangers, not just friends & family.

---

## 1. Market snapshot (July 2026)

What the research says about how people actually use AI agents day-to-day:

**Adoption is mainstream, and daily.** Consumer GenAI use hit 73% (up from 45% in early 2024); 32% of consumers use AI every day. Anthropic's Economic Index shows personal use (scores, product comparisons, home stuff) rose from 35% → 42% of Claude.ai conversations, and full-task delegation jumped from 27% → 39% of usage — automation now exceeds augmentation.

**The top consumer jobs-to-be-done** (in rough order of prevalence):
1. Pre-purchase research / shopping comparison — 61% of consumers, the #1 use case
2. Answering texts and emails
3. Travel planning — and notably high trust: 70% would let an agent book flights, 65% hotels
4. Financial questions
5. Recipes (19%), medical advice (16%), life decisions (15%)

**The 2026 dividing line is proactivity.** Reviewers consistently separate "chatbots" from "assistants" by whether the product stays active in the background — checking calendar, monitoring email, texting you when something needs attention. Gemini Spark (24/7 agentic, Gmail-integrated) and "Daily Brief" features are the flagship examples. HAL's heartbeat + watch architecture is exactly this — it's a differentiator to double down on, not a gap.

**Trust is the constraint, not capability.** Trust is falling as usage rises: 56% won't let an AI shop for them at all, 24% demand approval on every transaction, 90% distrust AI with their data. Top churn drivers: hallucinated actions ("I set up a tracker" that never fires — the exact confabulation the watch tool was built to kill), invented policies, weak escalation, sycophancy, and unclear data handling.

**Implication for HAL:** the wedge is *proactive, trustworthy, iMessage-native assistance* on the proven jobs (brief-me, watch-this, plan-travel, research-this-purchase). Growth work should remove distribution caps and make the first five minutes undeniable — the capability set is largely already there.

---

## 2. Where HAL stands

**Already shipped (don't rebuild):** watch/notify-when, sports scores, places, weather, travel time, trips, Resy, Google Calendar (r/w) + Gmail (read), memory/profiles/reminders, heartbeat anticipation checks, first-win moment after OAuth, group observations, usage caps + Stripe pay link, nightly growth loop with graded turns and a feature backlog.

**Growth blockers, in order of severity:**
1. **Distribution ceiling — the single MacBook iMessage bridge.** One consumer Mac, AppleScript delivery, cron watchdog, password in a doc. It's a SPOF, it can't scale past trivial volume, and it's the one piece a stranger's experience physically depends on.
2. **Google OAuth is unverified.** 100-user hard cap, scary consent screen, 7-day token expiry (users silently lose calendar/Gmail weekly). Playbook already written in `GOOGLE_VERIFICATION.md`; CASA assessment required because of `gmail.readonly`.
3. **No acquisition loop.** No way for a happy user to bring the next user.
4. **No funnel instrumentation.** The growth loop grades quality, but nobody can answer: how many new silos this week, what % reached first-win, D1/D7 retention, free→paid conversion.

---

## 3. The plan (4–6 weeks)

### Workstream A — Unblock distribution (weeks 1–3) · *highest priority*

**A1. Harden the bridge for real users (week 1).**
- Move the bridge to a dedicated always-on Mac mini (or hosted Mac, e.g. MacStadium); keyed SSH, no passwords in docs.
- Bridge health endpoint + orchestrator-side alerting: if no bridge poll in N minutes, text the admin via fallback (see A2). Today a dead bridge is silent total outage.
- Outbound delivery queue in Postgres (currently side_messages are lost if AppleScript fails mid-send): persist → send → ack.

**A2. SMS fallback channel via Twilio (weeks 2–3).**
- A second transport with the same `/api/message` contract: inbound webhook + outbound API. No bridge, no Mac, infinitely scalable, and Android users become reachable.
- Channel picker per silo: iMessage if the bridge serves that number, else SMS. This also becomes the outage fallback for A1.
- Explicitly *not* building: Sendblue/LoopMessage-style unofficial iMessage APIs (ToS + reliability risk) — revisit only if SMS conversion is poor.

**A3. Google verification (owner-led, start week 1 — long external timeline).**
- Execute `GOOGLE_VERIFICATION.md`: console config, domain, demo video, submit CASA. Claude-side artifacts (privacy/terms with Limited Use language) are done; fill the `TODO(owner)` fields.
- Until verified, add a token-refresh nudge: when a token is ~1 day from expiry, HAL proactively sends the reconnect link instead of failing silently.

### Workstream B — Nail the first five minutes (weeks 2–4)

**B1. Value before OAuth (week 2).** Onboarding currently collects (name → tz → home → work → Google) before demonstrating. Restructure: after name + home, immediately do something visibly useful with zero permissions (weather + commute + "want me to watch tonight's game?"), *then* ask for Google with a concrete promise ("connect and I'll brief you every morning on your actual day").
- Measure: time-to-first-win, drop-off per onboarding step.

**B2. Morning Brief as a first-class, promised feature (weeks 2–3).** The market's proven retention hook, and HAL has every ingredient (calendar, Gmail read, weather, trips, reminders, watches, sports). One scheduled internal turn per silo at a user-chosen time producing a single tight message. Offered at onboarding, on by default after Google connect, one-word snooze/stop. Distinct from heartbeat (reactive anticipation) — this is a predictable daily ritual, which is what builds the habit.

**B3. Purchase-research + price-watch pattern (week 4).** #1 consumer use case, and mostly prompt/playbook work: make "should I buy X / find me the best Y" reliably produce a comparison, and wire "tell me if it drops below $Z" into the existing watch tool. Zero new infrastructure; high perceived magic.

### Workstream C — Trust mechanics (weeks 3–4)

**C1. Approval gates on consequential actions.** Anything that books, sends, or spends (Resy, future actions) requires an explicit confirm message, always. Cheap to enforce in the tool layer; aligns with the 24%-approve-everything cohort and protects against the worst failure mode press-wise.

**C2. Receipts.** After any multi-step action, one compact "what I did" line (e.g. "Booked Lilia, 7:30pm, party of 2 — confirmation in your email"). Kills the "did it actually happen?" doubt that the confabulation era created.

**C3. Plain-language privacy answer.** One paragraph HAL can say verbatim when asked "what do you do with my data" (grounded in the /privacy page), plus `forget me` → full silo deletion. 90% of consumers distrust AI with data; being crisply good at this answer is differentiating.

### Workstream D — Acquisition loop (weeks 4–5)

**D1. Group-chat as the growth surface.** HAL already lives in groups. When a non-user in a group interacts with HAL meaningfully, HAL DMs a one-line invite ("I can do this for you directly — text me anytime"). Rate-limited, once per person ever. Groups are the only viral surface iMessage gives us — use it.

**D2. Referral mechanic.** "Introduce me to a friend" → both get bonus free messages (extends existing usage-cap machinery). Trackable via a signed ref in the intro link/contact card.

**D3. Shareable artifact moments.** When HAL produces something inherently shareable (trip plan, comparison table), offer a clean web page link (page-creator exists in the agent stable) with subtle "made by HAL" attribution.

### Workstream E — Measure the funnel (week 5–6, thin slice earlier)

- New-silo events: created → onboarded → google_connected → first_win → D1 active → D7 active → paid. Store as plain rows; surface weekly cohort table in the existing admin digest/dash.
- Define activation = first_win within 24h. Everything in Workstream B gets judged against this number.
- Free-tier tuning: verify `free_message_limit` is generous enough that users hit the habit before the paywall (brief + heartbeat are unmetered — good; keep it that way).

---

## 4. Sequencing summary

| Week | Ship |
|---|---|
| 1 | A1 bridge hardening · A3 start Google verification · E thin event logging |
| 2 | B1 onboarding restructure · A2 Twilio inbound/outbound |
| 3 | B2 Morning Brief · A2 channel picker + fallback · C1 approval gates |
| 4 | B3 purchase/price-watch · C2 receipts · C3 privacy answer · D1 group invites |
| 5 | D2 referrals · E funnel dashboard |
| 6 | D3 shareable pages · buffer / verification follow-through |

## 5. What we're deliberately NOT doing yet

- Unofficial iMessage API providers (ToS risk) — SMS is the scale path for now.
- Gmail *send* (dropped from scopes 2026-07-03; keeps CASA scope minimal — revisit post-verification).
- WhatsApp/Telegram channels — after SMS proves the multi-transport abstraction.
- Autonomous purchasing — market data says users don't want it (56% refuse outright); approval-gated actions only.

## 6. Risks

- **Google verification timeline is external and slow (CASA can take weeks–months).** Mitigation: token-refresh nudge + unverified-screen coaching in onboarding; start immediately.
- **Bridge remains a SPOF until A2 lands.** Mitigation: A1 alerting first week.
- **SMS costs money per message.** Mitigation: usage caps already exist; meter SMS silos identically.

---

### Market sources

- [Prophet — 2026 AI-Powered Consumer Report](https://prophet.com/2026/04/the-2026-ai-powered-consumer-report/)
- [Forrester — The State of GenAI and Consumers for 2026](https://www.forrester.com/blogs/the-state-of-genai-and-consumers-for-2026/)
- [YouGov — How do Americans use AI in 2026?](https://yougov.com/en-us/articles/54591-reality-checks-talkshow-humanx-ai-taylor-lorenz-gina-king)
- [Anthropic Economic Index — reports](https://www.anthropic.com/economic-index)
- [Microsoft 2026 Work Trend Index](https://www.microsoft.com/en-us/worklab/work-trend-index/agents-human-agency-and-the-opportunity-for-every-organization)
- [Zapier — Best AI personal assistant apps 2026](https://zapier.com/blog/ai-personal-assistant/)
- [TechCrunch — Gemini Spark, 24/7 agentic assistant](https://techcrunch.com/2026/05/19/google-introduces-gemini-spark-a-24-7-agentic-assistant-with-gmail-integration/)
- [McKinsey — State of AI trust in 2026](https://www.mckinsey.com/capabilities/tech-and-ai/our-insights/tech-forward/state-of-ai-trust-in-2026-shifting-to-the-agentic-era)
- [Contentgrip — AI trust drops as usage rises (Fractl 2026)](https://www.contentgrip.com/ai-trust-search-2026/)
- [Malwarebytes — 90% don't trust AI with their data](https://www.malwarebytes.com/blog/privacy/2026/03/90-of-people-dont-trust-ai-with-their-data/)
- [Ringly — 45 AI agent statistics 2026](https://www.ringly.io/blog/ai-agent-statistics-2026)
