---
{
  "description": "Evening recap of the baby's day (naps, feeds, night sleep, bedtime) plus tomorrow's outlook, from the structured baby log. Designed to pair with a daily ~7:15pm cron to the family group chat.",
  "keywords": ["baby digest", "bazzy digest", "evening digest", "how did the baby do today", "baby recap", "daily baby summary"],
  "inputs": []
}
---

Produce the baby's evening digest.

Steps:

1. Call baby action=stats period=today — today's feeds, naps, totals, bedtime.
2. Call baby action=stats period=week — his recent pattern and any regression flags.
3. Compare today against the weekly pattern: total nap time vs typical, nap
   count, bedtime on schedule or not, anything notable (an extra-long nap, a
   skipped feed window, a very short catnap day).

Reply in this exact format (plain text, iMessage-friendly, ~450 chars max):

🌙 <baby name> today:
Sleep: <N naps totaling Xh Ym — list as "8:00 (40m), 11:34 (40m), 1:54 (1h05)">
Feeds: <N — times like "5:10a, 7:30a, 9:50a, 12:42p">
<Bedtime line: "Down for the night at 6:45 PM" — or "Not down yet" if no bedtime logged>

vs his pattern: <ONE short line — e.g. "lighter nap day than usual (2h05 vs ~3h)" or "right on his usual rhythm">

Tomorrow: <expected wake time and first-nap window from the weekly pattern, e.g. "expect a ~6:15 AM wake-up, first nap ~8:00">

If stats reports a possible sleep regression flag, add one final line starting
with ⚠️ stating it plainly and one practical suggestion.

If NO events were logged today at all, reply with exactly "..." (stay silent —
don't post an empty digest).

Do not add filler, praise, or questions. This is a calm end-of-day summary.
