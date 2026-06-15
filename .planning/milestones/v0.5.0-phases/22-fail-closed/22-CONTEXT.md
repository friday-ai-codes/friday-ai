# Phase 22: 排除配置与统一过滤（fail-closed） - Context

**Gathered:** 2026-06-14
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous, auto-accepted recommendations)

<domain>
## Phase Boundary

本阶段建立**排除配置的单一事实源**（per-repo + 全局默认），并把"被排除文件"在**所有读取面** fail-closed 拦截，使其对 Friday 不可见（INV-4，DOMAIN §9.1）。

本阶段做：
- 排除规则数据模型（目录前缀 / glob 通配 / 正则）+ per-repo 与全局默认两层。
- 单一匹配器 `is_excluded(repo, path)` + 统一过滤函数，作为唯一判定入口。
- 在所有**读取/暴露面**挂接过滤：索引扫描（PF-04 修正 `scan_directory`）、MCP `get_file`/`grep`/`rag`、RAG 检索、agent 工具、编码容器 clone 后过滤。
- 工具层命中排除路径时 **fail-closed**（拒读/不返回，不降级泄漏明文）。
- 规则配置的 REST API + 最小前端配置入口（per-repo 排除规则编辑）。

本阶段**不做**（移交后续阶段）：
- 存量派生数据的清理/对账（Phase 23 EXCL-04..06）。
- AI 敏感文件识别建议名单（Phase 24 EXCL-03）。
- git object 物理抹除（明确 Out of Scope，靠工具层 denylist 兜底）。

</domain>

<decisions>
## Implementation Decisions

### D-01 配置数据模型与单一源
- **per-repo 规则**：新增 `RepoExclusionRule`（或等价结构）关联 `Repository`，字段含 `pattern`、`rule_type`(dir|glob|regex)、`enabled`、`source`(user|ai_suggested|global)、时间戳。理由：规则需可枚举/可增删/可审计，单 JSON 字段不利于对账（Phase 23 依赖）。
- **全局默认规则**：复用 `SystemSetting` / `SettingKeys`（CLAUDE 约束：新增设置必须复用既有键体系），键名 `code_index.exclusion.global_defaults`，存结构化规则列表；内置一组安全默认（如 `.env`、`*.pem`、`id_rsa`、`.git/`、`node_modules/`、密钥目录）。
- **合并语义**：有效规则 = 全局默认 ∪ per-repo 规则；per-repo 可在 UI 关闭某条全局默认（覆盖标记），但默认 fail-closed（命中即排除）。

### D-02 规则类型与匹配语义
- 支持三类：目录前缀（`dir`，匹配该目录及其子树）、glob 通配（`glob`，`fnmatch`/pathspec 语义，相对仓库根）、正则（`regex`，对相对路径全匹配）。
- 路径归一：一律转为**相对仓库根的 POSIX 路径**再匹配；大小写敏感跟随既有索引行为。
- 单一匹配器模块（如 `services/exclusion.py` 的 `ExclusionMatcher`），编译规则一次、复用；非法正则在保存时校验拒绝（fail-loud 配置错误），运行期匹配异常按 fail-closed 处理（命中即排除，宁可多排不可漏）。

### D-03 fail-closed 拦截点与失败模式
- 统一入口 `is_excluded(repo, rel_path) -> bool`，所有面共用：
  1. **索引扫描** `scan_directory` / indexer：跳过被排除文件（并修正 PF-04 谎称 .gitignore 的注释，挂真实过滤）。
  2. **MCP 工具** `get_file` / `grep` / `rag`：命中排除路径 → 拒绝返回内容（返回明确"已排除"信号，不返回明文片段）。
  3. **RAG 检索**：检索结果在返回前按排除过滤（即使 Qdrant 仍有残留 point，读取面也不暴露——存量清理留给 Phase 23）。
  4. **agent / 编码容器**：clone 后按 exclude 列表删除/过滤工作树文件，使容器内 agent 不可见。
- 失败模式 = **fail-closed**：规则评估出错、配置缺失、路径无法归一时，一律视为"排除/拒读"，绝不降级为返回明文。
- 留一条**审计埋点**（结构化日志事件，如 `exclusion.blocked`）记录被拦截的访问，供后续审计里程碑复用（本阶段仅埋点，不做 UI）。

### D-04 范围与兼容
- 不改动既有 Qdrant/ChunkRegistry 写入结构；本阶段只在**读取/暴露/扫描**侧加过滤层 + 配置模型 + API。
- 既有部署无规则时 = 仅内置全局默认生效，行为向后兼容（不破坏现有索引）。
- 新增 migration 仅加表/字段，不回填历史数据（清理是 Phase 23）。

### Claude's Discretion
- `RepoExclusionRule` 具体表名/字段命名、API 路由命名、前端组件落点与交互细节，由 planner/executor 依据既有 `server/<app>/api` 与 `web/src` 约定决定。
- 容器侧过滤实现（runner 传参 vs task 内过滤）由 planner 依据 `runner/` 与 `task/` 既有 env 注入约定选择，优先 clone 后在 task 容器内按 exclude 列表删除。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets（待 planner 核实精确路径）
- `server/services/indexer.py` — 索引扫描主流程；`scan_directory`（~833）注释谎称已应用 .gitignore（PF-04），是过滤挂接点。
- `server/services/code_parser.py` — `scan_directory` 目录名 + 扩展名白名单逻辑。
- `server/services/qdrant_service.py` — `delete_by_file_path`（Phase 23 复用；本阶段检索过滤参考其 file_path payload 字段）。
- `server/services/provider_config.py` / `SystemSetting` / `SettingKeys` — 全局默认规则存储复用入口。
- MCP / agent 工具：`server/agents/tools/`（`get_file`/`grep`/`search_repository_code` 等）、RAG 检索 service。
- `server/chat/coding_session_service.py` 与 `server/workflows/nodes/ai/coding.py` — 编码容器 env 注入参考（exclude 列表下传）。

### Established Patterns
- Django app 为界限上下文，各 app 拥有 `models/` `api/` `urls.py`；service 层无状态域逻辑（`server/services/`）。
- 异步 ORM 经 `sync_to_async`；凭证/设置 DB 加密存储。
- 前端 `web/src/api/` 类型化 client + Pinia/TanStack Query。

### Integration Points
- 新增 exclusion app/模型 或并入既有 repository app（planner 判定）。
- API 注册进 `server/friday/urls.py` 既有 `/api/*`。
- 前端排除规则编辑入口挂在仓库设置页。
</code_context>

<specifics>
## Specific Ideas

- 安全承诺措辞必须如实（DOMAIN §9.1）：UI/文档说明"Friday 不可见"，**不承诺** git object 物理消失。
- 内置全局默认应覆盖常见密钥/敏感文件模式，开箱即用。
- fail-closed 守护测试：构造命中规则的文件，断言其在索引扫描、MCP get_file/grep、RAG 检索四面均不可见。
</specifics>

<deferred>
## Deferred Ideas

- 存量派生数据清理 + 对账 UI → Phase 23（EXCL-04..06）。
- AI 敏感文件识别建议名单 → Phase 24（EXCL-03）。
- git object 物理抹除 / filter-repo → backlog（Out of Scope）。
</deferred>

---
*Phase: 22-fail-closed*
*Context gathered: 2026-06-14 via smart discuss (autonomous)*
