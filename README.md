# Friday AI Dev Agent
[简体中文](README.zh-CN.md) | English
🤖 **AI-Powered Agile Development Automation System**
Friday is an AI-driven agile development automation system that seamlessly integrates with Feishu/Lark Project Management, utilizing Claude Code to automate development tasks.
## 🏗️ Architecture
This project follows a Monorepo structure, containing independent frontend and backend services:
- **Frontend (`web/`)**: Vue 3 + TypeScript + Vite
- **Backend (`server/`)**: Django + Django REST Framework + Python 3.14+
- **Infrastructure**: Full-stack orchestration via Docker Compose
## 🚀 Quick Start
> **详细指南**: 查看 [快速开始文档](docs/quick-start.md) 获取完整的中文安装和配置指南。
### Full Stack Deployment (Docker)
**Prerequisites:** Docker & Docker Compose
#### One-Click Start
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
│ Django Server (friday-server:10241) │
│ ┌────────────────┐ ┌──────────────────────────────────┐ │
│ │ REST API │ │ Task Scheduler │ │
│ │ /api/* │ │ (Docker Container Management) │ │
│ └────────────────┘ └──────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```
### Environment Variables
| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SECRET_KEY` | ✅ | - | Django secret key (generate for production) |
| `FRIDAY_ENCRYPTION_KEY` | ✅ | - | Encryption key for sensitive data |
| `DATABASE_URL` | ❌ | sqlite:///./data/friday.db | Database connection URL |
| `FRIDAY_WEB_PORT` | ❌ | 10240 | Web frontend port |
| `FRIDAY_PORT` | ❌ | 10241 | Backend API port |
| `DEBUG` | ❌ | false | Enable debug mode |
### Claude Code Configuration
Claude API configuration supports two levels (higher priority overrides lower):
1. **Project Level** - Configure in Web UI → Project → Claude Settings
2. **System Level** - Configure in Web UI → Settings → Claude Configuration
This allows:
- Different API keys for different projects
- Custom proxy URLs for users in regions with limited API access
## 💻 Local Development Guide
### Backend Development (`server/`)
For detailed instructions, see [Server README](server/README.md).
```bash
cd server
uv sync
uv run python manage.py runserver
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
├── server/ # Backend Service (Django)
│ ├── src/ # Source Code
│ ├── task/ # Task Execution Container
│ └── README.md
├── web/ # Frontend Project (Vue 3)
│ ├── src/
│ └── README.md
├── docker-compose.yml # Full Stack Orchestration
└── README.md # Project Entry Documentation
```
## 🤝 Contributing
Issues and Pull Requests are welcome!
## 📄 License
MIT License
