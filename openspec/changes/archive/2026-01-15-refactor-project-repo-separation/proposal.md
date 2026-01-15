# Change: Refactor Project and Repository Separation
## Why
目前 `Project` 模型耦合了「飞书项目」和「Git 仓库」的概念。在实际业务场景中，一个飞书项目（如“学习工具与平台”）可能关联多个 Git 仓库（如 `study-app`, `onion-learning`），而一个 Git 仓库也可能被多个飞书项目共用。
当前的 1:1 强耦合关系限制了这种多对多的业务场景，导致无法灵活管理仓库与项目的关系。
## What Changes
- **核心概念分离**：
 - `Project`：仅代表飞书项目空间，负责管理飞书配置（App ID, Secret, Webhook）。
 - `Repository`：新增概念，代表 Git 代码仓库，负责管理 Git 配置（URL, Branch, Credentials）。
- **关系重构**：
 - 建立 `Project` 与 `Repository` 的多对多关联（Many-to-Many）。
 - 任务（Task）将同时关联到一个 Project（来源）和一个 Repository（执行地）。
- **数据迁移**：
 - 将现有 Project 数据拆分为 Project + Repository。
- **API 变更**：
 - 新增 Repository 管理接口。
 - Project 接口移除 Git 相关字段，增加 Repository 关联管理接口。
## Impact
- **Affected Specs**:
 - `ai-dev-automation`: 引入 Repository 概念，更新 Task 关联逻辑。
 - `feishu-integration`: Project 模型聚焦于飞书集成。
 - `frontend-architecture`: 新增仓库管理界面和关联配置界面。
- **Affected Code**:
 - Backend: `server/src/friday/models/`, `server/src/friday/routes/`, `server/src/friday/services/`
 - Frontend: `web/src/stores/`, `web/src/api/`, `web/src/pages/`