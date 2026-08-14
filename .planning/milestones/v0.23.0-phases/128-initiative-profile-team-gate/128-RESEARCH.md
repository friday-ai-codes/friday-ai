# Phase 128 Research: 专项画像 + 团队门禁地基

**Researched:** 2026-08-14  
**Domain:** process_runtime 漏斗入口（画像 + 团队硬门禁）  
**Confidence:** HIGH（代码路径已核对；无新外部依赖）

## Summary

Phase 128 在**漏斗入口**增加两块可单测能力：`InitiativeProfile`（从 feature list 机读画像）与 `TeamGate`（`team_core` 硬范围）。接线点是 `BlueprintRouteAdapter`、`RepoAssociationService`、MCP `arun_route_stage` / `RouteBlueprintReposView`。**禁止改写** `RepoRouterV2` 内核；其 `grouping_repository_ids` 保持 annotate-only，供裸直调兼容。漏斗路径改为 hard gate：`out_of_team` 不可作 primary；无团队 / 空 `team_core` → `clarify`，禁止静默全库 primary。

## Current Codebase Facts

### BlueprintRouteAdapter
- 路径：`server/services/process_runtime/blueprint_route.py`
- `route(session)`：解析 requirement_spec → 可选 pin → `_resolve_repository_ids` → `RepoRouterV2.route(..., repository_ids=...)` → 章程/历史融合
- `_resolve_repository_ids`：`include_repos` → work_item.space 仓 → **`None`（全库）** — 本相位漏斗路径不得再静默走全库 primary
- 观测：`blueprint_route_completed`，`category=sampling`，`component=process_runtime`

### RepoAssociationService
- 路径：`server/initiatives/services/repo_association_service.py`
- `propose`：`_build_query(features_flat)`（含 name/description/module，**现含验收语料风险**）→ 限定 `Space.repositories` → `RepoRouterV2.route(..., repository_ids=repo_ids, corpus_kind="requirement")`
- 空 `repo_ids` / 空 query：返回空候选 + `router_version=skipped`，**无 `clarify` 状态** — 需按 D3 改为 clarify 载荷
- 已有 Space 挂载解析：`_space_repository_ids` → `space.repositories.values_list("id")`

### RepoRouterV2 grouping
- `grouping_repository_ids`：**只标注** `in_project`/`global`，不过滤、不打分（`repo_router_v2.py` + `annotate_groups`）
- 本相位：**不改** V2 该语义；漏斗层自行 hard gate / clarify

### MCP route stage
- `arun_route_stage`（`stage_sandbox.py`）：候选范围 `include_repository_ids` > `project_id` space > **全库**；零落库 dry-run
- MCP 入口：`RouteBlueprintReposView` → `arun_route_stage`（`mcp_tools/views.py`）
- 现行为允许无团队时全库 primary — **违反 D1/D3**，须在 sandbox/入口加门禁

### Feature list 语料
- `FeatureListExtractor.extract_structure` → `{modules, features_flat}`；feature 含 `acceptance[]`
- `feature_list_import` 有 `summary_lines` / `acceptance_lines` 行号裁剪能力
- 画像主路径应优先：模块总览/简述/全局流转/功能描述；**剔除** `acceptance` / 测试 case 正文

### Space 挂载
- `projects.models.Space.repositories` M2M；`SpaceRepository` 中间表
- 项目选仓已以 Space 为候选范围；Blueprint 侧 work_item.space 同口径

### CallSource
- 权威枚举：`server/agents/call_source.py`（LOGGING-SPEC 对齐）
- 画像若调 LLM：新增 `initiative_profile`（或等价）并同步 LOGGING-SPEC 一行；temperature/idempotency 对齐既有 blueprint 路径

## Recommended Architecture

```text
feature_list / requirement_spec
        │
        ▼
 initiative_profile.build_profile(...)   → InitiativeProfile | clarify(insufficient_profile_corpus)
        │                                    fail-soft → degrade_reason（不抛垮）
        ▼
 team_gate.resolve_and_apply(...)
   ├─ resolve team_core（Project→Space → space_id/team_id → 上下文 Space）
   ├─ empty / unindexed → clarify(missing_team|empty_team_core)  ✗ 不调全库 V2 primary
   └─ annotate team_core | team_adjacent | out_of_team
        │
        ▼
 funnel route（Blueprint / RepoAssociation / MCP）
   ├─ repository_ids = team_core（硬过滤候选）
   ├─ primary 仅允许 team_core（adjacent 例外接口预留，证据校验 → 129）
   └─ stage 观测：profile + gate outcome + request_id/run_id
```

### Module layout（CONTEXT 锁定建议）
- `server/services/process_runtime/initiative_profile.py`
- `server/services/process_runtime/team_gate.py`
- 测试：`server/tests/services/process_runtime/test_initiative_profile.py`、`test_team_gate.py`；接线测落既有 blueprint_route / repo_association / stage_sandbox / MCP 测试文件或新建 `test_funnel_team_gate.py`

### Clarify 载荷最小形状（三入口统一）
```text
{
  "status": "clarify",
  "clarify_reason": "insufficient_profile_corpus" | "missing_team" | "empty_team_core",
  "candidates": [],           # 禁止塞全库 top-k 当主结果
  "team_core": [],
  "offer": { "bind_space": true, "spaces": [...] },  # MCP 可枚举时
  "profile": {...} | null,
  "degrade_reason": "" | "..."
}
```

## Constraints & Pitfalls

| Pitfall | Mitigation |
|---------|------------|
| 改 V2 grouping 为 hard filter | **禁止**；只在漏斗入口 hard gate |
| 空团队静默全库（当前 Blueprint/MCP） | D1/D3：返回 clarify，不调/不返回全库 primary |
| 画像吃 acceptance/测试 case | corpus 选择器显式剔除；仅操作细节 → clarify |
| 画像 LLM 失败拖垮路由 | fail-soft + `degrade_reason`；下游仍可走门禁 clarify |
| 日志写需求原文 | 只记长度/计数/reason；`category` + `component`；异常 `redact_secrets_in_text` |
| RepoAssociation 空 Space 现返回空候选 | 升级为 `status=clarify`，契约 additive：加键不删旧键 |

## Out of Scope（Deferred）
- shortlist / 历史先验 / 章程角色图 → 129
- 放置单元全量接线 → 130
- 发布门 / 反思 → 131
- 高三提分回归 → 132
- `team_adjacent` 证据校验实现 → 129（本相位仅留接口/枚举）

## Package Legitimacy
无新 pip/npm 包。复用既有 LLM / structlog / Django ORM。

## Validation Architecture (Nyquist)

| Behavior | Test file | Command |
|----------|-----------|---------|
| 画像成功字段齐全 | `test_initiative_profile.py` | `uv run pytest server/tests/services/process_runtime/test_initiative_profile.py -q` |
| 语料不足 clarify | 同上 | 同上 |
| team_core 解析 + out_of_team 非 primary | `test_team_gate.py` | `uv run pytest .../test_team_gate.py -q` |
| 空团队 clarify | 同上 | 同上 |
| 漏斗接线 + MCP 无静默全库 primary | `test_funnel_team_gate.py` / stage_sandbox / MCP | 对应 pytest |
| 裸 V2 annotate-only 不回归 | 既有 `test_repo_router_v2*` | 选择性回归 |

## Sources
- Primary: 上述源文件实读（2026-08-14）
- Locked: `.planning/milestones/v0.23.0-DECISIONS.md` D1/D3；`128-CONTEXT.md`
