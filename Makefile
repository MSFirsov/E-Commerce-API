.PHONY: up down logs lint format typecheck test check

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
