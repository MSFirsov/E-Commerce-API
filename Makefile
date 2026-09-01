.PHONY: up down logs lint format typecheck test check migrate revision downgrade db-shell

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f api

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check --fix .

typecheck:
	uv run mypy

test:
	uv run pytest -v

check: lint typecheck test

migrate:
	uv run alembic upgrade head

revision:
	uv run alembic revision --autogenerate -m "$(m)"

downgrade:
	uv run alembic downgrade -1

db-shell:
	docker compose exec postgres sh -c 'psql -U $$POSTGRES_USER -d $$POSTGRES_DB'
