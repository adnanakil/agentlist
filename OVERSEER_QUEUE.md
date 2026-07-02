# Overseer Queue — greenlit build specs

Specs pasted here get implemented by the weekly overseer maintenance routine
(scheduled Claude Code agent) — or by any Claude Code session asked to "work
the overseer queue". Sources: HAL's nightly digest (💡 backlog pings and 🩺
health findings carry ready-to-run specs in `hal_feature_backlog.spec`).

Rules for the implementing agent:
- Implement ONLY specs listed below, smallest first. Draft-only: commit to a
  branch `overseer/<slug>` and open a PR — never push to main, never deploy.
- Run the offline suites (services/hal-orchestrator/tests_*.py) before the PR;
  all must pass.
- Remove a spec from this file in the same PR that implements it.

## Queue

(empty)
