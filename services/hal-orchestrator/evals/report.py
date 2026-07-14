"""Quality-vs-cost report for the HAL eval suite.

Consumes the runner's results.json + the judge's grades.json + pricing.py and
writes a markdown report: per-model handled-rate (overall and per category),
hard-assertion pass rate, cost per turn, latency, and a projected monthly
cost extrapolated from real prod traffic volume.

Usage:
    python evals/report.py results.json grades.json --out evals/REPORT.md

Projection volume comes from prod hal_turns (read-only), via psql against
$HAL_PROD_DB_URL or $DATABASE_PUBLIC_URL — the URL carries a password, so it
is never hardcoded here. Offline fallback: --turns-per-day N. If neither is
available the projection section is skipped.

Handled-rate = handled / (handled + partial + failed). Grade "na" (judge or
harness failure) is excluded from the denominator, matching how prod
handled-rates are computed.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pricing import cost_of, has_pricing  # noqa: E402

RECOMMEND_WITHIN_POINTS = 3.0  # "cheapest within N points of best" threshold
BREAKS_GAP_POINTS = 10.0  # per-category gap that counts as "breaks here"


# --------------------------------------------------------------------------- #
# Aggregation (pure — unit-tested)
# --------------------------------------------------------------------------- #


def grade_key(rec: dict) -> str:
    return f"{rec.get('scenario_id', '?')}::{rec.get('model', '?')}"


def handled_rate(counts: dict[str, int]) -> float | None:
    """handled/(handled+partial+failed) as percent; None if no graded cases."""
    graded = sum(counts.get(g, 0) for g in ("handled", "partial", "failed"))
    if graded == 0:
        return None
    return 100.0 * counts.get("handled", 0) / graded


def aggregate(records: list[dict], grades: dict[str, dict]) -> dict[str, dict]:
    """Per-model rollup. Returns {model: {counts, rate, cat_counts, costs,
    latencies, assertions_passed, assertions_total, failures}}."""
    out: dict[str, dict] = {}
    for rec in records:
        model = rec.get("model", "?")
        m = out.setdefault(
            model,
            {
                "counts": {},
                "cat_counts": {},
                "costs": [],
                "latencies": [],
                "assertions_passed": 0,
                "assertions_total": 0,
                "failures": [],
            },
        )
        g = grades.get(grade_key(rec), {"grade": "na", "reason": "ungraded"})
        grade = g.get("grade", "na")
        m["counts"][grade] = m["counts"].get(grade, 0) + 1
        cat = rec.get("category", "uncategorized")
        cc = m["cat_counts"].setdefault(cat, {})
        cc[grade] = cc.get(grade, 0) + 1
        if grade in ("partial", "failed"):
            m["failures"].append(
                {
                    "scenario_id": rec.get("scenario_id", "?"),
                    "category": cat,
                    "grade": grade,
                    "reason": g.get("reason", ""),
                    "failure_category": g.get("failure_category"),
                }
            )
        asserts = rec.get("assertions") or {}
        passed = asserts.get("passed")
        failures = asserts.get("failures") or []
        if passed is not None:
            m["assertions_total"] += 1
            if passed and not failures:
                m["assertions_passed"] += 1
        usage = rec.get("usage") or {}
        if usage and has_pricing(model):
            m["costs"].append(cost_of(usage, model))
        if rec.get("latency_ms") is not None:
            m["latencies"].append(float(rec["latency_ms"]))
    for m in out.values():
        m["rate"] = handled_rate(m["counts"])
    return out


def recommend(agg: dict[str, dict], mean_costs: dict[str, float]) -> dict | None:
    """Cheapest model within RECOMMEND_WITHIN_POINTS of the best handled-rate.
    Only models with both a rate and a mean cost are eligible."""
    scored = {
        m: a["rate"]
        for m, a in agg.items()
        if a["rate"] is not None and m in mean_costs
    }
    if not scored:
        return None
    best_model = max(scored, key=lambda m: scored[m])
    best_rate = scored[best_model]
    eligible = {
        m: r for m, r in scored.items() if best_rate - r <= RECOMMEND_WITHIN_POINTS
    }
    pick = min(eligible, key=lambda m: mean_costs[m])
    return {
        "best_model": best_model,
        "best_rate": best_rate,
        "pick": pick,
        "pick_rate": scored[pick],
        "pick_cost": mean_costs[pick],
    }


def weak_categories(
    agg: dict[str, dict], model: str, best_model: str
) -> list[tuple[str, float, float]]:
    """Categories where `model` trails `best_model` by more than the gap
    threshold. Returns (category, model_rate, best_rate) tuples."""
    out = []
    for cat, counts in agg.get(model, {}).get("cat_counts", {}).items():
        r = handled_rate(counts)
        best = handled_rate(agg.get(best_model, {}).get("cat_counts", {}).get(cat, {}))
        if r is not None and best is not None and best - r > BREAKS_GAP_POINTS:
            out.append((cat, r, best))
    return sorted(out, key=lambda t: t[2] - t[1], reverse=True)


def paired_vs_baseline(
    records: list[dict], grades: dict[str, dict], baseline: str
) -> list[dict]:
    """Sign-test read of each model against the baseline on shared scenarios.
    Win = model handled a scenario the baseline didn't (partial/failed);
    loss = the reverse. Concordant scenarios (both handled / both not) carry
    no signal and are dropped, as are pairs with an na on either side. p is
    the two-sided exact binomial over the discordant pairs (null: 50/50)."""
    from math import comb

    by_model_scen: dict[str, dict[str, str]] = {}
    for rec in records:
        g = grades.get(grade_key(rec), {}).get("grade", "na")
        by_model_scen.setdefault(rec.get("model", "?"), {})[
            rec.get("scenario_id", "?")
        ] = g
    base = by_model_scen.get(baseline, {})
    out: list[dict] = []
    for model, scen in sorted(by_model_scen.items()):
        if model == baseline:
            continue
        wins = losses = 0
        for sid, g in scen.items():
            b = base.get(sid)
            if b is None or g == "na" or b == "na":
                continue
            model_handled, base_handled = g == "handled", b == "handled"
            if model_handled and not base_handled:
                wins += 1
            elif base_handled and not model_handled:
                losses += 1
        n = wins + losses
        if n:
            k = max(wins, losses)
            p: float | None = min(
                1.0, 2 * sum(comb(n, i) for i in range(k, n + 1)) / 2**n
            )
        else:
            p = None
        out.append({"model": model, "wins": wins, "losses": losses, "p": p})
    return out


# --------------------------------------------------------------------------- #
# Prod volume (read-only)
# --------------------------------------------------------------------------- #


def prod_turns_per_day() -> float | None:
    url = os.environ.get("HAL_PROD_DB_URL") or os.environ.get("DATABASE_PUBLIC_URL")
    if not url:
        return None
    try:
        out = subprocess.run(
            [
                "psql",
                url,
                "-Atc",
                "select round(count(*)::numeric / 14, 1) from hal_turns "
                "where created_at > now() - interval '14 days'",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if out.returncode == 0 and out.stdout.strip():
            return float(out.stdout.strip())
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return None


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


def fmt_rate(r: float | None) -> str:
    return f"{r:.1f}%" if r is not None else "—"


def render(
    records: list[dict],
    grades: dict[str, dict],
    turns_per_day: float | None,
    baseline: str | None = None,
    note: str = "",
) -> str:
    agg = aggregate(records, grades)
    models = sorted(agg, key=lambda m: -(agg[m]["rate"] or 0))
    mean_costs = {
        m: statistics.mean(a["costs"]) for m, a in agg.items() if a["costs"]
    }

    lines = ["# HAL Eval Report", ""]
    n_scenarios = len({r.get("scenario_id") for r in records})
    lines.append(
        f"{len(records)} runs — {n_scenarios} scenarios x {len(models)} models. "
        "Judge: fixed model, blind to candidate identity. Handled-rate "
        "excludes na (judge/harness failures)."
    )
    if note:
        lines += ["", note]
    lines += ["", "## Overall", ""]
    lines.append(
        "| Model | Handled | Partial | Failed | na | Handled-rate | "
        "Asserts | Mean $/turn | Median $/turn | Mean latency |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for m in models:
        a = agg[m]
        c = a["counts"]
        asserts = (
            f"{a['assertions_passed']}/{a['assertions_total']}"
            if a["assertions_total"]
            else "—"
        )
        mean_c = f"${statistics.mean(a['costs']):.4f}" if a["costs"] else "—"
        med_c = f"${statistics.median(a['costs']):.4f}" if a["costs"] else "—"
        lat = (
            f"{statistics.mean(a['latencies']) / 1000:.1f}s"
            if a["latencies"]
            else "—"
        )
        lines.append(
            f"| {m} | {c.get('handled', 0)} | {c.get('partial', 0)} | "
            f"{c.get('failed', 0)} | {c.get('na', 0)} | {fmt_rate(a['rate'])} | "
            f"{asserts} | {mean_c} | {med_c} | {lat} |"
        )

    # Per-category handled-rates
    cats = sorted({r.get("category", "uncategorized") for r in records})
    lines += ["", "## Handled-rate by category", ""]
    lines.append("| Category | " + " | ".join(models) + " |")
    lines.append("|---|" + "---|" * len(models))
    for cat in cats:
        row = [cat]
        for m in models:
            row.append(fmt_rate(handled_rate(agg[m]["cat_counts"].get(cat, {}))))
        lines.append("| " + " | ".join(row) + " |")

    # Paired significance vs baseline
    if baseline and baseline in agg:
        lines += ["", f"## Paired comparison vs {baseline}", ""]
        lines.append(
            "Discordant scenarios only (one model handled it, the other "
            "didn't); p = two-sided exact binomial. Small n means most gaps "
            "here are within noise — treat p < 0.05 as real signal."
        )
        lines += ["", "| Model | Wins | Losses | p |", "|---|---|---|---|"]
        for row in paired_vs_baseline(records, grades, baseline):
            p_str = f"{row['p']:.3f}" if row["p"] is not None else "—"
            lines.append(
                f"| {row['model']} | {row['wins']} | {row['losses']} | {p_str} |"
            )

    # Projection
    lines += ["", "## Projected monthly cost", ""]
    if turns_per_day is not None and mean_costs:
        lines.append(
            f"Prod volume: **{turns_per_day:.0f} turns/day** (hal_turns, "
            "trailing 14 days). Projection = mean eval cost/turn x volume x 30. "
            "Eval turns skew heavier than prod (fixtures force tool loops), so "
            "treat these as an upper bound for ranking, not a bill forecast."
        )
        lines += ["", "| Model | Mean $/turn | $/day | $/month |", "|---|---|---|---|"]
        for m in models:
            if m not in mean_costs:
                continue
            day = mean_costs[m] * turns_per_day
            lines.append(
                f"| {m} | ${mean_costs[m]:.4f} | ${day:.2f} | ${day * 30:.2f} |"
            )
    elif turns_per_day is None:
        lines.append(
            "_Skipped — no prod volume: set HAL_PROD_DB_URL (or "
            "DATABASE_PUBLIC_URL) for a live hal_turns count, or pass "
            "--turns-per-day N._"
        )
    else:
        lines.append(
            "_Skipped — no cost data: none of the evaluated models have "
            "usage + pricing (see evals/pricing.py)._"
        )

    # Recommendation
    rec = recommend(agg, mean_costs)
    lines += ["", "## Recommendation", ""]
    if rec is None:
        lines.append("_Not enough graded+priced data to recommend._")
    else:
        if rec["pick"] == rec["best_model"]:
            lines.append(
                f"**{rec['best_model']}** is both the best-scoring "
                f"({fmt_rate(rec['best_rate'])}) and the cheapest eligible model."
            )
        else:
            lines.append(
                f"Cheapest model within {RECOMMEND_WITHIN_POINTS:.0f} points of "
                f"best: **{rec['pick']}** ({fmt_rate(rec['pick_rate'])} vs "
                f"{rec['best_model']} at {fmt_rate(rec['best_rate'])}) at "
                f"${rec['pick_cost']:.4f}/turn."
            )
        weak = weak_categories(agg, rec["pick"], rec["best_model"])
        if weak:
            lines += ["", f"### Where {rec['pick']} breaks", ""]
            for cat, r, best in weak:
                lines.append(
                    f"- **{cat}**: {fmt_rate(r)} vs {fmt_rate(best)} on "
                    f"{rec['best_model']}"
                )

    # Failure detail
    lines += ["", "## Failures (partial + failed)", ""]
    any_fail = False
    for m in models:
        fails = agg[m]["failures"]
        if not fails:
            continue
        any_fail = True
        lines.append(f"### {m}")
        for f in fails:
            lines.append(
                f"- `{f['scenario_id']}` [{f['category']}] {f['grade']} "
                f"({f['failure_category']}): {f['reason']}"
            )
        lines.append("")
    if not any_fail:
        lines.append("_None._")

    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("results")
    ap.add_argument("grades")
    ap.add_argument("--out", default="evals/REPORT.md")
    ap.add_argument("--turns-per-day", type=float, default=None)
    ap.add_argument(
        "--baseline",
        default=None,
        help="model id for the paired discordant-scenario comparison section",
    )
    ap.add_argument(
        "--note", default="", help="extra markdown paragraph under the title"
    )
    args = ap.parse_args()

    with open(args.results) as f:
        records = json.load(f)
    with open(args.grades) as f:
        grades = json.load(f)

    tpd = args.turns_per_day if args.turns_per_day is not None else prod_turns_per_day()
    md = render(records, grades, tpd, baseline=args.baseline, note=args.note)
    with open(args.out, "w") as f:
        f.write(md)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
