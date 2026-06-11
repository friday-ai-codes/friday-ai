---
phase: 13-ingest
plan: 13-03
status: complete
subsystem: knowledge
requirements_addressed: [INGEST-03, INGEST-05]
tags: [normalizer, triggers, wiring, exception-isolation, has-plan-edge]
dependency_graph:
  requires:
    - server/knowledge/ingestion.py (IngestionRequest/IngestionEvent/EdgeSpec/aschedule_ingestion——13-02 产物)
    - server/knowledge/sources/__init__.py (惰性注册表，coding_plan/mcp_technical_plan 路径已登记)
    - server/knowledge/models.py (generate_entity_id natural key 规则表、EntityKind/EntityOrigin/EdgeRelation)
    - server/chat/models.py + server/mcp_tools/models.py (取材字段源)
  provides:
    - "knowledge/sources/coding_plan.py::normalize：CodingPlan → 单 tech_plan 事件（content=title+\\n\\n+tech_plan，OQ-3 锁定；零边、零对话原文接触面）"
    - "knowledge/sources/mcp_plan.py::normalize：McpWorkItemTechnicalPlan → [work_item 锚, tech_plan] 双事件 + HAS_PLAN exclusive EdgeSpec（target id 经 generate_entity_id 唯一入口）"
    - "5 处触发接线（chat ×3 / MCP ×2）：每处函数内 lazy import + 只组装 ID 投递，零取材逻辑"
    - "tests/knowledge/test_triggers.py：TestNormalizers/TestChatTriggers/TestMcpTriggers/TestExceptionIsolation 13 用例"
  affects:
    - 13-04（reconcile 对账消费本 plan 产生的实体/版本/边）
    - Phase 14（新触发点复制本接线模板 + 新增 normalizer 一行注册）
tech_stack:
  added: []
  patterns:
    - "触发接线统一形态：`from knowledge import ingestion`（函数内 lazy import 防循环）+ `await ingestion.aschedule_ingestion(ingestion.IngestionRequest(...))`——模块属性调用时解析，测试可 monkeypatch 模块属性拦截全部锚点"
    - "normalizer 统一签名 async def normalize(request) -> list[IngestionEvent]，后台按 source_id select_related 重读源模型，源缺失返回空列表 + warning 不 raise"
key_files:
  created:
    - server/knowledge/sources/coding_plan.py
    - server/knowledge/sources/mcp_plan.py
    - server/tests/knowledge/test_triggers.py
  modified:
    - server/chat/models.py
    - server/chat/coding_session_service.py
    - server/mcp_tools/technical_plan_service.py
    - server/mcp_tools/work_item_execution_service.py
decisions:
  - "接线 import 形态取 `from knowledge import ingestion` 模块整体引入（非 from-import 符号）：满足验收 grep 计数（models.py==2、其余各==1），且属性调用时解析使测试 monkeypatch 全锚点生效"
  - "OQ-3（规划定案落地）：chat content = title+\\n\\n+tech_plan，零 conversation 内容接触面；不为 chat 创建 work_item 实体"
  - "OQ-4（规划定案落地）：chat 触发编码挂 create_sessions_for_plan 成功尾部（result.created 非空），CodingSessionConfirmView 不挂"
  - "mcp work_item 锚 source_id 取 artifact 上的三元组冗余字段（与 context 同值），content 为轻量锚 name+description——Phase 14 INGEST-04 同 key 重摄为全量快照"
metrics:
  duration: ~16min
  tasks: 3
  files: 7
  completed: 2026-06-11
---

# Phase 13 Plan 03: 触发点接线与 source normalizer Summary

两个 source normalizer（chat CodingPlan / MCP 技术方案双事件 + HAS_PLAN exclusive 边）+ 5 锚点只接线不写逻辑的触发（chat 产出/修改/触发编码 ×3、MCP 产出/执行 ×2），INGEST-03/05 端到端打通——知识摄取成为业务流程自动副产品，"对话原文不入图"（T-13-01）在 normalizer 层以特征串断言钉死。

## 任务执行情况

| Task | 内容 | Commits |
|------|------|---------|
| 1 | coding_plan / mcp_plan normalizer + TestNormalizers 四用例 | c30790c5 (RED), 189b433f (GREEN) |
| 2 | 5 锚点接线（chat ×3 + MCP ×2，每处 lazy import + 投递） | 8b678dc7 |
| 3 | test_triggers.py 扩展：投递断言 ×6 + 异常隔离 ×3 | 7f155689 |

## 验收对照（must_haves truths）

- ✅ chat 三动作（创建 plan / 更新 plan / 批量创建 session）各投递一次（TestChatTriggers 三元组逐字段断言）；命中去重（created=False）与 fan-out 全失败零投递
- ✅ MCP create_feishu_technical_plan 产出 artifact 后、execute_work_item_repo_tasks 成功返回时各投递一次（TestMcpTriggers）
- ✅ coding_plan normalizer content 仅 title+tech_plan：conversation 下注入特征串，断言 content/payload/title 零泄漏（T-13-01）
- ✅ mcp normalizer 产出 work_item 锚（三元组 source_id 与 natural key 规则表逐字一致）+ tech_plan + HAS_PLAN exclusive EdgeSpec（目标 id 经 generate_entity_id）
- ✅ 异常隔离：run_in_background 抛 RuntimeError 时 aget_or_create_for_conversation / build_work_item_technical_plan 主流程仍成功；注册体抛错 warning 记录不上抛

验收 grep：`rg "conversation.messages|Message" sources/coding_plan.py` 零命中；`generate_entity_id` 在 mcp_plan.py 命中（4 处含 import/调用）；`aschedule_ingestion` 计数 models.py==2、coding_session_service.py / technical_plan_service.py / work_item_execution_service.py 各==1；chat/views.py 零命中（OQ-4 confirm 不挂）。

## OQ-2 副作用（规划定案要求必记）

CodingPlan 模型方法（`aget_or_create_for_conversation` / `aupdate_plan`）挂钩使历史迁移命令 `migrate_coding_sessions_to_plans` 在迁移历史 session 时**也会触发知识摄取**。规划定案为**不排除**：摄取幂等（hash 短路）保证无害，历史知识入图符合里程碑目标。`tests/test_migrate_coding_sessions_to_plans.py` 已验证零回归（迁移命令主流程不受影响）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - 验收冲突] 接线 import 形态从 from-import 改为模块引入**
- **Found during:** Task 2 验收
- **Issue:** 计划模板 `from knowledge.ingestion import IngestionRequest, aschedule_ingestion` 使 import 行也命中 grep，`rg -c "aschedule_ingestion"` 计数翻倍（models.py 得 4 ≠ 验收要求 2）
- **Fix:** 改为 `from knowledge import ingestion` + `ingestion.aschedule_ingestion(...)` 属性调用——grep 计数达标，lazy import 防循环语义不变，且属性调用时解析对测试 monkeypatch 更友好
- **Files modified:** 4 个接线文件
- **Commit:** 8b678dc7

**2. [Rule 3 - 格式] work_item_execution_service 接线行超 ruff 100 列**
- **Found during:** Task 2 验收
- **Issue:** `str(technical_plan.id)` 内联使 IngestionRequest 行 103 字符
- **Fix:** 提取 `plan_id` 局部变量（仍零取材逻辑）
- **Commit:** 8b678dc7

**3. [Rule 1 - 测试缺 mock] mcp_tasks_executed 用例补 `_execution_results_markdown` mock**
- **Found during:** Task 3
- **Issue:** 最小依赖 mock 漏了 markdown 渲染函数，SimpleNamespace fake task 缺 repository 属性报 AttributeError
- **Fix:** 增加 `monkeypatch.setattr(wie, "_execution_results_markdown", ...)`（计划明示允许最小依赖 mock，断言点不变）
- **Commit:** 7f155689

其余按计划逐字执行。

## 实现要点

- **接线总量**：5 锚点共 27 行插入（含 5 空行，逻辑行 22 ≤ 25 上限），每处零取材/组装逻辑；`aschedule_ingestion` 自身全吞异常（13-02 契约），接线处不包 try/except。
- **mcp 双事件顺序**：work_item 锚在前（与 PLAN 行为断言一致）；context 为 None 的防御分支只产出 tech_plan 单事件 + warning（FK 语义下不应发生）。
- **chat title 兜底**：plan.title 为空时取 tech_plan 首行截断 200 字符作为事件 title；content 拼法仍按 OQ-3 锁定（plan.title 原值参与拼接）。
- **宿主文件既有格式漂移**：4 个接线文件存在与本 plan 无关的 ruff format 漂移（如 coding_session_service.py 多处折行风格），按 scope boundary 未触碰——本 plan 插入行已验证 format-clean。

## Known Stubs

None — 两 normalizer、5 接线、13 测试用例全部真实实现，无占位数据流。

## Threat Flags

None — 未新增计划 threat_model 之外的安全面：T-13-01（content 取材边界 + 特征串断言）/ T-13-03（异常隔离三用例）/ T-13-02（project_id 取材断言）/ T-13-04（边只产出声明式 EdgeSpec）均按计划 mitigate。

## 验证结果

- `uv run pytest tests/knowledge/ tests/test_coding_tools.py tests/mcp_tools/ -x` → 178 passed（宿主套件零回归）
- 加测 `tests/test_coding_session_service.py tests/test_migrate_coding_sessions_to_plans.py` → 23 passed（OQ-2 副作用路径零回归）
- `-k chat` 7 passed / `-k mcp` 4 passed（13-VALIDATION 命令映射成立）
- `ruff check` 全部通过；新建文件 `ruff format --check` 通过

## Self-Check: PASSED

- 3 个产物文件全部存在（sources/coding_plan.py / sources/mcp_plan.py / tests/knowledge/test_triggers.py）
- 4 个 commit（c30790c5, 189b433f, 8b678dc7, 7f155689）全部在 git log 中
- tests/knowledge/ + tests/test_coding_tools.py + tests/mcp_tools/ → 178 passed
