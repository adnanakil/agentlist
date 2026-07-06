"""Tool definitions in Gemini function-calling format."""

from __future__ import annotations

# --------------------------------------------------------------------------- #
# Main orchestrator tools
# --------------------------------------------------------------------------- #

MAIN_TOOLS: list[dict] = [
    {
        "function_declarations": [
            {
                "name": "delegate",
                "description": (
                    "Delegate a task to a specialist agent. "
                    "Agents: research (web search, news, factual questions), "
                    "texting (send iMessages), "
                    "brainstorm (creative thinking, analysis)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agent": {
                            "type": "string",
                            "description": "Agent name: research, texting, brainstorm",
                        },
                        "task": {
                            "type": "string",
                            "description": "Clear description of the task for the agent",
                        },
                        "context": {
                            "type": "string",
                            "description": "Additional context: URLs, phone numbers, background info",
                        },
                    },
                    "required": ["agent", "task"],
                },
            },
            {
                "name": "current_time",
                "description": "Get the current date and time.",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "memory",
                "description": (
                    "Remember or recall information. Actions: remember, recall, list. "
                    "Scoped to the current chat's silo: a user's private memory in "
                    "1:1, the group's shared memory in group chats (never a member's "
                    "private memories)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "description": "remember, recall, or list",
                        },
                        "content": {
                            "type": "string",
                            "description": "What to remember or search for",
                        },
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "baby",
                "description": (
                    "Structured baby tracking — THE tool for all baby care events "
                    "and questions. Actions: log (record feed/nap_start/wake/"
                    "bedtime/tummy_time/diaper — returns the updated forecast and "
                    "auto-sets standing-preference reminders), forecast (next "
                    "wake/nap/feed/bedtime predicted from the baby's OWN recent "
                    "pattern), stats (today/yesterday/week summary + patterns + "
                    "regression flags), recent (raw recent events), undo (remove "
                    "a mislogged event), setup (first-time: create the baby "
                    "profile for this chat), configure (auto-reminder prefs, nap "
                    "cap, routines like 'tummy time 30min after feeds', "
                    "birthdate). The event log is shared across the family "
                    "(parents' DMs + family group chat). Use this INSTEAD of "
                    "memory for baby events."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "log", "forecast", "stats", "recent",
                                "undo", "setup", "configure",
                            ],
                        },
                        "kind": {
                            "type": "string",
                            "description": (
                                "For log: feed, nap_start, wake, bedtime, "
                                "tummy_time, diaper, or note. Use bedtime for "
                                "down-for-the-night, nap_start for daytime sleep, "
                                "wake for ANY wake-up."
                            ),
                        },
                        "time": {
                            "type": "string",
                            "description": (
                                "For log: when it happened — ISO timestamp WITH "
                                "offset (e.g. 2026-06-11T13:54:00-04:00). Omit "
                                "for 'just now'. The user often reports a past "
                                "clock time ('he slept at 8') — convert it."
                            ),
                        },
                        "note": {"type": "string", "description": "Optional detail for log"},
                        "period": {
                            "type": "string",
                            "description": "For stats: today, yesterday, or week",
                        },
                        "baby_name": {"type": "string", "description": "For setup"},
                        "baby_birthdate": {
                            "type": "string",
                            "description": "For configure: YYYY-MM-DD",
                        },
                        "nap_cap_minutes": {
                            "type": "integer",
                            "description": (
                                "For configure: nudge if a nap runs past this "
                                "(0 disables)"
                            ),
                        },
                        "auto_reminders": {"type": "boolean", "description": "For configure"},
                        "auto_wind_down": {"type": "boolean", "description": "For configure"},
                        "auto_feed_prep": {"type": "boolean", "description": "For configure"},
                        "add_routine": {
                            "type": "object",
                            "description": (
                                "For configure: {after: <event kind>, offset_min: "
                                "<minutes>, text: <reminder text>} — e.g. tummy "
                                "time 30 min after each feed"
                            ),
                            "properties": {
                                "after": {"type": "string"},
                                "offset_min": {"type": "integer"},
                                "text": {"type": "string"},
                            },
                        },
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "get_weather",
                "description": (
                    "Get current conditions + a short forecast (°F) for a "
                    "location. Call this ONLY when the task is weather-relevant — "
                    "planning an outing, what to wear, a stroller walk, whether to "
                    "stay in. Don't call it otherwise. Defaults to New York, NY. "
                    "Returns a daily summary AND an hourly 'Rain timing' line — "
                    "for a plan, reason from the rain timing for the ACTUAL hours, "
                    "not the daily % (which is a whole-day max often driven by "
                    "overnight rain)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "string",
                            "description": "City/neighborhood, e.g. 'New York, NY' or 'Brooklyn'",
                        },
                        "days": {
                            "type": "integer",
                            "description": "Forecast days (1-7, default 3)",
                        },
                    },
                },
            },
            {
                "name": "sports_score",
                "description": (
                    "Live/today's scores from ESPN (no key, deterministic). Use "
                    "for 'what's the score', 'did the Knicks win', and as the "
                    "check for any score-related watch condition — more reliable "
                    "than web_search for scores."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "league": {
                            "type": "string",
                            "description": (
                                "nba, wnba, ncaab/cbb, nfl, ncaaf/cfb, mlb, nhl, "
                                "epl, laliga, mls, ucl, worldcup (FIFA World Cup / "
                                "international) (default nba)"
                            ),
                        },
                        "team": {
                            "type": "string",
                            "description": "Optional team name/abbr to filter to one game, e.g. 'Knicks'",
                        },
                    },
                },
            },
            {
                "name": "watch",
                "description": (
                    "Notify the user ONCE when a condition becomes true, then "
                    "stop — staying silent until then. For 'let me know if/when "
                    "X happens' (a lead change, a price drop, a restock, a game "
                    "result). If you promise to alert them, you MUST create a "
                    "watch — never claim to be watching without one. Distinct "
                    "from schedule (runs on a clock) and set_reminder (re-sends "
                    "static text). 'stop watching' → action=cancel."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "description": "create, list, or cancel",
                        },
                        "condition": {
                            "type": "string",
                            "description": (
                                "What to watch for, in plain language, e.g. "
                                "'the Knicks take the lead' or 'the PS5 is back in stock at Best Buy'"
                            ),
                        },
                        "check_prompt": {
                            "type": "string",
                            "description": "Optional explicit instruction for how to check (defaults to the condition).",
                        },
                        "notify": {
                            "type": "string",
                            "description": "Optional message to send when it fires (defaults to 'Heads up — <condition>').",
                        },
                        "poll_every_sec": {
                            "type": "integer",
                            "description": "How often to re-check (min 90; default 150).",
                        },
                        "expires_in_min": {
                            "type": "integer",
                            "description": (
                                "Give up after this many minutes — set it to the "
                                "realistic window (a game ~180, a restock maybe a day). Default 360."
                            ),
                        },
                        "max_polls": {
                            "type": "integer",
                            "description": "Hard cap on checks (default 60).",
                        },
                        "job_id": {
                            "type": "string",
                            "description": "For cancel: the watch id (omit to cancel all in this chat).",
                        },
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "travel_time",
                "description": (
                    "Real travel time + distance between two places (Google Routes). "
                    "drive is LIVE-TRAFFIC-aware (shows current vs typical, so you can "
                    "say 'leave 15 min early'); transit returns real lines and departure "
                    "times. Use for ANY 'how long to get there / when should I leave' "
                    "question and for travel legs in day plans — never estimate from "
                    "memory or web_search."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "origin": {
                            "type": "string",
                            "description": "Start address or place, e.g. 'Chelsea, Manhattan' or '123 W 23rd St, NYC'",
                        },
                        "destination": {
                            "type": "string",
                            "description": "End address or place",
                        },
                        "mode": {
                            "type": "string",
                            "description": "drive (default, traffic-aware), walk, transit, bicycle",
                        },
                        "departure_time": {
                            "type": "string",
                            "description": "Optional future ISO time to leave (drive/transit), e.g. 2026-06-12T17:30:00-04:00. Omit for 'leave now'.",
                        },
                        "arrival_time": {
                            "type": "string",
                            "description": "Optional ISO time to arrive by (transit only) — finds the train/bus that makes it.",
                        },
                    },
                    "required": ["origin", "destination"],
                },
            },
            {
                "name": "places",
                "description": (
                    "Find real, current nearby places (Google Places). Text search like "
                    "'coffee shops near Fort Greene Brooklyn' or 'ramen open now in "
                    "Chelsea' returns name, rating + review count, price ($–$$$$), LIVE "
                    "open/closed status, address, phone, and a Google Maps link. Use this "
                    "for ANY 'near me / open now / find a spot / best X around here' "
                    "question instead of web_search — it's live and structured. Pass the "
                    "neighborhood/city in the query; set open_now to filter to what's open."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": (
                                "What + where, e.g. 'coffee shops near Fort Greene "
                                "Brooklyn' or 'best tacos in Austin'. Include the "
                                "neighborhood/city."
                            ),
                        },
                        "open_now": {
                            "type": "boolean",
                            "description": "Only return places open right now.",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "How many to return (1-8, default 5).",
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "profile",
                "description": (
                    "Read or update the user's persistent profile — a markdown doc "
                    "of STABLE facts and preferences (home neighborhood, gym, work "
                    "hours, family, routines, likes/dislikes). The profile is ALWAYS "
                    "in your context, so save durable info here instead of memory "
                    "(use memory for timestamped events/logs). Actions: view (read "
                    "the current profile), set (replace the whole profile with new "
                    "markdown), append (add a line/section). Scoped to the current "
                    "chat's silo: the user's private profile in 1:1, the group's "
                    "shared notes in group chats."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "description": "view, set, or append",
                            "enum": ["view", "set", "append"],
                        },
                        "content": {
                            "type": "string",
                            "description": (
                                "For set: the full updated profile markdown. "
                                "For append: the line/section to add."
                            ),
                        },
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "web_search",
                "description": (
                    "Web search — use it directly for quick lookups: current "
                    "events, hours, prices, news, reviews, facts, verifying a "
                    "place. Only delegate to the research agent for a genuinely "
                    "deep multi-source dive. If it reports the search service "
                    "was unavailable/blocked, that is NOT 'no results' — retry "
                    "once or use browser/web_fetch instead; never tell the user "
                    "nothing exists based on a blocked search."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query",
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "web_fetch",
                "description": (
                    "Fetch a URL and return its readable text — for verifying a "
                    "venue/listing page, reading an article, or following up a "
                    "web_search result. For JS-heavy pages, YouTube/TikTok "
                    "transcripts, or screenshots use browser instead."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The URL to fetch",
                        },
                    },
                    "required": ["url"],
                },
            },
            {
                "name": "send_message",
                "description": (
                    "Send an iMessage directly. Accepts a phone number OR the "
                    "name of a saved contact (saved via contacts action="
                    "add_contact — e.g. 'wife', 'Mom'). If a name isn't saved "
                    "it returns the saved-contact list instead of guessing. "
                    "For complex messaging tasks, delegate to the texting agent."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "to": {
                            "type": "string",
                            "description": (
                                "Phone number in +1XXXXXXXXXX format, or a saved "
                                "contact name"
                            ),
                        },
                        "text": {
                            "type": "string",
                            "description": "Message text",
                        },
                    },
                    "required": ["to", "text"],
                },
            },
            {
                "name": "contacts",
                "description": (
                    "Manage the current user's contact profile. "
                    "Actions: get (read profile), update (set fields like name, "
                    "timezone, home_location, work_location, onboarded, "
                    "google_connected, google_offered, email, notes), "
                    "add_contact (save a person's number under a name — 'wife', "
                    "'Mom', 'Seth' — so send_message works by name; when the "
                    "user gives you someone's number, save it proactively), "
                    "list_contacts (show the saved address book)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "description": "get, update, add_contact, or list_contacts",
                        },
                        "contact_name": {
                            "type": "string",
                            "description": (
                                "For add_contact: the name/relation to save, "
                                "e.g. 'wife', 'Mom', 'Seth'"
                            ),
                        },
                        "contact_phone": {
                            "type": "string",
                            "description": (
                                "For add_contact: their number, +1XXXXXXXXXX"
                            ),
                        },
                        "name": {
                            "type": "string",
                            "description": "User's name (for update)",
                        },
                        "timezone": {
                            "type": "string",
                            "description": (
                                "User's IANA timezone, e.g. 'America/Los_Angeles'. "
                                "Infer it from a city/state if they give one."
                            ),
                        },
                        "home_location": {
                            "type": "string",
                            "description": (
                                "Where the user lives (neighborhood/city) — for "
                                "planning, weather, and travel."
                            ),
                        },
                        "work_location": {
                            "type": "string",
                            "description": "Where the user works or spends their days.",
                        },
                        "onboarded": {
                            "type": "boolean",
                            "description": "Set to true after onboarding is complete",
                        },
                        "google_connected": {
                            "type": "boolean",
                            "description": "Whether Google is connected",
                        },
                        "google_offered": {
                            "type": "boolean",
                            "description": (
                                "Set true once you've offered the Google connect "
                                "link, so it isn't offered again."
                            ),
                        },
                        "email": {
                            "type": "string",
                            "description": "User's email (for update)",
                        },
                        "notes": {
                            "type": "string",
                            "description": "Any notes about the user",
                        },
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "set_reminder",
                "description": (
                    "Set a reminder for a user. HAL will text them when the time comes. "
                    "Can also list or delete reminders. Scoped to the current chat: in "
                    "a group chat the reminder is delivered to the WHOLE group, so for "
                    "personal reminders tell the user to text you 1:1."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "description": "create, list, or delete",
                            "enum": ["create", "list", "delete"],
                        },
                        "text": {
                            "type": "string",
                            "description": "The reminder message (for create)",
                        },
                        "due_time": {
                            "type": "string",
                            "description": (
                                "When to send the reminder in ISO format "
                                "(e.g. 2026-02-10T09:00:00). Interpreted in the "
                                "user's LOCAL timezone when no offset is given, so "
                                "'9am' means 9am their time. Use current_time first "
                                "if you need to calculate relative times."
                            ),
                        },
                        "recur": {
                            "type": "string",
                            "description": "Optional recurrence: daily, weekly, or monthly",
                        },
                        "cancel_if": {
                            "type": "string",
                            "description": (
                                "Optional plain-language condition under which this "
                                "reminder is no longer worth sending. At the due "
                                "time HAL re-checks it against live state and "
                                "silently drops (or rewords) the reminder if it's "
                                "moot. Use it whenever the reminder is tied to a "
                                "PREDICTED event that the user might do early/late "
                                "or skip, e.g. 'the user already left for the "
                                "airport' or 'the meeting was cancelled'. Omit for "
                                "fixed reminders that should always fire."
                            ),
                        },
                        "reminder_id": {
                            "type": "string",
                            "description": "Reminder ID (for delete)",
                        },
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "group_quiet",
                "description": (
                    "Group chats only. When a member tells you to butt out, keep "
                    "quiet, stop chiming in, or that you're 'not invited' "
                    "('stfu', 'keep it to yourself', 'please stop'), call this "
                    "with action=mute — it durably silences you in this group: "
                    "only messages that explicitly say 'Hal' will reach you "
                    "until the mute expires (default 3 days). Also use "
                    "action=mute when YOU decide to bow out of an event the "
                    "members are heading into (you said \"I'll butt out\" — make "
                    "it real). action=unmute only when a member explicitly "
                    "invites you back into the conversation."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["mute", "unmute", "status"],
                        },
                        "days": {
                            "type": "number",
                            "description": (
                                "How long to stay muted, in days (default 3, "
                                "max 30). Use ~0.5 for 'just during this "
                                "event/lunch', 3 for a general 'stop chiming "
                                "in', longer if they were emphatic."
                            ),
                        },
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "helpful_mode",
                "description": (
                    "Turn the user's proactive 'helpful mode' on/off or tune it. "
                    "When ON, HAL sends a short situation- and location-aware daily "
                    "brief (weather, local events/things to do, news, today's "
                    "agenda) plus a few capped same-day heads-ups. Use when the user "
                    "asks to enable/disable proactive briefs, change what they "
                    "cover, or change the time. Off by default."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["on", "off", "status", "set"],
                            "description": "on, off, status, or set (adjust interests/hour)",
                        },
                        "interests": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["weather", "events", "news", "agenda"],
                            },
                            "description": "Which topics the brief should cover.",
                        },
                        "hour": {
                            "type": "integer",
                            "description": "Local hour (5–21) to send the daily brief. Default 8.",
                        },
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "recall_history",
                "description": (
                    "Search THIS chat's own past conversation archive by keyword "
                    "and/or time — for 'what did we talk about last week', 'when did "
                    "I mention X', or recalling details older than the recent "
                    "messages. Different from memory (facts you deliberately saved): "
                    "this searches everything that was actually said. Pass a query "
                    "and/or a time range. Use current_time to resolve dates like "
                    "'last Tuesday' into since/until first."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Keywords to search for"},
                        "days_back": {"type": "integer", "description": "Search the last N days"},
                        "since": {"type": "string", "description": "ISO start of time range"},
                        "until": {"type": "string", "description": "ISO end of time range"},
                        "limit": {"type": "integer", "description": "Max results (default 10)"},
                    },
                },
            },
            {
                "name": "schedule",
                "description": (
                    "Schedule HAL to DO a task on a schedule and deliver the result "
                    "— a real agent action (tools, web, calendar...), not static "
                    "text. Use for recurring/future work: 'every weekday 8am text me "
                    "my morning brief', 'summarize my unread email at 6pm daily', "
                    "'next Monday research X and send it'. For a plain text nudge at "
                    "a time, use set_reminder instead. Actions: create (prompt = the "
                    "task to run, due_time = ISO first run, recur), list, delete. Use "
                    "current_time to compute due_time."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["create", "list", "delete"]},
                        "prompt": {"type": "string", "description": "The task for HAL to run at the scheduled time"},
                        "due_time": {"type": "string", "description": "ISO time of the first/next run"},
                        "recur": {
                            "type": "string",
                            "description": "once, daily, weekdays, weekly, or monthly",
                        },
                        "job_id": {"type": "string", "description": "Job id (for delete)"},
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "browser",
                "description": (
                    "Browse the web with full Chromium. Extract page content, "
                    "YouTube/TikTok transcripts, take screenshots, click elements, "
                    "type text, run JS, or list links. Auto-detects YouTube and "
                    "TikTok URLs and extracts transcripts automatically."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "URL to navigate to",
                        },
                        "action": {
                            "type": "string",
                            "description": (
                                "Action to perform: extract (default — auto-detects content type), "
                                "screenshot, click, type, evaluate, read, links"
                            ),
                        },
                        "selector": {
                            "type": "string",
                            "description": "CSS selector (for click/type actions)",
                        },
                        "text": {
                            "type": "string",
                            "description": "Text to type (for type action)",
                        },
                        "javascript": {
                            "type": "string",
                            "description": "JavaScript to run in page (for evaluate action)",
                        },
                    },
                    "required": ["url"],
                },
            },
            {
                "name": "image_edit",
                "description": (
                    "Edit or transform an image the user sent. Uses Gemini image model. "
                    "The user's image is automatically available — just pass the editing prompt."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {
                            "type": "string",
                            "description": (
                                "What to do with the image (e.g. 'make it a cartoon', "
                                "'remove background', 'add sunglasses')"
                            ),
                        },
                    },
                    "required": ["prompt"],
                },
            },
            {
                "name": "trip",
                "description": (
                    "Coordinate group trips. Create trips, collect availability, "
                    "find date overlap, search Airbnb, vote on options. "
                    "Use in group chats when someone wants to plan a trip."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "description": (
                                "create, status, parse_and_add, add_availability, "
                                "lock_dates, search_airbnb, save_options, vote, tally, cancel"
                            ),
                        },
                        "chat_id": {
                            "type": "string",
                            "description": "The group chat identifier (from system context)",
                        },
                        "location": {
                            "type": "string",
                            "description": "Trip destination (for create)",
                        },
                        "group_name": {
                            "type": "string",
                            "description": "Group chat name (for create)",
                        },
                        "phone": {
                            "type": "string",
                            "description": "Participant's phone number",
                        },
                        "name": {
                            "type": "string",
                            "description": "Participant's name",
                        },
                        "text": {
                            "type": "string",
                            "description": "Raw message text to parse for dates (for parse_and_add)",
                        },
                        "available": {
                            "type": "array",
                            "description": "Date ranges [{start, end}] (for add_availability)",
                            "items": {"type": "object"},
                        },
                        "unavailable": {
                            "type": "array",
                            "description": "Unavailable dates [YYYY-MM-DD] (for add_availability)",
                            "items": {"type": "string"},
                        },
                        "start": {
                            "type": "string",
                            "description": "Start date YYYY-MM-DD (for lock_dates)",
                        },
                        "end": {
                            "type": "string",
                            "description": "End date YYYY-MM-DD (for lock_dates)",
                        },
                        "guests": {
                            "type": "number",
                            "description": "Number of guests for the trip (for search_airbnb). Use this when the user specifies how many people are going.",
                        },
                        "option": {
                            "type": "number",
                            "description": "Option number to vote for, 1-indexed (for vote)",
                        },
                        "options": {
                            "type": "array",
                            "description": "Parsed Airbnb listings [{title, url, price_per_night, rating}] (for save_options)",
                            "items": {"type": "object"},
                        },
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "google_auth",
                "description": (
                    "Manage the user's Google connection (Calendar read & write, "
                    "Gmail read), scoped to this 1:1 chat. Actions: status (is it "
                    "connected, and as which account), start (returns a one-tap consent "
                    "LINK — send it to the user verbatim on its own line and ask them to "
                    "tap it, approve, and text back), disconnect (revoke + forget). If "
                    "google_calendar or google_gmail says it's not connected, call "
                    "start. Personal — refuses in group chats."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["status", "start", "disconnect"],
                        },
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "google_calendar",
                "description": (
                    "Read AND write the user's Google Calendar. Actions: list_events "
                    "(upcoming events; optional time_min/time_max as RFC3339, defaults "
                    "to the next 7 days), search_events (same plus a query string), "
                    "create_event (add an event to their primary calendar — needs "
                    "summary + start; end defaults to start + 1h; a naive start like "
                    "2026-07-02T15:00:00 is read in the user's own timezone). Requires "
                    "the user to have connected Google (google_auth); if the connection "
                    "predates write access you'll be told to have them reconnect. "
                    "Personal — refuses in group chats."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["list_events", "search_events", "create_event"],
                        },
                        "time_min": {"type": "string", "description": "RFC3339 start, e.g. 2026-06-09T00:00:00-04:00"},
                        "time_max": {"type": "string", "description": "RFC3339 end"},
                        "query": {"type": "string", "description": "Text to match (for search_events)"},
                        "max_results": {"type": "integer", "description": "Default 10"},
                        "summary": {"type": "string", "description": "Event title (for create_event)"},
                        "start": {"type": "string", "description": "Event start, ISO 8601. Naive (no offset) is read in the user's timezone, e.g. 2026-07-02T15:00:00 (for create_event)"},
                        "end": {"type": "string", "description": "Event end, ISO 8601; defaults to start + 1 hour (for create_event)"},
                        "description": {"type": "string", "description": "Event notes/description (for create_event)"},
                        "location": {"type": "string", "description": "Event location (for create_event)"},
                        "attendees": {"type": "array", "items": {"type": "string"}, "description": "Attendee email addresses to invite (for create_event)"},
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "google_gmail",
                "description": (
                    "Read the user's Gmail (READ-ONLY — HAL cannot send or draft "
                    "email). Actions: list_emails (query defaults to 'is:unread'; "
                    "supports Gmail search like 'is:unread newer_than:1d', returns "
                    "ids + sender + subject + snippet), read_email (full body by "
                    "message_id). Requires the user to have connected Google "
                    "(google_auth). If the user asks you to send or reply to an "
                    "email, say you can pull up the thread but they'll need to send "
                    "from their own Mail app. Personal — refuses in group chats."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["list_emails", "read_email"],
                        },
                        "query": {"type": "string", "description": "Gmail search query, e.g. 'is:unread newer_than:1d'"},
                        "max_results": {"type": "integer", "description": "Default 10"},
                        "message_id": {"type": "string", "description": "Message id (for read_email)"},
                    },
                    "required": ["action"],
                },
            },
            # NOTE: dead "not yet available" stubs (vault, connect_account,
            # manage_agents, events) are deliberately NOT advertised here —
            # offering the model tools that always fail wastes context and
            # makes HAL promise capabilities it doesn't have. The registry
            # still stubs them defensively if something calls one.
            {
                "name": "resy",
                "description": (
                    "Find restaurant tables on Resy and give the user a link to book. "
                    "Actions: search (name → venues, each with a Resy link), "
                    "availability (venue_id or query + date + party_size → the open "
                    "times for that day + a Resy booking link with the date/party "
                    "pre-filled). HAL does NOT book — it hands the user the Resy link "
                    "and they reserve on their own Resy account. Always include the "
                    "link on its own line. Public info, works anywhere."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["search", "availability"]},
                        "query": {"type": "string", "description": "Restaurant name"},
                        "venue_id": {"type": "string", "description": "Resy venue id (from search)"},
                        "date": {"type": "string", "description": "YYYY-MM-DD (availability)"},
                        "party_size": {"type": "integer", "description": "Number of people (default 2)"},
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "skill",
                "description": (
                    "Skills are reusable prompt templates that pre-load instructions, "
                    "context, and reference files for recurring tasks. Use this when "
                    "the user asks for something matching a known skill's keywords "
                    "(e.g. 'do my daily rollup', 'summarize this tiktok', 'every "
                    "weekday at 8am...') or types '/skill-name'. Actions: list, view, "
                    "invoke (render and return the body — TREAT THE RETURNED TEXT AS "
                    "YOUR NEXT INSTRUCTION SET and act on it), create, edit, "
                    "write_file (add references/templates/scripts), delete. Scoped to "
                    "the current chat's silo (plus shared read-only bundled skills) — "
                    "one user's custom skills are never visible to another user or "
                    "group."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "list",
                                "view",
                                "invoke",
                                "create",
                                "edit",
                                "write_file",
                                "delete",
                            ],
                        },
                        "name": {
                            "type": "string",
                            "description": "Skill name (kebab-case, lowercase)",
                        },
                        "inputs": {
                            "type": "object",
                            "description": (
                                "For invoke: values for the skill's input variables, "
                                "e.g. {team: 'eng', date: '2026-05-23'}"
                            ),
                        },
                        "description": {
                            "type": "string",
                            "description": "For create/edit: skill description",
                        },
                        "body": {
                            "type": "string",
                            "description": (
                                "For create/edit: skill body (markdown). Tokens: "
                                "{{var}} = input, {{$(cmd)}} = shell stdout, "
                                "{{file:references/foo.md}} = inline a sibling file."
                            ),
                        },
                        "keywords": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "For create/edit: routing keywords",
                        },
                        "skill_inputs": {
                            "type": "array",
                            "items": {"type": "object"},
                            "description": (
                                "For create/edit: list of {name, description, required} "
                                "for the skill's input variables."
                            ),
                        },
                        "path": {
                            "type": "string",
                            "description": (
                                "For write_file: relative path under references/, "
                                "templates/, or scripts/"
                            ),
                        },
                        "content": {
                            "type": "string",
                            "description": "For write_file: file content",
                        },
                        "reason": {
                            "type": "string",
                            "description": "For delete: archive reason",
                        },
                    },
                    "required": ["action"],
                },
            },
        ]
    }
]


# --------------------------------------------------------------------------- #
# Agent-specific tool subsets (Gemini format)
# --------------------------------------------------------------------------- #

def get_agent_tools(tool_names: list[str]) -> list[dict]:
    """Build a Gemini tools array containing only the specified tool names."""
    all_decls = MAIN_TOOLS[0]["function_declarations"]
    filtered = [d for d in all_decls if d["name"] in tool_names]

    if not filtered:
        return []

    return [{"function_declarations": filtered}]
