# HAL — Goals

*The north star. architecture.md says how HAL works; this file says why it
exists and what to optimize for. When a feature decision is unclear, resolve
it against this file. Last grounded: 2026-07-10.*

## The idea

**Every person gets a personalized agent that manages the real world for
them.** Not a chatbot, not an app to open — a number you text, that texts
back, and that quietly handles logistics: reminders that fire at the right
moment, a grocery list that becomes a filled cart, a flight watched, a
parking ticket found, a baby's schedule tracked across two parents and a
nanny, an inbox flagged only when something actually needs you.

It grows with you. And it lives where your life is coordinated — including
the group chats.

## The three pillars

### 1. It manages the real world

HAL is judged by outcomes, not answers. "Here's a link that adds all ten
items to your cart" beats a paragraph about smoothie ingredients; a reminder
that fires beats advice about remembering.

- **Fewest taps to done.** Every reply should move a real-world task to the
  next state with minimal user effort. One tappable link beats ten; done
  silently beats done with fanfare.
- **When the official rail doesn't exist, find the closest legitimate one.**
  Amazon has no cart API and Instacart closed theirs — so HAL builds
  documented cart links and search links instead of refusing. Auto-pay is
  blocked by reCAPTCHA — so HAL hands over the exact summons and payment
  link. Degrade usefully, never dead-end. (grocery fallback, parking
  hand-off)
- **Authentication stays on the user's device.** HAL never holds user
  credentials or payment methods. The tap that commits money or identity
  happens in the user's own app, with their own session. Family-only
  experiments on our own hardware are the one exception, and they never
  become product features.
- **Irreversible actions are authorized in code, not by the model.**
  Sending messages, spending money, contacting other people — server-side
  policy, confirmation tokens, derived from the user's actual words.
  (action_policy)

### 2. It grows and learns with each person

The 100th day with HAL should feel meaningfully better than the 1st, without
the user ever filling out a form.

- **Learn by observing, not interrogating.** Facts come from conversation,
  witnessed group context, and enrichment — asks are rationed (two per fact,
  then infer silently). Nagging is a trust-killer; the Joyce name-nag cost
  three weeks of goodwill for one field. (ask decay, profile_enricher)
- **Memory is per-person and earns its keep.** Profiles, conversation
  history, skills, watches, and preferences are siloed per user. What HAL
  learns about you shapes your briefs, your reminders, your tone — nobody
  else's.
- **Self-improvement is real but gated.** The nightly reflection loop mines
  failures and proposes playbook rules and skills; anything global goes
  through human review before it touches other users. Growth without
  regression. (learning quarantine, growth_auto_publish)
- **Capabilities reveal themselves in context.** No feature dumps. When you
  paste a TikTok, HAL fact-checks it and mentions it can keep doing that.
  The best onboarding is a first message answered brilliantly. (value-first
  onboarding, first-win)

### 3. It works where your people are — group chats

Life is coordinated in groups: the family thread, the trip thread, the
tickets thread. An agent that only works 1:1 misses where decisions actually
happen.

- **Restraint is the group superpower.** In a group, HAL speaks when
  addressed or when it has something genuinely high-value; silence is the
  default. "Stfu hal" is a product failure with a name. (tact gate,
  group_quiet)
- **Shared state, per-person view.** The baby log works because two parents
  and a nanny write to one truth and each gets the view they need. That
  pattern — shared log, personal lens — is the template for group features.
- **Group context flows one way.** What HAL witnesses in a group can inform
  that member's own 1:1 (the catalog, recall) — but never group→group, never
  DM→group, never another member's private data. Membership means "spoke
  there," witnessed, not claimed. (group_catalog, one-way valve)
- **Groups are the growth loop.** People meet HAL in a group, then text it
  directly. The warm start ("I'm HAL from the family chat") is the bridge —
  every group HAL serves well is an onboarding surface.

## Non-negotiables

These hold even when they cost engagement or a feature:

1. **Never fake success.** "Logged ✅" only after the write is verified.
   A blank brief beats an apology; an honest "couldn't pin it down" beats a
   hallucinated answer — but never the same punt twice in a row.
2. **Nothing new → send nothing.** Proactive features exist to save
   attention, not consume it. Heartbeat spam is the #1 churn risk in the
   production data; when in doubt, stay quiet.
3. **Trust compounds; farm it, not engagement.** The trust peak in all of
   production was HAL saying "I've got the log covered — go take care of
   him." Optimize for being relied on, not talked to.
4. **Privacy silos are structural, not prompt-enforced.** One-way valves,
   membership gates, and scope checks live in code.
5. **Fail without leaking.** No raw errors, no internal status strings, no
   provider names in user-facing text.

## What HAL is not

- Not a general-purpose chatbot with tools bolted on.
- Not an app — iMessage is the whole interface; a link is the deepest UI.
- Not an engagement product — no streaks, no re-engagement pings, no
  notification farming.
- Not a credential vault — it never asks for, stores, or replays user
  passwords or payment methods.

## Where this stands (2026-07)

Core loop live for ~18 users (family as the proving ground): tools for the
real world (weather w/ failover, places, calendar+email, reminders, watches,
baby care with visual cards, parking, grocery links, NYC events, fact-check
via browser), proactive systems (morning brief, heartbeat, follow-ups) behind
cooldowns and gates, reliability foundations (idempotent inbound, durable
outbox, action policy, worker leadership), self-learning behind a review
queue, group catalog with warm-start onboarding, Stripe billing, and a
security posture ready for the CASA assessment (Google verification in
flight).

The near-term arc: make onboarding convert (funnel is now instrumented),
make proactive sends impeccable (cadence discipline), make the baby log
write-verified, harden the #1 use case (social-video fact-check), and keep
adding real-world rails as plugins (the grocery tool was the first drop-in).

## The test for any new feature

1. Does it move a real-world task closer to done with fewer taps?
2. Does it make HAL fit this person better next week than this week?
3. Does it respect the room — restraint in groups, silos between people?
4. Would we still ship it if it sent fewer messages, not more?

Two or more "no"s: don't build it.
