# The HAL Growth Team — full setup

*How the autonomous marketing team for texthal.com is built, where every piece
lives, and how to operate it. Written 2026-08-05. The operating charter (the
rules the agents actually read every cycle) is `growth/CLAUDE.md`; this file is
the human-readable map.*

---

## 1. What it is

An always-on agent team that spends a capped ad budget, measures real
conversions (families texting HAL), runs experiments, and reports its
decisions. It lives on the **Hal Mac** (the always-on Big Sur machine that also
runs the iMessage/WhatsApp bridges) and needs nothing from the laptop.

```
Hal Mac (always on)
└─ launchd com.hal.growth  (KeepAlive)
   └─ supervisor.sh ──every 30 min──▶ watchdog.py      (free: budget cap + auth check)
                      └─every 6 h───▶ claude -p "/growth-daily"   (a full cycle)
                                        ├─ metrics.py            scoreboard (ads × DB)
                                        ├─ plan 1-3 moves
                                        ├─ critic subagent       attacks the plan
                                        ├─ execute: gads.py      (ads) / builder subagent (code)
                                        ├─ reviewer subagent     reviews any diff before deploy
                                        └─ report + ledger update
└─ launchd com.hal.growth.dashboard ──▶ http://hal.local:8787   (read-only, LAN)
```

## 2. Roles

| Role | Agent | Notes |
|---|---|---|
| Orchestrator / ads operator | Claude (the cycle session itself) | reads charter, runs scripts, mutates Google Ads |
| Strategy critic | `kimi:kimi-challenge` | attacks each cycle's plan before execution |
| Builder + code reviewer | **the eng team** (`eng/TEAM.md`) | since 2026-08-05, code work leaves this team |

### The eng counterpart (added 2026-08-05)

Growth no longer writes or deploys application code. It files a ticket in
`eng/queue/` and reads the answer back from that ticket's `## Result` on a later
cycle. Eng never touches ad accounts, budgets, or spend — including un-pausing a
campaign its own work just unblocked, which stays growth's call.

This split exists because on 2026-08-05 a growth cycle and Adnan's laptop
independently built the same landing hero CTA and the same Android SMS fix, in
two uncommitted working trees on two machines. One nearly deployed over the
other and would have silently reverted live instrumentation. Full story and
setup: `eng/TEAM.md`. The two supervisors now hold mutually-exclusive locks, so
a growth cycle and an eng cycle can never edit this working tree at once.

**On the Hal Mac the Kimi/Codex CLIs don't exist** (Kimi's binary is
arm64-only; Codex isn't installed) — the runbook substitutes `general-purpose`
Claude subagents for those roles and notes the substitution in each report.
In practice the first cycles show this works: the substitute critic blocked
two premature ad moves; the substitute reviewer failed a diff and forced
three fixes before deploy.

## 3. Where everything lives

**Laptop** (`/Users/adnanakil/Project/agentlist`): source of the original
setup; its launchd plists are parked in `~/Library/LaunchAgents/disabled/` —
never run them while Hal's copy runs (two swarms would double-mutate the same
ad account).

**Hal Mac** (`ssh hal.local`, same repo path `~/Project/agentlist`):

| Piece | Path on Hal |
|---|---|
| Charter (agents read this) | `growth/CLAUDE.md` |
| Runbook (the `/growth-daily` command) | `.claude/commands/growth-daily.md` |
| Supervisor loop | `growth/scripts/supervisor.sh` |
| Watchdog (cheap health check) | `growth/scripts/watchdog.py` |
| Budget guard (the $30 wall) | `growth/scripts/budget_guard.py` |
| Ads CLI | `growth/scripts/gads.py` |
| Scoreboard | `growth/scripts/metrics.py` |
| Dashboard server | `growth/scripts/dashboard.py` |
| Experiment ledger | `growth/state/experiments.md` |
| Cycle reports (decisions) | `growth/reports/<date>.md` |
| Logs | `growth/state/{supervisor,cycle,launchd,dashboard}.log` |
| Cadence stamp | `growth/state/last_cycle` (epoch; delete/zero to force a cycle) |
| launchd plists | `~/Library/LaunchAgents/com.hal.growth{,.dashboard}.plist` |
| Claude auth (headless) | `~/.growth-env` → `CLAUDE_CODE_OAUTH_TOKEN` (1-year token, minted 2026-08-04) |
| Python deps | `~/.growth-venv` (python.org 3.14; system pip is PEP-668-locked) |
| Google Ads creds | `~/google-ads.yaml` |
| Railway auth | `~/.railway/config.json` |

## 4. Money rules (enforced, not vibes)

- **$30/day hard cap across ALL paid channels.** `budget_guard.py` sums every
  ENABLED campaign's daily budget and proportionally clamps if over; runs at
  the start and end of every cycle and on every 30-min watchdog tick.
- Google Ads mutations only in account **4959722800** (never the MCC
  9667792835). Currently funded by a **$100 prepaid credit** (2026-08-04);
  reports track cumulative spend against it.
- One-off spends (e.g. the $75 Park Slope Parents commercial post) are
  **proposals to Adnan only** — the team never pays for anything itself.
- **No deletions, anywhere, without Adnan.** `growth/permissions.json` makes
  delete commands "ask"; headless that means auto-denied. Ads objects get
  PAUSED, never REMOVED. Payment methods are never touched by agents.
- Organic posting (Reddit, Facebook groups, forums) is **founder-led only** —
  the team drafts, Adnan posts. MARKETING.md's disclosure-always rules stand.

## 5. Measurement — the funnel, end to end

North star: **new households** = first-ever `phone` in `hal_turns`
(`+1555555*` test numbers excluded).

The chain (all live as of 2026-08-04):

1. Ad click → lands with `?c=g1&utm_source=google&...` (campaign
   `final_url_suffix`)
2. Landing view → `hal_page_hits` row with UTM + attribution code (server-side,
   no cookies, day-salted visitor hashes)
3. "Text HAL" tap → `hal_funnel_events` row (`sms_tap`, JS beacon, per-visitor
   dedup) *and* the SMS opens pre-filled with "… **(g1)**"
4. First text arrives with the code → HAL stamps
   `acquisition_source` on `hal_user_profiles` (same machinery as the
   `/go/<code>` print codes)
5. Scoreboard + dashboards split households by source → exact cost per
   household per channel

Attribution codes: `g1`=google ads, and by convention `r1`=reddit,
`p1`=pinterest, `m1`=meta when those channels open. Caveat: users can delete
"(g1)" before sending, so paid counts are a floor, never an overcount.

**Where to look:**
- Growth dashboard: `http://hal.local:8787` (status, charts, decisions,
  ledger, logs; LAN only)
- Funnel on prod: `https://www.texthal.com/admin/traffic?token=<ADMIN_TOKEN>`
  (+ `&format=json` for machines) — funnel totals, by-source, by-day
- Raw scoreboard: `growth/reports/scoreboard-<date>.md` /
  `growth/state/metrics-latest.json`

## 6. Channels

| Channel | State | Blocker / next step |
|---|---|---|
| Google Ads (Search) | **LIVE** — campaign 24100110386 "TextHAL - Baby Tracking - Search", $10/day, Maximize Clicks, US/EN, phrase keywords, 1 RSA | keyword pruning ~2026-08-10; switch to Maximize Conversions after ~15 attributed conversions (EXP-002) |
| Meta (FB/IG) | staged | Adnan: FB Page + ad account billing + Graph API token (steps in chat 2026-08-03) |
| Reddit Ads | ledger EXP-008 | Adnan: advertiser account at ads.reddit.com + payment |
| Pinterest Ads | ledger EXP-009 | Adnan: business account + payment; team drafts pins |
| TikTok Ads | EXP-010 **parked** | minimums (~$20-50/day) don't fit the cap; needs video |
| Organic Reddit | founder-led | Reddit CRM: reddit-dashboard-production.up.railway.app + `~/Project/Marketing/Social/reddit-dashboard` (separate tool, NOT the swarm's) |

## 7. Ops runbook

```bash
# Is it alive?
ssh hal.local 'launchctl print gui/$(id -u)/com.hal.growth | grep state'
ssh hal.local 'tail ~/Project/agentlist/growth/state/supervisor.log'

# Force a cycle now
ssh hal.local 'echo 0 > ~/Project/agentlist/growth/state/last_cycle'   # fires on next 30-min tick

# Pause / resume the whole team
ssh hal.local 'launchctl bootout gui/$(id -u)/com.hal.growth'
ssh hal.local 'launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.hal.growth.plist'

# Ads by hand (from either machine)
python3 growth/scripts/gads.py show
python3 growth/scripts/gads.py set-budget 24100110386 12.50   # then run budget_guard.py
python3 growth/scripts/budget_guard.py

# Change cadence / cap
#   cycle interval: CYCLE_HOURS in growth/scripts/watchdog.py (6h default)
#   watchdog tick:  WATCH_INTERVAL in growth/scripts/supervisor.sh (30 min)
#   spend cap:      CAP_USD in growth/scripts/budget_guard.py ($30)
```

### Known gotchas (learned the hard way)

- **Claude on Hal is pinned at 2.1.111.** 2.1.118+ ships a native binary
  built for macOS 13+; it dyld-aborts on Big Sur. Never `npm update` claude
  there. Auth is the env token, not keychain — survives headless.
- The 1-year token in `~/.growth-env` was minted 2026-08-04 (laptop
  `claude setup-token`, mints non-interactively when already logged in).
  When it dies: re-mint on the laptop, re-ship the `export` line.
- Google Ads OAuth (`~/google-ads.yaml`) periodically dies with
  `invalid_grant` — reauth needs Adnan's browser (flow in memory
  `hal-google-ads`). The watchdog surfaces this as an alert.
- Hal's clock/timezone reads ~9h ahead of local — cosmetic; cadence is
  epoch-based.
- Deploys of hal-orchestrator run from Hal:
  `railway up --service hal-orchestrator --detach`. Keep laptop and Hal repo
  copies rsynced after edits on either side — **Hal is the source of truth**
  for anything the swarm touches.
- The session contract in the runbook exists because cycle #1 ended its turn
  while a subagent was still running and never wrote its report. Reports are
  mandatory before a cycle may end, even blocked/no-op ones.

## 8. History (short)

- **2026-08-03**: Google campaign live ($10/day). Team scaffolded on the
  laptop; moved same day from cron to always-on launchd. $100 card prepaid
  into Google Ads. Channel directive: Reddit/Pinterest/TikTok added to ledger.
- **2026-08-04**: Migrated to the Hal Mac (auth saga: retired OAuth scope,
  Big Sur binary ceiling, token-capture truncation — see gotchas). First
  autonomous cycle shipped EXP-001 (funnel instrumentation) to production
  with review. Paid attribution closed (`c=g1` suffix). Funnel section added
  to `/admin/traffic`.
- Open reads: tap-rate verdict (is the landing CTA or the beacon the reason
  for 0 taps?), keyword pruning 2026-08-10.
