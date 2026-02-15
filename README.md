# AgentGate

Hosted agent marketplace — one URL, one API key, any agent.

## Quick Start

```bash
# 1. Install dependencies
make setup

# 2. Start PostgreSQL + Redis
make dev

# 3. Run migrations
make migrate

# 4. Seed database
uv run python scripts/seed_db.py --with-test-data

# 5. Start services (in separate terminals)
make gateway      # port 8000
make registry     # port 8001
make billing      # port 8002
make orchestrator # port 8003
```

## API

All consumer endpoints require `Authorization: Bearer <api_key>`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| POST | `/v1/discover` | Semantic search for agents |
| POST | `/v1/invoke` | Invoke an agent |
| GET | `/v1/balance` | Check credit balance |
| GET | `/v1/history` | Transaction history |
| POST | `/v1/deposit` | Create Stripe checkout session |

## Architecture

```
Consumer → Gateway (:8000)
              ├→ Registry (:8001)     /v1/discover
              ├→ Billing (:8002)      /v1/balance, /v1/deposit
              └→ Orchestrator (:8003) /v1/invoke
                    ├→ Billing        hold/settle/release
                    └→ Docker         container lifecycle
```

## Management Scripts

```bash
# Create account + API key
uv run python scripts/create_account.py --email user@example.com --password secret123 --role consumer

# Submit an agent
uv run python scripts/submit_agent.py --path agents/echo --developer-email dev@example.com

# Approve/suspend agents
uv run python scripts/manage_agent.py approve --slug echo
uv run python scripts/manage_agent.py list
```

## Testing

```bash
make test          # Run all tests
make test-cov      # With coverage
make lint          # Ruff lint + format check
make typecheck     # mypy
```

## Tech Stack

Python 3.12, FastAPI, SQLAlchemy 2.0, PostgreSQL + pgvector, Redis, Celery, Docker, Stripe, OpenAI embeddings.
