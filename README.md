# Friday AI Dev Agent
[简体中文](README.zh-CN.md) | English
🤖 **AI-Powered Agile Development Automation System**
Friday is an AI-driven agile development automation system that seamlessly integrates with Feishu/Lark Project Management, utilizing Claude Code to automate development tasks.
## ✨ v25.0 新功能：统一代码智能层
v25.0 构建了跨语言、跨仓库的代码智能层，主要特性：
- **多语言 extractor 矩阵**：Go（gopls LSP）/ TS/TSX / Vue 2.7+/3（volar LSP）/ HTML/CSS 全语言精确解析
- **Go gin 端点识别**：自动抽取 gin 路由 → `codegraph_endpoint` 表，含 middleware 元数据
- **跨仓库前后端 API 关联**：前端 axios call site 三步推断 → `CrossRepoApiCall` offline join → 精确连边
- **3D Galaxy 可视化**：`/codegraph/galaxy` — 银河感 3d-force-graph，5000+ 节点 30 FPS，Cmd+K 搜索 + NodeDetailDrawer
- **3 个新 MCP Tool**（Phase）：
 - `find_api_handler(url, method)` — URL → 后端 handler symbol
 - `find_api_callers(handler_name)` — handler → 前端业务调用点
 - `list_endpoints(repo_id)` — 列仓库所有 API 端点
- **HybridSearch wave**：跨仓 API_CALLS 扩散，budget 50/30/20
> 详细文档：[docs/v25.0-codegraph.md](docs/v25.0-codegraph.md)
---
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
