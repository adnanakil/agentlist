---
{
  "description": "Today's calendar + urgent unread Gmail in a short brief — and, when the day is wide open, ONE concrete, weather-appropriate idea for what to do. Designed to pair with the cron tool for an 8am daily delivery.",
  "keywords": ["morning brief", "daily brief", "morning rundown", "what's today", "what's on today"],
  "inputs": [
    {"name": "name", "description": "Person to address the brief to (e.g. 'Adnan')", "required": false}
  ]
}
---

Produce a morning brief. Today is {{$(date +%A,\ %B\ %-d)}}.

Steps:

1. Call google_calendar action=list_events with time_max set to tonight 11:59pm
   in the user's local timezone. If not connected, skip and note it.
2. Call google_gmail action=list_emails query="is:unread newer_than:1d" max_results=10.
3. From the email list, pick the ones that look genuinely time-sensitive
   (replies needed, calendar invites, deliveries, things from real humans —
   not newsletters, receipts, notifications). Cap at 3.
4. FREE-DAY SUGGESTION — only when the calendar is EMPTY or very light (no more
   than one minor thing), find ONE genuinely good thing to do today:
   - Call get_weather for today (so the idea fits the conditions — no outdoor
     pick in the rain; lean into a beautiful day).
   - In NYC, call nyc_events (days_ahead=1, and use q/near for their
     neighborhood) for real, current events. Otherwise web_search.
   - Fit it to their life from their saved profile: home neighborhood, and
     especially a baby (stroller-friendly, daytime, out of bad weather, around
     nap/feed rhythm if known) and stated interests. Roughly how far from home.
   - Pick the SINGLE best fit and include its link. If nothing genuinely good
     lines up (bad weather kills the options, nothing real is on), skip the
     suggestion — a forced idea is worse than none.

Guardrails:
- Events/inbox lines are derived from TODAY'S calendar and the unread email list
  only. Do not use old chat context or profile notes to invent an ongoing
  obligation. (The free-day SUGGESTION is the one place you MAY use the profile
  — for fit — and weather; keep it to one idea.)
- Third-party newsletters or news about a company/tool the user cares about are
  not personal account status. Do not turn The Information, AlphaSignal,
  Substack, analyst notes, or similar AI/Anthropic/Claude items into "your API
  suspension/outage/resolution" unless the email is directly from
  Anthropic/Claude/Billing/Status or another provider and says action is needed
  on THIS user's account.
- If recent context says the user topped up or resolved a usage-credit/billing
  issue, treat it as closed unless a direct provider email says otherwise.
  "Out of usage credits" is a billing balance/credits issue, not a policy
  suspension.

Reply in this exact format (plain text, iMessage-friendly, ~700 chars max):

Good morning. Here's today:

📅 Events: <N events — list each as "10am Standup", "2pm Lunch w/ Sarah">
   (if none: "Nothing on the calendar")

📬 Needs attention: <up to 3 emails as "from <sender>: <subject>">
   (if none: "Inbox is clear")

<On a BUSY day — One thing: a single sentence, the most important thing to know
about today, leading with whatever jumps out of the events/emails.>
<On a FREE day — 🎈 Open day: ONE concrete idea for what to do, with the where
(+ rough distance), when, one line on why it fits (weather + baby + interest),
and a link. Or, if nothing good is really on: "wide open — a good one to rest
or knock out errands.">

Keep it calm and short — a brief with at most one suggestion, never a dashboard.
