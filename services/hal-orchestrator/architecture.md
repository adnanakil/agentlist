# HAL Cloud Orchestrator — Architecture

Last updated: 2026-02-21

## Overview

HAL's brain has been moved from a 3,900-line monolithic Python script on a MacBook to a cloud service on Railway. The MacBook now runs a thin iMessage bridge (~300 LOC) that relays messages to/from the cloud orchestrator.

```
┌─────────────────────┐         HTTPS          ┌─────────────────────────────┐
│  MacBook (bridge)   │ ──────────────────────► │  hal-orchestrator (Railway) │
│                     │                         │                             │
│  hal_bridge.py      │  POST /api/message      │  Gemini API calls           │
│  - polls chat.db    │  ◄───────────────────── │  Tool execution             │
│  - sends via        │  {reply, side_messages}  │  Specialist agent sub-loops │
│    AppleScript      │                         │  Conversation state (PG)    │
│                     │                         │  Reminder background task   │
└─────────────────────┘                         └─────────────────────────────┘
        │                                                  │
        │ reads/writes                                     │ reads/writes
        ▼                                                  ▼
   ~/Library/Messages/chat.db                    Railway Postgres (shared)
```

## Why

- **Security**: Tools can't touch the Mac filesystem or processes
- **Reliability**: Proper process supervision, health checks, auto-restart on Railway
- **Scaling**: Multiple users don't bottleneck on a single MacBook process
- **Maintainability**: Clean separation — bridge is trivial, orchestrator is structured

## Components

### MacBook Bridge (`~/.hal/hal_bridge.py`)

~300 lines. Does three things:

1. **Polls chat.db** every 2 seconds for new incoming messages (same SQL as the old agent)
2. **POSTs to the cloud orchestrator** at `POST /api/message` with phone, text, group info
3. **Sends replies via AppleScript** — both the main reply and any `side_messages` (from the `send_message` tool)

Also handles:
- Message buffering (5s wait for link unfurls / split messages)
- Per-contact concurrency (one message at a time per phone, queue the rest)
- Message chunking (splits replies >1500 chars for iMessage)
- Markdown stripping (iMessage doesn't render it)
- Group chat detection (style=43 or chat_identifier format)

**Watchdog**: Cron runs `~/.hal/hal_watchdog.sh` every minute to restart if crashed.

### Cloud Orchestrator (`services/hal-orchestrator/`)

FastAPI service on Railway (port 8005). Structure:

```
hal_orchestrator/
├── main.py                    # App factory, lifespan, /health
├── state.py                   # Shared settings + httpx client (breaks circular imports)
├── routes/
│   └── message.py             # POST /api/message — the full tool-use loop
├── services/
│   ├── gemini.py              # Async Gemini API client (httpx, retry, backoff)
│   ├── conversation.py        # Load/save/validate history (Postgres, SELECT FOR UPDATE)
│   ├── profiles.py            # User profile CRUD
│   ├── memory.py              # Per-user remember/recall/list
│   └── reminders.py           # Reminder CRUD + background checker
├── tools/
│   ├── registry.py            # execute_tool() dispatcher + ToolContext
│   ├── current_time.py        # Returns current UTC time
│   ├── web_search.py          # DuckDuckGo search + URL fetch
│   ├── send_message.py        # Queues side_messages for bridge to send
│   ├── memory.py              # Wraps services/memory.py
│   ├── contacts.py            # Wraps services/profiles.py
│   ├── reminders.py           # Wraps services/reminders.py
│   ├── delegate.py            # Specialist agent sub-loop
│   └── stubs.py               # "Not yet available" for deferred tools
└── prompts/
    ├── system.py              # SYSTEM_PROMPT, AGENTS dict, build_user_context()
    └── tool_defs.py           # MAIN_TOOLS (Gemini format), get_agent_tools()
```

### Database (Railway Postgres, shared with other agentgate services)

4 new tables (migration 005):

| Table | Purpose |
|---|---|
| `hal_conversations` | Per-phone conversation history (JSONB), message count |
| `hal_user_profiles` | Name, email, onboarded flag, notes |
| `hal_user_memories` | Per-user memory entries (remember/recall) |
| `hal_reminders` | Scheduled reminders with recurrence support |

All indexed on `phone`. Conversations use `SELECT ... FOR UPDATE` to prevent race conditions.

## Message Flow

1. User sends iMessage
2. Bridge polls chat.db, picks up new ROWID
3. Bridge buffers 5s (for split messages), then POSTs to orchestrator
4. Orchestrator authenticates via `Authorization: Bearer {HAL_BRIDGE_SECRET}`
5. Loads conversation history + user profile from Postgres
6. Builds system prompt with per-user context
7. Enters Gemini tool-use loop (up to 15 iterations):
   - Calls Gemini with history + tools + system prompt
   - If Gemini returns function calls → execute tools → append results → loop
   - If Gemini returns text → that's the reply → break
8. Saves updated conversation history to Postgres
9. Returns `{reply, tool_calls, side_messages}` to bridge
10. Bridge sends the reply via AppleScript
11. Bridge sends any side_messages (from `send_message` tool) via AppleScript

## Tools — v1 Status

### Fully implemented
- `current_time` — returns UTC datetime
- `memory` — per-user remember/recall/list (Postgres)
- `contacts` — user profile get/update (Postgres)
- `web_search` — DuckDuckGo HTML scraping
- `web_fetch` — fetch + extract text from URLs
- `send_message` — queues side_messages for bridge delivery
- `delegate` — runs specialist agent sub-loops
- `set_reminder` — create/list/delete with recurrence + background checker

### Specialist agents (run as sub-loops, same process)
- `research` — web_search + web_fetch (Flash model)
- `texting` — send_message (Flash model)
- `brainstorm` — no tools, creative thinking (Pro model)

### Stubbed (return "not yet available")
- `google_auth`, `google_calendar`, `google_gmail`
- `vault`, `connect_account`
- `browser`, `bash`
- `resy`, `manage_agents`, `events`

## Key Design Decisions

**send_message via side_messages**: The MacBook isn't publicly reachable, so the orchestrator can't call back. Instead, `send_message` accumulates messages in `ToolContext.side_messages`, returned in the API response for the bridge to deliver.

**Synchronous request/response**: Bridge waits for the full orchestrator response (up to 120s timeout). Simpler than polling. Works because Gemini calls typically complete in 5-30s.

**Conversation concurrency**: `SELECT ... FOR UPDATE` on the conversation row prevents two rapid messages from the same user from corrupting history.

**Specialist agents as sub-loops**: Research/texting/brainstorm run inside the orchestrator process with their own system prompts and tool subsets. Not dispatched through the agentgate orchestrator — avoids latency and keeps logic centralized.

## Infrastructure

| Component | Location | URL |
|---|---|---|
| Orchestrator | Railway (agentgate project) | `https://hal-orchestrator-production.up.railway.app` |
| Bridge | MacBook (`~/.hal/hal_bridge.py`) | localhost only |
| Postgres | Railway (shared) | `postgres.railway.internal:5432` |
| Health check | `/health` | Returns `{"status":"ok","service":"hal-orchestrator"}` |

## Environment Variables (hal-orchestrator service)

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Postgres connection string (asyncpg) |
| `GEMINI_API_KEY` | Google AI Studio API key |
| `HAL_BRIDGE_SECRET` | Shared secret for bridge auth |
| `ENVIRONMENT` | `production` |
| `PORT` | `8005` |

## Deployment

**Orchestrator**: `railway up` from the agentlist repo root. Requires `railway.toml` symlinked to root (Railway reads it from upload root, not service subdirectory).

```bash
cd /path/to/agentlist
ln -sf services/hal-orchestrator/railway.toml railway.toml
railway service hal-orchestrator
railway up -d
rm railway.toml
```

**Bridge**: Copy to MacBook via SSH, kill old process, watchdog auto-restarts.

```bash
cat hal/hal_bridge.py | sshpass -p 'thankskevin' ssh adnanakil@adnanspsonalmac.lan "cat > ~/.hal/hal_bridge.py"
# Watchdog (cron, every minute) will restart it automatically
```

**Migrations**: Run from `packages/ag-db/` using the public Postgres URL.

```bash
cd packages/ag-db
DATABASE_URL="postgresql+asyncpg://...@yamanote.proxy.rlwy.net:11694/railway" uv run alembic upgrade head
```
