---
name: using-codex
description: Delegate coding work to OpenAI Codex from any Claude agent in this repo — spawning the codex-rescue agent, driving codex-companion.mjs directly, background job polling, and the sandbox/deploy/collision gotchas learned in production. Use when handing a task to Codex, checking a Codex job, or coordinating with a user-driven Codex session.
---

# Using Codex from Claude agents

Codex (OpenAI's coding agent) is available two ways in this environment. It
runs on the user's ChatGPT login; default model comes from `~/.codex/config.toml`
(currently `gpt-5.6-sol`, reasoning effort xhigh) — leave model unset unless the
user asks for a specific one.

## Path 1 — the plugin agent (preferred from a main session)

Spawn `subagent_type: "codex:codex-rescue"` via the Agent tool. It is a THIN
FORWARDER: it makes one Bash call to the companion script and returns stdout
verbatim. Put everything in the prompt — runtime flags first, then the task:

```
--background --model <model> <full task text>
```

- Flags `--background`/`--wait` control execution; `--model`/`--effort` select
  runtime. They are consumed by the forwarder, not sent as task text.
- Before spawning, check for a resumable thread:
  `node <companion> task-resume-candidate --json` — if `available: true`, ask
  the user whether to continue (`--resume`) or start fresh (`--fresh`).
- KNOWN FAILURE: the forwarder sometimes goes idle without launching anything.
  Always verify with `status --all` (below); if `running` and `recent` are both
  empty, the job never started — nudge the forwarder or run Path 2 yourself.

## Path 2 — the companion script directly (works from any agent with Bash)

The script lives under the plugin cache; resolve the path with a glob because
the version segment changes:

```bash
CJS=$(ls ~/.claude/plugins/cache/openai-codex/codex/*/scripts/codex-companion.mjs | tail -1)
node "$CJS" setup --json                       # readiness: codex installed? logged in?
node "$CJS" task --background --write [--model M] [--effort E] "<task text>"
node "$CJS" status <job-id> --json             # status + phase (or --all)
node "$CJS" result <job-id>                    # final report once status != running
node "$CJS" cancel <job-id>
```

- Background jobs do NOT notify the Claude harness. Poll with a backgrounded
  loop (`status` every ~30s until it leaves `running`); healthy jobs cycle
  phases `investigating`/`editing`/`verifying`. A 5-item two-repo task took
  ~11 minutes on gpt-5.6-sol.
- `result` prints the structured report plus a `codex resume <session-id>`
  line for follow-ups in the same Codex thread.

## Sandbox limits (measured, not theoretical)

A Codex job's write access is confined to the WORKSPACE ROOT it starts in
(this repo). In production use it could NOT:
- write files in another repo (e.g. `~/Project/Ephemera`) — edits rejected;
- write `.git` metadata even in-workspace (`index.lock`) — so it cannot
  commit; "commit your work" instructions will be skipped with a note;
- read Railway env vars or resolve public DNS in some phases.

Scope accordingly: give Codex the in-workspace file edits, keep cross-repo
work, commits, pushes, env-var reads, and smoke tests needing secrets in the
Claude session. Expect a "Skipped / Deferred" section in its report and plan
to finish those items yourself.

## Writing a good Codex brief

What worked: numbered items in priority order; verbatim file paths and line
regions; measured evidence for bugs (not vibes); explicit exclusion lists for
staging ("never git add -A", list the user's unrelated files by name); "flag
rather than guess" for ambiguity; explicit verification gates (exact test
commands) and a structured-output contract (per-item report + Skipped
section). Codex validates fixes in isolated copies when it can't write — its
verification results are trustworthy even when application is blocked.

## Deploys and authority

A delegated prompt that tells Codex to deploy production services trips the
security monitor (agent-authored delegation ≠ user consent). Either get the
user's explicit go-ahead for deploys in the brief you forward, or — cleaner —
have Codex stop at "committed and tested" and do deploys from the Claude
session where authority is directly traceable.

## Collisions with user-driven Codex sessions

The user often runs their own interactive Codex session in these repos. A
spawned Codex job is a SEPARATE session — it cannot see or coordinate with
theirs, and two writers in one working tree WILL overwrite each other
(observed: mid-edit "file modified since read" ping-pong). Before spawning
Codex into a repo, check `git status` for foreign in-flight changes and ask
the user who owns the integration. If told the user's session owns it, stand
down to non-contested files and hand findings over as a committed handoff doc.

## Quick reference

- Setup/auth check: `/codex:setup` or `setup --json` (expects `ready: true`,
  ChatGPT login active).
- Codex works happily on a DIRTY tree and will deploy uncommitted code —
  after any Codex work, ensure someone commits (stage by explicit path) and
  pushes; prod-only-in-working-tree is the failure mode to prevent.
- The rescue agent description says it best: use Codex for a second
  implementation/diagnosis pass, deep root-cause work, or substantial
  parallel coding — with a Claude agent reviewing the diff like any other
  teammate's.
