# HAL Growth Loop — nightly self-assessment and self-improvement

**Goal:** HAL should never be unable to answer a question or handle a task.
Operationally: every failure is SEEN, CATEGORIZED, and either auto-fixed,
backlogged with evidence, or explicitly accepted (external blocks) — and the
handled-rate trend is measured night over night.

## Two planes

**Data plane (per-silo, unchanged).** Conversations, memories, profiles,
reminders, baby events, per-user skills — keyed by silo. A user's facts never
leave their silo (the family is the one explicit exception, scoped to baby
events).

**Learning plane (global).** Turn records, friction events, outcome grades,
the failure taxonomy, the playbook, shared skills, and the feature backlog
read across ALL users and groups. HAL has one brain; it has one set of scars.

**Boundary rule:** what crosses up is what HAL learned about ITSELF, never
what it learned about a user. Enforced mechanically, not by prompt-trust:

1. **Grade locally, aggregate verdicts.** Deep assessment reads real
   conversation content, so it runs one silo at a time (no different from the
   live model having seen it). Only the verdict crosses: grade, failure
   category, redacted one-line goal, tools used.
2. **Redaction + name scrub** before any cross-silo model pass: phones,
   emails, plus a denylist of every known name (profiles, baby names) → placeholders.
3. **Privacy lint on everything published down.** Playbook entries and shared
   skills inject into every user's context, so each is checked against the
   all-silo PII denylist before publishing; violations are rejected.
4. **Two destinations for lessons.** Generic → global playbook. User-specific
   ("this user batch-logs events") → that silo's profile only, written by the
   in-silo grading pass.

## The four stages (nightly, ~3am ET)

### Stage 1 — Capture (see everything)
- `hal_turns`: EVERY turn recorded (user text, reply, tool/agent steps,
  status ok|gemini_failed|quiet), not just ≥5-tool successes. Failed and
  quiet-sentinel turns included; bridge echoes excluded.
- Friction kinds expanded: stub_tool, stuck, tool_error (existing) +
  `capability_refusal` (reply matches "I can't / don't have access / unable"
  heuristics) + `model_failure` (Gemini failure / breaker trip).
- Conversation-level signals (corrections, re-asks, abandonment) are detected
  by the nightly grader, which sees consecutive turns — no live-path code.

### Stage 2 — Assess (grade in-silo, aggregate globally)
- **Phase A (in-silo):** for each silo with ungraded turns, ONE pro-model call
  grades the day's turns chronologically: grade ∈ handled|partial|failed|na,
  category ∈ missing_tool | missing_knowledge | missing_data_access |
  bad_judgment | external_block | ambiguous_request | infra_error, plus
  conversation signals and optional per-silo lessons. Grades written to
  `hal_turns`; lessons appended to that silo's profile (capped section).
- **Phase B (global):** SQL rollups → scorecard: turns, handled-rate,
  failures by category, deltas vs trailing week. Examples redacted+scrubbed.

### Stage 3 — Act (tiered autonomy)
- **Tier 1 (autonomous):**
  - **Playbook** — `hal_playbook`: self-authored operating notes injected into
    the system prompt every turn ("## Operating Notes (self-learned)").
    Additive guidance only; hard rules (privacy, no-booking, safety) are
    code-owned and untouchable. Capped (~30 entries / ~4KB). Every entry
    carries provenance (origin reflection) + a hypothesis (target failure
    category/detail it should eliminate).
  - **Per-silo lessons** → profile (from Phase A).
  - **Shared skills** — auto-created as before (≤3/night, deduped).
- **Tier 3 (propose):** `hal_feature_backlog` — persistent, deduped feature
  requests that accumulate evidence across nights (`evidence_count`,
  first/last seen). Admin is pinged only for NEW items or items crossing an
  evidence threshold; high-priority items get a fuller `spec` drafted so a
  Claude Code session can build them directly. Pipeline: HAL proposes → admin
  greenlights → Claude Code builds.

### Stage 4 — Verify (close the loop)
- Each playbook entry's hypothesis is re-checked nightly: did its target
  failure recur? 3+ clean nights → `verified`. Recurrences persisting 3+
  nights → flagged "failing" and fed back into the next synthesis for
  revision; failing entries are first to be retired under cap pressure.
- Nightly admin digest: scorecard + actions taken + new backlog items.
  Sunday: weekly scorecard with handled-rate trend and verified wins.

## Decisions taken (2026-06-11)
- Playbook self-applies from day one (morning digest + provenance = easy
  revert; `hal_playbook.status` flips to `reverted` to roll back).
- Every turn is graded (volume ~50–150/day makes per-silo batching cheap).
- Feature proposals arrive as ready-to-run specs once evidence threshold hit.
- Grading + synthesis run on the PRO model (flash demonstrably ignores
  instructions; 3am quota is free).

## Schema (migration 022)
- `hal_turns(id, phone, sender_phone, user_text, reply, steps JSONB, status,
  grade, failure_category, grade_note, signals JSONB, graded_at, created_at)`
- `hal_playbook(id, content, hypothesis, target_category, target_detail,
  status active|verified|failing|reverted|retired, origin_reflection_id,
  clean_nights, fail_nights, created_at, updated_at)`
- `hal_feature_backlog(id, title, problem, evidence JSONB, sketch, spec,
  priority, status open|notified|greenlit|built|rejected, evidence_count,
  first_seen, last_seen, notified_at)`

## Key modules
- `services/growth.py` — nightly pipeline (phases A–E) + `growth_loop`
  (replaces `reflection_loop`; reuses `hal_reflections` for reports).
- `services/playbook.py` — load/cache active entries, format prompt block,
  apply changes through the privacy lint, enforce caps.
- `services/friction.py` — expanded kinds.
- `routes/message.py` — universal turn capture + refusal/model-failure
  friction.
- `scripts/run_growth_now.py` — manual trigger (needs DATABASE_URL +
  GEMINI_API_KEY).
