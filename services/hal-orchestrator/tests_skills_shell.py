"""Tests that {{$(cmd)}} shell substitution only runs for bundled skills.

User-created and auto-synthesized skills (hal_user_skills rows) must never
execute shell — a skill body is model- or user-authored text, and the
container env holds DATABASE_URL, API keys, and the token Fernet key.

Run: python3 services/hal-orchestrator/tests_skills_shell.py
"""

import asyncio
import os
import sys

_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-db"))
sys.path.insert(0, os.path.join(_ROOT, "packages", "ag-common"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hal_orchestrator.services import skills as skills_svc
from hal_orchestrator.services.skills import (
    SOURCE_BUNDLED,
    SOURCE_USER,
    SkillRecord,
    _expand,
)

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok: {name}")
    else:
        failures.append(name)
        print(f"  FAIL: {name} {detail}")


print("_expand shell gating:")
body = "today is {{$(echo SHELL_RAN)}}"

rendered, warnings = _expand(body, {}, {}, allow_shell=True)
check("bundled: shell runs", "SHELL_RAN" in rendered, rendered)
check("bundled: no warnings", warnings == [], warnings)

rendered, warnings = _expand(body, {}, {})
check("default: shell disabled", "SHELL_RAN" not in rendered, rendered)
check("default: placeholder", "[shell disabled]" in rendered, rendered)
check("default: warning emitted", any("shell disabled" in w for w in warnings), warnings)

rendered, _ = _expand("{{name}} and {{$(env)}}", {}, {"name": "x"})
check("vars still expand without shell", rendered.startswith("x and"), rendered)
check("env not leaked", "PATH=" not in rendered, rendered)

print("invoke wires source -> allow_shell:")


async def invoke_with_source(source):
    rec = SkillRecord(
        name="t",
        source=source,
        description="",
        keywords=[],
        inputs=[],
        body="{{$(echo SHELL_RAN)}}",
        files={},
    )

    async def fake_find(session, phone, name):
        return rec

    orig = skills_svc.find_skill
    skills_svc.find_skill = fake_find
    try:
        result, err = await skills_svc.invoke(None, "+15555550100", "t")
    finally:
        skills_svc.find_skill = orig
    assert err is None, err
    return result["rendered"]


rendered = asyncio.run(invoke_with_source(SOURCE_USER))
check("user skill: no shell", "SHELL_RAN" not in rendered, rendered)
check("user skill: placeholder", "[shell disabled]" in rendered, rendered)

rendered = asyncio.run(invoke_with_source(SOURCE_BUNDLED))
check("bundled skill: shell runs", "SHELL_RAN" in rendered, rendered)

print()
if failures:
    print(f"{len(failures)} FAILED: {failures}")
    sys.exit(1)
print("all passed")
