"""Hard $30/day cap across all paid channels. Run at start AND end of every growth session.

Sums daily budgets of ENABLED Google Ads campaigns in the operating account; if the
total exceeds the cap, budgets are scaled down proportionally so the total fits.
Exit codes: 0 = within cap, 2 = was over cap and got clamped (report loudly).
"""
import sys

from google.ads.googleads.client import GoogleAdsClient

CUSTOMER_ID = "4959722800"
CAP_USD = 30.0

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

total = sum(r.campaign_budget.amount_micros for r in rows) / 1e6
print(f"enabled campaigns: {len(rows)}, total daily budget: ${total:.2f} (cap ${CAP_USD:.2f})")
for r in rows:
    print(f"  {r.campaign.id} {r.campaign.name!r}: ${r.campaign_budget.amount_micros / 1e6:.2f}/day")

if total <= CAP_USD:
    print("OK: within cap")
    sys.exit(0)

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
print(f"CLAMPED: total ${total:.2f} exceeded cap; all enabled budgets scaled by {scale:.3f}")
sys.exit(2)
