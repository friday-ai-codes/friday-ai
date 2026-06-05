# External Integrations

**Analysis Date:** 2026-06-05

Friday AI integrates with LLM providers, Git platforms, vector storage, messaging (Feishu), and container runtimes. A key design point: **most third-party credentials (LLM keys, Git tokens) are stored encrypted in the database and configured at runtime**, NOT via environment variables. Env vars are reserved for infrastructure (DB, Redis, Qdrant, secret keys, runner registration).

## APIs & External Services

**LLM Providers** (resolved via `server/services/provider_config.py`; credentials in DB model `system.models.ProviderCredential`, encrypted):
- Anthropic Claude
  - SDK: `anthropic`, `claude-agent-sdk`, `langchain-anthropic`
  - Credential: `api_key` (stored in DB; optional custom `base_url` passthrough supported)
- OpenAI (two API formats: Responses API and Chat Completions)
  - SDK: `openai`, `langchain-openai`
  - Credential: `api_key` (+ optional org)
- Google Gemini
  - SDK: `google-genai`, `langchain-google-genai`
  - Credential: `api_key`
- Ollama (local/self-hosted)
  - SDK: `langchain-ollama`
  - Credential: optional/none, configured by base URL

Provider resolution uses a four-layer priority: **node-level > conversation-level > project-level > system-level** (`ProviderConfigService`). The five `ProviderType` values are `anthropic`, `openai_responses`, `openai_chat`, `gemini`, `ollama`.

**Git Platforms** (credentials stored encrypted in DB per repository):
- GitHub — SDK: `PyGithub>=2.0.0`
- GitLab — SDK: `python-gitlab>=4.0.0`
- Generic Git — `gitpython>=3.1.46` (local clone/diff/commit-distance ops; clone root `data/repos/{repo.id}/`)
- SSH access: `paramiko>=4.0.0`

**Messaging / Collaboration:**
- Feishu (Lark) — SDK: `lark-oapi>=1.5.2`
  - Code: `server/services/feishu_im.py`, `server/services/feishu_doc.py`, `server/agents/tools/feishu_im_tools.py`, `server/feishu/` app
  - Used for: IM notifications, document fetch, workflow status sync
  - Webhook signature verification via `FEISHU_ENCRYPT_KEY` / `FEISHU_SIGNATURE_REQUIRED`
  - Feishu credentials (`app_id`/`app_secret`) configured via DB system settings (`bootstrap_system_settings`)

**OpenAI-compatible API surface (incoming):**
- The server exposes an OpenAI-compatible API layer (`server/compat/`) for external clients
- Auth via `OPENAI_COMPAT_API_KEYS` (comma-separated allowlist; AllowAny when empty)

## Data Storage

**Databases (relational):**
- Configured via single `DATABASE_URL` env var (`django-environ` `env.db()`)
- Supported: PostgreSQL (`psycopg`, recommended/default in Compose), MySQL/MariaDB (`mysqlclient`), SQLite (local dev default: `data/friday.db`)
- Connection: `DATABASE_URL` (e.g. `postgres://friday:...@postgres:5432/friday`)
- ORM: Django ORM; custom user model `accounts.User`
- Compose service: `postgres:17-alpine`

**Vector Database:**
- Qdrant — client `qdrant-client>=1.9.0`; service `server/services/qdrant_service.py`
  - Connection: `QDRANT_URL` (default `http://qdrant:6333`), optional `QDRANT_API_KEY`
  - Ports: HTTP `6333`, gRPC `6334`
  - Used for: RAG semantic code search (`llama-index-vector-stores-qdrant`, `fastembed` embeddings)
  - Compose service: `qdrant/qdrant:latest`

**Caching / Message Broker:**
- Redis — Compose service `redis:7-alpine`
  - Channels layer: `REDIS_CHANNEL_LAYER_URL` / `REDIS_URL` (default `redis://127.0.0.1:6379/0`), toggled by `USE_REDIS_CHANNEL_LAYER` (defaults to in-memory channel layer when disabled)
  - Also backs `WORKFLOW_IDEMPOTENCY_BACKEND` (optional, default in-memory)

**File Storage:**
- Local filesystem under `data/` (`server/friday/settings.py`): `data/repos`, `data/sessions`, `data/credentials`
- Static files served by `whitenoise` (`STATIC_URL=/api/static/`)
- Compose bind mount root: `FRIDAY_DATA_DIR` (default `~/.friday-ai`)

## Authentication & Identity

**App Auth:**
- JWT via `djangorestframework-simplejwt` (`SIMPLE_JWT` in settings)
  - Access token 15 min, refresh token 7 days (env-overridable), rotation + blacklist enabled
  - Custom auth class: `common.authentication.CookieJWTAuthentication` (refresh token stored in HttpOnly cookie)
  - Signing key: `JWT_SECRET_KEY` (falls back to `SECRET_KEY`)
  - Throttling: `auth_login` 5/min, `auth_refresh` 20/min
- Password hashing: `passlib[argon2]` + Django validators
- OIDC support present (`server/tests/test_oidc.py`; `FRIDAY_FRONTEND_URL` used for OIDC redirects)

**Secrets encryption:**
- `FRIDAY_ENCRYPTION_KEY` (base64 32-byte) — encrypts stored provider/Git credentials via `cryptography`
- Runner token transport encrypted with AES (`runner/internal/crypto/aes.go`)

## Monitoring & Observability

**Error Tracking:**
- No dedicated external service (e.g. Sentry) detected

**Logs:**
- Backend: `structlog` (configured via `common.logging.configure_structlog` with credential-leak protection); Django `LOGGING` dictConfig to console; per-library levels for `httpx`/`httpcore`/`qdrant_client`
- Runner: `rs/zerolog`
- Task executor: `structlog`

**Metrics:**
- Runner collects host metrics via `gopsutil`
- Server has system monitoring via `psutil` and `server/system/` app

## CI/CD & Deployment

**Hosting:**
- Docker Compose (self-hosted). Services: `server`, `web` (Nginx reverse proxy → `deploy/docker/nginx-proxy.conf`), `runner`, `postgres`, `redis`, `qdrant`
- Prebuilt images: `ghcr.io/friday-ai-codes/friday-ai/{server,web,runner}:latest`

**CI Pipeline:**
- GitHub Actions: `.github/workflows/ci.yaml` (lint/test) and `.github/workflows/release.yaml` (image build/release)

**Container execution architecture:**
- The Go `runner` registers with the server over WebSocket (`runner/internal/ws/client.go`) and launches `friday-task` containers per job
- Executors: Docker (`runner/internal/docker/executor.go`) and Kubernetes (`runner/internal/k8s/executor.go`), selected via `FRIDAY_RUNNER_EXECUTOR`
- Default task image: `friday-task:latest` (`runner/internal/config/config.go`)
- Runner needs Docker socket access (`/var/run/docker.sock`, `DOCKER_GID`)

## Environment Configuration

**Required env vars (production):**
- `SECRET_KEY` — Django secret
- `DATABASE_URL` — DB connection
- `FRIDAY_ENCRYPTION_KEY` — credential encryption
- `RUNNER_REGISTRATION_TOKEN` — shared server↔runner registration secret
- `ALLOWED_HOSTS` — explicit hosts (wildcard rejected in production)

**Common optional env vars:**
- `QDRANT_URL`, `QDRANT_API_KEY` — vector DB
- `USE_REDIS_CHANNEL_LAYER`, `REDIS_URL` — channels backend
- `FEISHU_ENCRYPT_KEY`, `FEISHU_SIGNATURE_REQUIRED` — Feishu webhook security
- `OPENAI_COMPAT_API_KEYS` — incoming OpenAI-compatible API allowlist
- `SUBAGENT_API_URL`, `FRIDAY_BASE_URL`, `FRIDAY_FRONTEND_URL` — internal/callback URLs
- `CONTAINER_CALLBACK_TOKEN` — task container callback auth (auto-generated if unset)
- `FRIDAY_RUNNER_URL`, `FRIDAY_RUNNER_NAME`, `FRIDAY_RUNNER_EXECUTOR`, `DOCKER_GID` — runner

**Secrets location:**
- Infra secrets: `.env` (`server/.env` or root `.env`; template `.env.example`) — NOT committed
- LLM/Git/Feishu credentials: encrypted in DB (`ProviderCredential`, repository records, system settings); never in env
- Local credential workspace: `data/credentials/`

## Webhooks & Callbacks

**Incoming:**
- Feishu event/callback webhooks (signature-verified via `FEISHU_ENCRYPT_KEY`; `server/feishu/`)
- Task container → server callbacks (`server/subagent/api/callbacks.py`, authenticated by `CONTAINER_CALLBACK_TOKEN`)
- Runner callback HTTP server (`runner/internal/callback/server.go`, default port `8976`)

**Outgoing:**
- Browser push notifications via `pywebpush` (VAPID) — `server/chat` push (`test_chat_push.py`)
- Feishu IM messages / workflow status sync (`FF_SYNC_WORKFLOW_TO_FEISHU`)
- WebSocket push of workflow/chat updates to frontend (`channels`, `FF_ENABLE_WORKFLOW_WEBSOCKET`)
- Outbound LLM provider and Git platform API calls (`httpx`)

---

*Integration audit: 2026-06-05*
