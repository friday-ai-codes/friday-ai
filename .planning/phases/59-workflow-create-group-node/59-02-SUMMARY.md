---
phase: 59-workflow-create-group-node
plan: 02
subsystem: integrations
tags: [feishu, workflow-node, create_chat, create_group_chat, writeback, member_ids, fail-soft, inv6]

# Dependency graph
requires:
  - phase: 59-workflow-create-group-node (Plan 01)
    provides: FeishuIMService.create_chat（建群即拉人单步）+ WorkItemService.awriteback_feishu_chat_id（writeback 单一入口，INV-6）
  - phase: 58-cardkit
    provides: FeishuIMClient/Service 手写 httpx 范式 + 既有 feishu_chat 节点范式
provides:
  - "CreateGroupChatNode（@register_node 自动注册 create_group_chat，建群→输出 chat_id 一等字段→可选 writeback fail-soft）"
  - "_parse_id_list（member_ids 三形态解析 helper：逗号 / JSON 列表 / 模板变量）"
affects: [JoinGroupChatNode 下游消费 chat_id, 发卡节点, 工作流自动建群编排]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "节点 writeback 单一入口：仅调 WorkItemService.awriteback_feishu_chat_id（函数级 import 避循环依赖），禁直接写表（INV-6/P-6）"
    - "fail-soft 两类分开：建群失败（缺参/FeishuIMError）→ failed+error handle；writeback 失败（不存在/DB 异常）→ 节点仍 completed 返回 chat_id（try/except Exception + log.warning，绝不冒泡）"
    - "member_ids 三形态解析镜像 normalize_repositories：模板 get_template_value 保留 list / JSON 列表 / 逗号分隔，逐项 strip 去空"

key-files:
  created: []
  modified:
    - server/workflows/nodes/integrations/feishu_chat.py
    - server/tests/workflows/test_chat_nodes.py

key-decisions:
  - "建群失败走 error handle、writeback 失败节点仍 completed（D-7 两类边界分开），缺群名或缺成员均判 failed（建群+拉人核心，空成员无意义）"
  - "writeback 仅当 project_key + work_item_id 均非空才触发；work_item_id int() 转换失败 → warning 跳过（attempted=False），不掀翻建群成功（P-11）"
  - "writeback 测试 patch 源模块类属性 delivery.services.work_item_service.WorkItemService.awriteback_feishu_chat_id（节点函数级 import，mock 才生效，NOTE-3）"
  - "owner_id 输出用 data.get('owner_id','') 容错空串（owner 为 bot 时飞书不返回，P-3）"

patterns-established:
  - "工作流集成节点可选 writeback：仅经 service 单一入口 + fail-soft（异常 swallow + warning），主产物（chat_id）绝不因副作用失败而丢失"

requirements-completed: [GROUP-01]

# Metrics
duration: 5 min
completed: 2026-06-17
---

# Phase 59 Plan 02: CreateGroupChatNode 节点接线 Summary

**CreateGroupChatNode（@register_node 自动注册 create_group_chat）：经 FeishuIMService.create_chat 建群即拉人，输出 chat_id 一等字段供下游，member_ids 三形态解析 + 可选 writeback fail-soft（仅经 WorkItemService.awriteback_feishu_chat_id 单一入口，异常不冒泡）**

## Performance

- **Duration:** 5 min
- **Started:** 2026-06-17T13:22:02Z
- **Completed:** 2026-06-17T13:25:42Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments
- `CreateGroupChatNode`（`@register_node`，`node_type="create_group_chat"`，`NodeCategory.INTEGRATION`，`execution_mode="server_local"`）：镜像 `FetchGroupChatNode`/`JoinGroupChatNode` 结构，全中文 `display_name="创建群聊"` + `config_schema` title/description；`inputs=[default]`、`outputs=[default(成功), error(失败)]`。
- 建群即拉人单步经 `FeishuIMService.create(project).create_chat(name, user_id_list=member_ids, owner_id=, description=, user_id_type=)`；缺群名 **或** 缺成员 → `failed`+`error` handle；`create_chat` 抛 `FeishuIMError` → `failed`+`error` handle（D-7 建群失败）。
- `chat_id` 作 output 一等字段（`output={"chat_id","chat_name","owner_id"(容错空串),"source":"create_group_chat","writeback":{"attempted","success"}}`）供下游 `JoinGroupChatNode`/发卡节点消费（D-8）。
- 模块级 `_parse_id_list(value, context)` 解析 member_ids 三形态：模板 `{{...}}` → `get_template_value`（保留 list）/ JSON 列表 `["a","b"]`（兼容单引号）/ 逗号分隔 `"a, b"` / 上游注入 list，逐项 `str` 化 `strip` 去空。
- 可选 writeback（D-7 fail-soft）：仅当 `project_key`+`work_item_id` 均非空才执行；`int()` 失败 → warning 跳过（attempted=False）；`WorkItemService().awriteback_feishu_chat_id(...)` 经 `try/except Exception`+`log.warning` 包裹，DB 异常/返回 False 节点**仍 completed** 返回 chat_id，绝不冒泡（P-6 INV-6 单一入口，节点无直接写表）。
- 扩展 `test_chat_nodes.py` 新增 14 例（happy + member_ids 三形态 + 缺群名 + 缺成员 + 建群失败 + writeback happy/fail-soft/不存在/未配 + 自动注册断言）；全套 34 passed（含既有 Fetch/Join/Question 零回归）。

## Task Commits

1. **Task 1: CreateGroupChatNode + member_ids 三形态 + writeback fail-soft + 集成测** - `c37da3b02` (feat)

**Plan metadata:** docs(59-02) commit（含 SUMMARY + STATE + ROADMAP）

## Files Created/Modified
- `server/workflows/nodes/integrations/feishu_chat.py` - 新增 `CreateGroupChatNode` + 模块级 `_parse_id_list`，顶部 import 增 `FeishuIMError`（纯新增，既有两节点逐字不变）
- `server/tests/workflows/test_chat_nodes.py` - 新增 CreateGroupChatNode 测试段（14 例）+ import `CreateGroupChatNode`/`FeishuIMError` + helper `_make_create_context`/`_mock_create_im_service`

## Decisions Made
- 建群失败 vs writeback 失败两类边界分开（D-7）：前者 `failed`+error handle，后者节点仍 `completed`。
- writeback 触发条件 `project_key`+`work_item_id` 均非空；`int()` 转换失败 warning 跳过不阻断建群（P-11）。
- writeback 测试 patch 源模块类属性 `delivery.services.work_item_service.WorkItemService.awriteback_feishu_chat_id`（节点内函数级 import，patch feishu_chat 模块不生效，NOTE-3）。
- `owner_id` 输出 `data.get("owner_id","")` 容错（bot 为群主时飞书不返回 owner_id，P-3）。

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- GROUP-01 全部 Success Criteria 兑现：SC-1（建群+拉人）、SC-2（chat_id 节点输出供下游）、SC-3（可选 writeback + fail-soft）。
- Phase 59 完成（2/2 plans）；v0.11.0 里程碑 4 phases 全部 Complete，可进 `/gsd-complete-milestone` / `/gsd-verify-work 59`。
- 零回归：`FetchGroupChatNode`/`JoinGroupChatNode` 符号逐字不变（git diff 仅 import 行扩展 `FeishuIMError`）；节点无直接写表（INV-6/P-6 grep 干净）。

## Self-Check: PASSED
- `cd server && uv run ruff check workflows/nodes/integrations/feishu_chat.py tests/workflows/test_chat_nodes.py` → All checks passed。
- `cd server && uv run pytest tests/workflows/test_chat_nodes.py tests/delivery/test_inv6_guard.py -q` → 34 passed。
- `cd server && uv run pytest tests/services/test_feishu_im.py tests/workflows/test_chat_nodes.py tests/delivery/test_work_item_writeback.py tests/delivery/test_inv6_guard.py -q` → 60 passed（Wave 1+2 零回归）。
- 源断言：含 `class CreateGroupChatNode` + `node_type = "create_group_chat"` + `@register_node`；含 `from services.feishu_im import FeishuIMError, FeishuIMService`；含 `awriteback_feishu_chat_id` 调用；**无** `WorkItem.objects`/`.save(`（INV-6/P-6）。
- 自动注册：`NodeRegistry.get("create_group_chat") is CreateGroupChatNode` 断言通过。
- 零回归：`FetchGroupChatNode`/`JoinGroupChatNode` 主体 git diff 无删除/修改行（仅 import 行扩展）。

---
*Phase: 59-workflow-create-group-node*
*Completed: 2026-06-17*
