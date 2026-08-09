#!/bin/zsh
# HAL growth team supervisor — kept alive by launchd (com.hal.growth).
# Every WATCH_INTERVAL: run the cheap watchdog; when it says a cycle is due,
# run a full headless growth cycle with the scoped permission policy
# (everything allowed except deletions, which require Adnan).

REPO=/Users/adnanakil/Project/agentlist
# PATH covers both hosts: laptop (pyenv/homebrew/.local) and the Hal Mac
# (growth venv first so python3 resolves there, then nvm node + python.org 3.14)
export PATH=/Users/adnanakil/.growth-venv/bin:/Users/adnanakil/.local/bin:/Users/adnanakil/.pyenv/shims:/opt/homebrew/bin:/Users/adnanakil/.nvm/versions/node/v18.20.8/bin:/usr/local/bin:/usr/bin:/bin
WATCH_INTERVAL=1800
# optional per-host secrets (e.g. CLAUDE_CODE_OAUTH_TOKEN on the Hal Mac)
[ -f "$HOME/.growth-env" ] && source "$HOME/.growth-env"

cd "$REPO" || exit 1
echo "[$(date '+%Y-%m-%d %H:%M:%S')] supervisor started (pid $$)" >> growth/state/supervisor.log

# Mutual exclusion with the eng team (eng/scripts/supervisor.sh). Both teams
# share one working tree, and two concurrent agent cycles editing it is exactly
# the failure the eng team was created to prevent. A lock older than STALE_MIN
# is treated as a crashed cycle and cleared, so neither team can wedge the other.
LOCK="$REPO/growth/state/cycle.lock"
ENG_LOCK="$REPO/eng/state/cycle.lock"
STALE_MIN=90
other_cycle_running() {
  [ -f "$1" ] || return 1
  if [ -n "$(find "$1" -mmin +$STALE_MIN 2>/dev/null)" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] clearing stale lock $1" >> growth/state/supervisor.log
    rm -f "$1"
    return 1
  fi
  return 0
}

while true; do
  python3 growth/scripts/watchdog.py >> growth/state/supervisor.log 2>&1
  rc=$?
  if [ "$rc" -eq 10 ]; then
    if other_cycle_running "$ENG_LOCK"; then
      echo "[$(date '+%Y-%m-%d %H:%M:%S')] eng cycle in flight — deferring" >> growth/state/supervisor.log
    else
      date +%s > growth/state/last_cycle
      touch "$LOCK"
      echo "[$(date '+%Y-%m-%d %H:%M:%S')] launching growth cycle" >> growth/state/supervisor.log
      claude -p "/growth-daily" --settings growth/permissions.json \
        >> growth/state/cycle.log 2>&1
      echo "[$(date '+%Y-%m-%d %H:%M:%S')] cycle finished (rc=$?)" >> growth/state/supervisor.log
      rm -f "$LOCK"
    fi
  fi
  sleep "$WATCH_INTERVAL"
done
