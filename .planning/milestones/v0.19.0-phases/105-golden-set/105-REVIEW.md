---
phase: 105-golden-set
reviewed: 2026-07-29T06:05:00Z
depth: deep
reviewer: gsd-code-reviewer (Claude)
diff_range: a430d9d6..HEAD
files_reviewed: 28
files_reviewed_list:
  - server/agents/llm_factory.py
  - server/agents/tools/repository_relevance.py
  - server/agents/tools/schemas/repository_relevance.py
  - server/codegraph/management/commands/measure_repo_index_stats.py
  - server/codegraph/services/repo_router_eval.py
  - server/codegraph/services/repo_router_replay.py
  - server/codegraph/services/repo_router_scoring.py
  - server/codegraph/services/repo_router_v2.py
  - server/friday/settings.py
  - server/services/process_runtime/builtin_processes.py
  - server/services/process_runtime/repo_router_adapter.py
  - server/tests/agents/test_repository_relevance_tool.py
  - server/tests/codegraph/fixtures/repo_router_golden/golden_baseline.json
  - server/tests/codegraph/fixtures/repo_router_golden/golden_holdout.json
  - server/tests/codegraph/fixtures/repo_router_golden/golden_main.json
  - server/tests/codegraph/test_measure_repo_index_stats.py
  - server/tests/codegraph/test_repo_router_golden.py
  - server/tests/codegraph/test_repo_router_replay.py
  - server/tests/codegraph/test_repo_router_scoring.py
  - server/tests/codegraph/test_repo_router_stage1_idempotency.py
  - server/tests/codegraph/test_repo_router_v2_degraded.py
  - server/tests/services/test_engine_clarify.py
  - server/tests/services/test_repo_router_adapter.py
  - server/tests/test_llm_factory.py
  - server/tests/test_model_usage_call_source.py
  - web/src/components/chat/RoutingDecisionPanel.vue
  - web/src/components/chat/__tests__/RoutingDecisionPanel.test.ts
  - web/src/types/routing.ts
status: findings
findings:
  blocker: 0
  major: 2
  minor: 2
  info: 4
  total: 8
fix_status: applied
fixed_at: 2026-07-29T14:20:00+08:00
fixed: 6
deferred: 2
---

# Phase 105 Code Review Report（编排解锁与评估标尺）

**Reviewed:** 2026-07-29
**Depth:** deep（全文精读 + 跨模块调用链追踪 + 依赖库源码验证 + 测试实跑）
**Status:** findings（2 MAJOR / 2 MINOR / 4 INFO，无 BLOCKER）

## Summary

评审覆盖 `a430d9d6..HEAD` 全部 server/web 源码改动（28 文件，+4696/−105）。整体质量高：纯函数打分核心（scoring/eval/replay 三模块零 Django/零 I/O）契约严格，margin 置信度规则边界（0.55/0.08/0.35 含等号语义）、只降不升、Σbreakdown==score（按构造精确成立）、fsum + 先量化再比较的稳定排序均实现正确且有性质测试锁定；golden set 门禁三规则、hold-out 封存纪律、快照单一写入口（`_emit_event`）、`redact_for_ledger` 双重脱敏均落实。本地实跑验证：后端 141 相关用例全绿（18.8s）、前端 vitest 10 用例全绿、`vue-tsc --noEmit` 通过、fixture 完整性校验（14+6 条、cross_group 与 project_scope 无交集、gk-001 事故机制编码正确）通过。

两个 MAJOR 都集中在 Stage 1 幂等三件套的系统层实现：(1) `seed` 透传对 OpenAI Responses API 会导致每次 Stage 1 调用抛 `TypeError` 静默全灭；(2) 缓存 key 遗漏了 prompt 的动态 `top_k` 片段，跨 `top_k` 请求会发生缓存碰撞。二者均不破坏降级安全性（编排仍能靠确定性 confidence 推进），但都违背本 phase 自己定下的契约，建议合入前修复。

## Major

### MJ-01: seed 透传 OpenAI Responses API 必然抛 TypeError——该类供应商 Stage 1 每次调用静默全灭

**Fix Status:** ✅ fixed — commit `8a8288fb`（seed gate 收窄为 OPENAI_CHAT/OLLAMA 且 `not extra.use_responses_api`；补 3 组参数化守护用例）

**File:** `server/agents/llm_factory.py:147-164`（gate 分支）；触发点 `server/codegraph/services/repo_router_v2.py:584-593`
**Issue:** `build_chat_model` 把 `seed` 对 `ProviderType.OPENAI_CHAT / OPENAI_RESPONSES / OLLAMA` 三类放行。但已验证（依赖库源码级）：

- openai SDK `Responses.create()` 签名**无 `seed` 形参也无 `**kwargs`**（`inspect.signature` 确认），传入即客户端 `TypeError`；
- langchain-openai 的 `_construct_responses_api_payload` 只剥 `temperature`（gpt-5 系）/改名 `max_tokens`，**不剥 `seed`**，`_default_params` 里 `seed` 非 None 必进 payload。

因此凡是实际走 Responses API 的凭证（`extra.use_responses_api=true`，与 seed gate 判断的 `provider_type` 是两个独立维度），Stage 1 `ainvoke` **每次**抛 `TypeError` → 被 `route()` 的宽 except 捕获 → 永久降级 `v2_stage0_only`。降级链安全（这正是 RELY-04 的成果），但对这类用户 Stage 1 被本次改动静默杀死，日志里只有 `stage1_failed:TypeError`，与 105-05 计划「seed 不被支持的 provider 静默忽略（不传）」的意图相反。现有测试只 mock 构造 kwargs，未覆盖 Responses payload 路径，故全绿假阴。
**Fix:** seed gate 收窄——`OPENAI_RESPONSES` 与 `extra.get("use_responses_api")` 为真的凭证一律走「不传 + `llm_decode_param_ignored` debug」分支：

```python
supports_seed = resolved.provider_type in (
    ProviderType.OPENAI_CHAT, ProviderType.OLLAMA
) and not resolved.extra.get("use_responses_api")
if supports_seed:
    kwargs["seed"] = seed
else:
    logger.debug("llm_decode_param_ignored", param="seed", ...)
```

并在 `tests/test_llm_factory.py` 补一条「OPENAI_RESPONSES / use_responses_api 时 kwargs 无 seed」用例。

### MJ-02: Stage 1 缓存 key 未含 top_k——prompt 动态片段「最多输出 max(top_k,3) 项」在 key 之外，跨 top_k 缓存碰撞

**Fix Status:** ✅ fixed — commit `84342e64`（`stage0_input` 并入 `output_cap: max(top_k, 3)`，prompt 插值复用同一变量防漂移；补 key 敏感性用例 + 端到端「跨 top_k 不共享缓存」行为用例）

**File:** `server/codegraph/services/repo_router_v2.py:491-516`（`_stage1_cache_key`）、`:646`（prompt 内 `max(top_k, 3)` 插值）、`:659-662`（key 组装）
**Issue:** 缓存 key = sha256(model_id ‖ PROMPT_TEMPLATE_VERSION ‖ stage0_input ‖ decode_params ‖ index_version)，其中 `stage0_input = {query, candidates}` **不含 `top_k`**，而 system prompt 含动态插值 `"最多输出 " + str(max(top_k, 3)) + " 项"`。`top_k` 是 `route()` 的调用方参数（`repository_relevance` 工具与 MCP `route_repositories` 均可传非默认值）。后果：

1. 同 query 先以 `top_k=3` 路由（缓存 ≤3 项排列），随后 `top_k=5` 的请求命中同一 key，只能拿到 3 个候选——结果条数错误，且与「同输入同输出」的幂等定义相悖（这是**不同**的 LLM 输入）；
2. 快照的 `prompt_hash` 按当前请求的 prompt 重算（`:655-656`），缓存命中时记录的 `prompt_hash` 与实际产生该排列的 prompt 不一致——版本绑定四元组的审计语义被破坏。

`PROMPT_TEMPLATE_VERSION` 只覆盖模板文字，覆盖不了动态插值；`test_cache_key_sensitive_to_*` 两条敏感性用例未覆盖 top_k 维度。
**Fix:** 把输出上限并入 key 材料（任选其一，推荐前者）：

```python
stage0_input = {"query": query, "candidates": [...], "output_cap": max(top_k, 3)}
```

或直接把 `prompt_hash` 本身作为 key 材料的一部分（prompt 完全决定 LLM 文本输入，天然覆盖一切动态片段）。同步补一条 key 敏感性用例：`top_k=3` 与 `top_k=5` 的 key 不同。

## Minor

### MN-01: Stage 1 未对 LLM 输出的重复 repo_id 去重——重复候选可入结果并被缓存 24h 放大

**Fix Status:** ✅ fixed — commit `6acb2c51`（消费循环加已见集合首见保留；缓存存 parsed 原文、消费统一去重对直调/命中两条路径同时生效；补重复输出守护用例）

**File:** `server/codegraph/services/repo_router_v2.py:728-769`（parsed 消费循环）
**Issue:** LLM 输出数组若含重复 `repo_id`（prompt 只说「无关候选不要输出」，未禁重复），`by_id.get(rid)` 两次都命中，`candidates` 出现同仓重复项 → 透传到 `RepositoryRoutingTrace.candidates`（前端 `v-for :key="c.repository_id"` 重复 key）、`repo.routing` 快照与编排 session.routing。此行为旧代码即存在（非本次引入），但新加的输入哈希缓存会把含重复的 parsed 排列缓存 24h，使偶发的模型不遵指令固化为该输入的稳定错误输出；replay 侧忠实复现重复（记录与重算一致），verify 不拦截。
**Fix:** 消费循环加已见集合：

```python
seen: set[str] = set()
...
if base is None or rid in seen:
    continue
seen.add(rid)
```

（写缓存前过滤同理生效，因为缓存的是 parsed 原文、消费时统一去重即可。）

### MN-02: snapshot.versions.index_version 与 Stage 1 缓存 key 的 index_version 口径不一致

**Fix Status:** ✅ fixed — commit `c6f916a8`（Stage 1 的 index_version 随 stage1_meta 回传，`_build_snapshot` 优先复用同一值，Stage 1 未参与时才按最终候选仓集合计算；补两口径恒等守护用例）

**File:** `server/codegraph/services/repo_router_v2.py:439-449`（`_build_snapshot`：按**最终 top_k 候选**的仓集合、从 node_hits 首个命中取 built_at）vs `:631-632, 659`（`_stage1_llm_reasoning`：按**top-8 max_candidates 候选**的仓集合、从候选桶首 hit 取 built_at）
**Issue:** 同名概念「index_version」在同一次 route 里按两个不同仓集合计算，产出两个不同哈希：快照 versions 里记录的是前者，参与缓存 key 的是后者。当前无消费方交叉比对二者，尚不构成错误；但 Phase 106/107 若用 versions.index_version 做回放门禁或缓存审计（这是「版本绑定四元组」的设计意图），两个口径会直接对不上，且排障时极易误判「索引变了/没变」。
**Fix:** 统一口径——`_stage1_llm_reasoning` 算得的 `index_version` 随 `stage1_meta` 返回，`_build_snapshot` 优先复用该值（Stage 1 未参与时再按候选仓集合计算），或在 versions 里分别命名 `index_version`（快照口径）与 `stage1_cache_index_version` 以显式区分。

## Info

### IN-01: `measure_repo_index_stats` 日志字段名 `initiated_by` 与 LOGGING-SPEC 的 `initiated_by_user_id` 不一致

**Fix Status:** ✅ fixed — commit `192f4efe`

**File:** `server/codegraph/management/commands/measure_repo_index_stats.py:45`
**Issue:** `_LOG_KV` 用 `initiated_by="system"`；LOGGING-SPEC §CTX 与自检清单锁定的字段名是 `initiated_by_user_id`（无触发用户记 `system`）。字段名漂移会让按规范字段做的日志聚合查询漏掉本命令。
**Fix:** 改为 `initiated_by_user_id="system"`。

### IN-02: 缓存命中路径快照的 stage1.response 为空串——审计留痕缺原始响应文本

**Fix Status:** ⏸ deferred — 维持现状（105-05 SUMMARY 已记录的已知取舍；`cache_hit` 标志指引审计者回溯首次未命中事件；扩缓存 value 结构涉及缓存格式变更，收益不抵改动面，留待有真实审计需求时再做）

**File:** `server/codegraph/services/repo_router_v2.py:680, 775-781`
**Issue:** 命中缓存时只有 parsed 排列没有原始响应，`snapshot.stage1.response=""`、`cache_hit=True`。回放不受影响（回放只用 candidates 排列），但逐例审计「LLM 原话说了什么」在缓存命中的 route 上断链，需要回溯到最初未命中那次的事件。105-05 SUMMARY 已记录该取舍，此处仅确认为已知限制。
**Fix:**（可选）缓存 value 从 `parsed` 扩为 `{"parsed": ..., "response": redacted_text}`，命中时回填；或维持现状并依赖 `cache_hit` 标志指引审计者回溯。

### IN-03: confidence Tooltip 文案只描述 rank-1 margin 语义，但展示在所有候选的 Badge 上

**Fix Status:** ⏸ deferred — 归 Phase 107（分组呈现时按 rank 区分文案；文案为 UI-SPEC Copywriting 原文锁定，本 phase 不动）

**File:** `web/src/components/chat/RoutingDecisionPanel.vue:92-96, 230-239`
**Issue:** `CONFIDENCE_TOOLTIPS.medium = "中置信：首位分数达标但领先幅度不足…"`——对 rank>1 的 medium 候选（实际语义是 `score >= θ_med`，与「首位/领先幅度」无关）解释不准确。文案是 UI-SPEC Copywriting 原文锁定，非实现偏差；建议 Phase 107 做分组呈现时按 rank 区分文案。
**Fix:** Phase 107 处理；本 phase 无需改动。

### IN-04: 两处小的健壮性/规范尾巴

**Fix Status:** ✅ fixed — commit `90dcf7c7`（(a) 零候选提前短路 + `skipped_reason=no_stage0_candidates` + 守护用例；(b) `_EVENT_FAILED` 异常文本过 `redact_secrets_in_text`）

**File:** `server/codegraph/services/repo_router_v2.py:183-201`；`server/codegraph/management/commands/measure_repo_index_stats.py:181`
**Issue:** (a) node_hits 非空但全部缺 `repository_id` 时 `stage0_candidates` 为空，`route()` 仍会带着零候选进 Stage 1 发一次空 prompt 的 LLM 调用（结果必被白名单过滤为 None 再降级）——浪费一次调用，概率极低；(b) `logger.error(_EVENT_FAILED, error=str(exc))` 的异常文本未手动过 `redact_secrets_in_text`（依赖 structlog 自动 processor 的值模式兜底；Qdrant 异常含凭证概率低。`repo_router_v2_stage1_failed` 的同款写法为存量行，非本次引入）。
**Fix:** (a) `if not stage0_candidates: return cls._stage0_only_result(...)` 提前短路；(b) `error=redact_secrets_in_text(str(exc))`。

## 重点维度核对结论

1. **正确性（margin/只降不升/Σ==总分/重归一化/tie-break）**：全部正确。边界含等号（`s1>=0.55 and margin>=0.08`）有参数化用例（0.55/0.47 → high，0.079 margin → medium）；`apply_llm_adjustment` 9 组穷举 + None 全表；`score = fsum(breakdown.values())` 按构造使 INV-R3 **精确**成立（golden 测试用 `==` 而非容差，通过）；活跃度缺失走权重重归一化且 breakdown 无该键；排序 `(-round(score,6), repo_id)` 先量化后比较、第二键不可变。前端「合计==总分」链路核对：trace 走 `RepositoryRelevanceCandidate`（全精度浮点，非 to_dict 的 round4/round6），前端 1e-6 容差校验不会误报。
2. **幂等/确定性**：乱序 100 seed、双跑缓存命中零调用、禁缓存纯函数同结果、缓存异常不反噬均有测试且通过；replay 与 route 的 rank 语义逐字一致（含 `node_id` 回填 tie-break 的关键决策）；**缓存 key 有 MJ-02 所述完整性缺口**；deep 追踪确认 replay 的 rank_by_id（全量 scored）与 live（截断 top-8）对白名单内候选恒等。
3. **安全/脱敏**：快照 payload 在 router 层（stage1 prompt/response 各一次 `redact_for_ledger`）与 `_h_route` 层（整体一次）双重脱敏；假密钥注入断言、`friday_pat_` 兜底、64KB 上限、写入仅经 `_emit_event`（taxonomy 测试零改动通过）均验证。无凭证明文泄漏路径。
4. **可观测性**：新事件均带 category/component + snake_case + duration_ms；`repo_router_v2_scored` debug 级不刷屏；缓存/观测均 try/except best-effort；Stage 1 统一 `use_call_source(AUX_REPO_ROUTER)`。仅 IN-01 字段名与 IN-04(b) 异常文本两处小尾巴。
5. **消费方兼容**：`RepoRouteCandidateV2.breakdown` / `RepoRouteResultV2.degraded/snapshot` 全部带默认值；8 个消费方（adapter/route_views/mcp_tools/repo_association/artifact/space_tools/relevance/clarify）均按具名字段读取，additive-safe；3 个 stub 构造测试文件零改动通过；`_h_route` 落库前 pop snapshot 有测试断言。`skipped` 路径保持三键不变。
6. **前端**：无 breakdown（缺失与空 dict）不渲染 trigger、未知信号 key 回退英文原名、合计直显 `candidate.score`、和校验仅 console.warn、trace 更新重置展开态——vitest 10 用例 + vue-tsc 全绿；无新增依赖/颜色 token/v-html。i18n 沿组件家族硬编码中文惯例（UI-SPEC Unresolved 显式假设，归 Phase 107/110，非缺陷）。

## 验证证据

- `uv run pytest`（11 个相关测试文件）：**141 passed**, 18.79s
- `pnpm exec vitest run RoutingDecisionPanel.test.ts`：**10 passed**
- `pnpm exec vue-tsc --noEmit`：**通过**（exit 0）
- fixture 完整性脚本：主集 14 / hold-out 6（opened_count=0）、cross_group 2 条且与 project_scope 无交集、gk-001 命中分布 study-app 6 / onion-learning 1 / study-course 2 / study-user-status 1（事故机制编码正确）、id 无重复、baseline recall@5=0.9643 / top1=13/14 / 误自动选中率=0.0
- `rg golden_holdout tests/codegraph/test_repo_router_golden.py`：0 命中（hold-out 未被门禁加载）
- openai SDK `Responses.create` 签名检查：`seed` 形参不存在且无 `**kwargs`（MJ-01 证据）

---

## 修复处理记录（2026-07-29, gsd-code-fixer）

| Finding | 状态 | Commit | 说明 |
|---------|------|--------|------|
| MJ-01 | fixed | `8a8288fb` | seed gate 收窄——Responses API 凭证不透传 seed + 3 组参数化守护用例 |
| MJ-02 | fixed | `84342e64` | 缓存 key 并入 `output_cap`（prompt 插值复用同一变量）+ key 敏感性/端到端行为用例 |
| MN-01 | fixed | `6acb2c51` | 消费循环对重复 repo_id 首见保留去重 + 守护用例 |
| MN-02 | fixed | `c6f916a8` | snapshot.versions 复用 Stage 1 缓存 key 的 index_version + 两口径恒等用例 |
| IN-01 | fixed | `192f4efe` | 日志字段名 `initiated_by` → `initiated_by_user_id` |
| IN-02 | deferred | — | 已知取舍（105-05 SUMMARY 已记录），`cache_hit` 标志指引审计回溯 |
| IN-03 | deferred | — | 归 Phase 107 分组呈现时按 rank 区分 Tooltip 文案 |
| IN-04 | fixed | `90dcf7c7` | 零候选提前短路（含守护用例）+ 统计命令异常文本手动脱敏 |

**回归验证：** `cd server && uv run pytest tests/codegraph tests/test_llm_factory.py tests/test_model_usage_call_source.py -q` → **300 passed, 20 skipped**（skip 均为存量环境依赖跳过）。edited 源文件 `ruff check` 无新增违规（`test_llm_factory.py` 的 I001 与两处 format 漂移均为基线存量，未触碰）。

---

_Reviewed: 2026-07-29T06:05:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
_Fixes applied: 2026-07-29 (gsd-code-fixer)_
