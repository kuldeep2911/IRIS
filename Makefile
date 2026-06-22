# I.R.I.S. v5 — dev shortcuts. (GNU make; on Windows use Git Bash / WSL.)
.PHONY: install dev test up down fmt

install:
	pip install -e ".[dev]"

dev:
	uvicorn iris.gateway.api:app --reload --port 8000

test:
	pytest -q

up:
	docker compose up -d

down:
	docker compose down

fmt:
	ruff check --fix iris && ruff format iris
