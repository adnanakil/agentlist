---
{
  "description": "Today's calendar + urgent unread Gmail in a 4-line brief. Designed to pair with the cron tool for an 8am daily delivery.",
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

Reply in this exact format (plain text, iMessage-friendly, ~600 chars max):

Good morning. Here's today:

📅 Events: <N events — list each as "10am Standup", "2pm Lunch w/ Sarah">
   (if none: "Nothing on the calendar")

📬 Needs attention: <up to 3 emails as "from <sender>: <subject>">
   (if none: "Inbox is clear")

One thing: <a single sentence — the most important thing for them to know
about today. If something jumps out from the events or emails, lead with
that. Otherwise: "you're set, have a good one">

Do not add weather, news, or anything not derived from calendar/email.
This is a calm brief, not a dashboard.
