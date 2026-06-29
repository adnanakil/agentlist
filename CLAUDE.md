# AgentGate — CLAUDE.md

## Project Overview

AgentGate is a hosted agent marketplace where developers submit agent code and consumers invoke those agents through a single API endpoint (one URL + one API key). The platform handles hosting, sandboxed execution, credential management, billing (prepaid USD credits via Stripe), and agent discovery via semantic search.

## Tech Stack

- **Language**: Python 3.12
- **Framework**: FastAPI (all 5 services)
- **ORM**: SQLAlchemy 2.0 (async) with asyncpg
- **Database**: PostgreSQL 17 (Railway managed)
- **Cache/Broker**: Redis 7 (Railway managed)
- **Task Queue**: Celery 5 + Redis
- **Payments**: Stripe Checkout + webhooks
- **Embeddings**: OpenAI text-embedding-3-small (for semantic agent search)
- **Credential Encryption**: Fernet (AES-256)
- **Package Manager**: uv (workspace mode)
- **Linting**: ruff
- **Type Checking**: mypy
- **Testing**: pytest + pytest-asyncio
- **Deployment**: Railway (Dockerfiles)

## Monorepo Structure

```
agentgate/
├── pyproject.toml              # uv workspace root — defines members + dev deps
├── Makefile                    # dev commands: setup, dev, test, lint, migrate
├── docker-compose.yml          # local dev: postgres (pgvector) + redis
├── .env.example
│
├── packages/
│   ├── ag-common/              # shared: config, models, auth, errors
│   │   └── ag_common/
│   └── ag-db/                  # SQLAlchemy models + Alembic migrations
│       ├── ag_db/
│       └── migrations/versions/001_initial.py
│
├── services/
│   ├── gateway/    (:8000)     # public API — proxies to internal services
│   ├── registry/   (:8001)     # agent catalog + semantic search
│   ├── billing/    (:8002)     # ledger, holds, Stripe
│   ├── orchestrator/ (:8003)   # agent execution lifecycle
│   └── web/        (:8004)     # signup, dashboard, agent submission UI
│
├── agent-sdk/python/           # SDK for agent developers
├── agents/                     # 21 curated agents (echo, web-scraper, scholar, etc.)
├── scripts/                    # CLI tools: seed_db, create_account, submit_agent, populate_marketplace
└── tests/
```

## Architecture

```
Browser -> Web (:8004)                 signup, login, dashboard, agent submission
Consumer -> Gateway (:8000)
              ├-> Registry (:8001)     POST /v1/discover
              ├-> Billing (:8002)      GET /v1/balance, /v1/history, POST /v1/deposit
              └-> Orchestrator (:8003) POST /v1/invoke
                    ├-> Billing        hold/settle/release
                    ├-> Subprocess     hosted agent execution
                    └-> HTTP proxy     external agent execution
```

All inter-service communication is internal HTTP via httpx.AsyncClient. On Railway, services use private networking (`http://{service}.railway.internal:{port}`).

## Key Commands

```bash
# Local development
make setup          # install deps with uv
make dev            # start postgres + redis via docker-compose
make migrate        # run alembic migrations (local)
make gateway        # run gateway on port 8000
make registry       # run registry on port 8001
make billing        # run billing on port 8002
make orchestrator   # run orchestrator on port 8003

# Database (against Railway) — export DATABASE_URL from your .env first:
#   set -a && source .env && set +a   (or: export DATABASE_URL="$(grep ^DATABASE_URL .env | cut -d= -f2-)")
DATABASE_URL="$DATABASE_URL" uv run alembic -c packages/ag-db/alembic.ini upgrade head
DATABASE_URL="..." uv run python scripts/seed_db.py --with-test-data
DATABASE_URL="..." uv run python scripts/submit_agent.py --path agents/echo --developer-email test-developer@agentgate.dev
DATABASE_URL="..." uv run python scripts/manage_agent.py approve --slug echo

# Alembic must be run from packages/ag-db/ directory (script_location is relative)
cd packages/ag-db && DATABASE_URL="..." uv run alembic upgrade head

# Testing
make test           # pytest
make test-cov       # with coverage
make lint           # ruff
make typecheck      # mypy
```

## Railway Deployment

### Project Info
- **Project**: agentgate
- **Project ID**: d16287a1-5b7b-4f1e-8378-04521eb2b512
- **Region**: europe-west4
- **Gateway URL**: https://gateway-production-cd14.up.railway.app

### Services
| Service | Service ID | Port | Status |
|---------|-----------|------|--------|
| gateway | 2b7acf72-8f21-457b-b043-42c3dbf8327c | 8000 | Online |
| registry | fa3784b6-dc5d-49fb-8e66-3dbc888081c8 | 8001 | Online |
| billing | 11fa03d5-08e6-4682-95bf-a2f01fdcd9ca | 8002 | Online |
| orchestrator | 45691e09-a2da-43ab-b4a3-ca86f663489d | 8003 | Online |
| web | c23e54cc-7561-4b51-9964-5f2f4159480c | 8004 | Online |

- **Web URL**: https://web-production-f1dbe.up.railway.app
- **Custom Domain**: axon.talk (pending DNS verification)

### Database Credentials

Real connection strings are **not stored in the repo**. They live in:
- **Production**: Railway service variables (`DATABASE_URL`, `REDIS_URL`) — view with
  `railway variables --service <name>` or the Railway dashboard.
- **Local**: your gitignored `.env` (copy `.env.example` → `.env` and fill in).

Connection-string shapes (host/port only — secrets come from env):
- **Postgres internal**: `postgresql+asyncpg://postgres:${PGPASSWORD}@postgres.railway.internal:5432/railway`
- **Postgres public**: `postgresql://postgres:${PGPASSWORD}@yamanote.proxy.rlwy.net:11694/railway`
- **Redis**: `redis://default:${REDISPASSWORD}@redis.railway.internal:6379`

### Deploying to Railway

Each service has its own `railway.toml` in its subdirectory, but Railway only reads `railway.toml` from the project root. The deploy procedure is:

```bash
# For each service: copy its railway.toml to root, deploy, clean up
cp services/gateway/railway.toml railway.toml
railway up --service gateway --detach
rm railway.toml

# Repeat for billing, registry, orchestrator
```

### Dockerfile Notes

- **Do NOT use `uv pip install`** in Dockerfiles. uv enforces workspace source resolution (`tool.uv.sources`) which breaks in Docker context. Use plain `pip install --no-cache-dir` instead.
- **Do NOT use `COPY pyproject.toml ./`** (the root workspace pyproject.toml) in Dockerfiles — it triggers uv workspace validation.
- **Use shell form CMD** to read PORT from env: `CMD uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- `pydantic[email]` is required in ag-common (not just `pydantic`) because models use `EmailStr`.
- Every service MUST have a `GET /health` endpoint returning 200 — Railway healthcheck expects it.

### Environment Variables

All services get: `DATABASE_URL`, `REDIS_URL`, `ENVIRONMENT=production`, `LOG_LEVEL=INFO`, `PORT`

Service-specific:
- **gateway**: `REGISTRY_URL`, `BILLING_URL`, `ORCHESTRATOR_URL`, `RATE_LIMIT_PER_MINUTE`
- **registry**: `OPENAI_API_KEY`
- **billing**: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`
- **orchestrator**: `BILLING_URL`, `ENCRYPTION_KEY`, `AGENT_TIMEOUT_SECONDS`, `AGENT_MEMORY_LIMIT_MB`
- **web**: `SESSION_SECRET`, `ENCRYPTION_KEY`

## Test Accounts (Railway Production)

| Account | Email | API Key | Role |
|---------|-------|---------|------|
| Consumer | test-consumer@agentgate.dev | `ag_live_…` (see `.env` / Railway) | consumer |
| Developer | test-developer@agentgate.dev | `ag_live_…` (see `.env` / Railway) | developer |
| Admin | platform@agentgate.dev | (no API key) | admin |

Consumer has $10.00 (1000 cents) balance pre-loaded. The live test keys are kept
out of the repo — pull them from your `.env` or the Railway dashboard when needed.

## API Testing

```bash
# Health check
curl https://gateway-production-cd14.up.railway.app/health

# Check balance (requires auth) — export CONSUMER_KEY from .env first
curl -H "Authorization: Bearer $CONSUMER_KEY" \
  https://gateway-production-cd14.up.railway.app/v1/balance

# Discover agents (requires OpenAI API key on registry)
curl -X POST -H "Authorization: Bearer ..." -H "Content-Type: application/json" \
  -d '{"query": "echo"}' \
  https://gateway-production-cd14.up.railway.app/v1/discover

# Invoke agent (Docker runtime not available on Railway — returns 500)
curl -X POST -H "Authorization: Bearer ..." -H "Content-Type: application/json" \
  -d '{"agent_slug":"echo","input":{"message":"hello"}}' \
  https://gateway-production-cd14.up.railway.app/v1/invoke
```

## Web Service (`services/web/`)

Server-rendered FastAPI + Jinja2 app. No JS framework — just HTML forms with minimal inline CSS (dark theme). Cookie-based auth via `SessionMiddleware`.

### Routes

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | No | Landing page — agent catalog grouped by category, stats |
| GET | `/signup` | No | Signup form (email, password, role) |
| POST | `/signup` | No | Create account + API key + ledger accounts, redirect to dashboard |
| GET | `/login` | No | Login form |
| POST | `/login` | No | Validate credentials, set session cookie |
| GET | `/dashboard` | Cookie | API key, balance, CLAUDE.md snippet, My Agents (developer) |
| GET | `/dashboard/submit-agent` | Developer | Agent submission form (hosted or external) |
| POST | `/dashboard/submit-agent` | Developer | Validate + create Agent row + credentials |
| GET | `/dashboard/agents/{slug}/credentials` | Developer | Manage credentials for an agent |
| POST | `/dashboard/agents/{slug}/credentials/add` | Developer | Add/update encrypted credential |
| POST | `/dashboard/agents/{slug}/credentials/{id}/delete` | Developer | Delete credential |
| GET | `/logout` | Cookie | Clear session, redirect to landing |
| GET | `/health` | No | Health check |

### Templates

```
services/web/web/templates/
├── base.html                # shared layout, nav, dark theme CSS
├── index.html               # landing page — hero, stats, agent catalog by category
├── signup.html              # email/password/role form
├── login.html               # email/password form
├── dashboard.html           # API key, balance, My Agents list, CLAUDE.md snippet
├── submit_agent.html        # agent submission: hosted vs external, code/URL, credentials, schema
└── agent_credentials.html   # per-agent credential management (add/delete)
```

## User Flows

### Consumer Signup
1. Visit `/signup`, select "Consumer" role, enter email + password
2. Account created with `consumer_balance` + `held_funds` ledger accounts
3. API key generated (shown once on dashboard)
4. Dashboard shows balance, API key, copyable CLAUDE.md snippet
5. Consumer uses API key to call Gateway endpoints (discover, invoke, balance)

### Developer Signup
1. Visit `/signup`, select "Developer" role, enter email + password
2. Account created with `developer_earnings` ledger account
3. Dashboard shows "My Agents" section with "Submit New Agent" button

### Agent Submission (Developer)
1. Click "Submit New Agent" from dashboard
2. Fill in: slug, name, description, category, price, tags
3. Choose hosting type:
   - **Hosted**: Paste Python code (subclasses `AgentHandler` from SDK)
   - **External**: Provide HTTPS endpoint URL (developer hosts it themselves)
4. Optionally add credentials (API keys/secrets) — encrypted with Fernet (AES-256)
5. Optionally define input JSON schema
6. Agent created with `status="active"`, appears on marketplace immediately

### Agent Invocation (Consumer)
1. Consumer calls `POST /v1/invoke` via Gateway with `agent_slug` + `input`
2. Gateway proxies to Orchestrator
3. Orchestrator: create invocation record → place billing hold → execute agent → settle/release hold
4. Execution routing:
   - If `agent.endpoint_url` is set → **External Runtime**: POST `{"input": {...}}` to developer's URL
   - Otherwise → **Subprocess Runtime**: run agent code in local process
5. Response returned with output, duration, price charged

## Agent Hosting Model

### Hosted Agents (lightweight)
- Developer uploads Python code via web form
- Code stored in `manifest.agent_code` (JSONB)
- Runs on our infrastructure via subprocess runtime
- Suitable for: pure Python, API calls, text processing

### External Agents (heavy/custom)
- Developer provides an HTTPS endpoint URL
- We proxy invocations to their server: `POST {"input": {...}}` → expects `{"output": {...}}`
- Developer runs whatever they want: Chromium, GPU, Node.js, custom Docker images
- AgentGate handles: auth, billing, discovery, rate limiting
- Suitable for: browser automation, ML inference, anything needing custom infra

### Credential Management
- Developers add credentials per agent (e.g. `GEMINI_API_KEY`)
- Values encrypted with Fernet (AES-256) before storage in `agent_credentials` table
- At runtime, orchestrator decrypts and injects as env vars
- Web UI: add/update/delete from `/dashboard/agents/{slug}/credentials`
- Same `ENCRYPTION_KEY` shared between web service and orchestrator

## Marketplace Data

### Accounts (populated via `scripts/populate_marketplace.py`)
- 12 developer accounts (DataWeave, WebTools, TextCraft AI, DevUtils, SecureBytes, NetOps, Claude Labs, PlaceWise, PixelForge, DocShare, Scholar AI, FreshCart)
- 4 consumer accounts with pre-loaded balances ($5-$50)
- Test accounts (see Test Accounts section)

### Agents (21 total across 6 categories)
- **Data**: csv-analyzer, json-transformer
- **Web**: web-scraper, markdown-converter, place-finder, page-creator
- **Text**: text-summarizer, word-counter
- **Code**: code-formatter, regex-tester
- **Utilities**: hash-generator, base64-encoder, ip-lookup, email-validator, instacart-list, instacart-recipe
- **Research**: claude-assistant, brainstorm, scholar, image-generator

### Categories (8 seeded)
data, web, text, code, utilities, finance, communication, research

## Known Limitations / TODOs

1. **No pgvector on Railway Postgres** — `description_embedding` column is JSONB instead of `Vector(1536)`. Semantic search via cosine similarity not available. Options: custom Postgres image with pgvector, or Supabase/Neon.

2. **No Docker-in-Docker on Railway** — Hosted agents use subprocess runtime (not Docker containers). External agents use HTTP proxy to developer endpoints.

3. **Placeholder API keys** — `OPENAI_API_KEY`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` are placeholders. `ENCRYPTION_KEY` is set to a real Fernet key on web + orchestrator.

4. **Discover endpoint returns 500** — Registry tries to call OpenAI for embeddings with a placeholder key.

5. **Custom domain (axon.talk)** — DNS configured (CNAME → `3lw1p5wd.up.railway.app`) but Railway still shows "Waiting for DNS update". SSL cert not yet provisioned.

6. **No agent code execution for web-submitted hosted agents** — The subprocess runtime expects a Docker image, not inline code from `manifest.agent_code`. Need to build a runtime that extracts code from the manifest and runs it directly.

7. **Heavy agent hosting** — External endpoint model works for developers who self-host. Future: managed heavy runtimes (Chromium, GPU) as a premium tier.

## Curated Agents

21 agents in `agents/` directory, each with `manifest.yaml`, `agent.py`, and `Dockerfile`:
- **Original 14**: echo, web-scraper, text-summarizer, json-transformer, code-formatter, hash-generator, csv-analyzer, regex-tester, markdown-converter, word-counter, base64-encoder, email-validator, ip-lookup, claude-assistant
- **Ported from HAL (7)**: place-finder, image-generator, page-creator, scholar, brainstorm, instacart-list, instacart-recipe

## Database

- **Schema**: Managed by Alembic
  - `001_initial.py` — all tables
  - `002_add_endpoint_url.py` — `endpoint_url` column on agents for external hosting
- **Tables**: accounts, api_keys, categories, agents, agent_credentials, ledger_accounts, ledger_entries, billing_holds, invocations, stripe_events
- **Key columns on agents**: `endpoint_url` (nullable, for external agents), `manifest` (JSONB, stores agent_code for hosted agents)
- **Billing**: Double-entry bookkeeping with `SELECT ... FOR UPDATE` for concurrent hold safety
- **Auth**: API keys prefixed `ag_live_`, stored as SHA-256 hashes. Web auth via signed session cookies.
- **Seeded data**: 8 categories, 21 agents, 12 developer accounts, 4 consumer accounts (via `scripts/populate_marketplace.py`)
