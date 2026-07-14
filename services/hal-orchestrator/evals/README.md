# HAL behavior evals

Scenario-based evals that drive the REAL `/api/message` pipeline in-process
(ASGI, no server, no background daemons) against a LOCAL Postgres, with a
per-scenario model override — so candidate models can be compared on quality
and cost over identical inputs.

## Setup

1. Local Postgres (brew `postgresql@16` on :5432 works; docker-compose also fine):

   ```bash
   createdb hal_evals
   cd packages/ag-db && DATABASE_URL="postgresql+asyncpg://$USER@localhost:5432/hal_evals" \
     uv run alembic upgrade head
   ```

   Known migration drift (chain is missing two prod columns — patch manually):

   ```sql
   ALTER TABLE hal_user_memories ADD COLUMN embedding jsonb;
   ALTER TABLE hal_conversations ADD COLUMN summary text NOT NULL DEFAULT '';
   ALTER TABLE hal_conversations ADD COLUMN summarized_at_count integer NOT NULL DEFAULT 0;
   ```

2. API keys in env (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`).
   `run.py` auto-pulls missing ones from
   `railway variables --service hal-orchestrator --kv`. Never write keys to disk.

## Run

```bash
cd services/hal-orchestrator
uv run python evals/run.py --models gpt-5.6-luna,claude-sonnet-5 \
  --scenarios 'evals/scenarios/*.yaml' --categories baby-logging,smoke \
  --out evals/results.json
```

Override the DB with `--db` or `EVAL_DATABASE_URL` (non-local hosts are
refused — the harness TRUNCATEs every `hal_*` table per scenario).

## Scenario schema (`evals/scenarios/*.yaml`, one doc or a list per file)

```yaml
id: baby-log-feed-terse            # unique
category: baby-logging
description: one-line intent
silo: "+15551230001"               # "chat..." prefix = group chat id
is_group: false
sender: "+15551230001"             # actual speaker (differs from silo in groups)
group_name: "Weekend plans"        # groups only
now: "2026-07-08T14:32:00-04:00"   # freezes the current_time TOOL
internal: false                    # true = heartbeat/daemon-style turn
seed:
  profile: {name: ..., home_location: ..., timezone: ...}   # onboarded=True implied
  memories: ["plain strings"]                                # embedding-less
  history: [{role: user, text: "..."}, {role: model, text: "..."}]
  baby: {name: Bazzy, birthdate: "2026-04-02"}               # creates family
  baby_events: [{kind: feed, at: "2026-07-08T11:10:00-04:00", note: "4oz"}]
message: "incoming text"
tool_fixtures:                     # canned tool outputs for THIS scenario
  get_weather: "74F, rain 12-2pm"
expect:
  tools_called: ["baby"]           # each must appear in the trace
  tools_absent: ["send_message"]
  args_match:                      # some call of the tool matches ALL patterns
    baby: {kind: "feed"}           # regex if valid, else case-insensitive substring
  silent_expected: false           # true = reply must be empty/"..." sentinel
  reply_should: "rubric text for the LLM judge (harness ignores it)"
```

## Tool policy

- Fixtured tools return their canned string.
- `REAL_TOOLS` (baby, memory, set_reminder, contacts, profile, recall_history,
  group_quiet, helpful_mode, trip, skill, schedule, send_message) execute for
  real against the eval DB — args assertions check genuine behavior.
- Everything else returns `[eval stub: <tool> not fixtured for this scenario]`
  — nothing can hit the network. Choke point is
  `action_policy.authorize_tool` (every dispatch passes through it at call
  time; a string return short-circuits as the tool result), so delegate/
  specialist sub-loops are covered without prod-code edits.
- `current_time` is always frozen from `now`.

## Results (`--out` JSON, one record per scenario × model)

```json
{"scenario_id": "...", "category": "...", "model": "...",
 "reply": "...", "silent": false,
 "tool_trace": [{"tool": "baby", "args": {...}}],
 "assertions": {"passed": true, "failures": []},
 "usage": {"calls": 2, "input": 27663, "cached": 13695, "cache_write": 0,
           "output": 776, "reasoning": 563},
 "usage_other": {},
 "latency_ms": 22652, "error": null}
```

**Usage semantics differ by provider** (pricing must handle both):

- OpenAI (`openai.usage`): `input` is the TOTAL prompt tokens; `cached` is the
  subset of `input` billed at the cached rate. `reasoning` is inside `output`.
- Anthropic (`claude.usage`): `input`, `cached` (cache reads), and
  `cache_write` are DISJOINT buckets summing to the total prompt.
- `usage` counts only the candidate model's calls; `usage_other` is fixed
  background machinery (critic etc., pinned to `claude-haiku-4-5` for run-to-run
  comparability) and should be reported but not attributed to the candidate.
- Native-Gemini calls emit no usage event today (and Gemini credits are
  currently depleted) — a gemini candidate will run but report empty usage.

## Fidelity caveats

- Failover is disabled (`MODEL_FALLBACKS=""`): a failing candidate records an
  error instead of silently grading a fallback's answer.
- Dates the system prompt derives from the wall clock are NOT frozen — only
  the `current_time` tool is. Write scenarios that reason via the tool.
- Memory seeds have no embeddings; recall exercises the non-semantic path
  while Gemini embedding credits are depleted (matches current prod, ironically).
- Turns run sequentially by design; trace/usage capture is process-global.
