"""Eval harness — drive HAL's REAL /api/message pipeline in-process.

Runs scenarios through the actual FastAPI app (ASGI transport, no server, no
background daemons) against a LOCAL Postgres, with a per-scenario model
override, so candidate models can be compared on identical inputs.

Fidelity model:
- The full production turn runs: system prompt assembly, playbook, profiles,
  memories, conversation history, the tool loop, critic, suppressors.
- Tools are default-DENY for anything that could touch the network. A
  scenario's `tool_fixtures` supply canned outputs; `REAL_TOOLS` (baby,
  memory, reminders, contacts…) execute for real against the eval DB so
  args-assertions check genuine writes. Everything else returns an eval-stub
  string. The choke point is `action_policy.authorize_tool`, which EVERY
  dispatch passes through at call time (returning a string short-circuits the
  tool with that string as its result) — so specialist sub-loops are covered
  too, with no prod code edits.
- `current_time` is frozen from the scenario's `now`. Known compromise: any
  date the system prompt derives from the wall clock still uses the real
  clock — scenarios should reason via the tool, not the prompt date.
- Token usage is captured from the providers' structlog events (openai.usage /
  claude.usage), split into candidate-model usage vs other (background) model
  usage. Native-Gemini calls emit no usage event today; gemini candidates are
  also blocked on depleted credits, so that's academic for now.

IMPORTANT: call `prepare_env()` BEFORE importing anything from
hal_orchestrator — settings are constructed at import time from os.environ.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

EVAL_DB_URL = os.environ.get(
    "EVAL_DATABASE_URL", "postgresql+asyncpg://adnanakil@localhost:5432/hal_evals"
)
EVAL_BRIDGE_SECRET = "eval-secret"

# Tools allowed to execute for real (local DB only — no network).
REAL_TOOLS = {
    "baby",
    "memory",
    "set_reminder",
    "contacts",
    "profile",
    "recall_history",
    "group_quiet",
    "helpful_mode",
    "trip",
    "skill",
    "schedule",
    "send_message",  # writes to the in-memory/durable outbox, never the network
}

USAGE_EVENTS = {"openai.usage", "claude.usage", "gemini.usage", "glm.usage"}

_FORBIDDEN_DB_HOSTS = ("railway", "rlwy.net", "proxy")


def prepare_env(db_url: str = EVAL_DB_URL) -> None:
    """Set the process env for an eval run. MUST run before hal imports."""
    for host_fragment in _FORBIDDEN_DB_HOSTS:
        if host_fragment in db_url:
            raise RuntimeError(f"refusing non-local eval DB: {db_url[:40]}...")
    from cryptography.fernet import Fernet

    os.environ["DATABASE_URL"] = db_url
    os.environ["ENVIRONMENT"] = "development"
    os.environ["HAL_PROCESS_ROLE"] = "api"  # no background daemons
    os.environ["WORKER_LEADER_LOCK_ENABLED"] = "false"
    os.environ["HAL_BRIDGE_SECRET"] = EVAL_BRIDGE_SECRET
    os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
    os.environ.setdefault("CARD_SIGNING_KEY", "eval-card-signing-key")
    # Pin the always-on machinery (critic, summarizer prompts fired mid-turn)
    # to one FIXED funded model so its behavior is identical for every
    # candidate; its tokens are reported separately as usage_other.
    os.environ.setdefault("GEMINI_BACKGROUND_MODEL", "claude-haiku-4-5")
    os.environ.setdefault("GEMINI_FLASH_MODEL", "claude-haiku-4-5")
    # No failover during evals: a candidate that fails should FAIL the run,
    # not silently grade a fallback model's answer.
    os.environ["MODEL_FALLBACKS"] = ""
    os.environ.setdefault("BROWSER_SERVICE_URL", "")


@dataclass
class TurnResult:
    scenario_id: str
    category: str
    model: str
    reply: str = ""
    silent: bool = False
    tool_trace: list[dict] = field(default_factory=list)
    assertions: dict = field(default_factory=dict)
    usage: dict = field(default_factory=dict)
    usage_other: dict = field(default_factory=dict)
    latency_ms: int = 0
    error: str | None = None

    def to_record(self) -> dict:
        return {
            "scenario_id": self.scenario_id,
            "category": self.category,
            "model": self.model,
            "reply": self.reply,
            "silent": self.silent,
            "tool_trace": self.tool_trace,
            "assertions": self.assertions,
            "usage": self.usage,
            "usage_other": self.usage_other,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


class EvalHarness:
    """One instance per run. Sequential turns only (trace/usage capture is
    process-global, matching how the app itself serializes silo turns)."""

    def __init__(self) -> None:
        self._client = None
        self._engine = None
        self._session_factory = None
        self._orig_authorize = None
        self._fixtures: dict[str, str] = {}
        self._frozen_now: datetime | None = None
        self._trace: list[dict] = []
        self._usage_events: list[dict] = []

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        import httpx

        import hal_orchestrator.state as state
        from ag_db.session import create_engine_and_session

        # Importing main configures structlog and builds settings from env.
        from hal_orchestrator.main import create_app

        app = create_app()
        self._engine, self._session_factory = create_engine_and_session(
            state.settings.database_url, pool_size=5, max_overflow=5
        )
        state.http_client = httpx.AsyncClient(timeout=httpx.Timeout(120))
        self._client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://eval",
            timeout=600,
        )
        self._install_tool_hook()
        self._install_usage_capture()
        self._install_frozen_prompt_clock()
        self._install_gemini_usage_hook()

    async def stop(self) -> None:
        import hal_orchestrator.state as state

        if self._orig_authorize is not None:
            from hal_orchestrator.services import action_policy

            action_policy.authorize_tool = self._orig_authorize
        if self._client:
            await self._client.aclose()
        if state.http_client:
            await state.http_client.aclose()
        if self._engine:
            await self._engine.dispose()

    # ------------------------------------------------------------------ #
    # Hooks
    # ------------------------------------------------------------------ #

    def _install_gemini_usage_hook(self) -> None:
        """Native Gemini emits no usage log event; read usageMetadata off the
        raw generateContent response instead. Emitted subset-style (input =
        full prompt, cached ⊂ input) — _split_usage normalizes to disjoint.
        Gemini's candidatesTokenCount EXCLUDES thoughts, so output here adds
        them back to match the every-provider convention (reasoning ⊂ output)."""
        from hal_orchestrator.services import gemini as gemini_mod

        harness = self
        orig = gemini_mod._call_gemini_native

        async def wrapped(client, settings, history, tools, system, model, *a, **kw):
            data = await orig(client, settings, history, tools, system, model, *a, **kw)
            um = (data or {}).get("usageMetadata") or {}
            if um:
                thoughts = um.get("thoughtsTokenCount") or 0
                harness._usage_events.append(
                    {
                        "event": "gemini.usage",
                        "model": model,
                        "input": um.get("promptTokenCount") or 0,
                        "cached": um.get("cachedContentTokenCount") or 0,
                        "output": (um.get("candidatesTokenCount") or 0) + thoughts,
                        "reasoning": thoughts,
                    }
                )
            return data

        gemini_mod._call_gemini_native = wrapped

    def _install_frozen_prompt_clock(self) -> None:
        """Freeze the system prompt's wall clock to the scenario's `now`.

        `prompts/system.py:_now_block` stamps `datetime.now(tz)` into every
        system prompt; left unfrozen, "2:15" or "in 45 min" in a scenario
        resolves against the real run time and time-of-day scenarios fail for
        every model (the v1-baseline artifact). Patching the MODULE's datetime
        symbol scopes the freeze to prompt assembly — tool code and the DB see
        real time, matching how `current_time` is frozen in the tool hook."""
        from datetime import datetime as real_dt

        import hal_orchestrator.prompts.system as prompt_mod

        harness = self

        class _FrozenDatetime(real_dt):
            @classmethod
            def now(cls, tz=None):  # noqa: D102
                frozen = harness._frozen_now
                if frozen is None:
                    return real_dt.now(tz)
                if tz is not None:
                    return frozen.astimezone(tz)
                return frozen.replace(tzinfo=None)

        prompt_mod.datetime = _FrozenDatetime

    def _install_tool_hook(self) -> None:
        """Wrap authorize_tool: trace every dispatch, serve fixtures, and
        default-deny anything not in REAL_TOOLS. A string return value is
        treated by execute_tool as the tool's result (its 'blocked' path)."""
        from hal_orchestrator.services import action_policy

        self._orig_authorize = action_policy.authorize_tool
        harness = self

        async def eval_authorize(spec, args, ctx):
            name = spec.name
            harness._trace.append({"tool": name, "args": dict(args or {})})
            if name == "current_time" and harness._frozen_now is not None:
                return harness._frozen_time_string()
            if name in harness._fixtures:
                return str(harness._fixtures[name])
            if name not in REAL_TOOLS:
                return f"[eval stub: {name} not fixtured for this scenario]"
            return await harness._orig_authorize(spec, args, ctx)

        action_policy.authorize_tool = eval_authorize

    def _install_usage_capture(self) -> None:
        """Re-configure structlog with a capture processor appended AFTER
        main.py's configure. Provider modules only bind their pipeline on
        first emission, which happens during turns — after this runs."""
        import structlog

        harness = self

        def capture(logger, method_name, event_dict):
            if event_dict.get("event") in USAGE_EVENTS:
                harness._usage_events.append(dict(event_dict))
            return event_dict

        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.processors.add_log_level,
                structlog.processors.StackInfoRenderer(),
                structlog.dev.set_exc_info,
                structlog.processors.TimeStamper(fmt="iso"),
                capture,
                structlog.dev.ConsoleRenderer(),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(0),
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(),
            cache_logger_on_first_use=False,
        )

    def _frozen_time_string(self) -> str:
        now = self._frozen_now
        assert now is not None
        utc = now.astimezone(ZoneInfo("UTC"))
        return (
            now.strftime("%A, %B %d, %Y at %-I:%M %p %Z")
            + " — your local time"
            + f" ({utc.strftime('%H:%M')} UTC)"
        )

    # ------------------------------------------------------------------ #
    # Seeding
    # ------------------------------------------------------------------ #

    async def seed(self, scenario: dict) -> None:
        from sqlalchemy import text

        from ag_db.models import (
            HalBabyEvent,
            HalFamily,
            HalFamilyMember,
            HalUserMemory,
            HalUserProfile,
        )
        from hal_orchestrator.services.conversation import save_conversation

        seed = scenario.get("seed") or {}
        silo = scenario["silo"]

        async with self._session_factory() as session:
            tables = (
                await session.execute(
                    text(
                        "SELECT tablename FROM pg_tables WHERE schemaname='public' "
                        "AND tablename LIKE 'hal_%'"
                    )
                )
            ).scalars().all()
            await session.execute(
                text("TRUNCATE " + ", ".join(tables) + " CASCADE")
            )

            profile_seed = dict(seed.get("profile") or {})
            extra: dict[str, Any] = {}
            for key in ("timezone", "home_location"):
                if key in profile_seed:
                    extra[key] = profile_seed.pop(key)
            extra.update(profile_seed.pop("extra_data", {}) or {})
            session.add(
                HalUserProfile(
                    phone=scenario.get("sender") or silo,
                    name=profile_seed.pop("name", None),
                    onboarded=True,
                    extra_data=extra,
                    **profile_seed,
                )
            )

            for content in seed.get("memories") or []:
                session.add(
                    HalUserMemory(
                        phone=scenario.get("sender") or silo,
                        content=str(content),
                        embedding=None,
                    )
                )

            baby = seed.get("baby")
            events = seed.get("baby_events") or []
            if baby or events:
                baby = baby or {}
                family = HalFamily(
                    baby_name=baby.get("name", "Baby"),
                    baby_birthdate=(
                        datetime.fromisoformat(baby["birthdate"]).date()
                        if baby.get("birthdate")
                        else None
                    ),
                    timezone=extra.get("timezone", "America/New_York"),
                )
                session.add(family)
                await session.flush()
                member_silos = {silo}
                if scenario.get("sender"):
                    member_silos.add(scenario["sender"])
                for member in member_silos:
                    session.add(HalFamilyMember(family_id=family.id, silo=member))
                for ev in events:
                    session.add(
                        HalBabyEvent(
                            family_id=family.id,
                            kind=ev["kind"],
                            event_at=datetime.fromisoformat(ev["at"]),
                            silo=silo,
                            note=ev.get("note", ""),
                        )
                    )

            await session.commit()

            history = seed.get("history") or []
            if history:
                gemini_history = [
                    {"role": turn["role"], "parts": [{"text": turn["text"]}]}
                    for turn in history
                ]
                await save_conversation(session, silo, gemini_history)
                await session.commit()

            # Durable archive rows (recall_history's substrate) — lets
            # scenarios test recall/membership-boundary behavior over content
            # that predates the conversation window.
            archive = seed.get("archive") or []
            if archive:
                from ag_db.models import HalMessage

                for row in archive:
                    session.add(
                        HalMessage(
                            phone=row.get("silo") or silo,
                            role=row.get("role", "user"),
                            content=row["content"],
                            **(
                                {"created_at": datetime.fromisoformat(row["at"])}
                                if row.get("at")
                                else {}
                            ),
                        )
                    )
                await session.commit()

    # ------------------------------------------------------------------ #
    # Turn
    # ------------------------------------------------------------------ #

    async def run_turn(self, scenario: dict, model: str) -> TurnResult:
        result = TurnResult(
            scenario_id=scenario["id"],
            category=scenario.get("category", ""),
            model=model,
        )
        self._fixtures = dict(scenario.get("tool_fixtures") or {})
        now_raw = scenario.get("now")
        self._frozen_now = datetime.fromisoformat(now_raw) if now_raw else None
        self._trace = []
        self._usage_events = []

        payload = {
            "message_id": f"eval:{scenario['id']}:{model}:{uuid.uuid4().hex[:8]}",
            "phone": scenario["silo"],
            "text": scenario.get("message", ""),
            "is_group": bool(scenario.get("is_group")),
            "internal": bool(scenario.get("internal")),
            "model": model,
        }
        if scenario.get("is_group"):
            payload["chat_id"] = scenario["silo"]
            payload["phone"] = scenario.get("sender") or scenario["silo"]
            payload["group_name"] = scenario.get("group_name") or "eval group"
        # Bridge-style group lifecycle events (member added/removed) — used by
        # the persona suite's event beats.
        if scenario.get("group_event"):
            payload["group_event"] = scenario["group_event"]
            if scenario.get("group_event_target"):
                payload["group_event_target"] = scenario["group_event_target"]

        started = time.monotonic()
        try:
            resp = await self._client.post(
                "/api/message",
                json=payload,
                headers={"Authorization": f"Bearer {EVAL_BRIDGE_SECRET}"},
            )
            result.latency_ms = int((time.monotonic() - started) * 1000)
            if resp.status_code != 200:
                result.error = f"HTTP {resp.status_code}: {resp.text[:300]}"
                return result
            data = resp.json()
        except Exception as exc:  # noqa: BLE001 — record, don't crash the run
            result.latency_ms = int((time.monotonic() - started) * 1000)
            result.error = f"{type(exc).__name__}: {exc}"
            return result

        from hal_orchestrator.routes.message import _is_quiet_sentinel

        result.reply = data.get("reply") or ""
        result.silent = _is_quiet_sentinel(result.reply)
        result.tool_trace = list(self._trace)
        result.usage, result.usage_other = self._split_usage(model)
        result.assertions = evaluate_assertions(scenario, result)
        return result

    def _split_usage(self, candidate_model: str) -> tuple[dict, dict]:
        def add(bucket: dict, ev: dict) -> None:
            bucket["calls"] = bucket.get("calls", 0) + 1
            for src, dst in (
                ("input", "input"),
                ("cached", "cached"),
                ("cache_read", "cached"),
                ("cache_write", "cache_write"),
                ("output", "output"),
                ("reasoning", "reasoning"),
            ):
                val = ev.get(src)
                if isinstance(val, (int, float)):
                    bucket[dst] = bucket.get(dst, 0) + int(val)

        def normalize(ev: dict) -> dict:
            # OpenAI/Gemini report `cached` as a SUBSET of `input`; the
            # Anthropic shim (and cost_of's tested contract) use DISJOINT
            # buckets. Convert here so every stored record is disjoint —
            # otherwise the cached portion bills at full rate AND 10%.
            if ev.get("event") in ("openai.usage", "gemini.usage"):
                ev = dict(ev)
                inp = ev.get("input") or 0
                cached = ev.get("cached") or 0
                if isinstance(inp, (int, float)) and isinstance(cached, (int, float)):
                    ev["input"] = max(0, int(inp) - int(cached))
            return ev

        mine: dict = {}
        other: dict = {}
        for ev in self._usage_events:
            ev = normalize(ev)
            add(mine if ev.get("model") == candidate_model else other, ev)
        return mine, other


# ---------------------------------------------------------------------- #
# Hard assertions
# ---------------------------------------------------------------------- #


def _args_value_matches(value: Any, pattern: str) -> bool:
    text = str(value)
    try:
        if re.search(pattern, text):
            return True
    except re.error:
        pass
    return pattern.lower() in text.lower()


def evaluate_assertions(scenario: dict, result: TurnResult) -> dict:
    expect = scenario.get("expect") or {}
    failures: list[str] = []
    called = [t["tool"] for t in result.tool_trace]

    for tool in expect.get("tools_called") or []:
        if tool not in called:
            failures.append(f"expected tool '{tool}' was not called (called: {called})")
    for tool in expect.get("tools_absent") or []:
        if tool in called:
            failures.append(f"forbidden tool '{tool}' was called")

    for tool, patterns in (expect.get("args_match") or {}).items():
        calls = [t["args"] for t in result.tool_trace if t["tool"] == tool]
        if not calls:
            failures.append(f"args_match: tool '{tool}' was never called")
            continue
        if not any(
            all(_args_value_matches(args.get(key), str(pat)) for key, pat in patterns.items())
            for args in calls
        ):
            failures.append(
                f"args_match: no '{tool}' call matched {patterns} (calls: {calls})"
            )

    silent_expected = expect.get("silent_expected")
    if silent_expected is True and not result.silent:
        failures.append(f"expected silence, got reply: {result.reply[:120]!r}")
    if silent_expected is False and result.silent:
        failures.append("expected a reply, got silence")

    return {"passed": not failures, "failures": failures}


# ---------------------------------------------------------------------- #
# Convenience for ad-hoc use
# ---------------------------------------------------------------------- #


async def run_scenarios(
    scenarios: list[dict], models: list[str]
) -> list[dict]:
    harness = EvalHarness()
    await harness.start()
    records: list[dict] = []
    try:
        for model in models:
            for scenario in scenarios:
                await harness.seed(scenario)
                result = await harness.run_turn(scenario, model)
                records.append(result.to_record())
    finally:
        await harness.stop()
    return records


if __name__ == "__main__":
    prepare_env()
    print("harness module OK; use run.py")
    asyncio.run(asyncio.sleep(0))
