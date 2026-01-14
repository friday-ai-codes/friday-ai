# Change: Refactor Project Structure to Monorepo Style
## Why
为了更好地管理前端和后端代码，明确关注点分离，我们将项目重构为前后端分离的目录结构。原有的后端代码移动到 `server/` 目录，新建的前端项目位于 `web/` 目录。
## What Changes
### 目录结构调整
- **Backend**: 原根目录下的后端代码（`src/`, `tests/`, `main.py` 等）移动到 `server/` 目录。
- **Frontend**: 新增 Vue 3 前端项目，位于 `web/` 目录。
- **Config**: 根目录保留项目级配置和文档，各子项目的配置（如 `pyproject.toml`, `package.json`）移动到各自目录下。
### 架构模式
- 采用 Monorepo 风格管理（虽然目前可能不使用复杂的 Monorepo 工具，但物理结构上已分离）。
- 后端服务运行在 `server/` 上下文中。
- 前端服务运行在 `web/` 上下文中。
## Impact
- **Affected specs**: 无功能性 Spec 变更，但需更新 `project.md` 中的架构描述。
- **Affected code**: 整个项目的文件路径。
- **Breaking changes**: 所有之前的构建脚本、Docker 路径和开发命令都需要更新以适配新路径。