.PHONY: install dev dev-backend dev-frontend test test-backend test-frontend \
        lint lint-backend lint-frontend format format-backend format-frontend \
        typecheck typecheck-backend typecheck-frontend \
        docker-up docker-down docker-build clean

BACKEND_DIR := backend
FRONTEND_DIR := frontend
VENV := $(BACKEND_DIR)/.venv

install: ## Install backend (uv) and frontend (npm) dependencies
	cd $(BACKEND_DIR) && uv venv --python 3.13 .venv
	cd $(BACKEND_DIR) && . .venv/bin/activate && uv pip install -e ".[dev]"
	cd $(FRONTEND_DIR) && npm install

dev: ## Run backend + frontend dev servers together (Ctrl+C stops both)
	@$(MAKE) -j2 dev-backend dev-frontend

dev-backend:
	cd $(BACKEND_DIR) && . .venv/bin/activate && uvicorn app.main:app --reload

dev-frontend:
	cd $(FRONTEND_DIR) && npm run dev

test: test-backend test-frontend ## Run all test suites

test-backend:
	cd $(BACKEND_DIR) && . .venv/bin/activate && pytest

test-frontend:
	cd $(FRONTEND_DIR) && npm run test

lint: lint-backend lint-frontend ## Run all linters

lint-backend:
	cd $(BACKEND_DIR) && . .venv/bin/activate && ruff check .

lint-frontend:
	cd $(FRONTEND_DIR) && npm run lint

format: format-backend format-frontend ## Auto-format all code

format-backend:
	cd $(BACKEND_DIR) && . .venv/bin/activate && ruff format .

format-frontend:
	cd $(FRONTEND_DIR) && npx prettier --write . 2>/dev/null || true

typecheck: typecheck-backend typecheck-frontend ## Run all type checkers

typecheck-backend:
	cd $(BACKEND_DIR) && . .venv/bin/activate && mypy app

typecheck-frontend:
	cd $(FRONTEND_DIR) && npm run typecheck

docker-build: ## Build all Docker images
	docker compose build

docker-up: ## Start the full stack (Postgres + backend + frontend) via Docker Compose
	docker compose up --build

docker-down: ## Stop and remove the Docker Compose stack
	docker compose down

clean: ## Remove build artifacts and caches
	rm -rf $(BACKEND_DIR)/.pytest_cache $(BACKEND_DIR)/.mypy_cache $(BACKEND_DIR)/.ruff_cache $(BACKEND_DIR)/htmlcov
	rm -rf $(FRONTEND_DIR)/.next $(FRONTEND_DIR)/node_modules/.cache
