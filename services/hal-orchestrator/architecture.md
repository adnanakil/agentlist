# HAL — Architecture & Working Reference

_The one doc to read before touching HAL. Rewritten 2026-07-06 (was badly stale
from Feb). Part 1 is "pick up where we left off"; Parts 2+ are how the whole
system works._

HAL is a proactive personal assistant you text over iMessage. It plans, remembers,
watches for things, briefs you, and quietly gets to know you over time.

---

# PART 1 — START HERE NEXT TIME

## What HAL is, in one breath
An iMessage bridge on a Mac relays your texts to a FastAPI "brain" on Railway,
which runs an agent loop over 28 tools + 12 background daemons + a nightly
self-improvement pipeline, all backed by Postgres. A sibling service (Ephemera)
feeds it NYC events.

## Current state (as of 2026-07-06)
- **Live & healthy:** `hal-orchestrator` and `ephemera`, both on Railway.
- **Main model:** `claude-sonnet-5`, thinking HIGH, fallbacks opus-4-8 / gemini-3.1-pro.
- **Post-event follow-ups:** ON but scoped to the owner's DM only
  (`FOLLOWUP_ENABLED=true`, `FOLLOWUP_SILOS=+12017570419`). Widen by editing
  `FOLLOWUP_SILOS`; the dry-run harness is `dryrun_followup.py`.
- **Ephemera:** first full 353-source scrape done (~2,071 events); daily 9am-UTC
  in-process scheduler now owns refresh. HAL reaches it via `EPHEMERA_URL`
  (Railway private networking).
- **Open loose ends:** destroy the dead Heroku app `ephemera-nyc` (zero dynos,
  maintenance mode); rebuild the iOS app in Xcode (baseURL already points at
  Railway); redeploy Vercel once so its old cron stops double-scraping; push
  Ephemera's local-only commits if it has a remote.

## Key commands
```bash
# --- Deploy HAL (railway.toml must be at repo root at deploy time) ---
ln -sf services/hal-orchestrator/railway.toml railway.toml
railway up --service hal-orchestrator --detach ; rm railway.toml

# --- Deploy Ephemera (its dir is linked to the agentgate project) ---
cd ~/Project/Ephemera && railway up --service ephemera --detach

# --- Query PRODUCTION Postgres (read-only; the .env DB URL is a dead tunnel) ---
psql "$(railway variables --service Postgres --kv | grep DATABASE_PUBLIC_URL | cut -d= -f2-)"
#   grades:   SELECT grade,failure_category,grade_note FROM hal_turns WHERE grade IN ('partial','failed');
#   a user's brief:  SELECT notes FROM hal_user_profiles WHERE phone='+1...';
#   exclude grade='na' (heartbeat no-ops) from handled-rate math.

# --- Tests (standalone scripts, no framework) ---
for t in services/hal-orchestrator/tests_*.py; do python3 "$t" >/dev/null || echo FAIL $t; done

# --- Health ---
curl https://hal-orchestrator-production.up.railway.app/health
curl https://ephemera-production-e117.up.railway.app/health
```

## Deploy gotchas (learned the hard way — read before deploying)
- **The Railway CLI HIDES failed deployments** ("No deployments found"). To see a
  build failure, query GraphQL `backboard.railway.com/graphql/v2` with the token
  from `~/.railway/config.json` — ask for `deployments{status}` and
  `buildLogs(deploymentId)`. This is the single biggest time-saver.
- **Railway blocks builds with CVE'd deps** (rejected `next@15.5.6`). Keep deps patched.
- **`railway up` respects `.gitignore`** — gitignored files never reach the Docker
  build context (bit us with `next-env.d.ts` and `.npmrc`). Put npm flags in the
  Dockerfile, not `.npmrc`.
- **After deploy**, wait ~40s for the OLD instance to drain before running evals;
  requests during the overlap hit stale code. Confirm via a startup log marker
  (`followup.started` / `heartbeat.started`) before trusting new behavior.
- **Key provenance:** working Firecrawl/Scrapfly keys live in `Ephemera/.env.local`;
  its Anthropic key is DEAD — use hal-orchestrator's. `vercel env pull` corrupted
  some values once — verify a key with a real API call before trusting it.

## Where to change common things
| Want to change… | Edit |
|---|---|
| HAL's persona / tool-routing rules | `hal_orchestrator/prompts/system.py` |
| A tool's behavior / a new tool | `hal_orchestrator/tools/*.py` + `prompts/tool_defs.py` + `tools/registry.py` |
| A proactive daemon | `hal_orchestrator/services/{heartbeat,followup,helpful,reminders,cron,watch}.py` |
| The nightly grading/learning | `hal_orchestrator/services/growth.py` (+ `playbook.py`) |
| A recurring skill (digest, brief) | `hal_orchestrator/skills/<name>/SKILL.md` |
| The DB schema | `packages/ag-db/ag_db/models.py` + a new `migrations/versions/NNN_*.py` |
| Config / env defaults | `packages/ag-common/ag_common/config.py` |

---

# PART 2 — THE BIG PICTURE

Three cooperating systems, each in its own place:

```
 iMessage (your phone)
      │
      ▼
 ┌─────────────────────┐   HTTPS (bridge secret)   ┌──────────────────────────┐
 │  MacBook Bridge     │ ────────────────────────► │  HAL Orchestrator        │
 │  ~/.hal/hal_bridge  │   POST /api/message       │  (Railway, FastAPI)      │
 │  (AppleScript I/O)  │ ◄──────────────────────── │  the brain               │
 └─────────────────────┘   reply + attachments     └──────────────────────────┘
      ▲   │  polls GET /api/outbox (proactive sends)     │        │        │
      │   └──────────────────────────────────────────────┘        │        │
   sends to                                              ┌─────────┘        │
   your phone                                            ▼                  ▼
                                              ┌──────────────────┐  ┌────────────────┐
                                              │ Postgres (Railway)│  │ Ephemera       │
                                              │ 23 hal_* tables   │  │ (NYC events)   │
                                              └──────────────────┘  │ Railway+Redis  │
                                                                    └────────────────┘
```

- **MacBook Bridge** (`~/.hal/hal_bridge.py`, ~300 LOC, *not in this repo*): the
  only thing that can send/receive iMessage. Watches the Messages SQLite DB,
  POSTs inbound texts to the orchestrator, sends replies via AppleScript, and
  polls `/api/outbox` for proactive messages the daemons queued. A cron watchdog
  restarts it. **This single Mac is the biggest scaling constraint / SPOF** (see
  FEATURE_PLAN.md for the Twilio-fallback plan).
- **HAL Orchestrator** (this service): the brain. Everything below is about it.
- **Postgres + Redis** (Railway managed): all durable state (23 `hal_*` tables)
  and the outbox/queue substrate.
- **Ephemera** (separate repo `~/Project/Ephemera`): the NYC events engine HAL
  queries via `nyc_events`. See Part 8.

---

# PART 3 — THE REQUEST LIFECYCLE

Every inbound text routes through `POST /api/message` (`routes/message.py`, the
heart of the system):

1. **Auth** — `verify_bridge_auth` fails *closed*: an unset secret rejects every
   request. This is what makes trusting the caller-supplied silo safe.
2. **Silo resolution** — the *silo* is the isolation key for ALL state. 1:1 →
   your normalized phone/email; group → the group's chat id. A group is its own
   shared silo, walled off from members' personal silos (`identity.py`).
3. **Early guards** — `/clear`; echo guard (HAL's own bounced replies); per-user
   monthly quota → a Stripe pay link past the free cap.
4. **Group mute check** — a group told to butt out force-silences non-`Hal`
   messages *here*, before any model call (Part 7).
5. **Context assembly** — system prompt = base persona (`prompts/system.py`) +
   per-silo context (your profile *or* the group's shared notes) + the
   dm/group-scoped playbook + auto-recalled memories + archive recall + the
   rolling summary. Groups never load personal data.
6. **Tool-use loop** — up to `max_tool_iterations` rounds of: call model
   (`call_gemini`) → run tool calls (network-only tools in parallel) → feed
   results back → repeat until final text.
7. **Post-reply guards** (real turns): claimed-action enforcer (a "reminder set"
   with no tool call gets performed or unclaimed), group tact gate (vetoes
   unprompted group interjections), critic (revises plan turns in place),
   markdown stripping.
8. **Persist & deliver** — sanitized history saved, turn archived + graded, reply
   returned.

**Loop safety valves:** empty-text turns and `finishReason=MAX_TOKENS` truncations
route to `_finalize_answer` (tools-off re-synthesis at LOW thinking) instead of
shipping a fragment; a tool hammered `REPEAT_TOOL_LIMIT` times stops the loop; 3
consecutive model failures trip a per-silo circuit breaker.

**Internal turns** (`internal=True`, the daemons) run the same pipeline but persist
nothing when silent and never synthesize a user-facing message from a stall.

---

# PART 4 — THE 28 TOOLS

Registered in `tools/registry.py`; schemas in `prompts/tool_defs.py`.

| Group | Tools |
|-------|-------|
| **Info / world** | `web_search`, `web_fetch`, `get_weather`, `sports_score`, `current_time` |
| **Local / places** | `places` (Google Places + real photos), `travel_time` (Routes + Maps deep links), `nyc_events` (Ephemera) |
| **Memory** | `memory` (explicit facts), `profile` (living notes), `recall_history` (FTS archive), `contacts` |
| **Proactivity** | `set_reminder` (static nudge), `schedule` (agentic cron), `watch` (notify-when), `group_quiet` (mute), `helpful_mode` (briefs) |
| **Google (1:1 only)** | `google_auth`, `google_calendar` (r/w), `google_gmail` (read-only) |
| **Baby** | `baby` (log feeds/naps/wakes, stats, forecasts) |
| **Group** | `trip` (multi-person planning), `group_quiet` |
| **Actions** | `send_message`, `image_edit`, `browser`, `resy`, `skill`, `delegate` (sub-agents) |

**Reminder vs schedule vs watch:** `set_reminder` re-sends fixed text at a time;
`schedule` runs a real agent turn on a clock; `watch` fires once when a
world-condition flips. Reminders support a `cancel_if` condition re-checked at fire
time.

---

# PART 5 — THE 12 PROACTIVE DAEMONS

All launched in `main.py`; all deliver via the Redis outbox. This is HAL's
defining feature — acting in the background, not just when addressed.

| Daemon | Cadence | Does |
|--------|---------|------|
| `heartbeat_loop` | ~15 min/silo | Upcoming plan vs live traffic/weather; new inbox event. ~95% silent. 1:1 only. |
| `followup_loop` | ~45 min | Post-event check-ins (Part 7). Flag-gated. |
| `helpful_loop` | daily + capped | Opt-in morning brief + a few same-day pings. |
| `run_reminder_checker` | 30 s | Fires due reminders; re-checks `cancel_if`; commits each before delivery. |
| `run_cron_checker` | 30 s | Agentic scheduled tasks (`/morning-brief`, `/baby-digest`, `/nyc-events`). Slash-skills at MEDIUM thinking. |
| `run_watch_checker` | ~60 s | Polls notify-when conditions; fires once when true. |
| `baby_watch_loop` | — | Nudges when a logged nap runs long. |
| `summarizer_loop` | ~20 min | Maintains the rolling conversation summary. |
| `profile_enricher_loop` | ~30 min | Builds the user brief (Part 6); emits group→member observations. |
| `curator_loop` | weekly | Prunes user-authored skills. |
| `skill_synthesizer_loop` | — | Distills ≥5-tool successes into reusable skills. |
| `growth_loop` | nightly ~3am ET | The self-improvement pipeline (Part 6). |

**Anti-spam is layered & code-enforced** (over-texting is the #1 churn risk): a
cross-daemon cooldown (`state.proactive_sent`) blocks a heartbeat within 60 min of
any prior proactive send; per-item re-alert caps; identity-keyed inbox dedup; quiet
hours in *each silo's own timezone*.

---

# PART 6 — SELF-IMPROVEMENT & MEMORY

## The nightly learning loop (`growth.py`, GROWTH.md)
1. **Grade** each turn (private, per silo): handled/partial/failed/na + category.
2. **Aggregate** a de-identified scorecard (names/emails scrubbed).
3. **Verify** each live playbook rule's hypothesis against the day's grades.
4. **Synthesize** playbook changes (operating notes injected into every prompt —
   a 3am lesson changes 7am behavior), skills, and feature-backlog specs.
5. **Health check** (SRE-style) correlates friction into root causes → backlog.
6. **Publish** through a PII lint; admin gets a digest.

**Playbook rules are DM/group-scoped** (`hal_playbook.scope`) — a 1:1 lesson never
leaks into group turns. Hard rules (privacy, safety, no-booking) stay code-owned;
the loop can only add additive guidance.

## How HAL "knows you" (all injected into context every message)
- **Profile** (`hal_user_profiles.notes`) — the main **brief**: structured markdown
  rebuilt every ~30 min by the enricher from your conversations. Self-refreshing.
- **Memories** (`hal_user_memories`) — discrete facts the model explicitly saved.
- **Rolling summary** (`hal_conversations.summary`) — running recap.
- **Archive** (`hal_messages`) — every message, FTS + time indexed, for
  `recall_history`.

---

# PART 7 — GROUPS, PRIVACY, FOLLOW-UPS

## Silo isolation (HARD, code-owned)
Every piece of state is keyed by silo, and **data never crosses silos.** Your 1:1
profile/memories are invisible in any group; a group's notes are separate from
members' personal silos. Enforced in code, not just prompt. Google tools refuse in
groups. **One exception:** a *family* (`hal_families`) shares one baby's log across
parents' 1:1s + the family group. **One-way valve:** the group enricher may write
per-member observations into that member's 1:1 — never the reverse.

## Group participation states
- **Tag-only** (default) — HAL only sees "Hal" mentions.
- **Watched** (`hal_watched_groups`, 24h TTL) — sees every message, prompted to
  DEFAULT TO SILENCE; the tact gate vetoes unprompted interjections.
- **Muted** (`muted_until`) — someone said butt out; non-`Hal` messages are
  code-force-silenced. Set via `group_quiet`; auto-expires.

## Post-event follow-ups (`followup.py`) — backward-looking sibling of the heartbeat
A sweep finds events HAL helped plan that have passed and sends one model-gated
"how did it go?" (checkin) then later one "want to do it again?" with real options
(suggest). Idempotent via `hal_followups`; respects mutes + the cooldown.
Flag-gated (`FOLLOWUP_ENABLED`/`FOLLOWUP_SILOS`).

## Trip planning (`trip`, `hal_trips`)
Stateful multi-person flow: collect dates → lock → search Airbnbs → vote → tally.

---

# PART 8 — EPHEMERA (NYC EVENTS ENGINE)

Separate Next.js service (repo `~/Project/Ephemera`, Railway) that HAL queries via
`nyc_events`. Migrated off Heroku/Vercel-cron 2026-07-06.

- **Pipeline:** daily in-process scheduler (`instrumentation.ts`) scrapes ~353 NYC
  venue/aggregator sites (Firecrawl → Scrapfly), extracts events with Claude Haiku,
  geocodes, dedupes, caches in Upstash Redis. Watchdog auto-resets a stall. (No
  serverless ceiling on Railway → the full scrape completes, ~2,071 events.)
- **API:** `GET /api/events?since&until&near=lat,lng&radius_km&category&q&limit`
  → `{success, count, events, lastFetched}`. HAL reaches it over private networking
  (`EPHEMERA_URL`).
- **Consumers:** HAL's `nyc_events` tool + `/nyc-events` skill + the follow-up
  suggest phase; plus a Next.js web UI and a Swift iOS app.

---

# PART 9 — MODELS, DATA, INFRA

## Model providers (`services/gemini.py` — a provider-agnostic shim)
Main model = `GEMINI_MODEL` (`claude-sonnet-5`) + `MODEL_FALLBACKS` for outages.
Shims: `claude_provider.py` (adaptive thinking from `thinking_level`),
`glm_provider.py`, native Gemini. Cheap `GEMINI_BACKGROUND_MODEL` for
heartbeats/gates; frontier `OVERSEER_MODEL` for nightly grading. Thinking shares
the output-token budget → heavy reasoning can truncate (`MAX_TOKENS`), guarded in
the loop + mitigated by capping crons at MEDIUM.

## Data model (23 `hal_*` tables; Alembic through migration 027)
| Plane | Tables |
|-------|--------|
| Conversation | `hal_conversations`, `hal_messages` |
| Who you are | `hal_user_profiles`, `hal_user_memories`, `hal_user_skills` |
| Proactivity | `hal_reminders`, `hal_cron_jobs`, `hal_watches`, `hal_followups` |
| Groups | `hal_watched_groups`, `hal_group_observations`, `hal_trips` |
| Baby | `hal_families`, `hal_family_members`, `hal_baby_events` |
| Learning | `hal_turns`, `hal_reflections`, `hal_playbook`, `hal_feature_backlog`, `hal_friction_events`, `hal_skill_trajectories`, `hal_curator_state` |
| Integrations | `hal_google_accounts` (Fernet-encrypted) + shared `accounts`/`api_keys`/`stripe_events` |

## Infra & security
- Railway project `agentgate` (europe-west4): HAL + Postgres + Redis + Ephemera.
- Routers: `message`, `google` (OAuth callback), `admin` (token-gated dashboard),
  `landing`, `legal`, `stripe`.
- Fail-closed bridge auth; prod boot refuses to start without bridge secret + valid
  Fernet key; SSRF guard on `web_fetch`/`browser`; `LOG_MESSAGE_CONTENT=false` in
  prod; OAuth tokens encrypted at rest.

## Key env vars
`GEMINI_MODEL`, `GEMINI_THINKING_LEVEL`, `MODEL_FALLBACKS`, `HAL_BRIDGE_SECRET`,
`ENCRYPTION_KEY`, `GOOGLE_MAPS_API_KEY`, `ANTHROPIC_API_KEY`, `EPHEMERA_URL`,
`FOLLOWUP_ENABLED`/`FOLLOWUP_SILOS`, the Google OAuth trio, Stripe keys.

---

## Known limits (see FEATURE_PLAN.md)
The single-Mac bridge is the scaling ceiling (Twilio fallback planned); Google
OAuth is unverified (100-user cap, 7-day token expiry) pending CASA; no managed
heavy-agent runtimes yet.

## Further reading
`GROWTH.md` (learning loop) · `WATCH_FEATURE_SPEC.md` (notify-when) ·
`GOOGLE_VERIFICATION.md` (OAuth) · `FEATURE_PLAN.md` (roadmap/blockers) ·
`CONVO_MINING_2026-07-05.md` (transcript findings) · root `CLAUDE.md` (marketplace).
