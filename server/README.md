# Friday API Server
[简体中文](README.zh-CN.md) | English
This is the backend service for the Friday system, responsible for business logic, data persistence, and integration with Feishu, GitHub, and AI Agents.
## 🛠️ Tech Stack
- **Language**: Python 3.11+
- **Framework**: FastAPI
- **ORM**: SQLModel (SQLAlchemy + Pydantic)
- **Database**: SQLite (aiosqlite)
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
uv run uvicorn friday.main:app --reload
# Production Mode
uv run uvicorn friday.main:app --host 0.0.0.0 --port 8000
```
### Run Tests
```bash
uv run pytest
```
## 📁 Directory Structure
- `src/friday/`: Core business logic
- `task/`: Task execution environment (Docker)
- `tests/`: Unit and integration tests
- `data/`: Database and persistent storage