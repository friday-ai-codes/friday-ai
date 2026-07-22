---
phase: 104-tool-surface-closure
plan: 03
subsystem: tests
tags: [e2e, milestone-acceptance, learning-case, vector-search, unify]
requires:
  - "104-02: 删缝完成（planning_service.py 退役 + 残留清零）——E2E 在收口后最终代码上运行"
  - "Phase 102: Chat 工具 search_learning_cases + 编排召回默认 kinds 含 learning_case"
  - "Phase 100: MCP search_learning_cases 向量版 + learning_case 入图通路"
  - "Phase 103: 容器知识 MCP 链（task 侧 handler + X-Friday-Session-Id 关联）"
provides:
  - "server/tests/test_milestone_e2e_learning_case.py：里程碑四面检索端到端验收测试（内存 Qdrant + 确定性 embedding，自包含）"
  - "统一排序外部可观察证明：MCP 与 Chat 两面 top-1 case_id 一致断言"
  - "容器链同 URL 契约断言（reverse 反查）+ 组合覆盖逻辑文档化"
affects:
  - "v0.17.0 里程碑验收门：后续任何检索面回归都会在此测试上显形"
tech-stack:
  added: []
  patterns:
    - "里程碑验收测试自包含：golden_vector_stack / mcp_client 本地复刻，不跨测试模块 import"
    - "双种子区分度设计：强相关 + 弱相关 case 并存，top-1 断言防「返回任意结果即过」（T-104-07）"
    - "generate_entity_id 唯一派生入口反推编排召回命中的期望 entity_id（uuid5 稳定）"
key-files:
  created:
    - server/tests/test_milestone_e2e_learning_case.py
  modified: []
decisions:
  - "统一排序断言的 entity 标识以 MCP 面返回的 case_id 为准（Chat 面同 payload 外形，两面同经 learning_case_service → DeliveryKnowledgeSearchService）"
  - "四面同一 actor：PAT 归属 user == Chat 会话 owner == ConvergenceSession.created_by，保证权限 scope 一致、排序可比"
  - "sync 测试内经 async_to_sync 调 Chat 工具与 recall adapter（test_learning_cases.py ingest 同款范式），避免同文件混跑 async/sync 模式"
  - "task 侧测试组件不新建：容器链取组合覆盖（per plan/CONTEXT locked），既有 task/tests/test_knowledge_tools.py 半边 + 本文件服务端半边 + 同 URL 胶合断言"
metrics:
  duration: "~12min"
  completed: "2026-07-22"
  tasks: 2
  commits: 2
---

# Phase 104 Plan 03: 里程碑四面检索端到端验收 Summary

**One-liner:** 新建自包含 E2E 验收测试（内存 Qdrant + 确定性 bag-of-words embedding + 双种子区分度），断言同一条 learning case 在 Chat 工具 / 编排召回 / MCP view / 容器链（同 URL 契约 + 组合覆盖）四处均可检索，且 MCP 与 Chat top-1 case_id 一致（统一排序来自同一 DeliveryKnowledgeSearchService）——v0.17.0 里程碑验收门就位。

## Task 1: 测试基建 + 种子 + Chat/MCP 两面断言 + 统一排序（commit a35d74e7）

- 新建 `server/tests/test_milestone_e2e_learning_case.py`（最终 367 行 > min 150）：
  - **自包含基建**：本地复刻 `_bow_dense`/`_bow_sparse` + `golden_vector_stack`（`QdrantClient(":memory:")` monkeypatch `QdrantService.get_client`、确定性假 dense/sparse、`knowledge.ingestion.run_in_background` no-op）与 `mcp_client`（`make_access_token` PAT 铸造 + APIClient Bearer）。
  - **双种子**：强相关条（「登录超时 Bug 修复」，与查询共享「登录超时/token/刷新」token）+ 弱相关条（「支付回调重试风暴治理」，零共享 token），均走 create → 显式 `await ingest(...)` 真实全链路向量入库。
  - **面 3（MCP view）**：POST `/api/mcp/tools/search_learning_cases/` → 强相关条命中且 top-1（弱相关条不得抢位）。
  - **面 1（Chat 工具）**：`Conversation(created_by=user)` 权限前置 + `async_to_sync` 直调 `agents.tools.knowledge_read_tools.search_learning_cases` → 同一条 case 命中。
  - **统一排序断言（locked）**：MCP 面 top-1 case_id == Chat 面 top-1 case_id == 强相关条；docstring 写明该断言是「两面同经 DeliveryKnowledgeSearchService 排序」收口的外部可观察证明。
  - pytestmark `django_db(transaction=True)` + 显式补摄注释，DB 事务纪律对齐 test_learning_cases.py golden 用例。

## Task 2: 编排召回面 + 容器链同 URL 契约 + 组合覆盖文档化（commit 562f697c）

- **面 2（编排召回）**：`ConvergenceSession(stage_state={"decomposition": {"requirement_text": 查询}}, created_by=user)` → `DeliveryKnowledgeRecallAdapter().recall(session)` → 断言 `learning_case` 在返回 kinds 集合内、hits 含 kind=learning_case 且 entity_id 精确等于 `generate_entity_id("learning_case", "learning_case", str(case.id))`（uuid5 唯一派生入口反推，不靠 title 模糊匹配）。
- **面 4（容器链，组合覆盖 per locked 决策）**：
  - 胶合断言：`reverse("mcp-tool-search-learning-cases") == "/api/mcp/tools/search_learning_cases/"`——服务端挂载路径与 `task/core/knowledge_tools.py` 的字面 URL 拼接模板一致（reverse 反查而非硬编码复读，T-104-07）。
  - docstring 写明组合逻辑：task 侧 handler 契约测试（`task/tests/test_knowledge_tools.py` mock 端点模式）+ 本文件面 3 的服务端同 URL 真实检索行为 → 两半边组合即容器内代理可检索到同一条 case；服务端链路回归另见 `server/tests/mcp_tools/test_container_knowledge_chain.py`。
- **收尾回归（P6 收口顺序最后一步）**：E2E 在 104-01/02 删缝后的最终代码上运行，全绿。

## 测试结果

- `tests/test_milestone_e2e_learning_case.py`：**3 passed**（socket-disabled 隔离下，零外部 Qdrant/真实 embedding/网络）。
- 收尾定向回归 `tests/test_milestone_e2e_learning_case.py tests/mcp_tools/ tests/services/test_recall_adapter.py tests/agents/tools/test_knowledge_read_tools.py`：**216 passed，0 failed**。
- ruff check / format：通过。

## Deviations from Plan

None - plan executed exactly as written.

（注：任务执行顺序上把 Task 2 用例拆为独立 commit 以保持原子提交，文件与断言内容与 plan 完全一致；task 侧不新增任何测试文件，符合并行执行约束与 plan「组合覆盖」locked 决策。）

## 观测自检

- 纯测试交付，不改生产代码：无新增 LLM 调用点、无新增召回面、无新增请求入口、无新增队列/webhook。
- 被测链路的既有观测（RetrievalTrace / ToolCallRecord / RequestMetric）已由 Phase 100/102 测试覆盖，本文件不重复断言。

## Known Stubs

无。

## Threat Flags

无新增安全面（纯测试交付；T-104-07 mitigate 已由双种子区分度 + reverse 反查落实）。

## Self-Check: PASSED

- 文件存在：`server/tests/test_milestone_e2e_learning_case.py`（367 行，含 DeliveryKnowledgeRecallAdapter / knowledge_read_tools / search_learning_cases 关键 pattern）。
- 提交存在：a35d74e7 / 562f697c 均在 git log。
- 验证命令：单文件 3 passed；定向回归 216 passed。
