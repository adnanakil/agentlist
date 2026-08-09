# HAL — Architecture & Working Reference

_The one doc to read before touching HAL. Rewritten 2026-07-06 (was badly stale
from Feb); refreshed 2026-07-09 (reliable delivery, idempotency, worker
leadership, action policy, and quarantined learning). Part 1 is "pick up where we
left off"; Parts 2+ are how the whole system works._

HAL is a proactive personal assistant you text over iMessage. It plans, remembers,
watches for things, briefs you, and quietly gets to know you over time.

---

# PART 1 — START HERE NEXT TIME

## What HAL is, in one breath
An iMessage bridge on a Mac relays your texts to a FastAPI "brain" on Railway,
which runs an agent loop over 29 tools + 12 background daemons + a quarantined
nightly learning pipeline, all backed by Postgres. A sibling service (Ephemera)
feeds it NYC events.

## Current state (as of 2026-07-09)
- **Live & healthy:** `hal-orchestrator` and `ephemera`, both on Railway.
- **Main model:** `claude-sonnet-5`, thinking HIGH, fallbacks opus-4-8 / gemini-3.1-pro.
- **Bridge:** runs on a **separate Mac named "Hal"** — `ssh hal.local`, file
  `~/.hal/hal_bridge.py`, cron watchdog restarts it every minute (see Part 2 for
  the deploy/restart procedure). NOT this dev machine.
- **`parking` tool** (shipped 2026-07-08): NYC parking-ticket lookup by plate via
  NYC OpenData. Full auto-pay is blocked by reCAPTCHA on CityPay — lookup +
  tap-to-pay handoff only.
- **Billing pay→unlock is fixed** (2026-07-08): the bridge's `strip_markdown` was
  eating the underscores in a Stripe pay link's `client_reference_id`, so paying
  users never got unlocked. Fixed in the bridge (shield URLs); added a safety net
  that texts admin on any unmatched payment (Part 9 → Billing).
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
- **Reliability hardening is live (2026-07-09):** production is on migration
  `029`; the bridge sends stable Messages GUIDs, leases + acknowledges outbox
  rows, and keeps a 30-day local delivery-dedup ledger. The pre-rollout bridge
  backup is `~/.hal/hal_bridge.py.bak.20260709-182837` on `hal.local`.
- **Last production verification (2026-07-09):** `/health` returned 200; duplicate
  inbound requests returned byte-identical stored responses with HTTP 200; one
  test outbox row sent once and was acknowledged `1/1`; a rolling deploy showed
  the replacement process take worker leadership after the old process drained.

## Key commands
```bash
# --- Deploy HAL (railway.toml must be at repo root at deploy time) ---
ln -sf services/hal-orchestrator/railway.toml railway.toml
railway up --service hal-orchestrator --detach ; rm railway.toml

# --- Deploy the shared browser/scrape service ---
ln -sf agents/browser/railway.toml railway.toml
railway up --service browser --detach ; rm railway.toml

# --- Deploy Ephemera (its dir is linked to the agentgate project) ---
cd ~/Project/Ephemera && railway up --service ephemera --detach

# --- Change the iMessage BRIDGE (lives on a separate Mac, NOT this repo) ---
# Edit ~/.hal/hal_bridge.py ON hal.local, then restart it:
ssh hal.local 'cp ~/.hal/hal_bridge.py ~/.hal/hal_bridge.py.bak.$(date +%s)'   # back up
scp mylocalcopy.py hal.local:.hal/hal_bridge.py                                # or edit in place
ssh hal.local '/Library/Frameworks/Python.framework/Versions/3.8/bin/python3 -m py_compile ~/.hal/hal_bridge.py'
ssh hal.local 'pid=$(pgrep -f "$HOME/.hal/hal_bridge.py" | head -1); kill "$pid"; bash ~/.hal/hal_watchdog.sh'
ssh hal.local 'tail -8 /tmp/hal_bridge.log'                                    # verify clean startup banner

# --- Query PRODUCTION Postgres (read-only; the .env DB URL is a dead tunnel) ---
psql "$(railway variables --service Postgres --kv | grep DATABASE_PUBLIC_URL | cut -d= -f2-)"
#   grades:   SELECT grade,failure_category,grade_note FROM hal_turns WHERE grade IN ('partial','failed');
#   a user's brief:  SELECT notes FROM hal_user_profiles WHERE phone='+1...';
#   exclude grade='na' (heartbeat no-ops) from handled-rate math.

# --- Tests (standalone scripts, no framework) ---
for t in services/hal-orchestrator/tests_*.py; do python3 "$t" >/dev/null || echo FAIL $t; done
PYTHONPATH=services/hal-orchestrator:packages/ag-common:packages/ag-db \
  .venv/bin/python -m pytest -q tests/test_hal_reliability_foundations.py

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
  (`hal_orchestrator.worker_leader`, `followup.started`, or `heartbeat.started`)
  before trusting new behavior. Seeing `worker_standby` first is expected: the
  replacement retries election until the old process releases its advisory lock.
- **Always pass `--service hal-orchestrator`.** The local Railway link may point
  at Ephemera; relying on the linked service can deploy or inspect the wrong one.
- **Fetcher provenance:** Ephemera uses native HTTP first, then HAL's self-hosted
  Playwright browser service; no Firecrawl/Scrapfly key is required.
  Its Anthropic key is DEAD — use hal-orchestrator's. `vercel env pull` corrupted
  some values once — verify a key with a real API call before trusting it.
- **Scraper authentication:** `SCRAPER_API_KEY` is the shared Bearer secret for
  the browser service's `/scrape` and browser-action endpoints. Set the exact
  same value on all three Railway services: `browser` (verifies requests),
  `ephemera` (fetch-ladder caller), and `hal-orchestrator` (web/browser caller).
  `BROWSER_SERVICE_URL`/`SCRAPER_SERVICE_URL` selects the service URL; it is not
  the secret.
- **The bridge is on a SEPARATE Mac, not in this repo.** Editing
  `~/Project/*/hal/hal_bridge.py` on the dev machine does nothing — the live copy
  is `~/.hal/hal_bridge.py` on `hal.local`. Verify the actual PID with
  `ps -axo pid,command | grep ~/.hal/hal_bridge.py` before restarting. It
  `strip_markdown`s every outbound message — **URLs must be shielded
  before stripping** (an `_italic_` rule silently ate underscores in Stripe's
  `client_reference_id`, breaking pay→unlock for a full cycle; fixed 2026-07-08).

## Reliability rollout (2026-07-09)
Completed in production on 2026-07-09. For a new environment, deploy these as
one coordinated change:

1. Run Alembic migration `029_hal_reliability_foundations` against production.
2. Set a long random `CARD_SIGNING_KEY`. Keep `HAL_PROCESS_ROLE=all` for the
   current single service, or use `api` on web replicas and `worker` on one worker
   service. Postgres advisory leadership prevents duplicate daemon ownership;
   standby workers retry election and take over if the leader disappears.
3. Deploy the orchestrator. Legacy bridge requests remain accepted during the
   transition, but they do not get full inbound deduplication.
4. Update `~/.hal/hal_bridge.py` to pass the stable Messages database GUID as
   `message_id` on `POST /api/message`.
5. Change bridge polling to `GET /api/outbox?ack=false`. Send each returned row
   using its `id`, then call `POST /api/outbox/ack` with
   `{"message_ids": ["..."]}` only after AppleScript/WDA reports success. Reuse
   the outbox `id` as the bridge-side send deduplication key. Apply the same
   deduplication to `side_messages[].id` returned by `POST /api/message`.
6. Restart the bridge and verify that a retried inbound GUID returns the original
   response, and that an outbox row remains claimable until acknowledged.

Both the orchestrator and bridge have been observed on the new protocol. Keep
the compatibility paths only while rollback to the pre-029 bridge remains a
requirement. A stale inbound event is kept in `processing` rather than replayed
automatically because its first attempt may have performed an irreversible
action; reconcile it explicitly.

### Rollback
- Orchestrator: redeploy the previous Railway image. Migration `029` is additive,
  so old code can run while the new tables remain.
- Bridge: restore `~/.hal/hal_bridge.py.bak.20260709-182837`, syntax-check it with
  the framework Python 3.8 binary, kill the current PID, then run
  `~/.hal/hal_watchdog.sh`.
- Do not downgrade migration `029` while any new orchestrator or bridge process
  may still be using inbound receipts or outbox rows.

## Where to change common things
| Want to change… | Edit |
|---|---|
| HAL's persona / tool-routing rules | `hal_orchestrator/prompts/system.py` |
| A tool's behavior / a new tool | `hal_orchestrator/tools/*.py` + one `ToolSpec` registration in `tools/specs.py` (drop-in modules may use `tools/plugins/`) |
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
      ▲   │ leases /api/outbox; POSTs ack after send     │        │        │
      │   └──────────────────────────────────────────────┘        │        │
   sends to                                              ┌─────────┘        │
   your phone                                            ▼                  ▼
                                              ┌──────────────────┐  ┌────────────────┐
                                              │ Postgres (Railway)│  │ Ephemera       │
                                              │ 28 hal_* tables   │  │ (NYC events)   │
                                              └──────────────────┘  │ Railway+Redis  │
                                                                    └────────────────┘
```

- **MacBook Bridge** (`~/.hal/hal_bridge.py`, ~950 LOC, *not in this repo*): the
  only thing that can send/receive iMessage. Watches the Messages SQLite DB
  (`chat.db`), POSTs inbound texts to the orchestrator, sends replies via
  AppleScript/WDA, and leases `/api/outbox` rows for proactive messages. It
  acknowledges each row only after a successful send. Inbound Messages GUIDs
  become stable `message_id` values; split-message batches get a deterministic
  composite ID. Successful reply, side-message, attachment, and outbox delivery
  IDs are retained for 30 days in `~/.hal/hal_delivery.sqlite3`. **It runs on a
  dedicated Mac named "Hal"** (`ssh hal.local`, key-based,
  user `adnanakil`; `192.168.1.244` on the LAN) — *not* the dev machine. Stdlib
  only (`urllib`, `sqlite3`), **python.org framework Python 3.8** at
  `/Library/Frameworks/Python.framework/Versions/3.8/bin/python3` (switched off
  Xcode's python 2026-07-08 — an Xcode update had orphaned its Full Disk Access
  grant and took the bridge down; a `/Library/Frameworks` path is update-proof.
  A launchd LaunchAgent does NOT work here — launchd's TCC context lacks FDA even
  when the same python has it under ssh; keep the cron watchdog). Supervised by
  **cron every minute** + `@reboot` running `~/.hal/hal_watchdog.sh`, which
  respawns it whenever `pgrep -f hal_bridge.py` is empty (no launchd job for the
  bridge itself). To change it, see Part 1 → Key commands. **This single Mac is
  the biggest scaling constraint / SPOF** (see FEATURE_PLAN.md for the
  Twilio-fallback plan).
- **HAL Orchestrator** (this service): the brain. Everything below is about it.
- **Postgres** (Railway managed): all durable state, inbound event receipts,
  leased outbox rows, action confirmations, and worker leadership.
- **Ephemera** (separate repo `~/Project/Ephemera`): the NYC events engine HAL
  queries via `nyc_events`. See Part 8.

---

# PART 3 — THE REQUEST LIFECYCLE

Every inbound text routes through `POST /api/message` (`routes/message.py`, the
heart of the system):

1. **Auth and receipt** — `verify_bridge_auth` fails *closed*: an unset secret
   rejects every request. A stable `message_id` claims an inbound receipt before
   side effects; completed retries return the stored response. This is what makes
   trusting the caller-supplied silo safe.
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
8. **Persist & deliver** — sanitized history is saved with optimistic versioning,
   the turn is archived + graded, and the exact reply is stored on the inbound
   receipt before it is returned.

## Location

HAL has an on-demand, consent-based Find My integration. There is no supported
Find My API or AppleScript dictionary, so the Mac side uses the user's local Find
My sharing roster plus a narrowly scoped Accessibility helper.

### Intended flow

1. Each user explicitly shares their location with HAL's Apple account
   (`hal_msg@icloud.com`, configurable as `FINDMY_SHARE_HANDLE`) in Find My.
   HAL never enrolls or starts sharing for them. The Mac's system iCloud
   account MUST be the HAL Apple ID — when it was accidentally the owner's
   personal account (fixed 2026-07-15), the roster was the owner's own shares
   and lookups faithfully returned the wrong person's location.
2. The bridge sees the sender's iMessage phone/email and
   `scripts/hal_findmy_location.py` maps it to a Find My display name using
   `~/Library/Caches/com.apple.findmy.fmfcore/FriendCacheData.data`. Exceptional
   mappings can be added to `~/.hal/findmy_location_map.json`; the checked-in
   shape is `scripts/findmy_location_map.example.json`.
3. Only an explicitly location-dependent turn (`near me`, `around me`, `nearby`,
   `from here`, etc.) invokes the lookup. The signed
   `~/.hal/HalFindMyHelper.app` selects that person in Find My through macOS
   Accessibility and returns a visible location label to the bridge.
4. The bridge adds a one-turn `current_location` object to `POST /api/message`.
   `routes/message.py` validates it and puts it on `ToolContext`; the
   `tools/plugins/current_location.py` tool exposes it to the model. On failure
   the bridge instead sends `current_location_status` (status code only, never
   location data): `person_not_mapped` — the sender has never shared with
   HAL's account — turns the guard/tool reply into a one-time "share your
   location with HAL in Find My" invitation, while transient lookup failures
   keep asking for a neighborhood.
5. The prompt requires `current_location` before local discovery or travel.
   `tools/places.py` also enforces this structurally: on a `near me` turn it
   discards any neighborhood invented by the model and rebuilds the Places query
   from the user's wording plus the bridge-supplied Find My label.

### No-guess safety boundary

Location failure must never fall back to a profile home address, conversation
memory, or a model-guessed neighborhood. This is enforced in three places:

- The Mac lookup rejects Accessibility artifacts such as
  `Heading: 0 degrees, North` instead of treating map controls as addresses.
- `tools/places.py` refuses to perform a nearby search if the turn has no usable
  `current_location`.
- `routes/message.py` has an early server guard: a live-location request without
  a validated location returns
  `What neighborhood, address, or landmark should I search around?` before the
  model or any search tool runs.

The guard and the places enforcement share one canonical pattern
(`services/live_location.py`) so they cannot drift: it covers speaker-anchored
phrasings including non-adjacent `closest … to me`, and deliberately excludes
requests with an explicit anchor (`closest subway to Times Square`), where
forcing the live label would override an origin the user gave. In group chats
the early guard applies only when HAL is explicitly addressed — members
chatting about "anything nearby?" among themselves must not summon a canned
reply that would bypass the group mute and tact gates.

The last guard was verified against production with an authenticated request:
it returned the location question with `tool_calls=0`. The relevant Railway
deployment was `d4a745dc-fc67-4b19-8146-f1aa9ac0c026` on 2026-07-15.

### Privacy and lifetime

- Lookup is request-driven; there is no background location polling.
- A successful result is cached in Mac bridge memory for 90 seconds only;
  expired entries are pruned so the cache stays bounded.
- Helper runs are serialized and write into a private (`0700`) scratch
  directory that is removed whole afterwards; on timeout the orphaned helper
  instance is killed (`open -W` dying does not kill it), and the deleted
  directory means a late write has no surviving path to recreate.
- The bridge logs lookup status only, never the person, handle, or location.
- Raw location is excluded from inbound idempotency hashing. Before
  conversation history is saved, `current_location` tool results are redacted
  and the Find My label is scrubbed from persisted tool-call arguments (the
  model often copies it into a places query). The value exists only for the
  active turn.

### Current operational status

Automatic extraction works. Inspection of Find My's accessible fields showed
the selected person's location renders as a map-pin callout of the form
`"Northvale, NJ • 1 minute ago"` — one string carrying both the place and its
freshness — and that it renders asynchronously after selecting the person.
The original reader took a single snapshot after a fixed 2-second sleep, which
is why lookups flaked (an early snapshot leaves only map controls like the
compass heading to score). The helper now polls the detail pane for up to ~6s,
parses the callout (label and freshness split on the `•`), prefers the callout
nearest the selected person's own name node when several pins are visible, and
falls back to the scored heuristic only at the deadline. There is deliberately
no whole-window last resort for city-level strings: a sidebar scan could
attach a neighboring row's location to the wrong person. Verified on
2026-07-15: five consecutive cache-cleared lookups through the bridge module
returned clean labels in ~2.7s each.

The callout only ever carries city granularity ("New York, NY • Now") even
when the underlying fix is street-precise; the full address lives behind the
callout's More Info button. After reading the callout, the helper presses
More Info and scans the whole window for a street-level string (digit +
street suffix, `locationScore >= 6`), which cannot misattribute: other
people's list rows never show more than "City, ST", so only the open card can
produce a street address, and name-node proximity breaks any tie. Street
results are reported `approximate: false`, callout-only results
`approximate: true`. Street addresses arrive with an invisible U+200E
direction mark, which the bridge module strips (all Unicode Cf chars).
Verified end-to-end on 2026-07-16: three consecutive lookups returned the
street address in 8–9s each, and a real pipeline run answered "closest bakery
to me" with a spot a 3-minute walk from the pin.

The diagnostic build at `~/.hal/HalFindMyInspector.app` is approved for
Accessibility and stays available for future UI archaeology (`inspect` mode
dumps the detail-pane strings; the rebuilt production helper carries the same
mode). Helper binaries are ad-hoc signed on the Big Sur Mac, so rebuilding an
already-authorized app changes its code identity and invalidates its
Accessibility grant — expect a manual uncheck/re-check in System Preferences →
Security & Privacy → Accessibility after every rebuild of
`~/.hal/HalFindMyHelper.app`.

### Files and checks

- Mac lookup: `scripts/hal_findmy_location.py`
- Accessibility source/build: `scripts/hal_findmy_helper.swift`,
  `scripts/build_hal_findmy_helper.sh`, `scripts/HalFindMyHelper-Info.plist`
- Cloud tool: `hal_orchestrator/tools/plugins/current_location.py`
- Canonical request phrasing: `hal_orchestrator/services/live_location.py`
- Request boundary and hard guard: `hal_orchestrator/routes/message.py`
- Places enforcement: `hal_orchestrator/tools/places.py`
- Tests: `tests/test_findmy_location_bridge.py` and
  `tests/test_current_location.py`

The location and reliability test set last passed with 26 tests on 2026-07-15.

## Reliability semantics
- **Inbound:** `hal_inbound_events.id` is the bridge GUID/composite ID. The first
  request owns the turn; a completed duplicate gets the exact stored JSON. A
  duplicate still marked `processing` returns 409 and is never auto-taken over,
  because the first worker may have completed an irreversible side effect before
  crashing. This favors at-most-once action execution over automatic replay.
- **Outbound:** producers insert `hal_outbox_messages` in the same transaction as
  the state change that caused the send. The bridge leases rows with
  `GET /api/outbox?ack=false`; expired leases are reclaimable. It POSTs IDs to
  `/api/outbox/ack` only after AppleScript/WDA succeeds. The bridge ledger absorbs
  a lost-ack retry. There is still an unavoidable crash window between an iMessage
  send and recording its local delivery ID because Messages has no idempotency API.
- **Conversation concurrency:** model and network work runs without a row lock.
  `hal_conversations.version` provides optimistic append/merge on completion;
  same-process turns also use a short per-silo lock.
- **Workers:** `HAL_PROCESS_ROLE` selects `api`, `worker`, or `all`. One process
  owns the session-level Postgres advisory lock; standbys retry every 10 seconds.
  Loss of the lock connection or any daemon loop restarts leadership election.
- **Budgets:** request bodies are capped on both `Content-Length` and actual ASGI
  bytes. Defaults are 12,000 message characters, four images, 30 tool calls,
  45 seconds per tool, and 240 seconds per turn.

**Loop safety valves:** empty-text turns and `finishReason=MAX_TOKENS` truncations
route to `_finalize_answer` (tools-off re-synthesis at LOW thinking) instead of
shipping a fragment; a tool hammered `REPEAT_TOOL_LIMIT` times stops the loop; 3
consecutive model failures trip a per-silo circuit breaker.

**Internal turns** (`internal=True`, the daemons) run the same pipeline but persist
nothing when silent and never synthesize a user-facing message from a stall.

---

# PART 4 — THE 29 TOOLS

Declared centrally as `ToolSpec` objects in `tools/specs.py`; the registry loads
handlers from those specs and enforces scope, risk policy, timeout, and budget.
Drop-in modules under `tools/plugins/` may register additional specs without
editing the dispatcher. Startup validation rejects declaration/handler drift.

| Group | Tools |
|-------|-------|
| **Info / world** | `web_search`, `web_fetch`, `get_weather`, `sports_score`, `current_time` |
| **Local / places** | `places` (Google Places + real photos), `travel_time` (Routes + Maps deep links), `nyc_events` (Ephemera), `parking` (NYC parking-ticket lookup by plate; lookup + tap-to-pay handoff — auto-pay blocked by CityPay reCAPTCHA) |
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

## Sensitive action policy
`send_message` is server-authorized, not prompt-authorized. It is blocked in
groups and background turns. A DM may send immediately only when the actual
inbound user text contains send intent and the exact target. Otherwise HAL stages
a 10-minute `hal_action_confirmations` record bound to the silo, tool, and exact
argument hash; a later explicit approval must present its token. The model cannot
authorize itself using tool output or retrieved web content.

---

# PART 5 — THE 12 PROACTIVE DAEMONS

Launched by the elected worker leader in `main.py`; all deliver through leased,
acknowledged Postgres outbox rows. This is HAL's defining feature: acting in the
background, not just when addressed.

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
4. **Synthesize** playbook changes, skills, and feature-backlog specs into
   `hal_learning_candidates` for review.
5. **Health check** (SRE-style) correlates friction into root causes → backlog.
6. **Review and publish** through the admin candidate endpoints after PII lint;
   admin gets a digest. `GROWTH_AUTO_PUBLISH=false` is the secure default.

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

## Group-context catalog (group → your own DM, 2026-07-08)
A user's 1:1 prompt carries a compact catalog of the group chats they're IN
(proven by having spoken there — `hal_group_members`, upserted on every group
turn + backfilled): per group, last-active time + the head of its rolling
summary (~150 chars; ~400 if active <6h; block capped ~900 chars). The agent
pulls the real thread on demand via `recall_history(group=<id>)` —
membership-gated, 1:1-only, returns conversation content only (never HAL's
group notes/observations). Rationale: the user witnessed the group convo, so
their own DM knowing about it leaks nothing. Group summaries now LEAD with
decisions/plans/future-dated commitments (summarizer addendum) so the catalog
head carries the thing DMs reference later. Code:
`services/group_catalog.py`, backfill `backfill_group_members.py`, migration 028.

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
  venue/aggregator sites (plain HTTP → self-hosted Playwright), extracts events with Claude Haiku,
  geocodes, dedupes, caches in Upstash Redis. Watchdog auto-resets a stall. (No
  serverless ceiling on Railway → the full scrape completes, ~2,071 events.)
- **API:** `GET /api/events?since&until&near=lat,lng&radius_km&category&q&event_type&format&calendar_ready&limit`
  → `{success, count, events, lastFetched}`. Events carry a semantic type plus
  calendar-ready RFC3339 start/end/timezone, format, instructor/organizer,
  audience, price, registration, and recurrence metadata. Legacy cached events
  are normalized at read time; inferred end times are explicitly marked.
  HAL reaches it over private networking (`EPHEMERA_URL`).
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

## Data model (28 `hal_*` tables; Alembic through migration 029)
| Plane | Tables |
|-------|--------|
| Conversation | `hal_conversations`, `hal_messages` |
| Who you are | `hal_user_profiles`, `hal_user_memories`, `hal_user_skills` |
| Proactivity | `hal_reminders`, `hal_cron_jobs`, `hal_watches`, `hal_followups` |
| Groups | `hal_watched_groups`, `hal_group_members`, `hal_group_observations`, `hal_trips` |
| Baby | `hal_families`, `hal_family_members`, `hal_baby_events` |
| Learning | `hal_turns`, `hal_reflections`, `hal_playbook`, `hal_feature_backlog`, `hal_friction_events`, `hal_skill_trajectories`, `hal_curator_state`, `hal_learning_candidates` |
| Reliability | `hal_inbound_events`, `hal_outbox_messages`, `hal_action_confirmations` |
| Integrations | `hal_google_accounts` (Fernet-encrypted) + shared `accounts`/`api_keys`/`stripe_events` |

## Infra & security
- Railway project `agentgate`: HAL + Postgres + Ephemera and the other project
  services. HAL no longer uses Redis for delivery; its outbox is PostgreSQL.
- Routers: `message`, `google` (OAuth callback), `admin` (token-gated dashboard),
  `landing`, `legal`, `stripe`, and `card` (short-lived signed baby card).
- Fail-closed bridge auth; prod boot refuses to start without bridge secret + valid
  Fernet key + separate `CARD_SIGNING_KEY`; SSRF guard on `web_fetch`/`browser`;
  request-size middleware; code-owned sensitive-action policy;
  `LOG_MESSAGE_CONTENT=false` in prod; OAuth tokens encrypted at rest. Baby-card
  URLs expire after 15 minutes by default.
- Global playbook and shared-skill changes land in `hal_learning_candidates`.
  Admins list, approve, or reject them through token-protected admin endpoints;
  automatic publication is off in production.

## Billing (pay → unlock) — `services/billing.py` + `routes/stripe.py`
Free tier = `FREE_MESSAGE_LIMIT` (40) user-initiated msgs/month per 1:1 silo
(`usage.py`; groups/heartbeats/admin exempt). Over the cap → a funding message
with a static Stripe Payment Link + `?client_reference_id=<ref>` (signed with
`ENCRYPTION_KEY`, binds the payment to the silo). Stripe webhook
(`www.texthal.com/api/stripe/webhook`, secret `STRIPE_WEBHOOK_SECRET`, no
`STRIPE_SECRET_KEY` needed) → verify sig → resolve ref → `usage.set_plan(unlimited)`
+ queue the confirmation text. **Safety net:** an unmatchable payment
(`client_reference_id` null/invalid) texts `ADMIN_PHONE` instead of silently
dropping (`billing._alert_unmatched_payment`). **Manual replay** to unlock a lost
payment: sign a `checkout.session.completed` with `ENCRYPTION_KEY` +
`STRIPE_WEBHOOK_SECRET` and POST it to the webhook. (Gotcha: the URL must reach
the phone with underscores intact — see the bridge `strip_markdown` note in Part 1.)

## Key env vars
`GEMINI_MODEL`, `GEMINI_THINKING_LEVEL`, `MODEL_FALLBACKS`, `HAL_BRIDGE_SECRET`,
`CARD_SIGNING_KEY`, `HAL_PROCESS_ROLE`, `GROWTH_AUTO_PUBLISH`, `ENCRYPTION_KEY`,
`GOOGLE_MAPS_API_KEY`, `ANTHROPIC_API_KEY`, `EPHEMERA_URL`, `SCRAPER_API_KEY`,
`FOLLOWUP_ENABLED`/`FOLLOWUP_SILOS`, the Google OAuth trio, Stripe keys. Important
limits are configurable as `MAX_REQUEST_BYTES`, `MAX_MESSAGE_CHARS`,
`MAX_IMAGES_PER_MESSAGE`, `MAX_TOOL_CALLS_PER_TURN`, `TOOL_TIMEOUT_SECONDS`, and
`TURN_TIMEOUT_SECONDS`.

---

## Known limits (see FEATURE_PLAN.md)
The single-Mac bridge is the scaling ceiling (Twilio fallback planned); Google
OAuth is unverified (100-user cap, 7-day token expiry) pending CASA; no managed
heavy-agent runtimes yet. The live bridge source and its SQLite delivery ledger
exist only on `hal.local` (with timestamped backups), so bridge changes are not
yet reviewed or recovered through the repository's normal version-control path.

## Further reading
`GROWTH.md` (learning loop) · `WATCH_FEATURE_SPEC.md` (notify-when) ·
`GOOGLE_VERIFICATION.md` (OAuth) · `FEATURE_PLAN.md` (roadmap/blockers) ·
`CONVO_MINING_2026-07-05.md` (transcript findings) · root `CLAUDE.md` (marketplace).
