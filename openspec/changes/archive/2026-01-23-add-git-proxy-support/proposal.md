# Change: Add Git Proxy Support
## Why
在某些网络环境下，直接访问外部 Git 仓库（如 GitHub）可能受限或缓慢。用户需要一种方式来配置代理服务器，以确保 Git 仓库的克隆和交互操作能够稳定执行。此外，不同仓库可能位于不同的网络区域，需要支持仓库级别的独立代理配置。
## What Changes
- **系统级设置**：新增全局 Git 代理配置（`git_http_proxy`），作为默认代理。
- **仓库级设置**：在 `Repository` 模型中新增代理配置字段，允许为特定仓库覆盖全局设置。
- **优先级逻辑**：Git 操作时优先使用仓库级代理，若未配置则回退到系统级代理。
- **UI 支持**：在系统设置页面和仓库编辑页面增加代理配置输入框。
## Impact
- **Specs**: `ai-dev-automation` (Git Operations, Repository Management, System Settings)
- **Code**:
 - `server/projects/models.py` (Repository model update)
 - `server/core/models.py` (System Settings allowlist)
 - `server/services/task_scheduler.py` (Proxy resolution logic)
 - `web/src/views/settings/SystemSettings.vue` (Global config UI)
 - `web/src/views/projects/RepositoryEdit.vue` (Repo config UI)
