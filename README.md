# GitLab Agent

> An AI-powered review bot platform for GitLab. Connect a GitLab account, spin up one or more bots, and let LLM agents review merge requests, suggest changes, write docs, and hold a conversation — right inside the MR thread.

GitLab Agent turns merge-request review into a conversation with an LLM. Each bot is backed by a real GitLab project access token and webhook, so it participates in MRs like any other reviewer: it gets added, reads the diff, posts a structured review, answers `@mentions`, and runs slash commands — all while tracking token usage and cost per run.

---

## Highlights

- **Two agent modes.** A conversational/review **SmartAgent** that reads MR context and can approve/unapprove MRs and pull file contents on demand, plus a **CommandAgent** that dispatches slash commands (`/review`, `/describe`, `/suggest`, `/add_docs`, `/help`).
- **Real GitLab integration.** OAuth for users, per-bot project access tokens, webhook provisioning, and replies posted back as MR notes — managed end to end from the dashboard.
- **Model-agnostic via OpenRouter.** Per-bot model, temperature, max-output-tokens, system prompt, and extra kwargs. Swap models without touching code.
- **Cost & usage accounting.** Every agent run is recorded with token counts and cost in MongoDB, surfaced in a stats dashboard.
- **Admin panel.** A separate auth realm for configuring GitLab OAuth credentials and the selectable LLM catalog at runtime — the app boots and runs before GitLab is even configured.
- **Type-safe frontend.** The Next.js client is fully generated from the backend's OpenAPI spec, so the API contract is never hand-maintained.
- **One-command dev & prod.** A `Makefile` + Docker Compose stacks bring up MongoDB, the backend, the frontend, and a Traefik reverse proxy.

---

## Architecture

A monorepo with two independently deployable services.

```
┌─────────────┐      OAuth / REST       ┌──────────────────────────┐
│  Frontend   │ ──────────────────────► │         Backend          │
│  Next.js 16 │ ◄────────────────────── │   FastAPI · Python 3.13  │
│  React 19   │   generated OpenAPI     │                          │
└─────────────┘        client           │  ┌────────────────────┐  │
                                         │  │   SmartAgent       │  │
┌─────────────┐                          │  │   CommandAgent     │  │ pydantic-ai
│   GitLab    │ ── webhook (MR/Note) ──► │  └─────────┬──────────┘  │ ─────────► OpenRouter
│             │ ◄── notes / approvals ── │            │             │            (any LLM)
└─────────────┘                          │       MongoDB            │
                                         └──────────────────────────┘
```

### Request → agent flow

GitLab calls `POST /api/v{version}/webhooks/{bot_user_id}`. The handler loads the bot, verifies the `X-Gitlab-Token` secret, and dispatches on the event type:

- **Merge Request Hook** — triggers when the bot is newly added as a reviewer (or a review is re-requested). Runs `SmartAgent` to produce a full review and posts it as an MR note.
- **Note Hook** — acts only when the bot is `@`-mentioned:
  - `@bot /command …` → **CommandAgent** (slash-command style).
  - plain `@bot …` → **SmartAgent** in conversational mode, rebuilding chat history from the discussion's prior notes.

Each handler posts a temporary *"Processing…"* note, runs the agent, then replaces it with the result.

### Agents (`Backend/app/agents/`)

| Agent | Role | Capabilities |
|-------|------|--------------|
| **SmartAgent** | Conversational review & chat | Gathers MR diffs/title/description into the prompt; exposes tools `approve_mr`, `unapprove_mr`, `get_file` with hard usage caps; records every run with token/cost accounting. |
| **CommandAgent** | Slash-command dispatcher | Parses `/command --flags args` (shlex-based) and delegates to a command class. |

**Registered commands** (`Backend/app/agents/commands/`): `help`, `review`, `describe`, `suggest`, `add_docs`. Each subclasses a shared `CommandInterface` (GitLab data gathering, diff formatting with line numbers, `#NNN` issue extraction) and uses pydantic-ai structured output rendered to GitLab-flavored markdown. Prompt templates live in `Backend/app/prompts/` (Jinja2).

### Persistence

MongoDB only. Key collections: `users`, `bots`, `oauth_accounts`, `refresh_sessions`, `mr_agent_history` (token/cost ledger), `configs`, `app_settings`, `cache`, `counters` (atomic human-readable IDs).

### Configuration lifecycle

Two DB-backed config collections with deliberately opposite lifecycles:

- **`configs`** — runtime-overridable agent/LLM settings, **reset to defaults on every startup**.
- **`app_settings`** — GitLab OAuth credentials, **seeded once** from env then DB-authoritative and editable in the `/admin` panel. Until GitLab is configured, user OAuth login returns `503` while the rest of the app runs normally.

### Auth — three credential paths

- **App users** — JWT access/refresh, validated against a revocable `refresh_sessions` record; accounts created lazily on GitLab OAuth callback.
- **Admins** — a separate realm with username/password (bcrypt), seeded by `make create-admin`. JWTs carry an `is_admin` claim and guard `/admin`. Works *before* GitLab is configured.
- **Bots** — act via their own stored GitLab **project access token**, independent of user OAuth.

---

## Tech Stack

**Backend** — Python 3.13 (managed with [uv](https://docs.astral.sh/uv/)) · FastAPI · [pydantic-ai](https://ai.pydantic.dev/) · OpenRouter · MongoDB (pymongo) · python-gitlab · PyJWT · bcrypt · Jinja2 · Logfire / OpenTelemetry

**Frontend** — Next.js 16 · React 19 · TypeScript · Tailwind CSS 4 · Radix UI · Recharts · Zod · [Biome](https://biomejs.dev/) · [`@hey-api/openapi-ts`](https://heyapi.dev/) (generated API client)

**Infra** — Docker Compose · Traefik · MongoDB · mongo-express (dev)

---

## Getting Started

### Prerequisites

- [Docker](https://www.docker.com/) & Docker Compose
- [uv](https://docs.astral.sh/uv/) (backend) and [Node.js](https://nodejs.org/) 20+ (frontend) for local dev
- An [OpenRouter](https://openrouter.ai/) API key
- A GitLab instance + OAuth application (can be configured later, via the admin panel)

### 1. Configure environment

```bash
cp .env.sample .env
```

Both services read this single `.env`. At minimum set `SECRET_KEY`, `OPENROUTER_API_KEY`, and your `ADMIN_*` credentials. GitLab OAuth (`GITLAB_*`) is optional at boot — you can fill it in from the admin panel.

### 2. Run in development

```bash
make dev          # MongoDB in Docker; backend + frontend locally with hot-reload
```

- Backend → `http://localhost:8000` (interactive API docs at `/api/docs`)
- Frontend → `http://localhost:3000`
- mongo-express → `http://localhost:8081`

Prefer to run the services by hand?

```bash
# Backend (from Backend/)
uv sync
uv run uvicorn app.main:app --reload --port 8000

# Frontend (from Frontend/)
npm install
npm run dev
```

### 3. Create an admin

```bash
make create-admin     # uses ADMIN_* from .env; idempotent (re-run to reset password)
```

Sign in at `http://localhost:3000/admin/login` to set GitLab OAuth credentials and curate the LLM catalog.

### 4. Run in production

```bash
make prod         # Traefik + backend + frontend + MongoDB, behind / and /api
```

Use `.env.prod.sample` as a starting point. See `make help` for the full list of targets (`down*`, `clean*`, etc.).

---

## Usage

1. **Sign in** to the dashboard with GitLab OAuth.
2. **Create a bot** for a project — the platform provisions a project access token and a webhook for you.
3. **Add the bot as a reviewer** on a merge request, or `@mention` it in a comment.
4. The bot **reviews, replies, suggests, or documents** — and you can watch token usage and cost on the stats page.

**In an MR comment:**

```
@my-bot can you double-check the error handling in the auth module?

@my-bot /review
@my-bot /describe
@my-bot /suggest
@my-bot /add_docs
@my-bot /help
```

---

## Project Layout

```
.
├── Backend/                 # FastAPI service (Python 3.13, uv)
│   └── app/
│       ├── agents/          # SmartAgent, CommandAgent, slash-command classes
│       ├── api/routes/      # admin, auth, bot, gitlab, config, webhooks
│       ├── auth/            # JWT, GitLab OAuth, password hashing
│       ├── core/            # settings (pydantic-settings), logging, LLM catalog
│       ├── db/              # MongoDB models & init
│       ├── prompts/         # Jinja2 system/user templates per command
│       └── services/        # event handlers, app-settings, cache
├── Frontend/                # Next.js 16 admin panel + dashboard
│   └── src/
│       ├── app/             # routes (dashboard, bots, stats, admin)
│       └── client/          # generated OpenAPI client (do not edit by hand)
├── docker/                  # Dockerfiles + dev/prod compose stacks
├── Makefile                 # dev / prod / create-admin / cleanup targets
└── .env.sample
```

---

## Development Notes

- **Regenerating the frontend client.** When backend routes/schemas change, refresh `Frontend/openapi.json` from the running backend (`/api/openapi.json`) and run `npm run generate-client`. Never hand-edit `Frontend/src/client/`.
- **Linting/formatting.** Frontend uses Biome (`npm run lint` / `npm run format`, 4-space indent). The backend has no configured linter or test suite — `test.ipynb` files are scratch notebooks, not tests.
- **Config env mapping.** Settings use a nested delimiter (`_`, max one split), so `MONGODB_HOST`, `GITLAB_CLIENT_ID`, etc. map onto the `mongodb` / `gitlab` sub-models.

---

## Roadmap Ideas

- Automated test coverage for the backend agents and webhook dispatch
- More slash commands (e.g. security review, test generation)
- Self-hosted model providers alongside OpenRouter
- Richer per-bot analytics

---

*Built with FastAPI, pydantic-ai, and Next.js. Designed to demonstrate end-to-end LLM agent integration with a real third-party platform — webhooks, OAuth, structured tool use, cost tracking, and a generated type-safe client.*
