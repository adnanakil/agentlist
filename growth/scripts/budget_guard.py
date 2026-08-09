"""Hard $30/day cap across all paid channels. Run at start AND end of every growth session.

Sums daily budgets of ENABLED Google Ads campaigns in the operating account and ACTIVE
Meta campaigns; if the total exceeds the cap, Google budgets are scaled down proportionally
so the combined total fits. Meta budgets are not auto-scaled (growth's lane).
Exit codes: 0 = within cap, 2 = was over cap and got clamped (report loudly).
"""
import datetime as dt
import json
import os
import ssl
import sys
import urllib.parse
import urllib.request

import certifi
from google.ads.googleads.client import GoogleAdsClient

CUSTOMER_ID = "4959722800"
CAP_USD = 30.0
META_AD_ACCOUNT = "act_40885463"
META_API_VERSION = "v21.0"
META_API_BASE = f"https://graph.facebook.com/{META_API_VERSION}"


# ---------------------------------------------------------------------------
# Meta Graph API helpers
# ---------------------------------------------------------------------------

def _meta_get(path: str, params: dict, token: str) -> dict:
    """Make a GET request to the Graph API using Bearer auth (token never in URL)."""
    url = f"{META_API_BASE}/{path}?{urllib.parse.urlencode(params)}"
    ctx = ssl.create_default_context(cafile=certifi.where())
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
        return json.loads(resp.read().decode())


def meta_campaigns(token: str) -> list:
    """Return list of ACTIVE campaigns for the Meta ad account.

    Each entry is a Graph API campaign object with fields:
      id, name, status, daily_budget (cents str), lifetime_budget (cents str).
    """
    filtering = json.dumps(
        [{"field": "effective_status", "operator": "IN", "value": ["ACTIVE"]}]
    )
    data = _meta_get(
        f"{META_AD_ACCOUNT}/campaigns",
        {"fields": "id,name,status,daily_budget,lifetime_budget", "filtering": filtering},
        token,
    )
    if "error" in data:
        err = data["error"]
        print(
            f"FATAL: Meta Graph API error — {err.get('message', data['error'])} "
            f"(code {err.get('code', '?')}). Token may be expired."
        )
        sys.exit(1)
    return data.get("data", [])


def _meta_campaign_7d_spend(campaign_id: str, token: str) -> float:
    """Return average daily spend (USD) over the trailing 7 days for one campaign."""
    today = dt.date.today()
    since = today - dt.timedelta(days=7)
    until = today - dt.timedelta(days=1)  # yesterday = last full day
    time_range = json.dumps({"since": str(since), "until": str(until)})
    filtering = json.dumps(
        [{"field": "campaign.id", "operator": "IN", "value": [campaign_id]}]
    )
    data = _meta_get(
        f"{META_AD_ACCOUNT}/insights",
        {
            "fields": "spend,date_start,date_stop",
            "time_range": time_range,
            "level": "campaign",
            "filtering": filtering,
        },
        token,
    )
    if "error" in data:
        err = data["error"]
        print(
            f"  WARNING: could not fetch 7d insights for campaign {campaign_id}: "
            f"{err.get('message', data['error'])}"
        )
        return 0.0
    rows = data.get("data", [])
    if not rows:
        return 0.0
    total_spend = sum(float(r.get("spend", 0)) for r in rows)
    # Confirm date range from response if available
    if rows:
        date_start = rows[0].get("date_start", str(since))
        date_stop = rows[-1].get("date_stop", str(until))
        days_in_range = (
            dt.date.fromisoformat(date_stop) - dt.date.fromisoformat(date_start)
        ).days + 1
    else:
        days_in_range = 7
    return total_spend / max(days_in_range, 1)


# ---------------------------------------------------------------------------
# Meta section — must run BEFORE Google so we never show partial totals
# ---------------------------------------------------------------------------

meta_token = os.environ.get("META_ACCESS_TOKEN")
if not meta_token:
    print("Meta spend UNKNOWN — cap cannot be verified (META_ACCESS_TOKEN not set)")
    sys.exit(1)

campaigns = meta_campaigns(meta_token)

meta_daily = []    # ACTIVE campaigns with daily_budget
meta_lifetime = [] # ACTIVE campaigns with lifetime_budget (no daily cap)

for c in campaigns:
    db = c.get("daily_budget")
    lb = c.get("lifetime_budget")
    if db and db != "0":
        meta_daily.append(c)
    elif lb and lb != "0":
        meta_lifetime.append(c)
    # else: neither field set (shouldn't happen for active campaigns, skip)

print(f"Meta ACTIVE campaigns: {len(campaigns)}")

# Daily-budget campaigns — worst-case projection at 125% overdelivery
meta_daily_projected = 0.0
for c in meta_daily:
    budget_usd = int(c["daily_budget"]) / 100
    projected = budget_usd * 1.25
    meta_daily_projected += projected
    print(f"  [daily] {c['name']!r}: declared ${budget_usd:.2f}/day → worst-case ${projected:.2f}/day (×1.25)")

# Lifetime campaigns — fetch 7d trailing spend; do NOT add to cap total
print(f"Meta LIFETIME campaigns (no daily cap — Meta paces):")
if not meta_lifetime:
    print("  (none)")
for c in meta_lifetime:
    lb_usd = int(c["lifetime_budget"]) / 100
    avg_daily = _meta_campaign_7d_spend(c["id"], meta_token)
    print(
        f"  [lifetime] {c['name']!r}: lifetime budget ${lb_usd:.2f}, "
        f"avg 7d daily spend ${avg_daily:.2f}/day (informational — NOT in cap projection)"
    )

print(f"Meta daily-budget projected worst-case: ${meta_daily_projected:.2f}/day")

# ---------------------------------------------------------------------------
# Google section (unchanged logic)
# ---------------------------------------------------------------------------

client = GoogleAdsClient.load_from_storage("/Users/adnanakil/google-ads.yaml")
ga = client.get_service("GoogleAdsService")

rows = list(
    ga.search(
        customer_id=CUSTOMER_ID,
        query="""
        SELECT campaign.id, campaign.name, campaign.status,
               campaign_budget.resource_name, campaign_budget.amount_micros
        FROM campaign
        WHERE campaign.status = 'ENABLED'""",
    )
)

google_total = sum(r.campaign_budget.amount_micros for r in rows) / 1e6
print(f"\nGoogle enabled campaigns: {len(rows)}, total daily budget: ${google_total:.2f}")
for r in rows:
    print(f"  {r.campaign.id} {r.campaign.name!r}: ${r.campaign_budget.amount_micros / 1e6:.2f}/day")

# ---------------------------------------------------------------------------
# Combined cap check
# ---------------------------------------------------------------------------

total = google_total + meta_daily_projected
print(
    f"\nCombined projection: Google ${google_total:.2f} + Meta daily worst-case "
    f"${meta_daily_projected:.2f} = ${total:.2f} (cap ${CAP_USD:.2f})"
)

if total <= CAP_USD:
    print("OK: within cap")
    sys.exit(0)

# Over cap — scale Google budgets only; Meta is growth's lane
scale = CAP_USD / total
budget_svc = client.get_service("CampaignBudgetService")
ops = []
for r in rows:
    op = client.get_type("CampaignBudgetOperation")
    op.update.resource_name = r.campaign_budget.resource_name
    # floor to whole cents; rounding down keeps the clamped total under the cap
    op.update.amount_micros = int(r.campaign_budget.amount_micros * scale / 10_000) * 10_000
    op.update_mask.paths.append("amount_micros")
    ops.append(op)
budget_svc.mutate_campaign_budgets(customer_id=CUSTOMER_ID, operations=ops)
print(
    f"CLAMPED: combined total ${total:.2f} exceeded cap; "
    f"Google budgets scaled by {scale:.3f}"
)
print(
    "NOTE: Google budgets scaled to bring combined total under cap; "
    "Meta budgets unchanged (growth's lane)."
)
sys.exit(2)
