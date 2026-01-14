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
- Node.js 20+ (Local development only)
- Python 3.11+ (Local development only)
### One-Click Start
1. **Configure Environment Variables**
 ```bash
 cp server/.env.example server/.env
 # Edit server/.env and fill in required API Keys (Feishu, Anthropic, etc.)
 ```
2. **Start Full Stack Services**
 ```bash
 docker compose up -d
 ```
3. **Access Services**
 - **Frontend**: http://localhost:8080
 - **Backend API**: http://localhost:8000/docs
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