---
{
  "description": "Summarize a YouTube video — channel, 3 bullets, verdict.",
  "keywords": ["youtube", "yt video", "summarize youtube", "what is this video"],
  "inputs": [
    {"name": "url", "description": "YouTube watch URL or youtu.be shortlink", "required": true}
  ]
}
---

A YouTube video was shared. Extract its content and reply in this exact
format (plain text, no markdown — this goes to iMessage):

Channel: <channel name>
Title: <video title>
Summary:
- <one short bullet>
- <one short bullet>
- <one short bullet>
Verdict: <one sentence — is this worth watching, your take>

How to do it:

1. Delegate to the browser agent with task = "navigate to {{url}} then content".
   The browser intercepts YouTube caption network requests and parses
   the transcript via several fallback strategies.
2. If transcript came back, use it for the summary bullets. If transcript
   is huge, focus on the first ~5 minutes worth and the closing minute —
   that's usually enough for a meaningful summary.
3. If `transcript_error` or `has_captions: false` is returned, do NOT
   retry with click/scroll/evaluate. Use the title, channel, and
   description that came back and say "no transcript available — here's
   what the description says: ..."

Keep it under ~600 characters. The user wants the gist, not a transcript dump.
