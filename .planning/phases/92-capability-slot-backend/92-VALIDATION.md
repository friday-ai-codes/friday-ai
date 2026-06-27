---
phase: 92
slug: capability-slot-backend
nyquist_compliant: true
test_framework: "pytest 9.x + pytest-django 4.8 + pytest-asyncio（server）; vitest（web fixture 守护）"
quick_run: "cd server && uv run pytest tests/workflows/test_graph_validator.py tests/workflows/test_plan_research_node.py -x -q"
full_suite: "cd server && uv run pytest tests/workflows tests/feishu tests/delivery -q && cd web && pnpm vitest run node-sync"
---

# Phase 92 Nyquist Validation — 插槽系统（后端）

测试栈：pytest + fixture 守护（node-sync）+ node-sync.test.ts。本 phase **无 DB 迁移**，`makemigrations --check` 须保持干净。

## Per-Task Nyquist Map

| Plan-Task | Requirement | Behavior | Test Type | Automated Command | Test File（状态） |
|-----------|-------------|----------|-----------|-------------------|------------------|
| 92-01 T1 | SLOT-01 | NodePort.shape 默认空可省略构造 + get_schema inputs/outputs 含 shape 键 + KNOWN_PORT_SHAPES 7 值 | unit | `cd server && uv run pytest tests/workflows/test_node_schema.py -x -q` | `tests/workflows/test_node_schema.py`（Wave 0 新建） |
| 92-01 T2 | SLOT-01 | 双端契约不等→incompatible_port_shape error | unit（纯函数零 DB） | `cd server && uv run pytest tests/workflows/test_graph_validator.py -k shape -x -q` | `tests/workflows/test_graph_validator.py`（扩展） |
| 92-01 T2 | SLOT-01 | 任一端空/default/handle 非法→放行（既有图零回归） | unit | `cd server && uv run pytest tests/workflows/test_graph_validator.py -x -q` | `tests/workflows/test_graph_validator.py`（既有合法图用例兜底 + 新增空契约通配/default/handle 非法用例） |
| 92-02 T1 | SLOT-02 | ai_plan_research 含 clarify(out, clarification_request)/resume(in, clarification_answer) + default/error 保留（default shape 空） | unit | `cd server && uv run pytest tests/workflows/test_plan_research_node.py -k port -x -q` | `tests/workflows/test_plan_research_node.py`（扩展，12 测零回归） |
| 92-02 T2 | SLOT-02 | build_clarification_card action 默认 plan_clarify_answer（91 零回归）/ 传 clarify_card_answer 切换 | unit | `cd server && uv run pytest tests/feishu/test_chat_question_card.py -x -q` | `tests/feishu/test_chat_question_card.py`（扩展） |
| 92-03 T1 | SLOT-02 | clarification_card 注册 + 端口 shape 经 get_schema + 发卡 best-effort + ClarifyCardCallback 订阅 + waiting_event + 缺内容→failed/error | unit/integration | `cd server && uv run pytest tests/workflows/test_clarification_card_node.py -x -q` | `tests/workflows/test_clarification_card_node.py`（Wave 0 新建） |
| 92-03 T2 | SLOT-02 | clarify_card_ 回调据 execution_id/node_id 定位本节点 + 幂等门 + answer_round 落库（INV-6）/ 透传 + approve 本节点 + fail-soft 脱敏 | integration | `cd server && uv run pytest tests/feishu/test_clarify_card_callback.py -x -q` | `tests/feishu/test_clarify_card_callback.py`（Wave 0 新建） |
| 92-03 T3 | SLOT-02 | fixture node_count 36→37 含 clarification_card + ai_plan_research 端口名同步；node-sync 绿 | drift guard | `cd web && pnpm vitest run node-sync` | `web/src/components/__tests__/node-sync.test.ts`（既有，fixture 重生成） |

## Sampling Rate

- **Per task commit:** `cd server && uv run pytest tests/workflows/test_graph_validator.py tests/workflows/test_plan_research_node.py -x -q`
- **Per wave merge:** `cd server && uv run pytest tests/workflows tests/feishu -q`
- **Phase gate:** 全量 green + `ruff format --check` + `ruff check` + `mypy` + `makemigrations --check`（无迁移，须干净）+ `pnpm -C web vitest run node-sync`（动 fixture）。

## Wave 0 Gaps（执行各 wave 时先建测试骨架）

- [ ] `tests/workflows/test_node_schema.py`（92-01）— NodePort.shape 默认/赋值、get_schema shape 键、KNOWN_PORT_SHAPES 成员。
- [ ] `tests/workflows/test_graph_validator.py` 扩 shape 用例（92-01）— 不兼容报错 / 空契约通配 / default 通配 / handle 非法不重复报 / message 不回显 config。
- [ ] `tests/workflows/test_plan_research_node.py` 扩端口用例（92-02）— clarify/resume 存在 + shape + default/error 零回归（既有 12 测）。
- [ ] `tests/feishu/test_chat_question_card.py` 扩 action 用例（92-02）— 默认 plan_clarify_answer / 自定义 clarify_card_answer / 并列 id 字段。
- [ ] `tests/workflows/test_clarification_card_node.py`（92-03）— 注册/端口 shape/发卡 waiting_event/raw 透传/发卡失败 best-effort/缺内容 failed。
- [ ] `tests/feishu/test_clarify_card_callback.py`（92-03）— 前缀注册/ack·缺 id no-op/_build_answers 映射/后台 answer_round+approve 本节点/非 waiting 幂等/fail-soft/transient 无 clarification_id。

## Notes

- 92-01 validator 为高频纯函数：禁 INFO 刷屏（不打日志），零 ORM 可单测。
- 92-03 节点/回调发卡走既有 FeishuIMService 凭证链 + respx/mock 覆盖，无需真实飞书；INV-6 落库经 answer_round（grep 守护子模型）。
- 本 phase 无外部包安装（RESEARCH §Package Legitimacy Audit N/A），无 DB 迁移。
