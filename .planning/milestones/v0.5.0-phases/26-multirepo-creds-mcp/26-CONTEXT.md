# Phase 26: 多仓凭证统一 + MCP 多仓参数 - Context

**Gathered:** 2026-06-14
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous, auto-accepted recommendations)

<domain>
## Phase Boundary

本阶段补齐多仓能力两块：
1. **GitLab 凭证统一池**（REPO-01）：同一 GitLab 实例（host）的多个仓库可复用同一 access token，集中管理，不必每仓重复粘贴。
2. **MCP RAG 多仓检索参数**（REPO-02）：MCP RAG 检索工具暴露多仓 / 全仓检索参数，可跨多个仓库召回。

本阶段做：
- 实例级 Git 凭证模型（按 GitLab host 维度存加密 token），仓库按 host 解析复用；保留 per-repo 覆盖与既有 per-repo token 向后兼容（fallback）。
- 凭证解析器：给定仓库 URL → 取 host → 查实例凭证（per-repo 覆盖优先，其次实例池）。Fernet 加密复用既有凭证加密路径，token 绝不明文落库/进日志。
- MCP RAG 工具新增多仓参数（`repository_ids` 列表 / 全仓标志），跨仓检索；每仓仍 fail-closed 复用 Phase 22 排除；权限/范围受控。
- 凭证管理的最小 REST + 前端入口（实例凭证 CRUD）。

本阶段**不做**：
- 非 GitLab 平台凭证统一（GitHub 等）——本阶段聚焦 GitLab（REPO-01 措辞），结构可扩展但不强做。
- 跨仓编码/wave 派发（v0.8）。
- 全量凭证审计（v0.10）。

</domain>

<decisions>
## Implementation Decisions

### D-01 实例级凭证池（REPO-01）
- 新增实例级凭证（如 `GitInstanceCredential` 或复用既有凭证体系按 host 维度）：字段含 `host`（GitLab 实例域名，唯一）、`provider`(gitlab)、加密 `access_token`、label、时间戳。
- 复用现有加密方式（cryptography Fernet，与既有 `ProviderCredential`/凭证 service 一致），token 加密存储、读取时解密、绝不明文入日志。
- 仓库不再强制各存 token：解析时按 host 命中实例凭证。

### D-02 凭证解析与兼容
- 解析器 `resolve_git_credential(repo)`：优先 per-repo 显式 token（向后兼容既有部署），否则按 repo URL 的 host 查实例凭证池；都无则报明确错误（不静默失败）。
- 既有部署（每仓已存 token）升级后行为不回退（CLAUDE 兼容约束）：per-repo token 仍生效，实例池为新增可选层。
- clone / git platform API（python-gitlab / mirror / 索引拉取）统一经解析器取 token，消除散落的 per-repo 取 token 逻辑。

### D-03 MCP RAG 多仓参数（REPO-02）
- MCP RAG 检索工具（`search_rag_chunks` 及相关）新增可选参数：`repository_ids: list`（多仓）/ 全仓标志（如 `all_repositories: true` 或 `repository_ids` 省略=全部有权仓）。
- 跨仓检索：对每个目标仓分别检索并合并/排序结果；**每仓 fail-closed 复用 Phase 22 排除**（被排除文件跨仓也不可见）。
- 向后兼容：不传多仓参数时维持既有单仓行为（单 `repository_id`）。结果标注来源仓库（repo 标识）便于区分。
- 权限/范围受控：只检索调用方有权访问的仓库（复用既有权限判定）。

### D-04 安全与兼容
- token 全程加密、绝不明文落库/进日志/返回前端（前端只显示 label/host + 是否已配置，不回显明文）。
- 多仓检索每仓独立 fail-closed 排除，单仓失败不影响其余仓（best-effort 合并），但凭证缺失等错误明确报。
- migration 仅加表/字段，不回填；不破坏既有单仓检索与 per-repo token。

### Claude's Discretion
- 实例凭证模型名/表结构、是否并入既有凭证 app、解析器落点、MCP 多仓参数精确命名（`repository_ids` vs `repo_ids` / 全仓表达）、跨仓结果合并排序策略、前端凭证管理入口落点，由 planner/executor 研究既有凭证与 MCP 工具结构后定。
- 多仓检索的并发/串行与单仓上限（控成本），由 planner 依性能权衡设定。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets（待 planner 核实）
- 既有凭证：`ProviderCredential` / `SettingKeys` / 凭证 service（Fernet 加密路径复用）；仓库模型当前的 per-repo access token 字段（解析器兼容入口）。
- git 平台访问：`server/git_platform/`（python-gitlab / PyGithub 客户端）、`server/services/repo_mirror.py`、indexer clone 路径——统一经解析器取 token。
- MCP RAG 工具：`server/mcp_tools/views.py`（`search_rag_chunks` 等）+ `server/services/rag_search.py` / HybridSearchService（多仓检索改造点）。
- Phase 22 `services/exclusion.py`（多仓检索每仓 fail-closed 复用）。
- 前端 `web/src/api/` + 既有凭证/设置管理界面（实例凭证 CRUD 入口参考）。

### Established Patterns
- 凭证 DB 加密（cryptography Fernet）；service 层无状态域逻辑；异步 ORM 经 `sync_to_async`；adrf 异步视图。
- MCP 工具按既有 view + tool 注册范式（`mcp_tools/urls.py`）。
- 前端类型化 client + reka-ui + vue-i18n（默认中文）。

### Integration Points
- 凭证解析器接入 clone / git platform client / 索引拉取所有取 token 处。
- MCP 多仓参数改 `search_rag_chunks` 工具 schema + `search_rag`/HybridSearch 多仓路径。
- 实例凭证 REST 注册进 `/api/...`；前端入口挂在设置/凭证管理页。
</code_context>

<specifics>
## Specific Ideas

- REPO-01 守护测试：两个同 host GitLab 仓配置一个实例凭证，断言两仓 clone/API 都用该凭证（无需各自存 token）；per-repo token 存在时优先（兼容）。token 不明文进日志/返回。
- REPO-02 守护测试：建多仓，`search_rag_chunks(repository_ids=[a,b])` 跨仓召回；某仓被排除文件不出现（每仓 fail-closed）；省略多仓参数维持单仓行为；只检索有权仓。
- 安全守护：实例凭证 API 返回不含明文 token；日志不含 token。
</specifics>

<deferred>
## Deferred Ideas

- GitHub / 其他平台凭证统一池 → 结构可扩展，本阶段聚焦 GitLab。
- 跨仓编码 / wave 派发 → v0.8。
- 凭证操作全量审计 → v0.10（本阶段仅埋必要点）。
- 多仓检索高级排序 / 重排融合 → 后续。
</deferred>

---
*Phase: 26-multirepo-creds-mcp*
*Context gathered: 2026-06-14 via smart discuss (autonomous)*
