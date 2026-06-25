---
phase: 78
title: 飞书触发建项目 + 看板枚举 + 工作项组合
milestone: v0.15.0
status: planned
requirements: [FSPROJ-01, FSPROJ-02, FSPROJ-03, COMPOSE-01, COMPOSE-02]
depends_on: [77]
---

# Phase 78 PLAN — 飞书触发建项目 + 看板枚举 + 工作项组合

## 0. 目标与范围

把"飞书项目跟踪看板"自动转成 `Project` 聚合根：封装看板枚举（子项 story/缺陷 + 人员带角色）、
飞书事件幂等建项目并拉人（经身份映射带身份）、提供 `create_project` 工作流节点，并把
`WorkItem`（story/缺陷复用 `delivery.WorkItem`）经轻量关系边 `ProjectWorkItemLink` 组合进项目。

**In scope（FSPROJ-01~03, COMPOSE-01/02）**；Out of scope：KnowledgeEdge 富建模（Phase 79）、
前端工作台（Phase 81）、真实飞书凭证端到端枚举/事件人工验收（里程碑级）。

## 1. 飞书"项目跟踪"枚举能力盘点（CRITICAL FIRST STEP — 调研结论）

盘点 `server/services/feishu.py` / `feishu_parsing.py` / `server/feishu/client.py` 现有端点能力：

| 能力 | 飞书端点 | 现状 | 结论 |
|---|---|---|---|
| 取单个工作项详情（含 fields 数组） | `POST /open_api/{pk}/work_item/{type}/query`（`FeishuClient.get_work_item`，硬路径 `strict_response_json` fail-loud） | ✅ 可用 | 枚举入口：读"项目跟踪"看板工作项本身 |
| 取工作项关联关系 | `GET .../relation`（`get_work_item_relations`，`safe_response_json` fail-soft，PF-10 实测返回非 JSON 常降级 `[]`） | 🟡 不可靠 | **不作主路径**，仅兜底 |
| **整板 listing（一次列出看板下所有子项/成员）** | — | ❌ 无此 API | **确认无整板枚举 API** |

**核心结论（与 MILESTONE-PROPOSAL §3/§4 一致）：飞书无整板 listing API。** 枚举只能经"项目跟踪"
工作项的**关联多选字段（`field_type_key == work_item_related_multi_select`）派生子项 id**（复用
Phase 27 `derive_relations_from_fields` / `extract_related_ids` 范式），人员经工作项的**用户类字段**
（`field_type_key in {user, multi_user, role}`）派生。两者都是"读单个工作项 fields → 派生"，
**不依赖**任何不存在的整板接口。

**降级面（fail-soft 半自动）：**
- 硬路径 = 读"项目跟踪"工作项本身：非 JSON `strict_response_json` fail-loud 抛 `FeishuResponseError`；
  调用方（事件handler/节点）捕获 → **降级半自动**（仍幂等建项目，子项/成员留待后续 webhook 逐个并入）。
- 软路径 = 从 fields 派生子项/成员：拿不到（字段缺失/空）→ 返回**部分结果 + warning + `degraded=True`**，
  绝不抛。

**字段 key 不确定性（needs live-Feishu）：** 真实"项目跟踪"看板的子项关联字段 key、人员字段 key、
角色字段标签尚未经真实飞书 payload 校验。故采用**集中映射表 + 关键字推断 + 保守默认**（见 §2），
真实 key 经 live UAT 后补登记即可（不改逻辑）。测试用 respx mock 飞书 `query` 响应，不依赖真实凭证。

## 2. 锁定决策落地（LOCKED，照 CONTEXT 执行）

### 2.1 看板枚举 service（FSPROJ-01）— `server/services/feishu_project_board.py`
- 纯函数派生 + 一个 async 入口 `enumerate_board(client, *, feishu_project_key, board_work_item_id, board_work_item_type) -> BoardEnumeration`。
- dataclass：`BoardWorkItemRef(work_item_id:int, work_item_type:str)`、`BoardPerson(user_key:str, role:str)`、
  `BoardEnumeration(work_items, people, warnings:list[str], degraded:bool)`。
- 复用既有 `FeishuClient.get_work_item` + `feishu_parsing` helper，**不新引 SDK**。
- 角色映射表 `ROLE_LABEL_TO_PROJECT_ROLE`（集中定义，飞书角色标签 → `ProjectRole`），未命中保守默认 `backend`。
- 子项类型推断 `_infer_child_type`：字段名/别名含 `缺陷/bug/issue/defect` → `issue`，否则 `story`（保守）。
- 硬路径 fail-loud（board item 取数 strict）、软路径 fail-soft（派生缺料 → 部分 + warning + degraded）。
- 观测：`board_enumeration_started/completed/failed` + `duration_ms`，`component="feishu"`, `category="sampling"`；
  飞书响应体脱敏已由 `strict/safe_response_json` 兜底，本模块不 log 凭证。

### 2.2 工作项组合（COMPOSE-01/02）— `initiatives` 新增 through 模型
- `ProjectWorkItemLink`（`initiatives/models/work_item_link.py`）：`project` FK + `work_item` FK→`"delivery.WorkItem"`
  + `provenance`(board_derived/manual) + 时间戳，`unique_together(project, work_item)`；`Project.work_items` M2M（through）。
- story 与缺陷**统一复用 `delivery.WorkItem`**（按 `work_item_type` 区分），缺陷不重复建模（COMPOSE-02）。
- attach/detach 经 `ProjectService`（INV-6）：`attach_work_item`（get_or_create 幂等，board_derived 自动并入 + manual 手动并入）、
  `detach_work_item`（手动移除）。审计 `project.work_item_attached/detached` + WS 推送。
- INV-6 grep 守护扩 `ProjectWorkItemLink`。

### 2.3 飞书事件幂等建项目 + 拉人（FSPROJ-02）— `initiatives/services/project_board_sync.py`
- `ProjectBoardSyncService.sync_from_board(*, space, feishu_project_key, board_work_item_id, board_work_item_type, name, ..., client=None, initiated_by_user_id="system")`：
  入口同源 service，被飞书事件 handler 与 `create_project` 节点共用。
  1. `ProjectService.create`（幂等 `(space, feishu_project_key)`，Phase 77 已实现）。
  2. `enumerate_board`（fail-soft：枚举抛错 → 捕获、`degraded=True`、降级半自动，仍返回已建项目）。
  3. 拉人带身份：逐人 `resolve_feishu_user`（JIT 解析）→ 命中 `add_member(role)`；owner 角色经
     `add_member(backend)` + `transfer_owner` 落主R；未映射 fail-soft 跳过（保留可后补绑定）。
  4. 组合子项：逐子项 `WorkItemService.upsert(identity, fetch=False)`（确保 canonical 行，INV-6）
     → `ProjectService.attach_work_item(provenance=board_derived)`。
  - **幂等**：重复事件 → 项目不新建（created=False）、成员/链接 get_or_create 只补齐不重复。
  - 观测：`project_board_sync_started/completed` + `initiated_by_user_id` + `duration_ms`，
    `component="initiatives"`, `category="caller"`。
- 飞书 webhook 接线（`server/feishu/views.py`）：新增 `is_project_tracking_event(payload)` 识别"项目跟踪
  拖到节点/状态"（`WorkFlowNodeStatusEvent`/`WorkitemStatusEvent`，work_item_type 命中
  `PROJECT_TRACKING_WORK_ITEM_TYPE_KEYS`，默认 `{"project"}`，可经 live UAT 校正）→ 后台
  `run_in_background(sync_from_board, initiated_by_user_id=<解析触发人或 system>)`（worker 入口 re-bind）；
  仅投三元组标量，**不**把原始 webhook payload 再次落库（入口 `record_inbound_webhook` 已脱敏留痕）。
  gated + best-effort，绝不影响既有 webhook 主流程（零回归）。

### 2.4 `create_project` 工作流节点（FSPROJ-03）— `workflows/nodes/integrations/create_project.py`
- `@register_node` 自动注册 `create_project`（全局唯一）、`NodeCategory.INTEGRATION`、`execution_mode="server_local"`，
  镜像 `feishu_chat.CreateGroupChatNode` 结构 + 全中文 config_schema；inputs=[default]、outputs=[default, error]。
- execute：render 看板引用（project_key + board_work_item_id + type + name）→ 解析 Space（`_resolve_project`，
  缺则按 feishu_project_key 查 Space）→ 调 `sync_from_board`；缺看板引用 → `failed` + error handle；
  枚举 fail-soft 降级仍 `completed`（输出 `degraded`/`warnings`）。节点**不直接写表**，全经 service（INV-6）。

### 2.5 异步/失败策略
- async ORM 全走 `sync_to_async`（service 内已封装）；节点失败返回 `NodeResult(status="failed")`，绝不抛过引擎。

## 3. 执行波次（wave by wave，atomic commit）

- **Wave 1** — 看板枚举 service：`services/feishu_project_board.py`（`feat(78)`）。
- **Wave 2** — 组合模型 + service：`ProjectWorkItemLink` 模型 + migration + `ProjectService.attach/detach_work_item`
  + 审计词表 + INV-6 守护扩展（`feat(78)`）。
- **Wave 3** — 同源建项目 service + 飞书事件接线：`project_board_sync.py` + `feishu/views.py` 接线（`feat(78)`）。
- **Wave 4** — `create_project` 节点（`feat(78)`）。
- **Wave 5** — 测试（respx-mock 飞书）：枚举 happy/fail-soft/role 映射、幂等事件建项目、节点 happy/缺ref/fail-soft、
  attach/detach + INV-6、story vs 缺陷、initiated_by 绑定 + payload 脱敏（`test(78)`）。

迁移：`cd server && uv run python manage.py makemigrations initiatives`；收尾 `makemigrations --check --dry-run` 干净。

## 4. 测试矩阵（respx-mock，不依赖真实凭证）

| 测试 | 覆盖 |
|---|---|
| `tests/services/test_feishu_project_board.py` | 枚举 happy（子项+人员+角色映射）/ 无子项·无人员 degraded / 硬路径非 JSON fail-loud / 角色映射表 + 保守默认 / story vs 缺陷类型推断 |
| `tests/initiatives/test_project_work_item_link.py` | attach get_or_create 幂等 / board_derived + manual 并存 / detach / story 与缺陷同表挂入不重复建模 |
| `tests/initiatives/test_project_board_sync.py` | 幂等建项目（重复不新建、dup 补齐成员/链接）/ 枚举 fail-soft 降级仍建项目 / 拉人经身份映射（未映射跳过）/ initiated_by 绑定 |
| `tests/initiatives/test_project_inv6_guard.py`（扩展） | `ProjectWorkItemLink` 纳入 INV-6 守护 |
| `tests/workflows/test_create_project_node.py` | 节点 happy / 缺看板 ref → failed+error / 枚举 fail-soft → completed+degraded / 自动注册 |

## 5. 验收基线
- 后端：`cd server && uv run pytest -q`。BASELINE = 38 既有失败（`/tmp/phase76_baseline_failures.txt`）+ 1 既有跨套件
  ordering error（见 77-SUMMARY）。目标：**零新增回归**，新测试全绿。
- `makemigrations --check --dry-run` 干净。

## 6. Success Criteria 映射
1. 看板枚举封装（子项 story/缺陷 + 人员带角色，无整板 API 经子项字段派生，fail-soft 降级）→ §2.1 + Wave1 测试。
2. 飞书事件幂等建项目 + 拉人（重复不重复建）→ §2.3 + Wave3 测试。
3. `create_project` 节点（建项目 + 拉人带角色 + 关联子项，自动注册）→ §2.4 + Wave4 测试。
4. 组合多 WorkItem（story 复用 + 手动并入/移除；缺陷同样挂入不重复建模）→ §2.2 + Wave2 测试。
