# HAL — Google OAuth Verification Playbook

Goal: move HAL's Google OAuth app from "unverified" (100-user cap + scary warning
+ 7-day token expiry) to **verified + in production**, so strangers can connect
Gmail/Calendar safely.

What I (Claude) already built for you:
- **Privacy Policy** at `/privacy` and **Terms** at `/terms`, served by the
  orchestrator (`routes/legal.py`). They include Google's required **Limited Use**
  affirmation. Review the `TODO(owner)` fields (operator legal name, contact
  email, governing-law state) before submitting.

What only YOU can do (needs your Google account / a payment / a screen recording):
the console configuration, the domain, the demo video, and the security assessment.
Steps below, in order.

---

## Current app (from the code + Railway)

- **OAuth client:** `76038046231-...apps.googleusercontent.com` (real, configured)
- **Redirect URI:** `https://hal-orchestrator-production.up.railway.app/api/google/callback`
- **Scopes requested** (`services/google.py`):

| Scope | Tier | Verification burden |
|---|---|---|
| `openid`, `email` | none | none |
| `calendar.readonly` | sensitive | verification, no security audit |
| `calendar.events` | sensitive | verification, no security audit |
| `gmail.send` | sensitive | verification, no security audit |
| `gmail.readonly` | **restricted** | verification **+ CASA security assessment** |
| `gmail.compose` | **restricted** | verification **+ CASA security assessment** |

The two **restricted** Gmail scopes are what trigger the slow/costly part (CASA).
`gmail.readonly` powers inbox reading (heartbeat, unread summaries, first-win scan);
`gmail.compose` powers drafts. See "Decision: scopes" below.

---

## ⚠️ Blocker 0 — point tryhal.xyz at HAL, then verify it

Google will **not** verify an app whose homepage/privacy/redirect live on
`*.up.railway.app` (you can't prove you own `railway.app`). Domain: **tryhal.xyz**.

**Already done (by Claude):** `tryhal.xyz` + `www.tryhal.xyz` are attached to the
hal-orchestrator Railway service (the stale `tryhal.com` entries were removed).

**You do — set DNS at Namecheap** (Domain List → tryhal.xyz → Advanced DNS):
1. DELETE the existing `CNAME www → parkingpage.namecheap.com`.
2. DELETE the existing `URL Redirect @ → http://www.tryhal.xyz/`.
3. ADD `CNAME` — Host `www` — Value `bk523lyv.up.railway.app`.
4. ADD `ALIAS` — Host `@` — Value `7u4dul25.up.railway.app`.
   (Namecheap BasicDNS has an "ALIAS Record" type that works at the root. If it's
   not offered, keep an apex `URL Redirect @ → https://www.tryhal.xyz` and treat
   `www.tryhal.xyz` as canonical instead.)

Railway auto-issues the SSL cert once DNS resolves (minutes to a couple hours).
`/privacy` and `/terms` already work at the Railway URL; after DNS they resolve at
`https://tryhal.xyz/privacy` too.

**Then verify ownership** in **Google Search Console**
(https://search.google.com/search-console): add `tryhal.xyz` as a Domain property
and complete the TXT-record verification (another record at Namecheap). This is
what lets you list it as an authorized domain on the consent screen.

**Then move the OAuth redirect onto the domain:** in the Cloud Console OAuth
client, add `https://tryhal.xyz/api/google/callback` to Authorized redirect URIs
(keep the Railway one too), then set Railway `GOOGLE_REDIRECT_URI` to the new
value. Do this only after DNS + SSL are live, or the connect flow breaks.

---

## ⚠️ Blocker 1 — the 7-day token trap (fix regardless of verification)

An OAuth app in **"Testing"** publishing status issues refresh tokens that
**expire after 7 days** — HAL would silently lose Google access for every user
each week. Fix: in Google Cloud Console → APIs & Services → OAuth consent screen,
set **Publishing status → In production**. (You can be "In production" while
verification is still pending; users just see the unverified warning until it's
granted. Restricted scopes still cap you at 100 users until verified.)

---

## Decision: scopes (pick before submitting)

- **Keep full Gmail (recommended if inbox features matter):** submit all scopes,
  do the CASA assessment. HAL keeps every feature. Slower.
- **Launch lighter, skip CASA:** drop `gmail.readonly` + `gmail.compose`, keep
  `calendar.*` + `gmail.send`. Only sensitive scopes → verification but **no
  security assessment** → much faster/cheaper. HAL loses inbox reading + drafts.
  (Edit `SCOPES` in `services/google.py` and redeploy; existing users reconnect.)

Google reviewers reject apps that request more than they demonstrably use, so
request exactly the set you ship.

---

## Console steps (APIs & Services → OAuth consent screen)

1. **User type:** External. **Publishing status:** In production (see Blocker 1).
2. **App info:** name "HAL", user support email, an app logo (120×120 PNG),
   app homepage `https://tryhal.xyz`, privacy `https://tryhal.xyz/privacy`,
   terms `https://tryhal.xyz/terms`.
3. **Authorized domains:** `tryhal.xyz` (must be Search-Console-verified).
4. **Scopes:** add exactly the set you chose above.
5. **Submit for verification.** For each sensitive/restricted scope, paste a
   justification (drafts below). Attach a **demo video** (script below).

### Scope justifications (paste-ready)

- **calendar.readonly / calendar.events —** "HAL is a text-message assistant. When
  the user asks about their schedule ('what's on today?') HAL reads their primary
  calendar to answer, and when the user asks HAL to schedule something it creates
  an event. Access is only ever in direct response to the user's request in chat."
- **gmail.readonly —** "When the user asks HAL to check, summarize, or find email
  ('any important unread?', 'what did the landlord say?'), HAL reads the relevant
  messages to answer in chat. It also powers an opt-in proactive check that flags
  genuinely time-sensitive email. Email content is used only to respond to the
  user and is never used for ads or model training."
- **gmail.compose / gmail.send —** "When the user asks HAL to draft or send an
  email, HAL creates the draft or sends it. Sending always requires the user to
  confirm the exact recipient, subject, and body in chat first."

### Demo video (record with QuickTime/Loom; ~2–3 min, no login shown)

1. Show `tryhal.xyz` (homepage) and the `/privacy` page with the Limited Use line.
2. In Messages, text HAL "connect google" → tap the link → the Google consent
   screen (show the scopes) → approve → the "connected" confirmation.
3. Demonstrate each scope: "what's on my calendar today?" (calendar.readonly);
   "add lunch with Sam tomorrow at 1" (calendar.events); "any urgent unread
   email?" (gmail.readonly); "draft a reply saying I'll be 10 min late" then
   "send it" with the confirmation step (gmail.compose/send).
4. Show "disconnect google" revoking access.

---

## CASA security assessment (only if keeping restricted Gmail scopes)

Restricted scopes require an annual third-party assessment (CASA — Cloud
Application Security Assessment) before production access to many users.

- Google emails you a link to an authorized assessor after you submit.
- **Tier 2** (typical for restricted scopes) is a paid lab assessment; budget for
  cost + a few weeks. There's a self-guided scan tier for some cases.
- You'll attest to secure data handling. HAL already helps here: OAuth tokens are
  Fernet/AES-256 encrypted at rest, per-user isolation, TLS in transit, deletion
  paths ("/clear", "disconnect google").

---

## Limited Use compliance to confirm (important)

Under the Limited Use policy you may transfer Google user data to service
providers only to provide user-facing features, and **not** for model training.
HAL sends message content (which can include email/calendar data) to AI providers
to generate replies. Before submitting, confirm each provider you actually route
Google-user-data turns through does **not** train on API data:
- Google Gemini API and Anthropic API: do not train on API data by default. ✅
- If you route any Google-data turns through **GLM/Z.ai** (`GEMINI_*_MODEL=glm-*`)
  or OpenAI embeddings on email text, confirm their API data-use terms — or keep
  Google-connected users' turns off those providers. The privacy policy states
  providers don't train on your data, so this must be true.

---

## Order of operations

1. Point tryhal.xyz at HAL + verify it in Search Console (Blocker 0).
2. Set publishing status → In production (Blocker 1).
3. Fill in the `TODO(owner)` fields in `routes/legal.py`; redeploy.
4. Pick your scope set; trim `SCOPES` if launching lighter.
5. Configure consent screen (homepage/privacy/terms/domains/scopes) + submit with
   justifications + demo video.
6. If keeping restricted scopes, complete CASA when Google sends the link.
