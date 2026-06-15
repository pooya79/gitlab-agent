DEV_COMPOSE  := docker/docker-compose.yml
PROD_COMPOSE := docker/docker-compose-all.yml

.PHONY: help dev prod down-dev down-prod down clean-dev clean-prod clean

.DEFAULT_GOAL := help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

# --- Run -------------------------------------------------------------------

dev: ## Run the dev stack (backend + mongodb) with file-watch
	docker compose -f $(DEV_COMPOSE) up --build --watch

prod: ## Run the full prod stack (traefik + backend + frontend + mongodb)
	docker compose -f $(PROD_COMPOSE) up --build -d

# --- Stop ------------------------------------------------------------------

down-dev: ## Stop and remove dev containers
	docker compose -f $(DEV_COMPOSE) down

down-prod: ## Stop and remove prod containers
	docker compose -f $(PROD_COMPOSE) down

down: down-dev down-prod ## Stop and remove all containers

# --- Stop + remove volumes -------------------------------------------------

clean-dev: ## Stop dev stack and remove its volumes
	docker compose -f $(DEV_COMPOSE) down -v

clean-prod: ## Stop prod stack and remove its volumes
	docker compose -f $(PROD_COMPOSE) down -v

clean: clean-dev clean-prod ## Stop all stacks and remove all volumes
