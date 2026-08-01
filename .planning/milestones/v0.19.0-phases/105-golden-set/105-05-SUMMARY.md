---
phase: 105-golden-set
plan: 05
subsystem: api
tags: [repo-routing, idempotency, cache, llm-decode, call-source, snapshot, pytest]

# Dependency graph
requires:
  - phase: 105-golden-set (plan 03)
    provides: "RepoRouterV2 确定性分级 + degraded 标志 + snapshot Stage 0 材料/versions（stage1 留位）"
provides:
  - "Stage 1 幂等三件套：输入哈希缓存（key = sha256(model_id ‖ PROMPT_TEMPLATE_VERSION ‖ canonical(stage0_input 含 query) ‖ decode_params ‖ index_version)，Django cache 存 parsed 排列，命中零 LLM 调用）+ LLM 只输出排列（禁数值分数，解析侧过滤 score 键）+ decode 全固定（temperature=0/top_p=1/seed=42）"
  - "build_chat_model 可选 temperature/top_p/seed 透传（默认 None 零回归面；seed 仅 OpenAI/Ollama，其他 provider debug 静默忽略）"
  - "Stage 1 ainvoke 统一包 use_call_source(CallSource.AUX_REPO_ROUTER) 作用域（router 内部包，消灭调用方遗漏）"
  - "snapshot.stage1 材料（redact_for_ledger 脱敏 prompt/response + model_id + prompt_hash + cache_hit）；versions 合成版本绑定四元组（weight_set_version + index_version + prompt_hash + model_id）；降级/失联路径写 skipped_reason"
  - "幂等行为守护 6 用例（双跑零调用 / 禁缓存同结果 / key 敏感性×2 / score 过滤 / 缓存异常不反噬）"
affects: [105-06, 105-07, phase-106, phase-107]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Stage 1 缓存 key 绑定索引版本（_index_version = 参与候选各仓 built_at 排序拼接 sha256，与 snapshot.versions 共用同一 helper）——重索引后 key 变化旧缓存自然失效，TTL 仅兜底"
    - "_stage1_llm_reasoning 返回 (candidates, stage1_meta) 二元组：snapshot 材料随返回值携带，router 保持无 session 依赖（105-07 由 _h_route 组 payload 落库）"
    - "缓存读写 best-effort：get/set 均 try/except 吞异常走直调，绝不反噬路由"

key-files:
  created:
    - server/tests/codegraph/test_repo_router_stage1_idempotency.py
  modified:
    - server/agents/llm_factory.py
    - server/tests/test_llm_factory.py
    - server/codegraph/services/repo_router_v2.py
    - server/friday/settings.py
    - .env.example

key-decisions:
  - "缓存 key 的 stage0_input 含 query 文本（计划文本只列候选材料）——同候选不同需求是不同 LLM 输入，不含 query 会跨需求碰撞返回错误排列（正确性要求，Rule 2）"
  - "seed 按 provider_type 门控（OPENAI_CHAT/OPENAI_RESPONSES/OLLAMA 透传；ANTHROPIC/GEMINI 构造无 seed 形参，不传 + llm_decode_param_ignored debug）——工厂实为统一 init_chat_model 分派而非计划假设的 per-provider 分支"
  - "temperature/top_p 注入点放在 thinking/reasoning 分派之前：Anthropic thinking 的 temperature=1 硬性要求与 o 系列的 temperature/top_p 剥除仍按既有约束优先生效"
  - "缓存命中路径 snapshot.stage1.response 为空串（缓存只存 parsed 排列不存原始响应文本），cache_hit=True 供回放侧区分"

patterns-established:
  - "PROMPT_TEMPLATE_VERSION 常量（stage1-permutation-v1）：prompt 文案任何变更必须递增，参与缓存 key 与 prompt_hash 版本绑定"
  - "_stage1_cache_key/_canonical_json/_index_version 三个可直接单测的确定性 helper（key 敏感性测试直接断言输出）"

requirements-completed: [ROUTE-09, RELY-04]

# Metrics
duration: 10min
completed: 2026-07-29
status: complete
---

# Phase 105 Plan 05: Stage 1 幂等三件套 Summary

**Stage 1 幂等由系统层保证：输入哈希缓存（key 绑定模型/模板版本/规范化输入含 query/decode 参数/索引版本，命中零 LLM 调用）+ LLM 只输出排列（禁数值分数、解析侧过滤 score 键）+ decode 全固定（temperature=0/top_p=1/seed=42 经 build_chat_model 新透传形参）；ainvoke 统一包 AUX_REPO_ROUTER call_source 作用域，snapshot 补齐脱敏 stage1 材料与版本绑定四元组；6 条幂等行为测试锁定 success criterion 3**

## Performance

- **Duration:** ~10 min
- **Completed:** 2026-07-29
- **Tasks:** 3
- **Files modified:** 6

## Accomplishments

- **输入哈希缓存（幂等主防线）**：`_stage1_cache_key` = sha256(model_id ‖ `PROMPT_TEMPLATE_VERSION` ‖ canonical_json(stage0_input) ‖ canonical_json(decode_params) ‖ index_version)，前缀 `repo_router_v2:stage1:`；Django cache（Redis/LocMem 双轨既有配置）存 parsed 排列；命中记 `repo_router_v2_stage1_cache_hit`（debug，sampling）跳过 LLM；读写 try/except 吞异常走直调
- **排列输出（幂等第二防线）**：system prompt 明确「不要输出任何数值分数字段（如 score / 浮点分值）——排序只用数组顺序表达」；解析侧对每项过滤 `score` 键（防模型不遵指令），候选分数一律来自 Stage 0 归一化分
- **decode 固定（第三道防线）**：`build_chat_model` 新增 `temperature/top_p/seed` 可选形参（默认 None 零回归面），Stage 1 以 `_STAGE1_DECODE_PARAMS = {temperature: 0.0, top_p: 1.0, seed: 42}` 调用且该 dict 参与缓存 key
- **call_source 统一作用域**：`ainvoke` 包进 `use_call_source(CallSource.AUX_REPO_ROUTER)`（router 内部统一包，RESEARCH §9 现状缺口消灭）
- **snapshot stage1 材料**：成功路径 `{prompt, response}`（均经 `interactions.redaction.redact_for_ledger` 脱敏，T-105-10 mitigation）+ `model_id` + `prompt_hash` + `cache_hit`；`versions` 补 prompt_hash/model_id 与 105-03 的 weight_set_version/index_version 合成完整四元组；use_llm=False / 失联 / provider_missing / unparsable / v1_fallback 各路径写 `skipped_reason`
- **索引版本口径统一**：`_index_version` helper（参与候选各仓 built_at 按 repo_id 排序拼接 sha256）从 `_build_snapshot` 抽出，snapshot.versions 与缓存 key 共用——重索引后 key 变化旧缓存自然失效；`REPO_ROUTER_STAGE1_CACHE_TTL_SECONDS`（默认 86400）仅兜底防无界增长
- 定向回归零破坏：`tests/codegraph/ + tests/test_llm_factory.py` 全量 259 passed / 20 skipped；105-03 的 10 条 degraded 测试零改动通过

## Task Commits

Each task was committed atomically:

1. **Task 1: build_chat_model 扩展 decode 参数透传** - `a230b4f2` (feat)
2. **Task 2: Stage 1 重写——排列输出 + 输入哈希缓存 + call_source + snapshot 材料** - `951d006f` (feat)
3. **Task 3: 幂等行为测试** - `3f57c2a4` (test)

## Files Created/Modified

- `server/agents/llm_factory.py` - `build_chat_model` 新增 temperature/top_p/seed 可选形参；seed 按 provider_type 门控（不支持记 `llm_decode_param_ignored` debug）；注入点在 thinking/reasoning 分派之前保持既有约束优先
- `server/tests/test_llm_factory.py` - 4 条透传用例（OpenAI 三参透传 / Ollama seed / 默认 None 无新键（monkeypatch init_chat_model 捕获 kwargs）/ Anthropic seed 被忽略）；既有 25 条零改动通过
- `server/codegraph/services/repo_router_v2.py` - `PROMPT_TEMPLATE_VERSION` / `_STAGE1_DECODE_PARAMS` / `_canonical_json` / `_stage1_cache_key` / `_index_version`；`_stage1_llm_reasoning` 改返回 `(candidates, stage1_meta)`；`_stage0_only_result`/`_build_snapshot` 接 stage1_meta；`_fallback_v1` snapshot 补 skipped_reason
- `server/friday/settings.py` + `.env.example` - `REPO_ROUTER_STAGE1_CACHE_TTL_SECONDS`（env.int，默认 86400，注释说明 key 已含 index_version）
- `server/tests/codegraph/test_repo_router_stage1_idempotency.py` - 幂等守护 6 用例（279 行 >= 80）

## Decisions Made

- **缓存 key 含 query**：stage0_input 结构为 `{"query", "candidates": [{repo_id, facets, hits[node_path/summary/sub_project]}]}`——计划文本仅列候选材料，但 query 是 LLM 输入的一部分，不入 key 会跨需求碰撞（Rule 2 正确性补充，见 Deviations）
- **seed 门控而非 per-provider 分支**：工厂实为统一 `init_chat_model` 分派（计划描述的「各 provider 分支」不存在）；seed 仅对 OPENAI_CHAT/OPENAI_RESPONSES/OLLAMA 注入，ANTHROPIC/GEMINI 构造无该形参会构造失败，故不传 + debug 忽略
- **缓存命中不发 stage1_completed 事件**：该事件语义是「LLM 调用完成」（含 duration_ms）；命中路径只发 `repo_router_v2_stage1_cache_hit` debug 事件，观测语义不混淆

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - 缺失关键正确性] 缓存 key 的 stage0_input 增加 query 文本**
- **Found during:** Task 2
- **Issue:** 计划将 stage0_input 定义为「候选材料（repo_id + 有序 hits 的 node_path/summary）」，未含 query；但 query 是 human message 的一部分——两个不同需求若命中同一批候选材料会共享 key，缓存返回错误排列
- **Fix:** stage0_input 结构含 `query` 字段（CONTEXT 锁定的「canonical_json(stage0_input)」语义即完整 LLM 输入的结构化源）
- **Files modified:** server/codegraph/services/repo_router_v2.py
- **Verification:** `test_cache_key_sensitive_to_stage0_input`（不同 query → 不同 key）
- **Committed in:** `951d006f`

**2. [Rule 1 - 计划前提校正] build_chat_model 无 per-provider 分支，seed 按 provider_type 门控**
- **Found during:** Task 1
- **Issue:** 计划文本假设「按既有 capabilities/kwargs 分派模式把非 None 值传给各 provider 构造（anthropic/openai/gemini/ollama 分支）」，实际工厂是统一 `init_chat_model(f"{prefix}:{model}", **kwargs)` 单点分派
- **Fix:** temperature/top_p 各家通用直接注入 kwargs；seed 按 `resolved.provider_type` 门控（OpenAI/Ollama 支持，Anthropic/Gemini 不传 + `llm_decode_param_ignored` debug）——语义与计划一致（不支持即静默忽略）
- **Files modified:** server/agents/llm_factory.py
- **Verification:** `test_seed_ignored_unsupported_provider`（Anthropic 构造 kwargs 无 seed 且不抛错）
- **Committed in:** `a230b4f2`

---

**Total deviations:** 2 auto-fixed（1 正确性补充 + 1 计划前提校正），零范围蔓延；所有 must_haves truths 均实现并被测试锁定。

说明：Task 3 标注 `tdd="true"`，但其被测行为即 Task 2 产物（计划刻意先实现再补行为守护，同 105-03 先例）——无独立 RED 阶段，测试首跑即绿（6 passed, 0.09s），符合计划任务顺序而非偏差。

## Issues Encountered

- Task 1 新用例首版对 Anthropic `claude-sonnet-4-5-*` 断言 temperature 透传失败：`ModelCapabilities.get` 将该模型标记 supports_reasoning=True → reasoning 分支剥除 temperature/top_p。修正为显式传 `_make_caps(supports_reasoning=False)` 隔离 reasoning 分支——透传与剥除的优先级行为符合设计（reasoning 约束优先）。

## User Setup Required

None - 缓存走既有 Django cache（Redis 缺省回退 LocMem）；`REPO_ROUTER_STAGE1_CACHE_TTL_SECONDS` 带默认值，无需配置。

## Next Phase Readiness

- 105-07（快照落库 + replay）：`RepoRouteResultV2.snapshot` 的 stage1 材料（脱敏 prompt/response + prompt_hash + model_id + cache_hit）与版本四元组已齐备，`_h_route` 可直接组 payload emit；105-07 需补「快照无 sk- 模式」断言（T-105-10 第二重防线）
- Phase 106（公式定版）：decode 固定与缓存 key 结构不受打分公式变更影响（weight_set_version 在 snapshot.versions 独立演进）
- Phase 107（rank-swap budget 有界重排）：排列输出模式即其输入形态（LLM 输出有序 repo_id 数组）

## Known Stubs

None——缓存命中路径 `snapshot.stage1.response=""` 为设计决策（缓存只存 parsed 排列），`cache_hit=True` 标记可区分，非 stub。

## Self-Check: PASSED

- FOUND: server/tests/codegraph/test_repo_router_stage1_idempotency.py（279 行 >= 80）
- FOUND: server/codegraph/services/repo_router_v2.py 含 `PROMPT_TEMPLATE_VERSION`（5 处 >= 2）/ `use_call_source`（3 处 >= 1）/ `redact_for_ledger`（4 处 >= 2）
- FOUND: commit a230b4f2（Task 1）/ 951d006f（Task 2）/ 3f57c2a4（Task 3）
- 验证命令：`cd server && uv run pytest tests/codegraph/ tests/test_llm_factory.py -q` → 259 passed, 20 skipped

---
*Phase: 105-golden-set*
*Completed: 2026-07-29*
