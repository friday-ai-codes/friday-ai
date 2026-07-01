---
phase: 99-association-visualization-crosslink
verified: 2026-07-01T12:50:00Z
status: human_needed
score: 3/3 must-haves verified (code + tests); 0 gaps
overrides_applied: 0
human_verification:
  - test: "打开某项目作战室关系星图（ProjectGalaxyCard），确认 artifact(amber #f59e0b)/capability(rose #ec4899) 节点与图例可见，力导图渲染正常"
    expected: "工件/能力节点以语义色渲染，图例含『工件』『能力』，点击节点详情正确显示类型/载体"
    why_human: "3D 力导图（3d-force-graph + three）真实渲染与交互无法用 grep/静态检查验证"
  - test: "在含真实 Phase 98 关联数据的环境打开一个工件（document）知识实体详情页，查看『关联』区块"
    expected: "展示关联仓库（可点跳 /repositories/{id}）、能力、关键词徽标；无关联时显示优雅空态不渲染空块"
    why_human: "真实关联召回（graph_store.neighbors / RELATES_TO 边）依赖 live 数据，单测用 mock，需真机确认端到端召回与展示"
  - test: "打开一个仓库（repository）知识实体详情页，查看反向『相关交付文档』并点击其中一项"
    expected: "列出相关交付文档，点击 RouterLink 跳转到该文档知识实体详情（/knowledge/entities/{entity_id}），形成双向闭环"
    why_human: "点击导航跳转与页面切换属浏览器运行时行为，需人工点击验证"
  - test: "在作战室『外部依赖』区（DependenciesSection）某工件行点击『知识』(brain) 图标入口"
    expected: "跳转到该工件对应知识实体详情（/knowledge/entities/{entity_id}），闭合『作战室↔知识』环"
    why_human: "跨页面路由跳转 + entity_id 映射正确性在真实数据下的端到端行为需人工点击确认"
---

# Phase 99: 关联可视化与交叉入口 Verification Report

**Phase Goal:** 把工件↔仓库/能力/关键词的关联可视化到星图与知识图谱，并在作战室外部依赖区与知识体系之间打通双向交叉入口。
**Verified:** 2026-07-01T12:50:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth (ROADMAP SC + KDEP) | Status | Evidence |
| --- | --- | --- | --- |
| 1 | KDEP-10: `_build_project_galaxy` 纳入 artifact 节点 + HAS_ARTIFACT/ARTIFACT_REPO/ARTIFACT_CAPABILITY 边；project↔repo 来源并入 verified RepoAssociation；复用 Phase 98 查询；max_nodes 含 artifact；best-effort；access_scope | ✓ VERIFIED | `server/initiatives/views.py:1790-1844` artifact 分支整体 `try/except`（best-effort，异常记 `project_galaxy_artifact_branch_failed`）；`:1799-1804` `artifact:{id}` 节点 + `HAS_ARTIFACT`；`:1815` `ARTIFACT_REPO`；`:1822` `ARTIFACT_CAPABILITY`；`:1825-1833` verified `RepoAssociation`→`USES_REPO`（`add_edge` 去重与 MR 来源统一 `:1725,1733-1738`）；`:1866-1905` `_agather_artifact_assocs` 复用 Phase 98 `ArtifactAssociationService.get_artifact_associations(user=...)`（access_scope fail-closed）；`:1846-1851` max_nodes 截断在全部节点加入后、artifact 天然纳入预算。测试 8 passed（5 新 `test_project_galaxy_artifacts.py` + 3 既有零回归） |
| 2 | KDEP-11: 实体详情/关系图展示工件↔仓库/能力/关键词；仓库/能力反向展示相关交付文档；双向可导航 | ✓ VERIFIED | 后端反查 `server/knowledge/api/repository_artifacts.py:31-66`（薄委托 `find_artifacts_by_repository`，access_scope fail-closed，每项补 `entity_id`）；路由 `server/knowledge/api/urls.py:27-29` `repositories/<uuid>/artifacts/`；`server/initiatives/serializers.py:400-406` `ArtifactSerializer.entity_id`（document 派生 id）。前端 `EntityAssociationsCard.vue`：正向 `:95-150`（仓库 RouterLink→`/repositories/{id}` `:103`、能力/关键词 Badge）+ 反向 `:153-186`（文档 RouterLink→`/knowledge/entities/{entity_id}` `:160`）；`entities/[id].vue:69-74,149-162` 条件挂载。测试 19 passed；`vue-tsc --noEmit` 零错误 |
| 3 | KDEP-12: 作战室「外部依赖」工件处跨入口到知识实体（携 entity_id），闭合作战室↔知识环 | ✓ VERIFIED | `DependenciesSection.vue:247-253` `RouterLink :to="/knowledge/entities/${a.entity_id}"`（`v-if="a.entity_id"`，`icon-[lucide--brain]` + tooltip + `data-testid="deps-view-knowledge-btn"`）；`web/src/api/artifacts.ts:33` `Artifact.entity_id: string`；星图渲染 `projectGalaxy.ts:9-10` node type 扩 `artifact`/`capability`，`ProjectGalaxyCard.vue:34-35` 语义色 + `:43-44` label + `:51-53` 图例；i18n `zh-CN.json:1347` viewKnowledge / galaxy type 键齐备 |

**Score:** 3/3 truths verified (code present + wired + Phase 99 tests green)

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `server/initiatives/views.py` | galaxy artifact 节点/边 + verified repo + best-effort | ✓ VERIFIED | `_build_project_galaxy` + `_agather_artifact_assocs` 扩展，`_ARTIFACT_RELATIONS` 计数 |
| `server/tests/initiatives/test_project_galaxy_artifacts.py` | 5 用例 | ✓ VERIFIED | 8 passed（本文件 5 + 既有 galaxy 3） |
| `server/knowledge/api/repository_artifacts.py` | 反查端点 | ✓ VERIFIED | `RepositoryArtifactsView`，access_scope fail-closed，entity_id 补全 |
| `server/knowledge/api/urls.py` | 路由注册 | ✓ VERIFIED | `knowledge-repository-artifacts` |
| `server/initiatives/serializers.py` | `ArtifactSerializer.entity_id` | ✓ VERIFIED | `SerializerMethodField` 函数内 import 派生 |
| `web/src/components/knowledge/EntityAssociationsCard.vue` | 正/反向双向导航 + 空态 | ✓ VERIFIED | forward/reverse useQuery + RouterLink + CompactEmptyState |
| `web/src/pages/knowledge/entities/[id].vue` | 条件挂载关联区块 | ✓ VERIFIED | `showAssociations` + section + 锚点 |
| `web/src/api/knowledge.ts` | getArtifactAssociations/getRepositoryArtifacts + 类型 | ✓ VERIFIED | 两函数 + `ArtifactAssociations`/`RepositoryArtifact(s)` 类型，barrel 导出 |
| `web/src/api/projectGalaxy.ts` | node type 扩展 | ✓ VERIFIED | `artifact`/`capability` 联合类型 |
| `web/src/components/project/warroom/ProjectGalaxyCard.vue` | 语义色 + label + 图例 | ✓ VERIFIED | TYPE_COLOR/TYPE_LABEL 扩展，图例自动纳入 |
| `web/src/api/artifacts.ts` | `Artifact.entity_id` | ✓ VERIFIED | `entity_id: string` |
| `web/src/components/project/workbench/DependenciesSection.vue` | 知识跨入口 | ✓ VERIFIED | RouterLink→`/knowledge/entities/{id}` |

### Key Link Verification

| From | To | Via | Status |
| --- | --- | --- | --- |
| `_build_project_galaxy` | Phase 98 `ArtifactAssociationService` | `_agather_artifact_assocs` → `get_artifact_associations(user=)` | ✓ WIRED (views.py:1873,1886) |
| `RepositoryArtifactsView` | Phase 98 反查 | `find_artifacts_by_repository(user=)` | ✓ WIRED (repository_artifacts.py:44) |
| `EntityAssociationsCard` | 正向/反向端点 | `knowledgeApi.getArtifactAssociations/getRepositoryArtifacts` | ✓ WIRED (card:42,49) |
| `entities/[id].vue` | `EntityAssociationsCard` | 条件 `<EntityAssociationsCard :source-kind :source-id :kind>` | ✓ WIRED (id.vue:157-161) |
| 反向文档项 | 知识实体详情 | RouterLink `/knowledge/entities/{entity_id}` | ✓ WIRED (card:160) |
| `DependenciesSection` 工件行 | 知识实体详情 | RouterLink `/knowledge/entities/{entity_id}` (v-if entity_id) | ✓ WIRED (deps:247-248) |

### Probe / Behavioral Execution

| Check | Command | Result | Status |
| --- | --- | --- | --- |
| galaxy artifact + 回归 | `uv run pytest tests/initiatives/test_project_galaxy_artifacts.py tests/test_project_galaxy.py -q` | 8 passed | ✓ PASS |
| 反查端点 + 关联 + serializer | `uv run pytest tests/knowledge/test_repository_artifacts_api.py test_artifact_associations_api.py test_artifact_associations_service.py tests/initiatives/test_artifact_serializer_entity_id.py -q` | 19 passed | ✓ PASS |
| initiatives 广域（galaxy/artifact 过滤） | `uv run pytest tests/initiatives -q -k "galaxy or repository_artifact or artifact"` | 31 passed, 1 failed（见下，越界） | ⚠️ PASS w/ out-of-scope fail |
| 前端类型 | `pnpm exec vue-tsc --noEmit` | 零错误（exit 0） | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Status | Evidence |
| --- | --- | --- | --- |
| KDEP-10 | 99-01, 99-04 | ✓ SATISFIED | galaxy artifact/capability 节点+3边+verified repo+best-effort（后端）；语义色渲染+图例（前端） |
| KDEP-11 | 99-02, 99-03 | ✓ SATISFIED | 反查端点+entity_id（后端）；正/反向双向可导航卡+条件挂载（前端） |
| KDEP-12 | 99-02, 99-04 | ✓ SATISFIED | ArtifactSerializer.entity_id + 作战室 RouterLink 跨入口，闭环 |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| `delivery/services/artifact_service.py` | 98 | `Artifact.objects.create` 触发 `test_artifact_inv6_guard.py` 失败 | ℹ️ Info（越界，pre-existing） | **不属于 Phase 99 范围**：failure 位于 `delivery/` app（与 `initiatives` Artifact 无关的重名模型/服务）；`delivery/services/artifact_service.py` 最近由无关提交（`工作流底盘重构 Chassis v2`）改动，Phase 99 未触碰 `delivery/`。属既有架构漂移（INV-6 guard allow-list 仅含 `initiatives/services/artifact_service.py`），非本阶段回归。Phase 99 只读约束满足——未新增任何关联真相源写入 |

**READ-ONLY 约束确认：** Phase 99 galaxy 分支、反查端点、serializer entity_id、前端卡片/入口全部为只读查询/派生展示，无任何新增 `KnowledgeEdge`/`RepoAssociation`/`Artifact` 写入。Phase 98 关联真相源保持收口。

### Human Verification Required

见 frontmatter `human_verification`（4 项）：3D 星图真实渲染与节点色/图例、真实 Phase 98 关联数据下的正向/反向展示与召回、双向导航点击跳转、作战室工件行『知识』跨入口点击闭环。均为浏览器可视化 / live-env 运行时行为，静态检查无法覆盖，按任务要求 deferred 为人工验收，不计失败。

### Gaps Summary

无 Phase 99 范围内 gap。所有 3 条 ROADMAP Success Criteria / KDEP-10/11/12 需求的代码已实现、已连线，后端 8+19 测试全绿、前端 vue-tsc 零错误。唯一失败的 `test_artifact_inv6_guard` 命中 `delivery/` app（越界 + pre-existing 架构漂移），不阻塞本阶段目标。剩余为浏览器可视化 / live 数据端到端验收，转人工。

---

_Verified: 2026-07-01T12:50:00Z_
_Verifier: Claude (gsd-verifier)_
