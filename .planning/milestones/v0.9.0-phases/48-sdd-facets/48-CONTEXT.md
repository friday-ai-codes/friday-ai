# Phase 48: SDD 仓库检测 + facets 打标 + 前端标签 - Context

**Gathered:** 2026-06-17
**Status:** Ready for planning
**Mode:** Smart discuss (autonomous — 灰区由设计文档自动决策，未向用户提问)

<domain>
## Phase Boundary

索引完成后自动识别 spec-driven（openspec）仓库并打标，用户在前端可识别 SDD 仓库。

**In scope:**
- 索引完成钩子检测仓库根 `openspec/` 目录 → 写 `Repository.facets["methodology"]="SDD"`（SDD-01）
- 前端仓库列表 + 详情展示 "SDD" 方法论标签（SDD-02）

**Out of scope（本 phase）:**
- 产 spec（Phase 49）、spec 状态机（Phase 50）、编码 gate（Phase 51）、关联/验收（Phase 52）
- openspec 内容深度校验/lint（v2 SDDX-01）
</domain>

<decisions>
## Implementation Decisions（smart discuss 自动决策）

### D-48-1 检测触发点：复用索引完成钩子 + 真实 clone 路径
索引 `run_full_index` 的 FINALIZING 末尾（与 Phase 24 sensitive-detect / Phase 25 commit-index 同位、同 best-effort 派发范式）检测——此时临时 clone 目录尚未 rmtree，可直接探测仓库根 `openspec/`。**仅 base 路径**（`if not branch:`），与 commit-index 一致。失败/异常整段 try/except 吞为 warning `sdd_detect_dispatch_failed`，**绝不阻断索引 success 终态**（D-04 范式）。

### D-48-2 检测判据：仓库根存在 `openspec/` 目录
判据 = clone 根目录下存在名为 `openspec` 的目录（`os.path.isdir(repo_path/"openspec")`）。最小充分信号，不解析 openspec 内容（内容校验留 v2）。

### D-48-3 写入单一入口 + 幂等 + 不误标 + 尊重 pin
新建 `server/services/sdd_detect.py`（镜像 `sensitive_detect.py` 形状），暴露 async `detect_and_tag_sdd(repository_id, repo_path)`：
- openspec/ 存在 → `facets["methodology"]="SDD"`
- openspec/ 不存在 → 若 `facets["methodology"]` 当前为自动写入的 `"SDD"` 则清除（删 openspec → 取消标记，防漂移/陈旧）；其他值不动
- 尊重 `facets["_pinned"]`（含 `methodology` 则跳过，复用 FacetService pin 语义）
- 经 `repo.asave(update_fields=["facets","updated_at"])` 写回；幂等（值未变则 no-op，不漂移）
- 与 `FacetService` 的事实分面**键不冲突**（methodology 为独立语义键，FacetService 不碰，对齐 facet_service.py 既有约定）

### D-48-4 前端标签：复用既有 facets 透出 + 显式 SDD 徽标
`repositories/tree_views.py` 已把非 `_` 前缀 facets 透出（含 methodology）。前端在仓库列表卡片 + 详情页对 `facets.methodology === "SDD"` 渲染显式 "SDD" 徽标（区别于普通事实分面 chip，给予方法论语义高亮），i18n zh-CN 文案接入既有 vue-i18n。

### D-48-5 检测器轻量、无重依赖
检测器纯文件系统探测（isdir），不 import 索引重依赖、不跑 tree-sitter/LLM；可独立单测（构造临时目录含/不含 openspec/）。
</decisions>

<code_context>
## Existing Code Insights

- `Repository.facets = models.JSONField(default=dict)`（`server/repositories/models.py:328`）——通用分面 JSON，已有 `_pinned` skip 语义。
- `FacetService.refresh_fact_facets`（`server/repositories/facet_service.py`）——事实分面（活跃度/技术栈等）自动刷新，**键不与 methodology 冲突**；尊重 `_pinned`。methodology 为本 phase 新增独立语义键，**不**走 FacetService 计算。
- 索引完成 best-effort 派发范式（参照实现）：Phase 24 `_run_sensitive_detection`、Phase 25 `_run_commit_index`——均在 `run_full_index` FINALIZING、rmtree 前用真实 clone 路径执行，整段 try/except 吞异常仅 warning，绝不阻断 index success（见 STATE.md Phase 24/25 decisions）。SDD 检测复刻此挂接点与 guard。
- 前端 facets 透出：`server/repositories/tree_views.py`（facets dict 过滤 `_` 前缀）；仓库列表/详情 Vue 组件消费。
- structlog 结构化日志约定（`logger.info("event_name", key=val)`）。
</code_context>

<specifics>
## Specific Ideas

- 检测器文件名 `server/services/sdd_detect.py`，函数 `detect_and_tag_sdd`。
- facets 语义键 `"methodology"`，值 `"SDD"`（大写，与 DOMAIN-MODEL/vNext 措辞一致）。
- 守护测试：含 openspec/ → 打标；不含 → 不标；删除 openspec/ 重索引 → 取消标记；`_pinned` 含 methodology → 跳过；重复检测幂等（updated_at/facets 不漂移）；检测异常不阻断 index success。
- 前端守护测试：facets.methodology==="SDD" 渲染 SDD 徽标；非 SDD 不渲染；i18n 文案以真实 zh-CN.json 断言。
</specifics>

<deferred>
## Deferred Ideas

- openspec spec 内容/格式深度校验（v2 SDDX-01）。
- 非 openspec 的其他 SDD 方法论识别（v2 SDDX-03）。
- methodology 之外的方法论维度（如 TDD/BDD 自动识别）——本里程碑只做 SDD。
</deferred>
