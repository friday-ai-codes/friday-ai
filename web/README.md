# Friday Web Client
[简体中文](README.zh-CN.md) | English
The frontend management interface for the Friday system, providing visual task boards, configuration management, and execution status monitoring.
## 🛠️ Tech Stack
- **Framework**: Vue 3
- **Language**: TypeScript
- **Build Tool**: Vite
- **Package Manager**: pnpm
## 🚀 Development Guide
### Install Dependencies
```bash
pnpm install
```
### Start Development Server
```bash
pnpm dev
```
Default port is usually 5173. When running via `docker compose`, it maps to 8080.
### Build for Production
```bash
pnpm build
```
Build artifacts will be output to the `dist/` directory.