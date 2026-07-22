---
phase: 100-learning-case-mcp
plan: 04
status: complete
date: 2026-07-15
---

# Phase 100 Plan 04: search_learning_cases 向量切换 + backfill + golden set 验收门 Summary

**一句话**：`search_learning_cases` 底层从 token 打分切换为 `DeliveryKnowledgeSearchService.search_similar(entity_kinds=["learning_case"])`（对外契约不变、token 实现零残留、hint 变实、Qdrant fail-soft）+ `backfill_learning_cases` 存量回填命令（三件套 P1 防线闭环）+ golden set 三形态查询对照测试（KNOW-02 验收门）与 RetrievalTrace/指标观测断言。

## What Was Built

### Task 1: search_learning_cases 向量切换 + token 退役 + fail-soft

- `server/mcp_tools/learning_case_service.py`
  - 签名新增关键字参数 `user`（检索权限主体，`search_similar` fail-closed 需要）；`views.py SearchLearningCasesView` 调用点补 `user=request.user`。
  - 查询增强：query + work_item_type + repo/file/symbol hints 拼入查询文本（空段过滤）；拼装后为空直接返回 `[]`（向量检索无「无查询返回最新」语义，schema 描述已注明）。
  - 检索：`search_similar(query_text, user=user, top_k=max(limit*3, 10), entity_kinds=["learning_case"])`（超采样供 rerank/行过滤余量；kind 真过滤由 100-01 保证）。
  - 回捞：命中实体 `source_id`（McpLearningCase UUID str）一次批量 async 查询建 dict；实体命中但行已删跳过（弱引用语义）；`work_item_type` 非空按行字段 post-filter。
  - 结果层 rerank：排序键 = `dto.score + bonus`（repo/file/symbol hint 命中各 +0.05/条，子串不区分大小写，沿用旧匹配语义）；**payload `score` = 原始 `dto.score`（向量融合分 0-1 浮点，locked 定版），bonus 只影响排序**。
  - 渲染：rerank 后前 `limit` 条经 `learning_case_payload(case, score=dto.score)`——payload 外形函数一字未改。
  - fail-soft：整段检索+回捞+渲染包 `try/except Exception` → `learning_case_search_failed` warning（`redact_secrets_in_text` 脱敏）+ 返回 `[]`（Qdrant/embedding 不可用不 500）。
  - token 退役：`_TOKEN_RE`/`_tokens`/旧循环实现删除，`rg "_tokens|_TOKEN_RE"` 零命中，**无任何 fallback 开关**；模块 docstring 更新为中文并注明 v0.17.0 起底层为统一向量检索（KNOW-02）。
  - 观测：`learning_case_search_started/completed` 结构化事件（query_len/hint 计数/result_count/duration_ms，component=mcp_tools，category=caller）；检索内部沿用 knowledge 域既有 sampling 事件，不新增刷屏点。
- `server/mcp_tools/serializers.py`
  - `SearchLearningCasesRequestSerializer` 类 docstring + `query` 字段 `help_text` 定版（中文）：向量排序 / score 语义变更（token 计数 → 向量融合分 0-1）/ hints 参与查询增强与提权。**TOOL_SCHEMA_SNAPSHOT 键集与序列化字段名逐字未动**（快照测试守门通过）。

### Task 2: backfill_learning_cases 管理命令

- `server/knowledge/management/commands/backfill_learning_cases.py`（rebuild_project_context 范式，中文 docstring 说明三件套闭环/幂等/绝不删库与「切换当天检索全空」防线定位）
  - `_backfill()` 四段 async 遍历（`aiterator`）：McpLearningCase→`learning_case`、McpCodingPlan→`mcp_coding_plan`、McpRepositoryAnalysis→`mcp_repository_analysis`、McpCodingExecutionTrace→`mcp_execution_trace`，各自 `aschedule_ingestion(trigger="backfill_learning_cases")`（不传 initiated_by_user_id——命令行无触发用户记 system），返回按 source_kind 计数 dict。
  - `Command.handle`：`asyncio.run` + `backfill_learning_cases_started/completed` 结构化事件（按类 scheduled 计数 + duration_ms + component=knowledge + category=caller）+ stdout SUCCESS 摘要；每 100 条 stdout 进度一行（Claude's Discretion）。
  - `--only`（choices=四类，`action="append"` 可重复），缺省全量四类。
- `server/tests/knowledge/test_backfill_learning_cases.py`（5 用例）：四类计数与 source_id/trigger 逐条断言、`--only` 单类过滤、`--only` 重复传入、两次执行投递集合相同（命令层幂等——内容幂等由 ingest hash 短路兜底，100-02/03 已断言）、源码不含整库删除入口静态守护。

### Task 3: golden set 验收门 + 契约/fail-soft/RetrievalTrace 断言

- `server/tests/mcp_tools/test_learning_cases.py` 全量改写（6 用例）
  - **测试基建 `golden_vector_stack`**：monkeypatch `QdrantService.get_client` → `QdrantClient(":memory:")` 内嵌实例（零网络，pytest-socket 安全）；确定性假 embedding——bag-of-words dense（token md5 稳定 hash 到 `DEFAULT_EMBEDDING_DIMENSION`=1024 维 + L2 归一化，ASCII 词/路径整 token、中文逐字）+ token-hash sparse；`knowledge.ingestion.run_in_background` no-op（transaction=True 下 on_commit 真触发，测试内显式 `ingest()` 同步补摄避免竞态）。摄取走真实 `ingest()` 全链路（PG 实体/版本 + 内存 Qdrant hybrid 向量点，`ensure_delivery_knowledge_collection` 真建集合）。
  - **golden set（KNOW-02 验收门）**：5 条内容判然不同的 case（登录超时/支付回调重试/前端构建/慢查询/推送丢失，top-3 断言有区分度）经 mcp_client 走 HTTP：
    - 中文问题描述（"登录超时 token 刷新"）→ results 非空 + 目标 case top-3；
    - 路径类（file_hints=["src/auth/session.py"] + 泛化 query）→ 目标 top-3 且有 hint 排名 ≤ 无 hint 排名（增强+提权生效）；
    - symbol 类（symbol_hints=["retry_callback"]）→ 同上；
    - payload 键集 == `learning_case_payload` 全 18 键（case_id/.../reuse_judgement/created_at/score），score 为 0-1 浮点；
    - **criterion 1 双入口收口**：同一 query 经 `search_delivery_knowledge`（entity_kinds=["learning_case"]）同样召回同一 case。
  - **既有用例适配**：create→search 用例挂 golden_vector_stack + `project_memberships`（PAT user 权限闸），HTTP 创建后显式 `ingest()` 同步补摄，`score > 0` 断言保留；方案自动召回用例同样补摄后跑绿。
  - **fail-soft 用例**：monkeypatch `search_similar` 抛 RuntimeError → HTTP 200 + `results == []` + `total == 0`。
  - **观测断言（criterion 5，MCP 链）**：每条命中一行 FILE `RetrievalTrace`（payload 含 source="learning_case"/case_id/score）；`ToolCallRecord.duration_ms` 非负；`RequestMetric`（route="mcp:search_learning_cases"）经 `metric_sink.flush_now()` 落库后存在且 duration_ms 非负。Chat 链本 phase 只需 service 层可复用——`search_learning_cases(user=...)` 纯 service 签名已满足（白名单接入是 Phase 102 KNOW-05，不做）。

## Deviations from Plan

1. **[Rule 3 - 阻塞随修] technical_plan_service.py 第二调用点补 `user=actor`**
   - **发现于**：Task 1（签名新增 `user` 后 grep 全仓调用点）
   - **问题**：plan 只列出 views.py 调用点，但 `build_work_item_technical_plan`（方案生成自动召回相似案例）也调用 `search_learning_cases`，签名变更后会 TypeError。
   - **修复**：传 `user=actor`（发起编排的用户，view 已透传 request.user；None 时 search_similar fail-closed 空召回，与该函数既有 T-94-03-ELEV 文档化降级语义一致）。
   - **文件**：`server/mcp_tools/technical_plan_service.py`；**Commit**：`a383d198`
2. **[计划偏差] 既有用例二（方案自动召回）非零改动**
   - plan 预期"第二用例零改动预期，跑绿确认"，但该用例依赖自动召回命中——向量路径下必须先把创建的 case 入图（vector store）且 PAT user 具备项目 membership。适配：挂 golden_vector_stack + project_memberships + 显式 `ingest()` 补摄。断言本体（evidence 含 learning_case 源 + title 匹配）未变。
3. **[验证口径] Task 1 verify 命令的短路缺陷按 plan-checker 提示规避**：不使用原 verify 的 `&& rg ...; test $? -eq 1` 链（pytest 失败可能被误读为通过），改为分别独立运行 pytest（检查真实退出码 0）与 rg（确认零命中）。

## Verification Evidence

- Task 1 verify：`tests/mcp_tools/test_schema_snapshot.py` → `1 passed`（exit 0）；`rg "_TOKEN_RE|def _tokens|_tokens" server/mcp_tools/learning_case_service.py` 零命中。
- Task 2 verify：`tests/knowledge/test_backfill_learning_cases.py` → `5 passed`（exit 0）。
- Task 3 verify：`tests/mcp_tools/test_learning_cases.py tests/mcp_tools/test_retrieval_trace.py tests/mcp_tools/test_schema_snapshot.py` → `9 passed`（exit 0）。
- 整体验证（plan `<verification>`）：`uv run pytest tests/mcp_tools/ tests/knowledge/ -q` →

  ```text
  ==== 3 failed, 559 passed, 1 deselected, 181 warnings in 103.31s (0:01:43) =====
  ```

  3 个失败全部为 `tests/knowledge/test_triggers.py::TestWorkflowTriggers::test_workflow_plan_generation_*` 的**已知预存腐烂失败**（`ModuleNotFoundError: No module named 'workflows.nodes.ai.plan_generation'`，模块已删除，与本 plan 零关联；orchestrator 已列为忽略项）。
- criterion 1 双入口召回断言（golden 中文用例内 `search_delivery_knowledge` 交叉断言）通过。
- `uv run ruff check` + `ruff format` 全部触及文件干净（serializers.py 仅局部编辑，避免全文件 format 漂移污染 diff）。

## Commits

| Commit | 说明 |
| --- | --- |
| `cf92605d` | feat(100-04): search_learning_cases 切换统一向量检索并退役 token 打分（KNOW-02） |
| `8062da30` | feat(100-04): backfill_learning_cases 存量回填命令（三件套闭环 P1 防线） |
| `a383d198` | test(100-04): golden set 验收门 + 契约/fail-soft/RetrievalTrace 断言（KNOW-02） |

## Known Stubs

无。token 实现完全退役（无 fallback 开关）；hint 参数真实参与查询增强与提权；Chat 链白名单接入按 phase 边界留给 Phase 102（KNOW-05），service 层签名已就绪。

## Threat Flags

无新增安全面：T-100-09（越权）已 mitigate——检索经 `search_similar(user=request.user)` fail-closed，回捞按命中实体 source_id 收口不放大行集（technical_plan_service 自动召回同样传 actor）；T-100-10（信息泄露）已 mitigate——fail-soft 异常文本经 `redact_secrets_in_text` 后才入日志；T-100-11（超采样 DoS）accept——limit 序列化层已限 ≤20，3 倍放大仍个位数十位开销；T-100-SC accept——零新依赖（qdrant-client `:memory:` 为既有依赖内嵌模式，仅测试用）。

## Self-Check: PASSED

- `server/mcp_tools/learning_case_service.py`（contains `DeliveryKnowledgeSearchService`，token 零残留） — FOUND
- `server/knowledge/management/commands/backfill_learning_cases.py` — FOUND
- `server/tests/knowledge/test_backfill_learning_cases.py` — FOUND
- `server/tests/mcp_tools/test_learning_cases.py`（golden set + 契约/fail-soft/trace 断言） — FOUND
- Commit `cf92605d` / `8062da30` / `a383d198` — FOUND
