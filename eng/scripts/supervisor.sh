#!/bin/zsh
# HAL eng team supervisor — kept alive by launchd (com.hal.eng).
# Queue-driven: every TICK, ask queue_check.py whether there is actionable work.
# An empty queue costs one cheap python run and nothing else.
#
# Deliberately offset from the growth supervisor's schedule and gated on its own
# lock so the two teams never run a cycle at the same moment — they share one
# working tree, and concurrent edits are exactly the failure this team exists
# to prevent.

REPO=/Users/adnanakil/Project/agentlist
# Same PATH shape as growth/scripts/supervisor.sh: covers laptop (pyenv/brew)
# and the Hal Mac (growth venv first, then nvm node + python.org 3.14).
export PATH=/Users/adnanakil/.growth-venv/bin:/Users/adnanakil/.local/bin:/Users/adnanakil/.pyenv/shims:/opt/homebrew/bin:/Users/adnanakil/.nvm/versions/node/v18.20.8/bin:/usr/local/bin:/usr/bin:/bin
TICK=600
LOCK="$REPO/eng/state/cycle.lock"
GROWTH_LOCK="$REPO/growth/state/cycle.lock"

[ -f "$HOME/.growth-env" ] && source "$HOME/.growth-env"   # CLAUDE_CODE_OAUTH_TOKEN

cd "$REPO" || exit 1
mkdir -p eng/state eng/reports
echo "[$(date '+%Y-%m-%d %H:%M:%S')] eng supervisor started (pid $$)" >> eng/state/supervisor.log

while true; do
  python3 eng/scripts/queue_check.py >> eng/state/supervisor.log 2>&1
  rc=$?
  if [ "$rc" -eq 10 ]; then
    if [ -f "$GROWTH_LOCK" ]; then
      echo "[$(date '+%Y-%m-%d %H:%M:%S')] growth cycle in flight — deferring" >> eng/state/supervisor.log
    else
      date +%s > eng/state/last_cycle
      touch "$LOCK"
      echo "[$(date '+%Y-%m-%d %H:%M:%S')] launching eng cycle" >> eng/state/supervisor.log
      claude -p "/eng-cycle" --settings eng/permissions.json \
        >> eng/state/cycle.log 2>&1
      echo "[$(date '+%Y-%m-%d %H:%M:%S')] eng cycle finished (rc=$?)" >> eng/state/supervisor.log
      rm -f "$LOCK"
    fi
  fi
  sleep "$TICK"
done
