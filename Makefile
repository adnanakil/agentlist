.PHONY: setup dev test lint migrate format typecheck clean

setup:
	uv sync --all-packages
	cp -n .env.example .env 2>/dev/null || true

dev:
	docker compose up -d
	@echo "Waiting for services..."
	@sleep 3
	@echo "PostgreSQL and Redis are running"

dev-down:
	docker compose down

migrate:
	cd packages/ag-db && uv run alembic upgrade head

migrate-new:
	cd packages/ag-db && uv run alembic revision --autogenerate -m "$(msg)"

test:
	uv run pytest tests/ -v --tb=short

test-cov:
	uv run pytest tests/ -v --tb=short --cov=packages --cov=services --cov-report=html

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

typecheck:
	uv run mypy packages/ services/

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true

# Service runners
gateway:
	uv run uvicorn gateway.main:app --host 0.0.0.0 --port 8000 --reload

registry:
	uv run uvicorn registry.main:app --host 0.0.0.0 --port 8001 --reload

billing:
	uv run uvicorn billing.main:app --host 0.0.0.0 --port 8002 --reload

orchestrator:
	uv run uvicorn orchestrator.main:app --host 0.0.0.0 --port 8003 --reload

worker:
	uv run celery -A orchestrator.worker worker --loglevel=info
