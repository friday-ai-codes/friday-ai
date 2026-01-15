# Friday AI Dev Agent
[简体中文](README.zh-CN.md) | English
🤖 **AI-Powered Agile Development Automation System**
Friday is an AI-driven agile development automation system that seamlessly integrates with Feishu/Lark Project Management, utilizing Claude Code to automate development tasks.
## 🏗️ Architecture
This project follows a Monorepo structure, containing independent frontend and backend services:
- **Frontend (`web/`)**: Vue 3 + TypeScript + Vite
- **Backend (`server/`)**: FastAPI + Python 3.11 + SQLModel
- **Infrastructure**: Full-stack orchestration via Docker Compose
## 🚀 Quick Start (Full Stack)
### Prerequisites
- Docker & Docker Compose
### One-Click Start
1. **Configure Environment Variables**
 ```bash
 cp .env.example .env
 # Edit .env and fill in required values
 ```
2. **Generate Encryption Key** (Required)
 ```bash
 # Using Python
 python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key.decode)"
 # Or using OpenSSL
 openssl rand -base64 32
 ```
 Add the generated key to `FRIDAY_ENCRYPTION_KEY` in `.env`
3. **Start Full Stack Services**
 ```bash
 docker compose up -d
 ```
4. **Access Services**
 - **Application**: http://localhost:10240 (Nginx serves frontend + proxies API)
 - **API Docs**: http://localhost:10240/docs (Swagger UI)
 - **Direct API Access**: http://localhost:10241 (Optional, for debugging)
### Service Architecture
```
┌─────────────────────────────────────────────────────────────┐
│ User Browser │
└───────────────────────────┬─────────────────────────────────┘
 │
 ▼
┌─────────────────────────────────────────────────────────────┐
│ Nginx (friday-web:10240) │
│ ┌─────────────────────┐ ┌───────────────────────────────┐ │
│ │ Static Files │ │ Proxy: /api/* /health /docs │ │
│ │ (Vue SPA) │ │ → server:8000 │ │
│ └─────────────────────┘ └───────────────────────────────┘ │
└───────────────────────────┬─────────────────────────────────┘
 │
 ▼
┌─────────────────────────────────────────────────────────────┐
│ FastAPI Server (friday-server:10241) │
│ ┌────────────────┐ ┌──────────────────────────────────┐ │
│ │ REST API │ │ Task Scheduler │ │
│ │ /api/* │ │ (Docker Container Management) │ │
│ └────────────────┘ └──────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```
### Environment Variables
| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `FRIDAY_ENCRYPTION_KEY` | ✅ | - | Encryption key for sensitive data |
| `ANTHROPIC_API_KEY` | ✅* | - | Anthropic API key for Claude Code |
| `FRIDAY_WEB_PORT` | ❌ | 10240 | Web frontend port |
| `FRIDAY_PORT` | ❌ | 10241 | Backend API port |
| `FRIDAY_DEBUG` | ❌ | false | Enable debug mode |
*Required for task execution functionality
## 💻 Local Development Guide
### Backend Development (`server/`)
For detailed instructions, see [Server README](server/README.md).
```bash
cd server
uv sync
uv run uvicorn friday.main:app --reload
```
### Frontend Development (`web/`)
For detailed instructions, see [Web README](web/README.md).
```bash
cd web
pnpm install
pnpm dev
```
## 📂 Project Structure
```
friday/
├── server/ # Backend Service (FastAPI)
│ ├── src/ # Source Code
│ ├── task/ # Task Execution Container
│ └── README.md
├── web/ # Frontend Project (Vue 3)
│ ├── src/
│ └── README.md
├── openspec/ # Project Specs & Design Docs
├── docker-compose.yml # Full Stack Orchestration
└── README.md # Project Entry Documentation
```
## 🤝 Contributing
Issues and Pull Requests are welcome!
## 📄 License
MIT License