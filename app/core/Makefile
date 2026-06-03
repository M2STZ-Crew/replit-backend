.PHONY: help install dev run lint format typecheck test check docker-build docker-up docker-down clean

help:
	@echo "Targets:"
	@echo "  install       uv sync (create venv + install deps)"
	@echo "  dev           run with autoreload"
	@echo "  run           run without autoreload"
	@echo "  lint          ruff check"
	@echo "  format        ruff format"
	@echo "  typecheck     mypy app"
	@echo "  test          pytest"
	@echo "  check         lint + typecheck + test"
	@echo "  docker-build  build the image via compose"
	@echo "  docker-up     start the container (detached)"
	@echo "  docker-down   stop and remove the container"
	@echo "  clean         remove tool caches"

install:
	uv sync

dev:
	uv run uvicorn app.main:app --reload

run:
	uv run uvicorn app.main:app --host 0.0.0.0 --port 8000

lint:
	uv run ruff check .

format:
	uv run ruff format .

typecheck:
	uv run mypy app

test:
	uv run pytest

check: lint typecheck test

docker-build:
	docker compose build

docker-up:
	docker compose up -d

docker-down:
	docker compose down

clean:
	uv run python -c "import shutil; [shutil.rmtree(p, ignore_errors=True) for p in ['.pytest_cache','.mypy_cache','.ruff_cache']]"