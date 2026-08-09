"""Google Ads operations CLI for the growth team (account 4959722800 only).

Commands:
  show                          campaigns + budgets + last-7d stats
  set-budget <campaign_id> <usd>
  pause <campaign_id> | enable <campaign_id>
  add-keywords <ad_group_id> "kw" ["kw" ...] [--match PHRASE|EXACT|BROAD]
  pause-keyword <ad_group_id> <criterion_id>
  search-terms <campaign_id>    search-term report, last 7 days
"""
import argparse

from google.ads.googleads.client import GoogleAdsClient

CUSTOMER_ID = "4959722800"


def _client():
    return GoogleAdsClient.load_from_storage("/Users/adnanakil/google-ads.yaml")


def show(_args):
    client = _client()
    ga = client.get_service("GoogleAdsService")
    print("== campaigns ==")
    for r in ga.search(
        customer_id=CUSTOMER_ID,
        query="""
        SELECT campaign.id, campaign.name, campaign.status,
               campaign_budget.amount_micros, metrics.impressions, metrics.clicks,
               metrics.cost_micros, metrics.ctr
        FROM campaign WHERE segments.date DURING LAST_7_DAYS""",
    ):
        m = r.metrics
        print(
            f"  {r.campaign.id} {r.campaign.name!r} [{r.campaign.status.name}] "
            f"${r.campaign_budget.amount_micros / 1e6:.2f}/day | 7d: "
            f"{m.impressions} impr, {m.clicks} clicks, ${m.cost_micros / 1e6:.2f}, ctr {m.ctr:.2%}"
        )
    print("== keywords (enabled, last 7d) ==")
    for r in ga.search(
        customer_id=CUSTOMER_ID,
        query="""
        SELECT ad_group.id, ad_group_criterion.criterion_id,
               ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type,
               metrics.impressions, metrics.clicks, metrics.cost_micros
        FROM keyword_view
        WHERE segments.date DURING LAST_7_DAYS
          AND ad_group_criterion.status = 'ENABLED'""",
    ):
        c, m = r.ad_group_criterion, r.metrics
        print(
            f"  ag {r.ad_group.id} crit {c.criterion_id} {c.keyword.text!r} "
            f"[{c.keyword.match_type.name}] {m.impressions} impr, {m.clicks} clicks, "
            f"${m.cost_micros / 1e6:.2f}"
        )


def set_budget(args):
    client = _client()
    ga = client.get_service("GoogleAdsService")
    rows = list(
        ga.search(
            customer_id=CUSTOMER_ID,
            query=f"""
            SELECT campaign.id, campaign_budget.resource_name, campaign_budget.amount_micros
            FROM campaign WHERE campaign.id = {int(args.campaign_id)}""",
        )
    )
    assert rows, f"campaign {args.campaign_id} not found"
    op = client.get_type("CampaignBudgetOperation")
    op.update.resource_name = rows[0].campaign_budget.resource_name
    op.update.amount_micros = int(round(float(args.usd) * 1e6))
    op.update_mask.paths.append("amount_micros")
    client.get_service("CampaignBudgetService").mutate_campaign_budgets(
        customer_id=CUSTOMER_ID, operations=[op]
    )
    print(f"budget for {args.campaign_id}: ${float(args.usd):.2f}/day")
    print("REMINDER: run budget_guard.py now")


def _set_campaign_status(campaign_id, status_name):
    client = _client()
    op = client.get_type("CampaignOperation")
    op.update.resource_name = f"customers/{CUSTOMER_ID}/campaigns/{int(campaign_id)}"
    op.update.status = client.enums.CampaignStatusEnum[status_name]
    op.update_mask.paths.append("status")
    client.get_service("CampaignService").mutate_campaigns(
        customer_id=CUSTOMER_ID, operations=[op]
    )
    print(f"campaign {campaign_id} -> {status_name}")


def add_keywords(args):
    client = _client()
    ops = []
    for kw in args.keywords:
        op = client.get_type("AdGroupCriterionOperation")
        c = op.create
        c.ad_group = f"customers/{CUSTOMER_ID}/adGroups/{int(args.ad_group_id)}"
        c.status = client.enums.AdGroupCriterionStatusEnum.ENABLED
        c.keyword.text = kw
        c.keyword.match_type = client.enums.KeywordMatchTypeEnum[args.match]
        ops.append(op)
    res = client.get_service("AdGroupCriterionService").mutate_ad_group_criteria(
        customer_id=CUSTOMER_ID, operations=ops
    )
    for r in res.results:
        print("added:", r.resource_name)


def pause_keyword(args):
    client = _client()
    op = client.get_type("AdGroupCriterionOperation")
    op.update.resource_name = (
        f"customers/{CUSTOMER_ID}/adGroupCriteria/"
        f"{int(args.ad_group_id)}~{int(args.criterion_id)}"
    )
    op.update.status = client.enums.AdGroupCriterionStatusEnum.PAUSED
    op.update_mask.paths.append("status")
    client.get_service("AdGroupCriterionService").mutate_ad_group_criteria(
        customer_id=CUSTOMER_ID, operations=[op]
    )
    print(f"keyword {args.criterion_id} paused")


def add_negatives(args):
    """Add campaign-level negative keywords (BROAD match) to block unwanted queries."""
    client = _client()
    ops = []
    for kw in args.keywords:
        op = client.get_type("CampaignCriterionOperation")
        c = op.create
        c.campaign = f"customers/{CUSTOMER_ID}/campaigns/{int(args.campaign_id)}"
        c.negative = True
        c.keyword.text = kw
        c.keyword.match_type = client.enums.KeywordMatchTypeEnum.BROAD
        ops.append(op)
    res = client.get_service("CampaignCriterionService").mutate_campaign_criteria(
        customer_id=CUSTOMER_ID, operations=ops
    )
    for r in res.results:
        print("added negative:", r.resource_name)


def search_terms(args):
    client = _client()
    ga = client.get_service("GoogleAdsService")
    for r in ga.search(
        customer_id=CUSTOMER_ID,
        query=f"""
        SELECT search_term_view.search_term, metrics.impressions, metrics.clicks,
               metrics.cost_micros
        FROM search_term_view
        WHERE segments.date DURING LAST_7_DAYS AND campaign.id = {int(args.campaign_id)}
        ORDER BY metrics.impressions DESC""",
    ):
        m = r.metrics
        print(
            f"  {r.search_term_view.search_term!r}: {m.impressions} impr, "
            f"{m.clicks} clicks, ${m.cost_micros / 1e6:.2f}"
        )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show")
    sp = sub.add_parser("set-budget")
    sp.add_argument("campaign_id")
    sp.add_argument("usd")
    for name in ("pause", "enable"):
        sp = sub.add_parser(name)
        sp.add_argument("campaign_id")
    sp = sub.add_parser("add-keywords")
    sp.add_argument("ad_group_id")
    sp.add_argument("keywords", nargs="+")
    sp.add_argument("--match", default="PHRASE", choices=["PHRASE", "EXACT", "BROAD"])
    sp = sub.add_parser("pause-keyword")
    sp.add_argument("ad_group_id")
    sp.add_argument("criterion_id")
    sp = sub.add_parser("add-negatives")
    sp.add_argument("campaign_id")
    sp.add_argument("keywords", nargs="+")
    sp = sub.add_parser("search-terms")
    sp.add_argument("campaign_id")
    args = p.parse_args()
    if args.cmd == "show":
        show(args)
    elif args.cmd == "set-budget":
        set_budget(args)
    elif args.cmd == "pause":
        _set_campaign_status(args.campaign_id, "PAUSED")
    elif args.cmd == "enable":
        _set_campaign_status(args.campaign_id, "ENABLED")
        print("REMINDER: run budget_guard.py now")
    elif args.cmd == "add-keywords":
        add_keywords(args)
    elif args.cmd == "add-negatives":
        add_negatives(args)
    elif args.cmd == "pause-keyword":
        pause_keyword(args)
    elif args.cmd == "search-terms":
        search_terms(args)


if __name__ == "__main__":
    main()
