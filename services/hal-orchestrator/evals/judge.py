"""LLM judge for the HAL eval suite.

Grades each candidate reply against the scenario's rubric on a FIXED model
(claude-fable-5 — the same model as prod's nightly overseer), so grades are
comparable across the candidate models being evaluated. The judge is BLIND to
which model produced a reply: the prompt carries the scenario, rubric, tool
trace, and reply — never the model id.

Rubric mirrors the prod nightly grader (GROWTH.md stage 2): grade is
handled | partial | failed, so eval handled-rates line up with prod
handled-rates. Failure categories use the eval suite's slugs (a superset
split of prod's) for sharper cost-reduction diagnostics.

Usage:
    python evals/judge.py results.json --out grades.json

results.json: list of records with at least
    {scenario_id, category, model, description?, expect?, reply, silent,
     tool_trace, assertions?}
grades.json: {"<scenario_id>::<model>": {grade, reason, failure_category}}

A judge failure (API error, refusal, bad JSON after retries) records grade
"na" for that case and never crashes the batch. The Anthropic key is read
from ANTHROPIC_API_KEY or pulled at runtime from the hal-orchestrator Railway
service — never from a file in the repo.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys

import httpx

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
JUDGE_MODEL = os.environ.get("EVAL_JUDGE_MODEL", "claude-fable-5")
# medium keeps a 250-case batch affordable; bump via env for a final run.
JUDGE_EFFORT = os.environ.get("EVAL_JUDGE_EFFORT", "medium")
_RETRYABLE = {429, 500, 503, 529}
_BACKOFF = [5, 10, 20]
_CONCURRENCY = 4

GRADES = ("handled", "partial", "failed")
CATEGORIES = (
    "bad_judgment",
    "infra_error",
    "missed_tool",
    "verbosity",
    "hallucination",
    "other",
)

# Structured output schema — the API guarantees the reply parses to this.
GRADE_SCHEMA = {
    "type": "object",
    "properties": {
        "grade": {"type": "string", "enum": list(GRADES)},
        "reason": {"type": "string"},
        "failure_category": {
            "anyOf": [
                {"type": "string", "enum": list(CATEGORIES)},
                {"type": "null"},
            ]
        },
    },
    "required": ["grade", "reason", "failure_category"],
    "additionalProperties": False,
}

SYSTEM = """\
You grade one turn of HAL, a personal iMessage assistant. Grade ONLY the \
turn shown, against the expected behavior. Rubric (mirror of the production \
nightly grader):

- handled: did what the situation required — matches the expected behavior \
in substance (wording may differ), correct tool usage, no fabrication, \
appropriate length for a text message.
- partial: genuinely helped but missed a piece — a wrong detail, an \
unnecessary question, a skipped step, noticeable bloat, or claimed more \
certainty than the tool trace supports.
- failed: wrong, ignored the ask, fabricated success (said it did something \
the tool trace doesn't show), spoke when silence was required, or stayed \
silent when a reply was required.

failure_category (null when grade=handled): bad_judgment (wrong call on \
what to do), infra_error (a tool errored and the reply degraded), \
missed_tool (should have called a tool it didn't), verbosity (right answer \
buried in bloat), hallucination (asserted something unsupported by the \
trace), other.

One-line reason. Judge the substance, not the style, unless style was the \
ask."""


def load_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key
    out = subprocess.run(
        ["railway", "variables", "--service", "hal-orchestrator", "--kv"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    for line in out.stdout.splitlines():
        if line.startswith("ANTHROPIC_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit(
        "No ANTHROPIC_API_KEY in env and none found via railway variables"
    )


def parse_grade(text: str) -> dict:
    """Strict-parse a judge reply into {grade, reason, failure_category}.
    Tolerates fenced/prefixed junk around one JSON object; anything that
    doesn't yield a valid grade raises ValueError."""
    s = text.strip()
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"no JSON object in judge reply: {text[:120]!r}")
    data = json.loads(s[start : end + 1])
    grade = data.get("grade")
    if grade not in GRADES:
        raise ValueError(f"bad grade {grade!r}")
    cat = data.get("failure_category")
    if grade == "handled":
        cat = None
    elif cat not in CATEGORIES:
        cat = "other"
    return {
        "grade": grade,
        "reason": str(data.get("reason", ""))[:300],
        "failure_category": cat,
    }


def _fmt_trace(trace: list) -> str:
    if not trace:
        return "(no tool calls)"
    lines = []
    for i, step in enumerate(trace, 1):
        if isinstance(step, dict):
            name = step.get("tool") or step.get("name") or "?"
            args = json.dumps(step.get("args", {}), default=str)[:300]
            result = str(step.get("result", ""))[:300]
            lines.append(f"{i}. {name}({args}) -> {result}")
        else:
            lines.append(f"{i}. {step}")
    return "\n".join(lines)


def build_case_prompt(rec: dict) -> str:
    expect = rec.get("expect") or {}
    silent_expected = bool(expect.get("silent_expected") or expect.get("silent_ok"))
    reply = (rec.get("reply") or "").strip()
    assertions = rec.get("assertions") or {}
    failures = assertions.get("failures") or []
    parts = [
        f"SITUATION:\n{rec.get('description', '(none)')}",
        f"EXPECTED BEHAVIOR:\n{expect.get('reply_should', '(none stated)')}",
        f"SILENCE EXPECTED: {'yes' if silent_expected else 'no'}",
        f"TOOL TRACE (ordered):\n{_fmt_trace(rec.get('tool_trace') or [])}",
        "ACTUAL REPLY:\n" + (reply if reply else "[stayed silent]"),
    ]
    # The trace records calls but not returns; without the canned fixture
    # outputs the judge can misread a fixture-grounded reply as fabrication.
    fixtures = rec.get("tool_fixtures") or {}
    if fixtures:
        parts.insert(
            4,
            "CANNED TOOL OUTPUTS (what the fixtured tools returned to the "
            "model — treat as the ground-truth data it had):\n"
            + "\n".join(f"- {t}: {v}" for t, v in fixtures.items()),
        )
    if failures:
        parts.append(
            "HARD-ASSERTION FAILURES (mechanically verified):\n- "
            + "\n- ".join(str(f) for f in failures)
        )
    return "\n\n".join(parts)


async def judge_one(client: httpx.AsyncClient, api_key: str, rec: dict) -> dict:
    body = {
        "model": JUDGE_MODEL,
        "max_tokens": 8192,
        "system": SYSTEM,
        "output_config": {
            "effort": JUDGE_EFFORT,
            "format": {"type": "json_schema", "schema": GRADE_SCHEMA},
        },
        "messages": [{"role": "user", "content": build_case_prompt(rec)}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    last_err = "unknown"
    for attempt in range(3):
        try:
            resp = await client.post(
                ANTHROPIC_URL, headers=headers, json=body, timeout=180
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("stop_reason") == "refusal":
                    return {
                        "grade": "na",
                        "reason": "judge refusal",
                        "failure_category": None,
                    }
                text = "".join(
                    b.get("text", "")
                    for b in data.get("content", [])
                    if b.get("type") == "text"
                )
                return parse_grade(text)
            last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
            if resp.status_code in _RETRYABLE and attempt < 2:
                await asyncio.sleep(_BACKOFF[attempt])
                continue
            break
        except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
            last_err = f"{type(exc).__name__}: {exc}"
            if attempt < 2:
                await asyncio.sleep(_BACKOFF[attempt])
    return {
        "grade": "na",
        "reason": f"judge error: {last_err}"[:300],
        "failure_category": None,
    }


async def run(records: list[dict]) -> dict[str, dict]:
    api_key = load_api_key()
    sem = asyncio.Semaphore(_CONCURRENCY)
    grades: dict[str, dict] = {}

    async with httpx.AsyncClient() as client:

        async def work(rec: dict) -> None:
            key = f"{rec.get('scenario_id', '?')}::{rec.get('model', '?')}"
            if rec.get("error") and not (rec.get("reply") or "").strip():
                # The harness itself failed — nothing to grade.
                grades[key] = {
                    "grade": "na",
                    "reason": f"harness error: {rec['error']}"[:300],
                    "failure_category": None,
                }
                return
            async with sem:
                grades[key] = await judge_one(client, api_key, rec)
            done = grades[key]
            print(f"  {key}: {done['grade']} — {done['reason'][:80]}")

        await asyncio.gather(*(work(r) for r in records))
    return grades


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("results", help="results.json from the eval runner")
    ap.add_argument("--out", default="grades.json")
    args = ap.parse_args()

    with open(args.results) as f:
        records = json.load(f)
    if not isinstance(records, list):
        sys.exit("results.json must be a JSON array of records")

    print(f"Judging {len(records)} cases on {JUDGE_MODEL} (effort={JUDGE_EFFORT})")
    grades = asyncio.run(run(records))
    with open(args.out, "w") as f:
        json.dump(grades, f, indent=2, sort_keys=True)
    counts: dict[str, int] = {}
    for g in grades.values():
        counts[g["grade"]] = counts.get(g["grade"], 0) + 1
    print(f"Wrote {args.out}: {counts}")


if __name__ == "__main__":
    main()
