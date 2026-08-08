# ENG-005 — count Meta spend in budget_guard + metrics

- id: ENG-005
- from: growth
- status: needs-adnan
- priority: P1
- blast: green
- opened: 2026-08-07

## Request

budget_guard.py and metrics.py only see Google. Meta ad account 40885463 is
live and spending (growth/CLAUDE.md "Owned social accounts") — the $30/day cap
is currently reconciled by hand. Adnan is generating a system-user token with
ads_read (standup decision D3); it will land as META_ACCESS_TOKEN in
hal:~/.growth-env.

When the token exists (flip this ticket to open):

1. budget_guard.py: fetch act_40885463/campaigns?fields=name,status,
   daily_budget,lifetime_budget (Graph API v21+, stdlib urllib — no new deps).
   Include ACTIVE campaigns' daily_budget in the cap sum alongside Google;
   list lifetime-budget campaigns separately in the output (pacing is Meta's,
   not inferable).
2. metrics.py: pull act_40885463/insights daily spend into the scoreboard
   table so CPA includes Meta.
3. Fail LOUD once integrated: token missing/expired must print "Meta spend
   UNKNOWN — cap cannot be verified" and exit nonzero from budget_guard.
   Never show Google-only totals as if they were complete.

## Acceptance

- [ ] budget_guard sums Google + Meta active daily budgets against $30
- [ ] metrics scoreboard shows Meta spend per day
- [ ] loud failure on missing/expired token
