# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

A GitLab review bot platform. Users connect a GitLab account (OAuth), register one or more "bots" (each backed by a GitLab project access token + webhook), and the bots respond to merge-request events and comments by running LLM agents that post reviews, suggestions, and replies back to the MR.

Monorepo with two independently-deployed services:
- `Backend/` — FastAPI (Python 3.13, managed by **uv**), MongoDB, agents built on **pydantic-ai** routed through **OpenRouter**.
- `Frontend/` — Next.js 16 / React 19 admin panel; the API client is **generated** from the backend's OpenAPI spec.

## Commands

### Backend (run from `Backend/`)
```bash
uv sync                                              # install deps
uv run uvicorn app.main:app --reload --port 8000     # dev server (docs at /api/docs)
```
There is no test suite or linter configured for the backend; `test.ipynb` files are scratch notebooks, not tests.

### Frontend (run from `Frontend/`)
```bash
npm install
npm run dev                # next dev (http://localhost:3000)
npm run build
npm run lint               # biome check
npm run format             # biome format --write (4-space indent)
npm run generate-client    # regenerate src/client/ from Frontend/openapi.json
```

### Docker
All Docker assets live in `docker/` (compose files + `Backend.Dockerfile`, `Frontend.Dockerfile` and its `.dockerignore`). A root `Makefile` wraps the common flows (`make help` to list): `make dev` / `make prod`, `make down*`, `make clean*`. Or invoke compose directly **from the repo root** (paths inside the compose files are relative to `docker/`, so they resolve via `../`):
```bash
docker compose -f docker/docker-compose.yml up --watch        # dev: backend + mongodb
docker compose -f docker/docker-compose-all.yml up            # prod: + frontend + traefik (behind / and /api)
```
Copy `.env.sample` → `.env` first (in the repo root); both services read it. The same `.env` drives `core/config.py` (backend) and `NEXT_PUBLIC_BACKEND_URL` (frontend).

## Architecture

### Request → agent flow
GitLab calls `POST /api/v{api_version}/webhooks/{bot_user_id}` (see `app/api/routes/webhooks.py`). The handler loads the `Bot` by `gitlab_user_id`, verifies `X-Gitlab-Token` against the bot's stored secret, then dispatches on `X-Gitlab-Event` to `app/services/event_handlers.py`:

- **Merge Request Hook** → triggers only when the bot is *newly added as reviewer* or a review is *re-requested*. Runs `SmartAgent` to produce a full review and posts it as an MR note.
- **Note Hook** → only acts when the bot is `@`-mentioned on an MR note. Two sub-paths:
  - `@bot/command ...` → `CommandAgent` (slash-command style).
  - plain `@bot ...` → `SmartAgent` in conversational mode, rebuilding chat history from the discussion's prior notes (capped by `max_chat_history`).

Each handler posts a temporary "Processing…" note, runs the agent, then replaces it with the result.

### Two agent kinds (`app/agents/`)
- **`SmartAgent`** (`smart_agent.py`) — the conversational/review agent. Gathers MR context (diffs, title, description; large diffs skipped via `token_counter`) into the system prompt, and exposes **tools** (`approve_mr`, `unapprove_mr`, `get_file`) with hard usage caps (`UsageLimits(tool_calls_limit=3)`). Every run is recorded in the `mr_agent_history` collection with token/cost accounting (`_start_history`/`_update_history`).
- **`CommandAgent`** (`command_agent.py`) — parses `/command --flags args` (shlex-based `_parse_bot_command`) and delegates to a command class in `app/agents/commands/`. Registered commands: `help`, `review`, `describe`, `suggest`, `add_docs`. Each subclasses `CommandInterface`, which provides shared GitLab data-gathering (`gether_gitlab_data`, diff formatting with line numbers, issue extraction from `#NNN` references). Commands use pydantic-ai `output_type` for structured LLM output, then render it to GitLab-flavored HTML/markdown.

Prompt templates live in `app/prompts/` (Jinja2 `system_template`/`user_template` per command).

### LLM configuration
Models go through OpenRouter (`OpenRouterProvider` + `OpenAIChatModel`). Per-bot settings (`llm_model`, `llm_temperature`, `llm_max_output_tokens`, `llm_additional_kwargs`, `llm_system_prompt`) live on the `Bot` document. The catalog of selectable models and their defaults is seeded from `app/core/llm_configs.py` (`LLMModelInfo` list) and editable at runtime via `/api/v1/config/available-llms`.

### Configuration layering
`app/core/config.py` (`Settings`, pydantic-settings) reads env vars with **nested delimiter `_`, max split 1** — so `MONGODB_HOST`, `GITLAB_CLIENT_ID`, etc. map onto the `mongodb` / `gitlab` sub-models. Runtime-overridable values live in the Mongo `configs` collection (`Configs` model), which `init_db()` **resets to defaults on every startup**.

### Persistence — MongoDB only
Despite a stray `data/database.db`, the app uses MongoDB exclusively (`app/db/database.py`). A module-global client is lazily created; `init_db()` (called in the FastAPI lifespan) creates indexes and seeds config. Models in `app/db/models.py` subclass `MongoModel` and convert via `to_document()` / `from_document()`. Human-readable integer IDs come from `get_next_sequence()` (an atomic counter collection), separate from Mongo `_id`. Key collections: `users`, `bots`, `oauth_accounts`, `refresh_sessions`, `mr_agent_history`, `configs`, `cache`, `counters`.

### Auth
Two distinct credential systems:
- **App users** authenticate with JWTs (`app/auth/jwt.py`); `get_current_user` validates the token *and* checks a live `refresh_sessions` record (revocable sessions).
- **GitLab access** is per-user OAuth (`app/auth/gitlab.py`); `get_gitlab_client` (in `app/api/deps.py`) transparently refreshes expired OAuth tokens and persists them. Bots, by contrast, act via their own stored GitLab **project access token**, not user OAuth.

### Frontend ↔ backend contract
`Frontend/src/client/` is fully generated by `@hey-api/openapi-ts` from `Frontend/openapi.json` — **do not hand-edit it**. When backend routes/schemas change, refresh `openapi.json` from the running backend (`/api/openapi.json`) and run `npm run generate-client`. Runtime client config (base URL, bearer auth) is wired in `Frontend/src/hey-api.ts`; `BACKEND_URL` comes from `NEXT_PUBLIC_BACKEND_URL` via `src/env.ts`.

## Conventions
- `token_counter` (`app/agents/utils.py`) is a deliberate approximation (`len(text)//4`), used to gate diff/file/context size against `max_tokens_per_*` settings — not exact tokenization.
- Backend route modules each expose a `router` aggregated in `app/api/main.py` under the `/api/v{api_version}` prefix.
- Frontend uses Biome (not ESLint/Prettier) with 4-space indentation and on-save import organization.
</content>
</invoke>
