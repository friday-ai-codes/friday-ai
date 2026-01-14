# Design: AI-Powered Development Automation System
## Context
本系统旨在构建一个 AI 驱动的敏捷开发自动化平台，打通飞书项目管理与代码开发的闭环。
### 背景
- 互联网公司的敏捷开发流程中，需求从看板到代码落地需要大量人工操作
- Claude Code 具备强大的代码生成能力，但缺乏与项目管理系统的集成
- 人工评审（Human-in-the-Loop）是保证代码质量的关键环节
### 约束
- Docker 容器的无状态性与人类评审断点的矛盾
- 上下文窗口限制和 Token 成本控制
- 飞书 API 的复杂状态流转机制
- 多 Git 平台认证的统一管理
## Goals / Non-Goals
### Goals
- 实现飞书 Project → Claude Code → Git 的工作流自动化
- 支持 Plan（规划）和 Execute（执行）两阶段模式，保留人工评审环节
- 提供简单的一键部署方案（Docker Compose）
- 支持多项目、多 Git 平台（GitHub/GitLab/Gitea/Bitbucket）
### Non-Goals
- 不实现复杂的集群编排（Kubernetes）
- 不实现 Web 管理界面（仅 API）
- 不实现多租户隔离
- 不实现 AI 代码的自动合并（保留人工 Review）
## Decisions
### Decision 1: 每任务一容器（One Container per Task）
**选择**: 为每个开发任务启动独立的 Docker 容器执行
**理由**:
- 完全隔离不同任务的执行环境
- 任务失败不影响其他任务
- 容器退出后自动清理资源
- 便于资源限制和监控
**替代方案**:
- Worker Pool（复用容器）：实现复杂，状态管理困难
- 进程池：隔离性不足，Python GIL 限制
### Decision 2: SQLite + aiosqlite
**选择**: 使用 SQLite 作为持久化存储
**理由**:
- 零配置，开箱即用
- 适合单机部署场景
- 异步驱动（aiosqlite）满足性能需求
- 数据文件便于备份和迁移
**替代方案**:
- PostgreSQL：需要额外部署和维护
- Redis：不适合持久化结构化数据
### Decision 3: 双阶段状态机
**选择**: Plan → 人工评审 → Execute 的两阶段模式
**理由**:
- 保留人工评审环节，确保代码质量
- Claude Code 会话可持久化恢复
- 评审反馈可作为新的上下文传入执行阶段
**状态流转**:
```
PENDING → PLANNING → PLAN_REVIEW → EXECUTING → CODE_REVIEW → MERGED
 ↓ ↓ ↓ ↓ ↓
 FAILED FAILED PLANNING FAILED EXECUTING
```
### Decision 4: HTTP 直接调用飞书 API
**选择**: 使用 httpx 直接调用飞书 API，而非 lark_oapi SDK
**理由**:
- lark_oapi SDK 的 Project API 模块兼容性问题
- 直接调用更灵活，易于调试
- 减少第三方依赖
### Decision 5: Fernet 对称加密凭证
**选择**: 使用 cryptography.fernet 加密存储 SSH Key 和 Access Token
**理由**:
- 简单可靠的对称加密方案
- Python 标准库支持
- 密钥通过环境变量注入
## Risks / Trade-offs
### Risk 1: Claude Code CLI 稳定性
**风险**: Claude Code CLI 是相对新的工具，可能存在 API 变更
**缓解**:
- 封装调用层，隔离变更影响
- 版本锁定
- 定期跟踪上游更新
### Risk 2: 容器启动开销
**风险**: 每任务启动新容器有冷启动开销
**缓解**:
- 预构建镜像，减少启动时间
- 仓库缓存复用（挂载共享 Volume）
- Claude Code 会话恢复减少重复分析
### Risk 3: 上下文窗口限制
**风险**: 大型代码库可能超出 Claude 上下文限制
**缓解**:
- 实现 .claudeignore 过滤无关文件
- 利用 developer-notes.md 提供项目概览
- 按需加载相关文件
## Migration Plan
不涉及迁移（新项目）。
## Open Questions
1. **飞书 Project API 权限**: 需确认企业内部飞书应用的权限申请流程
2. **Claude Code 多模态能力**: 飞书文档中的图片如何传递给 Claude
3. **并发任务数限制**: 需根据服务器资源确定合理的并发容器数