"""Skill packages for HAL orchestrator.

Two-tier loader: bundled skills (read-only, ship in this package at
hal_orchestrator/skills/<name>/SKILL.md) + user skills (mutable, stored in
the hal_user_skills Postgres table). User entries override bundled entries
of the same name. Editing a bundled skill clones it into the user table;
deleting a bundled-only skill is refused.

User skills are scoped to a silo (`phone`: a user's handle in 1:1 chats, the
group chat id in group chats). One silo's skills are never visible to another;
bundled skills are shared read-only.

SKILL.md format:
    ---
    {"description": "...", "keywords": [...], "inputs": [{"name","required"}]}
    ---
    <markdown body with {{var}}, {{$(cmd)}}, {{file:rel/path}} tokens>

{{$(cmd)}} runs only in bundled skills; in user/auto-created skills it is
neutralized to a placeholder (see _expand).

The curator only ever sees user skills; bundled are immutable.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ag_db.models import HalUserSkill, utcnow

log = structlog.get_logger()

# Bundled skills directory — shipped inside the Python package, so it
# survives a container restart and can't be edited at runtime.
BUNDLED_DIR = Path(__file__).resolve().parent.parent / "skills"

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)
VAR_RE = re.compile(r"\{\{([^}]+)\}\}")
SAFE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
ALLOWED_SUBDIRS = ("references", "templates", "scripts")

SOURCE_USER = "user"
SOURCE_BUNDLED = "bundled"

# Silo key for skills HAL learns in aggregate (nightly reflection) that should be
# available to EVERYONE. Loaded for all silos, below a user's own skills.
SHARED_OWNER = "__shared__"

MAX_SKILLS = 100
SHELL_TIMEOUT_SECONDS = 10


@dataclass
class SkillRecord:
    """Normalized view of a skill, regardless of source."""

    name: str
    source: str  # "user" | "bundled"
    description: str
    keywords: list
    inputs: list
    body: str
    files: dict  # {rel_path: content}


# --------------------------------------------------------------------------- #
# Internals                                                                   #
# --------------------------------------------------------------------------- #


def _normalize_name(name: str | None) -> str | None:
    n = (name or "").strip().lower().replace(" ", "-")
    if not SAFE_NAME_RE.match(n):
        return None
    return n


def _parse(text: str) -> tuple[dict, str]:
    """Parse SKILL.md text. Raises ValueError on bad JSON frontmatter."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {"description": "", "keywords": [], "inputs": []}, text.strip()
    fm_text, body = m.group(1), m.group(2)
    try:
        fm = json.loads(fm_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON frontmatter: {e}") from e
    if not isinstance(fm, dict):
        raise ValueError("Frontmatter must be a JSON object")
    fm.setdefault("description", "")
    fm.setdefault("keywords", [])
    fm.setdefault("inputs", [])
    return fm, body.strip()


def _bundled_list() -> list[SkillRecord]:
    """Scan the bundled directory for skills. Cached lightly — directory is
    read-only at runtime, so this is cheap to recompute per call."""
    out: list[SkillRecord] = []
    if not BUNDLED_DIR.is_dir():
        return out
    for entry in sorted(BUNDLED_DIR.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        skill_md = entry / "SKILL.md"
        if not skill_md.is_file():
            continue
        try:
            fm, body = _parse(skill_md.read_text())
        except (ValueError, OSError) as e:
            log.warning("skills.bundled.invalid", path=str(entry), error=str(e))
            continue
        files = {}
        for sub in ALLOWED_SUBDIRS:
            sub_dir = entry / sub
            if sub_dir.is_dir():
                for f in sub_dir.rglob("*"):
                    if f.is_file() and not f.name.startswith("."):
                        rel = f.relative_to(entry).as_posix()
                        try:
                            files[rel] = f.read_text()
                        except (OSError, UnicodeDecodeError):
                            pass
        out.append(
            SkillRecord(
                name=entry.name,
                source=SOURCE_BUNDLED,
                description=fm.get("description", ""),
                keywords=fm.get("keywords", []),
                inputs=fm.get("inputs", []),
                body=body,
                files=files,
            )
        )
    return out


def _user_row_to_record(row: HalUserSkill) -> SkillRecord:
    return SkillRecord(
        name=row.name,
        source=SOURCE_USER,
        description=row.description or "",
        keywords=list(row.keywords or []),
        inputs=list(row.inputs or []),
        body=row.body or "",
        files=dict(row.files or {}),
    )


async def _user_get(
    session: AsyncSession, phone: str, name: str
) -> HalUserSkill | None:
    q = await session.execute(
        select(HalUserSkill).where(
            HalUserSkill.phone == phone,
            HalUserSkill.name == name,
            HalUserSkill.archived.is_(False),
        )
    )
    return q.scalar_one_or_none()


async def _user_list(session: AsyncSession, phone: str) -> list[HalUserSkill]:
    q = await session.execute(
        select(HalUserSkill).where(
            HalUserSkill.phone == phone, HalUserSkill.archived.is_(False)
        )
    )
    return list(q.scalars().all())


def _expand(
    body: str, files: dict, inputs: dict, *, allow_shell: bool = False
) -> tuple[str, list[str]]:
    """Apply {{var}}, {{$(cmd)}}, {{file:path}} substitutions.

    {{$(cmd)}} only executes when allow_shell is True — i.e. for bundled
    skills, which ship in this repo and are human-reviewed. User-created and
    auto-synthesized skills (anything from the hal_user_skills table) must
    not be a code-execution path: a skill body is model- or user-authored
    text, and the container env holds DATABASE_URL, API keys, and the token
    Fernet key. Dynamic values in non-bundled skills belong in real tools.
    """
    warnings: list[str] = []

    def replace(m: re.Match) -> str:
        token = m.group(1).strip()
        # {{$(cmd)}}
        if token.startswith("$(") and token.endswith(")"):
            cmd = token[2:-1]
            if not allow_shell:
                warnings.append(f"shell disabled in non-bundled skill: {cmd!r}")
                return "[shell disabled]"
            try:
                out = subprocess.check_output(
                    ["/bin/sh", "-c", cmd],
                    stderr=subprocess.STDOUT,
                    timeout=SHELL_TIMEOUT_SECONDS,
                )
                return out.decode("utf-8", "replace").rstrip("\n")
            except subprocess.TimeoutExpired:
                warnings.append(f"shell timeout: {cmd!r}")
                return f"[shell timeout: {cmd}]"
            except subprocess.CalledProcessError as e:
                warnings.append(f"shell failed: {cmd!r} (exit {e.returncode})")
                return f"[shell exit {e.returncode}: {cmd}]"
            except Exception as e:
                warnings.append(f"shell error: {cmd!r}: {e}")
                return f"[shell error: {e}]"
        # {{file:rel/path}}
        if token.startswith("file:"):
            rel = token[5:].strip()
            if rel in files:
                return files[rel]
            warnings.append(f"file not found: {rel!r}")
            return f"[file not found: {rel}]"
        # {{var}}
        if token in inputs:
            return str(inputs[token])
        warnings.append(f"missing input: {token!r}")
        return f"[missing: {token}]"

    return VAR_RE.sub(replace, body), warnings


# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #


async def list_skills(session: AsyncSession, phone: str) -> list[SkillRecord]:
    """Bundled + shared (HAL-learned, everyone) + this silo's own skills, deduped
    by name. Precedence on conflict: user > shared > bundled."""
    out: dict[str, SkillRecord] = {s.name: s for s in _bundled_list()}
    out.update(
        {row.name: _user_row_to_record(row) for row in await _user_list(session, SHARED_OWNER)}
    )
    if phone != SHARED_OWNER:
        out.update(
            {row.name: _user_row_to_record(row) for row in await _user_list(session, phone)}
        )
    return sorted(out.values(), key=lambda s: s.name)


async def find_skill(
    session: AsyncSession, phone: str, name: str
) -> SkillRecord | None:
    n = _normalize_name(name)
    if not n:
        return None
    row = await _user_get(session, phone, n)
    if row is not None:
        return _user_row_to_record(row)
    if phone != SHARED_OWNER:
        shared = await _user_get(session, SHARED_OWNER, n)
        if shared is not None:
            return _user_row_to_record(shared)
    for s in _bundled_list():
        if s.name == n:
            return s
    return None


async def invoke(
    session: AsyncSession, phone: str, name: str, inputs: dict | None = None
) -> tuple[dict | None, str | None]:
    """Render a skill body with the given inputs.
    Shell expansion happens in a thread to avoid blocking the event loop."""
    rec = await find_skill(session, phone, name)
    if rec is None:
        return None, f"Skill {name!r} not found."
    provided = inputs or {}
    missing = [
        inp.get("name", "?")
        for inp in rec.inputs
        if isinstance(inp, dict) and inp.get("required") and inp.get("name") not in provided
    ]
    if missing:
        return None, f"Missing required inputs: {', '.join(missing)}"
    rendered, warnings = await asyncio.to_thread(
        _expand,
        rec.body,
        rec.files,
        provided,
        allow_shell=rec.source == SOURCE_BUNDLED,
    )
    return {
        "name": rec.name,
        "source": rec.source,
        "description": rec.description,
        "rendered": rendered,
        "warnings": warnings,
    }, None


async def view(
    session: AsyncSession, phone: str, name: str
) -> tuple[dict | None, str | None]:
    rec = await find_skill(session, phone, name)
    if rec is None:
        return None, f"Skill {name!r} not found."
    return {
        "name": rec.name,
        "source": rec.source,
        "frontmatter": {
            "description": rec.description,
            "keywords": rec.keywords,
            "inputs": rec.inputs,
        },
        "body": rec.body,
        "files": sorted(rec.files.keys()),
    }, None


async def create(
    session: AsyncSession,
    phone: str,
    name: str,
    *,
    description: str,
    body: str,
    keywords: list | None = None,
    inputs: list | None = None,
) -> tuple[dict | None, str | None]:
    n = _normalize_name(name)
    if not n:
        return None, "Invalid skill name. Use lowercase letters, digits, '-', '_'."
    user_count = len(await _user_list(session, phone))
    if user_count >= MAX_SKILLS:
        return None, f"Max {MAX_SKILLS} user skills reached."
    existing = await _user_get(session, phone, n)
    if existing is not None:
        return None, f"Skill {n!r} already exists. Use edit instead."
    row = HalUserSkill(
        id=uuid.uuid4(),
        phone=phone,
        name=n,
        description=description or "",
        body=body or "",
        keywords=list(keywords or []),
        inputs=list(inputs or []),
        files={},
    )
    session.add(row)
    await session.commit()
    return {"name": n}, None


async def edit(
    session: AsyncSession,
    phone: str,
    name: str,
    *,
    description: str | None = None,
    body: str | None = None,
    keywords: list | None = None,
    inputs: list | None = None,
) -> tuple[dict | None, str | None]:
    n = _normalize_name(name)
    if not n:
        return None, "Invalid skill name."
    rec = await find_skill(session, phone, n)
    if rec is None:
        return None, f"Skill {n!r} not found."
    forked = False
    row = await _user_get(session, phone, n)
    if row is None:
        # Fork bundled into user table
        row = HalUserSkill(
            id=uuid.uuid4(),
            phone=phone,
            name=n,
            description=rec.description,
            body=rec.body,
            keywords=list(rec.keywords),
            inputs=list(rec.inputs),
            files=dict(rec.files),
        )
        session.add(row)
        forked = True
    if description is not None:
        row.description = description
    if body is not None:
        row.body = body
    if keywords is not None:
        row.keywords = list(keywords)
    if inputs is not None:
        row.inputs = list(inputs)
    await session.commit()
    return {"name": n, "forked_from_bundled": forked}, None


async def write_file(
    session: AsyncSession, phone: str, name: str, *, path: str, content: str
) -> tuple[dict | None, str | None]:
    n = _normalize_name(name)
    if not n:
        return None, "Invalid skill name."
    rec = await find_skill(session, phone, n)
    if rec is None:
        return None, f"Skill {n!r} not found."
    rel = (path or "").strip().lstrip("/")
    parts = rel.split("/", 1)
    if len(parts) < 2 or parts[0] not in ALLOWED_SUBDIRS:
        return None, f"path must start with one of: {', '.join(ALLOWED_SUBDIRS)}"
    if ".." in rel.split("/"):
        return None, "path must not contain '..'"
    row = await _user_get(session, phone, n)
    if row is None:
        # Fork bundled into user
        row = HalUserSkill(
            id=uuid.uuid4(),
            phone=phone,
            name=n,
            description=rec.description,
            body=rec.body,
            keywords=list(rec.keywords),
            inputs=list(rec.inputs),
            files=dict(rec.files),
        )
        session.add(row)
    files = dict(row.files or {})
    files[rel] = content or ""
    row.files = files
    await session.commit()
    return {"name": n, "path": rel, "size": len(content or "")}, None


async def delete(
    session: AsyncSession, phone: str, name: str, reason: str = ""
) -> tuple[dict | None, str | None]:
    n = _normalize_name(name)
    if not n:
        return None, "Invalid skill name."
    row = await _user_get(session, phone, n)
    if row is None:
        # Bundled-only — refuse, mirrors local skills.py behavior
        for s in _bundled_list():
            if s.name == n:
                return None, (
                    f"Skill {n!r} is bundled and cannot be archived directly. "
                    "Use edit to fork it to the user table, then archive."
                )
        return None, f"Skill {n!r} not found."
    row.archived = True
    row.archived_reason = reason or ""
    row.archived_at = datetime.now(timezone.utc)
    await session.commit()
    return {"name": n, "archived": True, "reason": reason}, None


async def list_user_skills_for_curator(session: AsyncSession) -> list[HalUserSkill]:
    """Curator-only view: ALL silos' user skills as raw rows (bundled never
    exposed). Rows carry .phone so the curator can act per-owner."""
    q = await session.execute(
        select(HalUserSkill).where(HalUserSkill.archived.is_(False))
    )
    return list(q.scalars().all())
