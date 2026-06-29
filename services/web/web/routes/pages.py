"""HTML page routes — signup, login, dashboard."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path

import structlog
from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ag_common.auth import generate_api_key
from ag_common.config import WebConfig
from ag_db.models import (
    Account,
    Agent,
    AgentCredential,
    AgentSubscription,
    ApiKey,
    Category,
    ConsumerCredential,
    LedgerAccount,
    McpSubscription,
    McpTool,
)
from ag_db.session import get_session

log = structlog.get_logger()
router = APIRouter()
settings = WebConfig()

templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

GATEWAY_URL = "https://gateway-production-cd14.up.railway.app"


def _encrypt_value(plaintext: str) -> bytes:
    """Encrypt a credential value with Fernet."""
    key = settings.encryption_key
    if not key:
        raise ValueError("ENCRYPTION_KEY not configured")
    return Fernet(key.encode()).encrypt(plaintext.encode())


def _pricing_label(agent: Agent) -> str:
    if agent.pricing_model == "subscription":
        monthly = (agent.pricing_config or {}).get("monthly_cents", 0)
        return f"${monthly / 100:.2f}/mo"
    if agent.pricing_model == "byo_creds":
        monthly = (agent.pricing_config or {}).get("hosting_cents", 0)
        return f"${monthly / 100:.2f}/mo hosting"
    return f"{agent.price_per_call_cents}c/call"


def _parse_tool_schema(raw: str, default_schema: dict) -> list[dict]:
    if not raw.strip():
        return [
            {
                "name": "invoke",
                "description": "Invoke this MCP server.",
                "inputSchema": default_schema or {"type": "object", "properties": {}},
            }
        ]
    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        raise ValueError("Tool schema must be a JSON array.")

    tools = []
    for item in parsed:
        if not isinstance(item, dict):
            raise ValueError("Every tool must be a JSON object.")
        name = str(item.get("name", "")).strip()
        if not re.match(r"^[A-Za-z0-9_-]+$", name):
            raise ValueError("Tool names may contain letters, numbers, underscores, and hyphens.")
        tools.append(
            {
                "name": name,
                "description": str(item.get("description") or ""),
                "inputSchema": item.get("inputSchema")
                or item.get("input_schema")
                or {"type": "object", "properties": {}},
            }
        )
    return tools


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_account_id(request: Request) -> uuid.UUID | None:
    """Read account_id from session cookie."""
    raw = request.session.get("account_id")
    if raw:
        try:
            return uuid.UUID(raw)
        except ValueError:
            pass
    return None


# ---------------------------------------------------------------------------
# Landing page
# ---------------------------------------------------------------------------


@router.get("/", response_model=None)
async def index(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    # Fetch active agents with their categories
    result = await session.execute(
        select(Agent)
        .where(Agent.status == "active")
        .options(selectinload(Agent.category))
        .order_by(Agent.slug)
    )
    agents = result.scalars().all()

    # Count stats
    agent_count = len(agents)
    result = await session.execute(
        select(func.count(Account.id)).where(Account.role == "developer")
    )
    developer_count = result.scalar() or 0

    # Group agents by category
    agents_by_category: dict[str, list] = {}
    for agent in agents:
        cat_name = agent.category.name if agent.category else "Other"
        agents_by_category.setdefault(cat_name, []).append(agent)

    snippet_raw = _build_claude_snippet("YOUR_API_KEY")

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "agents": agents,
            "agents_by_category": agents_by_category,
            "agent_count": agent_count,
            "developer_count": developer_count,
            "category_count": len(agents_by_category),
            "gateway_url": GATEWAY_URL,
            "snippet_raw": snippet_raw,
            "pricing_label": _pricing_label,
        },
    )


# ---------------------------------------------------------------------------
# Signup
# ---------------------------------------------------------------------------


@router.get("/signup", response_class=HTMLResponse)
async def signup_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "signup.html")


@router.post("/signup", response_model=None)
async def signup_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form("consumer"),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse | RedirectResponse:
    # Validate role
    if role not in ("consumer", "developer"):
        return templates.TemplateResponse(
            request, "signup.html", {"error": "Invalid role."}, status_code=400
        )

    # Validate inputs
    email = email.strip().lower()
    if not email or "@" not in email:
        return templates.TemplateResponse(
            request, "signup.html", {"error": "Please enter a valid email."}, status_code=400
        )
    if len(password) < 8:
        return templates.TemplateResponse(
            request,
            "signup.html",
            {"error": "Password must be at least 8 characters."},
            status_code=400,
        )

    # Check if account exists
    result = await session.execute(select(Account).where(Account.email == email))
    if result.scalar_one_or_none():
        return templates.TemplateResponse(
            request,
            "signup.html",
            {"error": "An account with this email already exists."},
            status_code=400,
        )

    # Create account
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    account = Account(
        id=uuid.uuid4(),
        email=email,
        password_hash=password_hash,
        role=role,
    )
    session.add(account)

    # Create API key
    full_key, key_prefix, key_hash = generate_api_key()
    api_key = ApiKey(
        id=uuid.uuid4(),
        account_id=account.id,
        key_hash=key_hash,
        key_prefix=key_prefix,
    )
    session.add(api_key)

    # Create ledger accounts
    if role == "consumer":
        ledger_types = ["consumer_balance", "held_funds"]
    else:
        ledger_types = ["developer_earnings"]

    for acct_type in ledger_types:
        la = LedgerAccount(
            id=uuid.uuid4(),
            account_id=account.id,
            account_type=acct_type,
        )
        session.add(la)

    await session.commit()

    log.info("account.created", email=email, role=role, account_id=str(account.id))

    # Set session
    request.session["account_id"] = str(account.id)
    request.session["flash_api_key"] = full_key

    return RedirectResponse(url="/dashboard", status_code=303)


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "login.html")


@router.post("/login", response_model=None)
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse | RedirectResponse:
    email = email.strip().lower()
    password_hash = hashlib.sha256(password.encode()).hexdigest()

    result = await session.execute(
        select(Account).where(Account.email == email, Account.password_hash == password_hash)
    )
    account = result.scalar_one_or_none()

    if not account:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Invalid email or password."},
            status_code=400,
        )

    if not account.is_active:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "This account has been deactivated."},
            status_code=400,
        )

    request.session["account_id"] = str(account.id)

    log.info("account.login", email=email, account_id=str(account.id))

    return RedirectResponse(url="/dashboard", status_code=303)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@router.get("/dashboard", response_model=None)
async def dashboard(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse | RedirectResponse:
    account_id = _get_account_id(request)
    if not account_id:
        return RedirectResponse(url="/login", status_code=303)

    # Fetch account
    result = await session.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        request.session.clear()
        return RedirectResponse(url="/login", status_code=303)

    # Fetch API key prefix
    result = await session.execute(
        select(ApiKey).where(ApiKey.account_id == account_id, ApiKey.is_active.is_(True))
    )
    api_key = result.scalar_one_or_none()
    key_prefix = api_key.key_prefix if api_key else "N/A"

    # Fetch balance (consumer_balance for consumers, developer_earnings for developers)
    balance_cents = 0
    ledger_type = "developer_earnings" if account.role == "developer" else "consumer_balance"
    result = await session.execute(
        select(LedgerAccount).where(
            LedgerAccount.account_id == account_id,
            LedgerAccount.account_type == ledger_type,
        )
    )
    ledger_account = result.scalar_one_or_none()
    if ledger_account:
        balance_cents = ledger_account.balance_cents

    balance_label = "Earnings" if account.role == "developer" else "Balance"
    balance_dollars = f"${balance_cents / 100:.2f}"

    # Flash messages (shown only once)
    flash_api_key = request.session.pop("flash_api_key", None)
    flash_agent = request.session.pop("flash_agent", None)

    # Build CLAUDE.md snippet
    display_key = flash_api_key if flash_api_key else f"{key_prefix}..."
    claude_snippet = _build_claude_snippet(display_key)

    # Fetch developer's agents (if developer account)
    my_agents = []
    if account.role == "developer":
        result = await session.execute(
            select(Agent)
            .where(Agent.developer_id == account_id)
            .options(selectinload(Agent.category))
            .order_by(Agent.created_at.desc())
        )
        my_agents = list(result.scalars().all())

    # Fetch active MCP subscriptions (consumer dashboard)
    result = await session.execute(
        select(McpSubscription)
        .where(McpSubscription.account_id == account_id, McpSubscription.status == "active")
        .options(selectinload(McpSubscription.agent).selectinload(Agent.mcp_tools))
        .order_by(McpSubscription.created_at.desc())
    )
    mcp_subscriptions = list(result.scalars().all())

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "account": account,
            "key_prefix": key_prefix,
            "flash_api_key": flash_api_key,
            "balance": balance_dollars,
            "balance_label": balance_label,
            "claude_snippet": claude_snippet,
            "gateway_url": GATEWAY_URL,
            "my_agents": my_agents,
            "mcp_subscriptions": mcp_subscriptions,
            "flash_agent": flash_agent,
            "pricing_label": _pricing_label,
        },
    )


# ---------------------------------------------------------------------------
# Submit Agent (developer only)
# ---------------------------------------------------------------------------


async def _require_developer(
    request: Request, session: AsyncSession
) -> Account | None:
    """Return the developer Account or None if not logged in / not a developer."""
    account_id = _get_account_id(request)
    if not account_id:
        return None
    result = await session.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if not account or account.role != "developer":
        return None
    return account


@router.get("/dashboard/submit-agent", response_model=None)
async def submit_agent_form(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse | RedirectResponse:
    account = await _require_developer(request, session)
    if not account:
        return RedirectResponse(url="/login", status_code=303)

    return templates.TemplateResponse(
        request,
        "submit_agent.html",
        {"account": account, "values": {}},
    )


@router.post("/dashboard/submit-agent", response_model=None)
async def submit_agent_submit(
    request: Request,
    slug: str = Form(...),
    name: str = Form(...),
    description: str = Form(...),
    price_per_call_cents: int = Form(0),
    pricing_model: str = Form("per_call"),
    monthly_price_cents: int = Form(0),
    hosting_type: str = Form("hosted"),
    agent_code: str = Form(""),
    endpoint_url: str = Form(""),
    input_schema: str = Form(""),
    tool_schema: str = Form(""),
    required_consumer_credentials: str = Form(""),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse | RedirectResponse:
    account = await _require_developer(request, session)
    if not account:
        return RedirectResponse(url="/login", status_code=303)

    form_values = {
        "slug": slug,
        "name": name,
        "description": description,
        "price_per_call_cents": price_per_call_cents,
        "pricing_model": pricing_model,
        "monthly_price_cents": monthly_price_cents,
        "hosting_type": hosting_type,
        "agent_code": agent_code,
        "endpoint_url": endpoint_url,
        "input_schema": input_schema,
        "tool_schema": tool_schema,
        "required_consumer_credentials": required_consumer_credentials,
    }

    def _err(msg: str) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "submit_agent.html",
            {"account": account, "values": form_values, "error": msg},
            status_code=400,
        )

    # Validate slug
    slug = slug.strip().lower()
    if not slug or not re.match(r"^[a-z0-9][a-z0-9\-]*[a-z0-9]$", slug):
        return _err("Slug must be lowercase letters, numbers, and hyphens (e.g. my-agent).")

    # Check uniqueness
    result = await session.execute(select(Agent).where(Agent.slug == slug))
    if result.scalar_one_or_none():
        return _err(f"An agent with slug '{slug}' already exists.")

    # Validate name / description
    name = name.strip()
    description = description.strip()
    if not name:
        return _err("Name is required.")
    if not description:
        return _err("Description is required.")

    # Auto-assign "utilities" category (or first available)
    result = await session.execute(
        select(Category).where(Category.slug == "utilities")
    )
    cat = result.scalar_one_or_none()
    if not cat:
        result = await session.execute(select(Category).limit(1))
        cat = result.scalar_one_or_none()
    cat_uuid = cat.id if cat else None

    # Validate price
    if price_per_call_cents < 0:
        return _err("Price cannot be negative.")
    if pricing_model not in ("per_call", "subscription", "freemium", "byo_creds"):
        return _err("Invalid pricing model.")
    if monthly_price_cents < 0:
        return _err("Monthly price cannot be negative.")

    # Parse required consumer credentials
    req_consumer_creds = [
        c.strip().upper() for c in required_consumer_credentials.split(",") if c.strip()
    ] if required_consumer_credentials.strip() else []
    for cred_name in req_consumer_creds:
        if not re.match(r"^[A-Z][A-Z0-9_]*$", cred_name):
            return _err(
                f"Consumer credential name '{cred_name}' must be uppercase with underscores (e.g. INSTACART_API_KEY)."
            )

    # Parse input schema
    schema_dict: dict = {}
    if input_schema.strip():
        try:
            schema_dict = json.loads(input_schema)
        except json.JSONDecodeError:
            return _err("Input schema must be valid JSON.")

    try:
        tools = _parse_tool_schema(tool_schema, schema_dict)
    except (json.JSONDecodeError, ValueError) as exc:
        return _err(str(exc))

    pricing_config: dict = {}
    if pricing_model == "subscription":
        pricing_config["monthly_cents"] = monthly_price_cents
    elif pricing_model == "byo_creds":
        pricing_config["hosting_cents"] = monthly_price_cents

    # Validate hosting type
    is_external = hosting_type == "external"
    agent_code = agent_code.strip()
    endpoint_url = endpoint_url.strip()

    if is_external:
        if not endpoint_url:
            return _err("Endpoint URL is required for external agents.")
        if not endpoint_url.startswith("https://"):
            return _err("Endpoint URL must use HTTPS.")
    else:
        if not agent_code:
            return _err("Agent code is required for hosted agents.")

    # Build manifest
    manifest: dict = {
        "name": name,
        "description": description,
        "version": "0.1.0",
        "runtime": "external" if is_external else "python",
        "price_per_call_cents": price_per_call_cents,
        "pricing_model": pricing_model,
        "pricing_config": pricing_config,
        "input_schema": schema_dict,
        "tools": tools,
        "tags": [],
    }
    if agent_code:
        manifest["agent_code"] = agent_code

    # Parse credentials from dynamic form fields
    form_data = await request.form()
    cred_names = form_data.getlist("cred_name")
    cred_values = form_data.getlist("cred_value")
    credentials: list[tuple[str, str]] = []
    for cn, cv in zip(cred_names, cred_values):
        cn_str = cn.strip() if isinstance(cn, str) else str(cn).strip()
        cv_str = cv.strip() if isinstance(cv, str) else str(cv).strip()
        if cn_str and cv_str:
            if not re.match(r"^[A-Z][A-Z0-9_]*$", cn_str):
                return _err(
                    f"Credential name '{cn_str}' must be uppercase with underscores (e.g. API_KEY)."
                )
            credentials.append((cn_str, cv_str))

    agent_id = uuid.uuid4()
    agent = Agent(
        id=agent_id,
        developer_id=account.id,
        category_id=cat_uuid,
        slug=slug,
        name=name,
        description=description,
        version="0.1.0",
        runtime="python",
        status="active",
        price_per_call_cents=price_per_call_cents,
        input_schema=schema_dict,
        manifest=manifest,
        tags=[],
        image_uri=None if is_external else f"agentgate-agent-{slug}:latest",
        endpoint_url=endpoint_url if is_external else None,
        required_consumer_credentials=req_consumer_creds,
        runtime_kind="external_url" if is_external else "python",
        runtime_version=None,
        entry_point="server.py" if not is_external else None,
        tool_schema=tools,
        pricing_model=pricing_model,
        pricing_config=pricing_config,
    )
    session.add(agent)

    for tool in tools:
        session.add(
            McpTool(
                id=uuid.uuid4(),
                agent_id=agent_id,
                name=tool["name"],
                description=tool.get("description") or description,
                input_schema=tool.get("inputSchema") or {},
                price_cents=tool.get("price_cents"),
            )
        )

    # Save encrypted credentials
    for cred_name, cred_value in credentials:
        encrypted = _encrypt_value(cred_value)
        session.add(
            AgentCredential(
                id=uuid.uuid4(),
                agent_id=agent_id,
                credential_name=cred_name,
                encrypted_value=encrypted,
            )
        )

    await session.commit()

    log.info(
        "agent.submitted",
        slug=slug,
        developer_id=str(account.id),
        credentials=len(credentials),
    )

    request.session["flash_agent"] = slug
    return RedirectResponse(url="/dashboard", status_code=303)


@router.post("/marketplace/{slug}/subscribe", response_model=None)
async def mcp_subscribe(
    request: Request,
    slug: str,
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    account = await _require_authenticated(request, session)
    if not account:
        return RedirectResponse(url="/login", status_code=303)

    result = await session.execute(
        select(Agent).where(Agent.slug == slug, Agent.status == "active")
    )
    agent = result.scalar_one_or_none()
    if not agent:
        return RedirectResponse(url="/#agents", status_code=303)

    result = await session.execute(
        select(McpSubscription).where(
            McpSubscription.account_id == account.id,
            McpSubscription.agent_id == agent.id,
        )
    )
    subscription = result.scalar_one_or_none()
    if subscription:
        subscription.status = "active"
    else:
        session.add(
            McpSubscription(
                id=uuid.uuid4(),
                account_id=account.id,
                agent_id=agent.id,
                status="active",
            )
        )
        agent.install_count += 1

    await session.commit()
    request.session["flash_agent"] = slug
    log.info("mcp.subscription.created", account_id=str(account.id), slug=slug)
    return RedirectResponse(url="/dashboard", status_code=303)


@router.post("/dashboard/subscriptions/{sub_id}/cancel", response_model=None)
async def mcp_subscription_cancel(
    request: Request,
    sub_id: str,
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    account = await _require_authenticated(request, session)
    if not account:
        return RedirectResponse(url="/login", status_code=303)

    try:
        sub_uuid = uuid.UUID(sub_id)
    except ValueError:
        return RedirectResponse(url="/dashboard", status_code=303)

    result = await session.execute(
        select(McpSubscription).where(
            McpSubscription.id == sub_uuid,
            McpSubscription.account_id == account.id,
        )
    )
    subscription = result.scalar_one_or_none()
    if subscription:
        subscription.status = "cancelled"
        await session.commit()

    return RedirectResponse(url="/dashboard", status_code=303)


# ---------------------------------------------------------------------------
# Agent Credentials (developer only)
# ---------------------------------------------------------------------------


async def _require_agent_owner(
    request: Request, session: AsyncSession, slug: str
) -> tuple[Account, Agent] | tuple[None, None]:
    """Return (account, agent) if the logged-in user owns this agent."""
    account = await _require_developer(request, session)
    if not account:
        return None, None
    result = await session.execute(
        select(Agent).where(Agent.slug == slug, Agent.developer_id == account.id)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        return None, None
    return account, agent


@router.get("/dashboard/agents/{slug}/credentials", response_model=None)
async def agent_credentials_page(
    request: Request,
    slug: str,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse | RedirectResponse:
    account, agent = await _require_agent_owner(request, session, slug)
    if not account or not agent:
        return RedirectResponse(url="/dashboard", status_code=303)

    result = await session.execute(
        select(AgentCredential)
        .where(AgentCredential.agent_id == agent.id)
        .order_by(AgentCredential.credential_name)
    )
    credentials = list(result.scalars().all())

    flash_msg = request.session.pop("flash_cred", None)

    return templates.TemplateResponse(
        request,
        "agent_credentials.html",
        {
            "account": account,
            "agent": agent,
            "credentials": credentials,
            "flash_msg": flash_msg,
        },
    )


@router.post("/dashboard/agents/{slug}/credentials/add", response_model=None)
async def agent_credential_add(
    request: Request,
    slug: str,
    cred_name: str = Form(...),
    cred_value: str = Form(...),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse | RedirectResponse:
    account, agent = await _require_agent_owner(request, session, slug)
    if not account or not agent:
        return RedirectResponse(url="/dashboard", status_code=303)

    cred_name = cred_name.strip().upper()
    cred_value = cred_value.strip()

    if not cred_name or not re.match(r"^[A-Z][A-Z0-9_]*$", cred_name):
        request.session["flash_cred"] = "Invalid credential name. Use UPPER_SNAKE_CASE."
        return RedirectResponse(url=f"/dashboard/agents/{slug}/credentials", status_code=303)

    if not cred_value:
        request.session["flash_cred"] = "Credential value cannot be empty."
        return RedirectResponse(url=f"/dashboard/agents/{slug}/credentials", status_code=303)

    # Check if credential already exists — update it
    result = await session.execute(
        select(AgentCredential).where(
            AgentCredential.agent_id == agent.id,
            AgentCredential.credential_name == cred_name,
        )
    )
    existing = result.scalar_one_or_none()

    encrypted = _encrypt_value(cred_value)

    if existing:
        existing.encrypted_value = encrypted
        request.session["flash_cred"] = f"Updated {cred_name}."
    else:
        session.add(
            AgentCredential(
                id=uuid.uuid4(),
                agent_id=agent.id,
                credential_name=cred_name,
                encrypted_value=encrypted,
            )
        )
        request.session["flash_cred"] = f"Added {cred_name}."

    await session.commit()
    log.info("credential.saved", slug=slug, credential_name=cred_name)
    return RedirectResponse(url=f"/dashboard/agents/{slug}/credentials", status_code=303)


@router.post("/dashboard/agents/{slug}/toggle", response_model=None)
async def agent_toggle(
    request: Request,
    slug: str,
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    """Toggle an agent between active and suspended status."""
    account, agent = await _require_agent_owner(request, session, slug)
    if not account or not agent:
        return RedirectResponse(url="/dashboard", status_code=303)

    if agent.status == "active":
        agent.status = "suspended"
    else:
        agent.status = "active"

    await session.commit()
    log.info("agent.toggled", slug=slug, new_status=agent.status)
    return RedirectResponse(url="/dashboard", status_code=303)


@router.post("/dashboard/agents/{slug}/delete", response_model=None)
async def agent_delete(
    request: Request,
    slug: str,
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    """Permanently delete an agent and its credentials."""
    account, agent = await _require_agent_owner(request, session, slug)
    if not account or not agent:
        return RedirectResponse(url="/dashboard", status_code=303)

    # Delete credentials first
    await session.execute(
        delete(AgentCredential).where(AgentCredential.agent_id == agent.id)
    )
    await session.execute(
        delete(Agent).where(Agent.id == agent.id)
    )
    await session.commit()
    log.info("agent.deleted", slug=slug, developer_id=str(account.id))
    return RedirectResponse(url="/dashboard", status_code=303)


@router.post("/dashboard/agents/{slug}/credentials/{cred_id}/delete", response_model=None)
async def agent_credential_delete(
    request: Request,
    slug: str,
    cred_id: str,
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    account, agent = await _require_agent_owner(request, session, slug)
    if not account or not agent:
        return RedirectResponse(url="/dashboard", status_code=303)

    try:
        cred_uuid = uuid.UUID(cred_id)
    except ValueError:
        return RedirectResponse(url=f"/dashboard/agents/{slug}/credentials", status_code=303)

    await session.execute(
        delete(AgentCredential).where(
            AgentCredential.id == cred_uuid,
            AgentCredential.agent_id == agent.id,
        )
    )
    await session.commit()

    request.session["flash_cred"] = "Credential deleted."
    log.info("credential.deleted", slug=slug, cred_id=cred_id)
    return RedirectResponse(url=f"/dashboard/agents/{slug}/credentials", status_code=303)


# ---------------------------------------------------------------------------
# Consumer Credentials
# ---------------------------------------------------------------------------


async def _require_authenticated(
    request: Request, session: AsyncSession
) -> Account | None:
    """Return the logged-in Account or None."""
    account_id = _get_account_id(request)
    if not account_id:
        return None
    result = await session.execute(select(Account).where(Account.id == account_id))
    return result.scalar_one_or_none()


@router.get("/dashboard/credentials", response_model=None)
async def consumer_credentials_page(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse | RedirectResponse:
    account = await _require_authenticated(request, session)
    if not account:
        return RedirectResponse(url="/login", status_code=303)

    result = await session.execute(
        select(ConsumerCredential)
        .where(ConsumerCredential.account_id == account.id)
        .order_by(ConsumerCredential.service_name)
    )
    credentials = list(result.scalars().all())

    flash_msg = request.session.pop("flash_consumer_cred", None)

    return templates.TemplateResponse(
        request,
        "consumer_credentials.html",
        {
            "account": account,
            "credentials": credentials,
            "flash_msg": flash_msg,
        },
    )


@router.post("/dashboard/credentials/add", response_model=None)
async def consumer_credential_add(
    request: Request,
    service_name: str = Form(...),
    cred_value: str = Form(...),
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    account = await _require_authenticated(request, session)
    if not account:
        return RedirectResponse(url="/login", status_code=303)

    service_name = service_name.strip().upper()
    cred_value = cred_value.strip()

    if not service_name or not re.match(r"^[A-Z][A-Z0-9_]*$", service_name):
        request.session["flash_consumer_cred"] = "Invalid name. Use UPPER_SNAKE_CASE (e.g. INSTACART_API_KEY)."
        return RedirectResponse(url="/dashboard/credentials", status_code=303)

    if not cred_value:
        request.session["flash_consumer_cred"] = "Credential value cannot be empty."
        return RedirectResponse(url="/dashboard/credentials", status_code=303)

    # Upsert: check if credential already exists
    result = await session.execute(
        select(ConsumerCredential).where(
            ConsumerCredential.account_id == account.id,
            ConsumerCredential.service_name == service_name,
        )
    )
    existing = result.scalar_one_or_none()

    encrypted = _encrypt_value(cred_value)

    if existing:
        existing.encrypted_value = encrypted
        request.session["flash_consumer_cred"] = f"Updated {service_name}."
    else:
        session.add(
            ConsumerCredential(
                id=uuid.uuid4(),
                account_id=account.id,
                service_name=service_name,
                encrypted_value=encrypted,
            )
        )
        request.session["flash_consumer_cred"] = f"Added {service_name}."

    await session.commit()
    log.info("consumer_credential.saved", account_id=str(account.id), service_name=service_name)
    return RedirectResponse(url="/dashboard/credentials", status_code=303)


@router.post("/dashboard/credentials/{cred_id}/delete", response_model=None)
async def consumer_credential_delete(
    request: Request,
    cred_id: str,
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    account = await _require_authenticated(request, session)
    if not account:
        return RedirectResponse(url="/login", status_code=303)

    try:
        cred_uuid = uuid.UUID(cred_id)
    except ValueError:
        return RedirectResponse(url="/dashboard/credentials", status_code=303)

    await session.execute(
        delete(ConsumerCredential).where(
            ConsumerCredential.id == cred_uuid,
            ConsumerCredential.account_id == account.id,
        )
    )
    await session.commit()

    request.session["flash_consumer_cred"] = "Credential deleted."
    log.info("consumer_credential.deleted", account_id=str(account.id), cred_id=cred_id)
    return RedirectResponse(url="/dashboard/credentials", status_code=303)


# ---------------------------------------------------------------------------
# HAL Signup Flow
# ---------------------------------------------------------------------------


def _normalize_phone(raw: str) -> str | None:
    """Normalize a phone string to E.164. Returns None if invalid."""
    digits = re.sub(r"[^\d+]", "", raw.strip())
    if digits.startswith("+"):
        if len(digits) >= 11:
            return digits
    elif digits.startswith("1") and len(digits) == 11:
        return f"+{digits}"
    elif len(digits) == 10:
        return f"+1{digits}"
    return None


def _get_twilio_client():
    """Lazy-init Twilio Verify client."""
    from twilio.rest import Client

    return Client(settings.twilio_account_sid, settings.twilio_auth_token)


@router.get("/get-hal", response_class=HTMLResponse)
async def get_hal_landing(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "get_hal.html")


@router.post("/get-hal/verify", response_model=None)
async def get_hal_verify(
    request: Request,
    phone: str = Form(...),
) -> HTMLResponse:
    normalized = _normalize_phone(phone)
    if not normalized:
        return templates.TemplateResponse(
            request,
            "get_hal.html",
            {"error": "Please enter a valid US phone number."},
            status_code=400,
        )

    try:
        client = _get_twilio_client()
        client.verify.v2.services(
            settings.twilio_verify_service_sid
        ).verifications.create(to=normalized, channel="sms")
    except Exception as exc:
        log.error("twilio.verify.send_failed", phone=normalized, error=str(exc))
        return templates.TemplateResponse(
            request,
            "get_hal.html",
            {"error": "Could not send verification code. Please try again."},
            status_code=500,
        )

    request.session["hal_signup_phone"] = normalized
    log.info("hal.signup.otp_sent", phone=normalized)

    return templates.TemplateResponse(
        request, "get_hal_otp.html", {"phone": normalized}
    )


@router.post("/get-hal/confirm", response_model=None)
async def get_hal_confirm(
    request: Request,
    code: str = Form(...),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    phone = request.session.get("hal_signup_phone")
    if not phone:
        return RedirectResponse(url="/get-hal", status_code=303)

    code = code.strip()
    if not re.match(r"^\d{6}$", code):
        return templates.TemplateResponse(
            request,
            "get_hal_otp.html",
            {"phone": phone, "error": "Please enter the 6-digit code."},
            status_code=400,
        )

    try:
        client = _get_twilio_client()
        check = client.verify.v2.services(
            settings.twilio_verify_service_sid
        ).verification_checks.create(to=phone, code=code)
        if check.status != "approved":
            raise ValueError("not approved")
    except Exception:
        return templates.TemplateResponse(
            request,
            "get_hal_otp.html",
            {"phone": phone, "error": "Invalid or expired code. Please try again."},
            status_code=400,
        )

    # Check for existing subscription
    result = await session.execute(
        select(AgentSubscription).where(
            AgentSubscription.phone == phone,
            AgentSubscription.agent_slug == "hal",
        )
    )
    existing = result.scalar_one_or_none()

    if existing and existing.status == "active":
        # Already provisioned — just show success
        request.session.pop("hal_signup_phone", None)
        return templates.TemplateResponse(
            request, "get_hal_success.html", {"phone": phone}
        )

    if not existing:
        sub = AgentSubscription(
            id=uuid.uuid4(),
            phone=phone,
            agent_slug="hal",
            status="pending_provision",
        )
        session.add(sub)
        await session.commit()
        log.info("hal.signup.subscription_created", phone=phone)
    # If exists but not active (e.g. cancelled), reset to pending
    elif existing.status != "pending_provision":
        existing.status = "pending_provision"
        existing.provisioned_at = None
        await session.commit()
        log.info("hal.signup.subscription_reset", phone=phone)

    request.session.pop("hal_signup_phone", None)
    return templates.TemplateResponse(
        request, "get_hal_success.html", {"phone": phone}
    )


@router.get("/internal/pending-provisions", response_model=None)
async def pending_provisions(
    request: Request,
    secret: str = "",
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    if not settings.hal_provision_secret or secret != settings.hal_provision_secret:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    result = await session.execute(
        select(AgentSubscription).where(
            AgentSubscription.status == "pending_provision",
            AgentSubscription.agent_slug == "hal",
        )
    )
    rows = result.scalars().all()

    return JSONResponse([
        {"phone": r.phone, "sub_id": str(r.id)} for r in rows
    ])


@router.post("/internal/provision-complete", response_model=None)
async def provision_complete(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    body = await request.json()
    secret = body.get("secret", "")
    sub_id = body.get("sub_id", "")

    if not settings.hal_provision_secret or secret != settings.hal_provision_secret:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    try:
        sub_uuid = uuid.UUID(sub_id)
    except ValueError:
        return JSONResponse({"error": "invalid sub_id"}, status_code=400)

    result = await session.execute(
        select(AgentSubscription).where(AgentSubscription.id == sub_uuid)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        return JSONResponse({"error": "not found"}, status_code=404)

    from datetime import datetime, timezone
    sub.status = "active"
    sub.provisioned_at = datetime.now(timezone.utc)
    await session.commit()

    log.info("hal.provision.complete", phone=sub.phone, sub_id=sub_id)
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


@router.get("/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)


# ---------------------------------------------------------------------------
# CLAUDE.md snippet builder
# ---------------------------------------------------------------------------


def _build_claude_snippet(api_key: str) -> str:
    return f"""# AgentGate MCP Marketplace

You have access to AgentGate, a hosted MCP marketplace.
Subscribed MCP servers are exposed through one gateway endpoint.

## API Access

- **Gateway URL:** `{GATEWAY_URL}`
- **API Key:** `{api_key}`

## Available Endpoints

```bash
# Check your balance
curl -H "Authorization: Bearer {api_key}" {GATEWAY_URL}/v1/balance

# Discover agents by keyword
curl -X POST -H "Authorization: Bearer {api_key}" \\
  -H "Content-Type: application/json" \\
  -d '{{"query": "summarize"}}' \\
  {GATEWAY_URL}/v1/discover

# Invoke an agent
curl -X POST -H "Authorization: Bearer {api_key}" \\
  -H "Content-Type: application/json" \\
  -d '{{"agent_slug":"echo","input":{{"message":"hello"}}}}' \\
  {GATEWAY_URL}/v1/invoke

# List subscribed MCP tools
curl -X POST -H "Authorization: Bearer {api_key}" \\
  -H "Content-Type: application/json" \\
  -d '{{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{{}}}}' \\
  {GATEWAY_URL}/v1/mcp
```

## Notes
- MCP tools are namespaced as `server_slug__tool_name`.
- Subscribe to servers from the dashboard before calling `/v1/mcp`.
- Use `/v1/balance` to check remaining credits."""
