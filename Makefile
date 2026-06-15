DEV_COMPOSE  := docker/docker-compose.yml
PROD_COMPOSE := docker/docker-compose-all.yml
ENV_FILE     := .env

# Local dev backend port (override: make dev BACKEND_PORT=8001). The frontend
# is pointed at this port via NEXT_PUBLIC_BACKEND_URL so its API calls follow.
BACKEND_PORT ?= 8000

# Compose resolves its project directory (and thus auto-loads .env) from the
# compose file's folder (docker/), so point it at the repo-root .env explicitly.
COMPOSE      := docker compose --env-file $(ENV_FILE)

.PHONY: help dev prod create-admin down-dev down-prod down clean-dev clean-prod clean

.DEFAULT_GOAL := help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

# --- Run -------------------------------------------------------------------

dev: ## Run mongodb in Docker; run backend + frontend locally with hot-reload
	$(COMPOSE) -f $(DEV_COMPOSE) up -d
	@echo "MongoDB is up in Docker. Starting local backend (:$(BACKEND_PORT)) + frontend (:3000)..."
	@cd Frontend && npm install
	@trap 'kill 0' INT TERM EXIT; \
		( cd Backend && MONGODB_HOST=localhost uv run uvicorn app.main:app --reload --port $(BACKEND_PORT) --env-file ../.env ) & \
		( cd Frontend && NEXT_PUBLIC_BACKEND_URL=http://localhost:$(BACKEND_PORT) npm run dev ) & \
		wait

prod: ## Run the full prod stack (traefik + backend + frontend + mongodb)
	$(COMPOSE) -f $(PROD_COMPOSE) up --build -d

create-admin: ## Create/update the admin user (uses ADMIN_* from .env; or pass ARGS="--username ... --email ... --password ...")
	cd Backend && MONGODB_HOST=localhost uv run --env-file ../.env python -m scripts.create_admin $(ARGS)

# --- Stop ------------------------------------------------------------------

down-dev: ## Stop and remove dev containers
	$(COMPOSE) -f $(DEV_COMPOSE) down

down-prod: ## Stop and remove prod containers
	$(COMPOSE) -f $(PROD_COMPOSE) down

down: down-dev down-prod ## Stop and remove all containers

# --- Stop + remove volumes -------------------------------------------------

clean-dev: ## Stop dev stack and remove its volumes
	$(COMPOSE) -f $(DEV_COMPOSE) down -v

clean-prod: ## Stop prod stack and remove its volumes
	$(COMPOSE) -f $(PROD_COMPOSE) down -v

clean: clean-dev clean-prod ## Stop all stacks and remove all volumes
