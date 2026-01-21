# 历史设计文档归档
**归档日期**: 2025-01-21
## 说明
本目录包含 Friday 项目早期的设计文档。这些文档创建于项目初期，描述的技术方案与最终实现有所不同，现已归档作为历史参考。
## 文档列表
| 文档 | 内容 | 过时原因 |
|------|------|----------|
| 架构设计.md | 系统架构、技术栈选择、状态机设计 | 描述 Temporal.io + Redis Streams，实际采用 Docker 调度 |
| 技术方案.md | 详细技术研究、CLI 规范、飞书集成 | 描述 FastAPI + SQLModel，实际采用 Django + DRF |
| 实施方案.md | 项目结构、数据模型、API 设计 | `src/` 目录结构与实际 Django apps 结构不符 |
## 当前有效文档
请参考以下位置获取最新的规范文档：
- **项目约定**: `openspec/project.md`
- **AI 任务执行**: `openspec/specs/ai-dev-automation/spec.md`
- **飞书集成**: `openspec/specs/feishu-integration/spec.md`
- **Docker 部署**: `openspec/specs/docker-deployment/spec.md`
- **前端架构**: `openspec/specs/frontend-architecture/spec.md`
## 有价值的历史决策
以下设计决策已融入当前规范：
1. **双阶段状态机** (Plan → Review → Execute) - 见 `ai-dev-automation/spec.md`
2. **容器隔离执行** - 见 `docker-deployment/spec.md`
3. **飞书 Webhook 集成** - 见 `feishu-integration/spec.md`
4. **Session 持久化方案** - 见 `ai-dev-automation/spec.md`
