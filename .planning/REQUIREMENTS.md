# Requirements: v0.5.0 索引检索地基与排除文件

> 由 `MILESTONE-CONTEXT.md` + `ROADMAP-vNext.md` v0.5 派生。设计底座见 `DOMAIN-MODEL.md §9`；前置修复见 `PREFLIGHT.md`。
>
> *Milestone started: 2026-06-14*

## Goal

把代码索引/检索的地基补齐——敏感文件全链路 fail-closed 不可见（普通排除 / 敏感清理两模式）、commit 历史可检索、行级反查可用、多仓 GitLab 凭证统一。

## v1 Requirements

### EXCL — 排除文件

- [x] **EXCL-01**：用户可配置 per-repo 排除规则（目录 / 通配 / 正则），并支持全局默认规则。（22-01 数据模型 + 全局默认键 + 内置默认；22-05 REST API CRUD + regex fail-loud + 缓存失效 + 仓库详情页编辑面板，闭环达成）
- [x] **EXCL-02**：被排除文件在 RAG 检索、MCP（get_file/grep/rag）、agent、编码容器中均 fail-closed 不可见（不降级泄漏）。（22-VERIFICATION gap closed：CodeSearchView._search REST 旁路面挂接 build_matcher_for_repo + is_excluded，56d230553）
- [x] **EXCL-03**：索引/描述生成阶段 AI 识别敏感文件（密钥/env/敏感信息），产出建议名单供用户确认/增删，不静默删除。
- [x] **EXCL-04**：普通排除清理可删除已索引的派生数据（Qdrant 主+overlay、ChunkRegistry、codegraph、repo_summaries/index_nodes）。
- [x] **EXCL-05**：敏感清理在普通排除基础上额外清理操作记录数据面（message parts、agent trace、TaskResult、CodeChangeArchive diff、prompt snapshot、错误日志可控范围）。
- [x] **EXCL-06**：用户可在 UI 对比"当前排除规则 vs 已索引内容"，有差异时收到提示并可一键执行清理。

### IDX — 索引增强

- [x] **IDX-01**：commit 历史（message / author / 变更）被索引为可语义检索的 RAG 内容。
- [x] **IDX-02**：`ChunkRegistry.line_start/line_end` 在索引时回填，并提供 `file:line → chunk_id` 查询能力。

### REPO — 多仓

- [ ] **REPO-01**：GitLab access token 可统一/集中管理，同一 GitLab 实例的多个仓库可复用同一凭证。
- [ ] **REPO-02**：MCP RAG 检索工具暴露多仓参数（多仓/全仓检索）。

## Future Requirements（deferred）

- 片段 → 需求反查（依赖 IDX-02 行号回填）— v0.6
- git object 物理抹除（filter-repo 强清）— backlog
- 全量操作审计 — v0.10

## Out of Scope

- git object 物理抹除：安全边界定为"Friday 不可见"，不承诺 git 历史物理消失（成本高、破坏 shallow）。
- 任何飞书 / work item 相关摄取 — v0.6。
- 全量操作审计（成员/凭证/同步等）— v0.10；本里程碑仅埋排除/清理操作审计点。

## 前置修复（PREFLIGHT，本里程碑内一并处理）

- **PF-03**：incremental 删除只删 Qdrant、不删 FileIndex/ChunkRegistry → 抽统一 `purge_file`（EXCL-04 复用）。
- **PF-04**：`scan_directory` 注释谎称已应用 .gitignore → 修正 + 挂统一过滤（EXCL-01/02）。
- **PF-05**：`delete_by_file_path` 不删 overlay → 扩展覆盖 overlay（EXCL-04）。

## Traceability（填充于 ROADMAP）

| REQ-ID | Phase |
|--------|-------|
| EXCL-01, EXCL-02 | 22 |
| EXCL-04, EXCL-05, EXCL-06 | 23 |
| EXCL-03 | 24 |
| IDX-01, IDX-02 | 25 |
| REPO-01, REPO-02 | 26 |
