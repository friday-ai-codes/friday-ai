# Friday API Server

[简体中文](README.zh-CN.md) | English

This is the backend service for the Friday system, responsible for business logic, data persistence, and integration with Feishu, GitHub, and AI Agents.

## 🛠️ Tech Stack
- **Language**: Python 3.14+
- **Framework**: Django 6.0 + Django REST Framework
- **Authentication**: djangorestframework-simplejwt (JWT)
- **Database**: SQLite
- **Production Server**: Gunicorn + Uvicorn (ASGI)
- **Tooling**: uv (Package Management)

## 🚀 Development Guide

### Install Dependencies
We use `uv` for package management:

```bash
# Install dependencies
uv sync

# Activate virtual environment (optional, uv run handles this automatically)
source .venv/bin/activate
```

### Start Service
```bash
# Development Mode (Hot Reload)
uv run python manage.py runserver

# Production Mode (Gunicorn + Uvicorn)
uv run gunicorn friday.asgi:application \
    --workers 2 \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:8000
```

### Database Migration
```bash
# Generate migration after model changes
uv run python manage.py makemigrations

# Apply migrations
uv run python manage.py migrate
```

### Run Tests
```bash
uv run pytest
```

## 📁 Directory Structure
```
server/
├── friday/           # Django project settings
│   ├── settings.py   # Django configuration
│   ├── urls.py       # Root URL routing
│   ├── asgi.py       # ASGI application entry
│   └── wsgi.py       # WSGI application entry
├── core/             # Core app (auth, health, settings)
├── projects/         # Projects and repositories management
├── tasks/            # Task lifecycle management
├── webhooks/         # Feishu and GitHub webhook handling
├── services/         # Business logic services
│   ├── feishu.py     # Feishu API client
│   ├── scheduler.py  # Docker container scheduler
│   └── claude_config.py  # Claude configuration service
├── tests/            # Unit and integration tests
├── data/             # Database and persistent storage
└── manage.py         # Django management script
```

## 🔐 Authentication
The API uses JWT (JSON Web Token) authentication:

- **Login**: `POST /api/auth/login` - Returns access_token and sets refresh_token cookie
- **Refresh**: `POST /api/auth/refresh` - Refreshes access token using cookie
- **Logout**: `POST /api/auth/logout` - Clears refresh token cookie

## 📡 API Endpoints

| Path | Description |
|------|-------------|
| `/health` | Health check |
| `/api/auth/` | Authentication endpoints |
| `/api/projects/` | Project CRUD operations |
| `/api/repositories/` | Repository management |
| `/api/tasks/` | Task lifecycle management |
| `/api/webhook/` | Webhook handlers (Feishu, GitHub) |
| `/api/settings/` | System settings |

## 🐳 Docker Deployment
```bash
# Build image
docker build -t friday-server .

# Run container
docker run -p 8000:8000 \
    -v $(pwd)/data:/app/data \
    -e FRIDAY_ENCRYPTION_KEY=your-secret-key \
    friday-server
```

The Docker container uses Gunicorn with Uvicorn workers for production deployment.
