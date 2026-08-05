# The HAL Eng Team — full setup

*The engineering counterpart to `growth/TEAM.md`. Growth decides what to try;
eng builds, verifies, and ships it. Written 2026-08-05. The operating charter
(what the agents actually read) is `eng/CLAUDE.md`; this file is the map.*

---

## 1. Why it exists

On 2026-08-05 the growth team on the Hal Mac and Adnan's laptop independently
built the same landing hero CTA and the same Android SMS fix, in two
uncommitted working trees on two machines. Hal's next cycle would have deployed
its copy over the laptop's and silently reverted live A/B instrumentation while
the production database sat a migration ahead of the code.

Nothing was wrong with either piece of work. What was missing was a place for
code work to live, one owner for deploys, and a channel between the team that
wants a change and the team that makes it. That is this.

## 2. Shape

Queue-driven, not clock-driven — an empty queue costs one cheap Python run per
tick and nothing else.

```
Hal Mac (always on)
└─ launchd com.hal.eng  (KeepAlive)
   └─ eng/scripts/supervisor.sh ──every 10 min──▶ queue_check.py   (free)
        exit 10 only when a ticket is `status: open` AND the 20-min
        gap since the last cycle has passed, AND growth is not mid-cycle
        └─ claude -p "/eng-cycle"
             ├─ dirty-tree guard        (refuses to deploy over foreign edits)
             ├─ triage blast radius     GREEN → ship / RED → stage + escalate
             ├─ builder subagent
             ├─ tests + reviewer subagent   (APPROVED or it does not ship)
             ├─ deploy + verify_prod.py     (required, behavioural)
             └─ write ## Result into the ticket + eng/reports/<date>-<id>.md
```

## 3. Lanes — who touches what

| | Growth | Eng |
|---|---|---|
| Ad accounts, budgets, keywords, creative | **owns** | never |
| Experiment ledger, channel strategy | **owns** | reads |
| Application code, deploys | files a ticket | **owns** |
| Funnel plumbing / instrumentation | specifies | **builds** |

Eng never un-pauses a campaign, even one its own work just unblocked — that is
spend. It reports the unblock; growth acts on it next cycle. The lane rule is
enforced in `eng/permissions.json`, not just in prose: `gads.py` is in the
"ask" list, which headless means denied.

## 4. Blast radius — where autonomy ends

**GREEN** (build → review → deploy → verify, no human): `landing.py`,
`page_hits.py`, funnel/admin read-only dashboards, `growth/scripts/*`,
`eng/scripts/*`, static assets, tests, docs.

**RED** (stage, then stop for Adnan): any Alembic migration; HAL's
message-handling brain (`prompts/`, `routes/message.py`, `services/`, `tools/`);
billing/Stripe/auth/secrets; bridges, launchd, Dockerfile, Railway config;
dependency additions; any deletion.

Migrations are RED on purpose. The schema must reach production *before* the
code that writes to it, and that ordering is too easy to get wrong headless —
`alembic upgrade` is in the permission "ask" list so a cycle physically cannot
run one.

## 5. The ticket protocol

`eng/queue/ENG-NNN-slug.md`, format in `eng/queue/README.md`. The header is
machine-parsed; the body is prose.

`open` → `in-progress` → `done` | `blocked` | `needs-adnan`

Only `open` wakes the team. Eng writes its answer into the **same file** under
`## Result`, so the requester reads the outcome where they filed the request.
Tickets are never deleted — `done` ones are the team's memory, the way growth's
ledger is.

## 6. Where everything lives

| Piece | Path |
|---|---|
| Charter (agents read this) | `eng/CLAUDE.md` |
| Runbook (the `/eng-cycle` command) | `.claude/commands/eng-cycle.md` |
| Supervisor loop | `eng/scripts/supervisor.sh` |
| Queue gate (cheap, no LLM) | `eng/scripts/queue_check.py` |
| Production smoke checks | `eng/scripts/verify_prod.py` |
| Permission policy | `eng/permissions.json` |
| Ticket queue | `eng/queue/ENG-*.md` |
| Cycle reports | `eng/reports/<date>-<ticket>.md` |
| Logs / cadence stamp | `eng/state/{supervisor,cycle}.log`, `eng/state/last_cycle` |
| launchd plist | `eng/com.hal.eng.plist` → `~/Library/LaunchAgents/` |

Auth, Python, and Railway credentials are shared with growth (`~/.growth-env`,
`~/.growth-venv`, `~/.railway/config.json`) — see `growth/TEAM.md` §3.

## 7. Ops runbook

```bash
# What is pending?
python3 eng/scripts/queue_check.py --list

# Is production healthy? (safe to run anytime; the tap probe is tagged
# utm_source=verify-test, which the funnel dashboards exclude)
python3 eng/scripts/verify_prod.py

# File a ticket
cp eng/queue/README.md eng/queue/ENG-00N-my-slug.md   # then edit the header

# Is it alive?
ssh hal.local 'launchctl print gui/$(id -u)/com.hal.eng | grep state'
ssh hal.local 'tail ~/Project/agentlist/eng/state/supervisor.log'

# Force a cycle now (if a ticket is open)
ssh hal.local 'echo 0 > ~/Project/agentlist/eng/state/last_cycle'

# Pause / resume
ssh hal.local 'launchctl bootout gui/$(id -u)/com.hal.eng'
ssh hal.local 'launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.hal.eng.plist'

# Tuning
#   tick:      TICK in eng/scripts/supervisor.sh (10 min)
#   min gap:   MIN_GAP_MINUTES in eng/scripts/queue_check.py (20 min)
```

## 8. Keeping the two machines honest

**The Hal Mac is the only machine that deploys.** `railway up` uploads the
working directory, not the git HEAD — so a deploy from a tree carrying someone
else's half-finished edits publishes those edits.

- Work done on the laptop must reach Hal as **commits**, not loose files:
  ```bash
  git bundle create /tmp/sync.bundle <last-common-sha>..main
  scp /tmp/sync.bundle hal.local:/tmp/
  ssh hal.local 'cd ~/Project/agentlist && git fetch /tmp/sync.bundle main && git merge --ff-only FETCH_HEAD'
  ```
  (A bundle keeps this off GitHub. `git pull` works too once things are pushed.)
- The cycle's dirty-tree guard refuses to deploy over uncommitted code it cannot
  account for. If it stops for that reason, reconcile the machines first.

## 9. History

- **2026-08-05**: created, after growth and the laptop collided on EXP-006. The
  laptop's superset shipped (hero CTA above the fold at every width, sticky
  mobile bar, UA-aware sms separator, desktop copy-to-clipboard, hero-copy A/B
  with per-arm funnel recording, migration 034). Hal's divergent copy was
  reviewed first — its one better idea, putting the correct Android URI in the
  markup rather than JS-patching it, was merged and shipped as `f031001`. Hal's
  version is preserved in its `stash@{0}` and `/tmp/hal-presync/`.
  First ticket: ENG-001, does desktop traffic justify a QR path.
