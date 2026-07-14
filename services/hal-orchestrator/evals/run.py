"""Eval runner CLI.

  uv run python evals/run.py --models gpt-5.6-luna,claude-sonnet-5 \
      --scenarios 'evals/scenarios/*.yaml' --out evals/results.json

Runs every scenario against every model sequentially through the real
/api/message pipeline (see harness.py), evaluates hard assertions, and writes
one JSON record per (scenario, model). API keys are pulled from the current
env, falling back to `railway variables --service hal-orchestrator --kv`
(never written to disk).
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")
_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-db"))
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-common"))

from evals.harness import EVAL_DB_URL, prepare_env  # noqa: E402

KEY_VARS = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY")


def ensure_api_keys() -> None:
    missing = [k for k in KEY_VARS if not os.environ.get(k)]
    if not missing:
        return
    try:
        out = subprocess.run(
            ["railway", "variables", "--service", "hal-orchestrator", "--kv"],
            capture_output=True, text=True, timeout=60, check=True,
        ).stdout
    except Exception as exc:  # noqa: BLE001
        print(f"warning: could not pull keys from railway ({exc}); "
              f"missing: {missing}", file=sys.stderr)
        return
    for line in out.splitlines():
        key, _, value = line.partition("=")
        if key in missing and value:
            os.environ[key] = value.strip()


def load_scenarios(pattern: str, categories: set[str] | None) -> list[dict]:
    import yaml

    scenarios: list[dict] = []
    for path in sorted(glob.glob(pattern)):
        with open(path) as f:
            doc = yaml.safe_load(f)
        docs = doc if isinstance(doc, list) else [doc]
        for scenario in docs:
            if not scenario or "id" not in scenario:
                print(f"warning: skipping malformed scenario in {path}", file=sys.stderr)
                continue
            if categories and scenario.get("category") not in categories:
                continue
            scenarios.append(scenario)
    return scenarios


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run HAL behavior evals")
    parser.add_argument("--models", required=True, help="comma-separated model ids")
    parser.add_argument("--scenarios", default="evals/scenarios/*.yaml")
    parser.add_argument("--categories", default="", help="comma-separated filter")
    parser.add_argument("--out", default="evals/results.json")
    parser.add_argument("--db", default=EVAL_DB_URL)
    args = parser.parse_args()

    ensure_api_keys()
    prepare_env(args.db)

    from evals.harness import EvalHarness  # after prepare_env

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    categories = {c.strip() for c in args.categories.split(",") if c.strip()} or None
    scenarios = load_scenarios(args.scenarios, categories)
    if not scenarios:
        print(f"no scenarios matched {args.scenarios}", file=sys.stderr)
        return 1
    print(f"{len(scenarios)} scenario(s) x {len(models)} model(s)")

    harness = EvalHarness()
    await harness.start()
    records: list[dict] = []
    try:
        for model in models:
            for scenario in scenarios:
                await harness.seed(scenario)
                result = await harness.run_turn(scenario, model)
                record = result.to_record()
                # Judge context: the grader needs the scenario's intent and
                # rubric alongside the transcript (see judge.py's record shape).
                record["description"] = scenario.get("description", "")
                record["expect"] = scenario.get("expect", {})
                record["tool_fixtures"] = scenario.get("tool_fixtures", {})
                records.append(record)
                status = (
                    "ERROR" if result.error
                    else ("pass" if result.assertions.get("passed") else "FAIL")
                )
                print(
                    f"[{model}] {scenario['id']}: {status} "
                    f"({result.latency_ms}ms, tools={[t['tool'] for t in result.tool_trace]})"
                )
                if result.error:
                    print(f"    {result.error}")
                for failure in result.assertions.get("failures", []):
                    print(f"    assert: {failure}")
    finally:
        await harness.stop()

    with open(args.out, "w") as f:
        json.dump(records, f, indent=1)
    print(f"\nwrote {len(records)} records to {args.out}")

    for model in models:
        mine = [r for r in records if r["model"] == model and not r["error"]]
        errors = sum(1 for r in records if r["model"] == model and r["error"])
        passed = sum(1 for r in mine if r["assertions"]["passed"])
        print(f"{model}: {passed}/{len(mine)} hard-assert pass, {errors} errors")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
