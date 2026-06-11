---
{
  "description": "Summarize a TikTok video — creator, 3 bullets, verdict.",
  "keywords": ["tiktok", "video summary", "what is this video", "summarize tiktok"],
  "inputs": [
    {"name": "url", "description": "TikTok video URL (full or shortlink t/...)", "required": true}
  ]
}
---

A TikTok was shared. Extract its content and reply in this exact format
(no markdown, plain text only — this goes back to iMessage):

Creator: <name or @handle>
Summary:
- <one short bullet>
- <one short bullet>
- <one short bullet>
Verdict: <one sentence — your take, agree/disagree/skeptical/useful>

How to do it:

1. Delegate to the browser agent with task = "navigate to {{url}} then content".
   The browser already knows how to handle TikTok shortlinks and pulls the
   transcript from the rehydration data when captions exist.
2. If the result has `transcript_error` or `has_captions: false`, do NOT
   keep trying. Use the title and author that came back and answer with
   just those — say "no captions, here's what the description says" if
   you can't summarize the actual content.
3. If the shortlink failed to resolve (bot wall), say so plainly: "TikTok
   is blocking us from loading the video right now — try again later or
   send the @user/video/<id> link directly."

Keep it under ~500 characters total. No preamble, no "here you go".
