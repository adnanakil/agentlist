"""skill tool — wraps services/skills.py for the agent."""

from __future__ import annotations

import json

import structlog

from hal_orchestrator.services import skills as skills_svc
from hal_orchestrator.tools.registry import ToolContext

log = structlog.get_logger()


async def tool_skill(args: dict, ctx: ToolContext) -> str:
    action = args.get("action", "list")

    if action == "list":
        items = await skills_svc.list_skills(ctx.session, ctx.phone)
        if not items:
            return "No skills installed. Create one with skill action=create."
        lines = ["Available skills:"]
        for s in items:
            kw = ", ".join((s.keywords or [])[:5])
            tag = "[bundled]" if s.source == skills_svc.SOURCE_BUNDLED else "[user]"
            lines.append(f"- {tag} {s.name}: {s.description}  (keywords: {kw or 'none'})")
        return "\n".join(lines)

    if action == "view":
        result, err = await skills_svc.view(ctx.session, ctx.phone, args.get("name", ""))
        if err:
            return f"Error: {err}"
        return json.dumps(result, indent=2)

    if action == "invoke":
        result, err = await skills_svc.invoke(
            ctx.session, ctx.phone, args.get("name", ""), inputs=args.get("inputs") or {}
        )
        if err:
            return f"Error: {err}"
        warnings = result["warnings"]
        out = [f"[Skill: {result['name']}]"]
        if warnings:
            out.append(f"[Warnings: {'; '.join(warnings)}]")
        out.append("")
        out.append(result["rendered"])
        return "\n".join(out)

    if action == "create":
        result, err = await skills_svc.create(
            ctx.session,
            ctx.phone,
            args.get("name", ""),
            description=args.get("description", "") or "",
            body=args.get("body", "") or "",
            keywords=args.get("keywords") or [],
            inputs=args.get("skill_inputs") or [],
        )
        if err:
            return f"Error: {err}"
        return f"Skill {result['name']!r} created."

    if action == "edit":
        result, err = await skills_svc.edit(
            ctx.session,
            ctx.phone,
            args.get("name", ""),
            description=args.get("description"),
            body=args.get("body"),
            keywords=args.get("keywords"),
            inputs=args.get("skill_inputs"),
        )
        if err:
            return f"Error: {err}"
        msg = f"Skill {result['name']!r} updated."
        if result.get("forked_from_bundled"):
            msg += " (forked from bundled — your edits live in the user table; bundled copy is unchanged.)"
        return msg

    if action == "write_file":
        result, err = await skills_svc.write_file(
            ctx.session,
            ctx.phone,
            args.get("name", ""),
            path=args.get("path", "") or "",
            content=args.get("content", "") or "",
        )
        if err:
            return f"Error: {err}"
        return (
            f"Wrote {result['path']} ({result['size']} bytes) to skill {result['name']!r}."
        )

    if action == "delete":
        result, err = await skills_svc.delete(
            ctx.session, ctx.phone, args.get("name", ""), reason=args.get("reason", "") or ""
        )
        if err:
            return f"Error: {err}"
        return f"Skill {result['name']!r} archived."

    return f"Unknown action: {action}"
