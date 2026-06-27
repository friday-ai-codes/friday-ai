# Phase 95: 拆分完善 (decompose-llm) - Research

**Researched:** 2026-06-28
**Domain:** LLM 结构化需求拆分（plan_orchestration decompose stage）+ 可观测性 call_source + fail-soft 降级
**Confidence:** HIGH（核心结论全部基于现有代码实证 grep/read）

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **A. LLM 拆分**：`PlanOrchestrationEngine._decompose` 从 `requirement_text.splitlines()` 按行切分，升级为 LLM 跨仓**业务线 / 模块 / 前后端**拆分，产结构化 `segments`（保持下游 routing 消费契约不变）。输入复用现有：`decomposition.requirement_text`（或 `work_item.title`）+ `include_repos`。
- **B. 观测**：新增 `CallSource.PLAN_DECOMPOSE` 枚举值并登记 LOGGING-SPEC §4.1；LLM 调用经 `use_call_source` 标注，上报请求/token/TTFT/上游错误码；事件 started/completed/failed + duration_ms（category 合理设定）。
- **C. fail-soft 降级**：LLM 失败 / 缺 default_model / 解析异常 → **回退现状「按非空行切分」**（best-effort，绝不阻断编排）。

### Claude's Discretion
- 拆分 prompt 设计、segment 结构细化（是否带 module/repo_hint 字段）、call_source category 取值由 plan-phase 定。

### Deferred Ideas (OUT OF SCOPE)
- None — 范围聚焦 DECOMP-01。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DECOMP-01 | `decompose` 阶段从「按非空行切分」升级为 LLM 跨仓业务线/模块/前后端拆分，提升路由/调研精度（`call_source` 赋值、fail-soft 降级回退现状） | 全文：§标准栈（复用 build_chat_model + ProviderConfigService.aresolve + use_call_source）、§架构模式（新建 decompose_segments.py helper 镜像 clarification_questions.py）、§契约（_route 只读 requirement_text/include_repos，segments 无下游读取）、§观测（PLAN_DECOMPOSE 登记）、§Validation |
</phase_requirements>

## Summary

Phase 95 把 `PlanOrchestrationEngine._decompose`（现 `requirement_text.splitlines()` 按非空行切分的 stub）升级为 LLM 跨仓「业务线/模块/前后端」结构化拆分。最关键的实证发现：**`segments` 没有任何下游消费者**。`_route`（`RepoRouterV2Adapter`）只读 `decomposition["requirement_text"]` 与 `decomposition["include_repos"]`，从不读 `segments`（已 grep 全 `server/` 确认）。因此 `segments` 的 schema 可以自由丰富（带 module/repo_hint/layer），**不会破坏 routing 契约**——真正需要保持的契约只是 decomposition dict 里 `requirement_text` 和 `include_repos` 两个键不变。

实现范式已有现成、几乎 1:1 可镜像的样板：`server/services/plan_orchestration/clarification_questions.py`（CLARIFY-02）。它是「入口无关、纯 helper、健壮 JSON 解析、`use_call_source` 标注、best-effort 失败返回降级值、绝不抛」的标准实现，且其测试范式（`patch` 模块级 helper + AsyncMock 注入 LLM 产出 / 返回空触发 fail-soft）可直接复刻到 decompose。

`CallSource` 枚举（`server/agents/call_source.py`）当前实际有 31 个值（docstring 写「30 值」已轻微 stale，因 `PLAN_CLARIFICATION` 加入时未更新计数）。新增 `PLAN_DECOMPOSE = "plan_decompose"` 后为 32 值。LOGGING-SPEC §4.1 表格目前止于 `branch_naming`，**连 `plan_clarification` 都尚未登记**——本 phase 应补 `plan_decompose`（并顺手补 `plan_clarification`）。

**Primary recommendation:** 新建 `server/services/plan_orchestration/decompose_segments.py`，导出 `async def agenerate_decomposition_segments(...)`，完整镜像 `clarification_questions.py` 的结构（system prompt + robust JSON 解析 + normalize + `use_call_source(CallSource.PLAN_DECOMPOSE)` + `category="sampling"`/`component="plan_orchestration"` + started/completed/failed + `duration_ms`，失败返回 `None` 触发 `_decompose` 内的 splitlines 回退）。`_decompose` 调它取 segments，保留 `requirement_text`/`include_repos`，照常 `transition("decomposed")`。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| LLM 拆分推理（产结构化 segments） | API / Backend（service helper） | — | 纯 server 端 LLM 调用，入口无关；与 clarification_questions 同层 |
| call_source 标注 + 指标上报 | API / Backend（chokepoint） | — | `use_call_source` contextvar → `acquire_llm_slot`/Runner 自动上报，helper 只标注 |
| fail-soft 降级 | API / Backend（helper + engine handler） | — | helper 返回降级信号，engine `_decompose` 永远完成 `transition("decomposed")` |
| 状态转移 | API / Backend（PlanSessionService） | — | engine 绝不直接写 status，只经 `transition`（T-36-03-01 纯度守护） |

## Standard Stack

### Core（全部已在仓内，无新增外部依赖）
| Library/Module | 位置 | Purpose | Why Standard |
|---------|------|---------|--------------|
| `agents.llm_factory.build_chat_model` | `server/agents/llm_factory.py` | ResolvedProviderConfig + model → LangChain BaseChatModel | 仓内唯一 chat model 构造入口；capabilities 驱动 thinking/reasoning/timeout |
| `services.provider_config.ProviderConfigService.aresolve` | `server/services/provider_config.py:874` | 解析系统默认 Provider 凭证（含 `extra.default_model`） | 与 clarification_questions 同源；无凭证抛 `ProviderConfigError`（须 try 捕获） |
| `agents.call_source.use_call_source` / `CallSource` | `server/agents/call_source.py` | 作用域内声明 LLM 调用来源（contextvar） | 指标/TTFT/上游错误按 call_source 维度统计的权威机制 |
| `langchain_core.messages.SystemMessage/HumanMessage` | langchain（已装） | 构造单轮 prompt | clarification_questions 同款 |
| `structlog.get_logger(__name__)` | structlog（已装） | started/completed/failed 结构化事件 | 项目强制日志规范 |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| 在 `engine.py` 内联 LLM 逻辑 | 新建独立 helper 模块 | 内联会污染 engine 纯度（入口无关 + 不耦合 IO）；helper 模块可独立测试、与 clarification_questions 对称。**强烈推荐 helper 模块** |
| `model.ainvoke`（单轮） | streaming | decompose 是单轮结构化产出，`streaming=False`（对齐 clarification_questions L154） |

**Installation:** 无需安装任何包（纯仓内复用）。

## Package Legitimacy Audit

**SKIPPED** — 本 phase 不安装任何外部包，全部复用仓内既有模块（`llm_factory` / `provider_config` / `call_source` / `langchain` / `structlog` 均已在 `server/pyproject.toml`）。

## Architecture Patterns

### System Architecture Diagram

```text
PlanSession(status=DECOMPOSING)
        │  engine.advance(session) → handlers[DECOMPOSING] = _decompose
        ▼
  _decompose(session)
        │  existing = session.decomposition or {}
        │  requirement_text = existing["requirement_text"]  (空则回退 work_item.title)
        │  include_repos    = existing["include_repos"]
        ▼
  agenerate_decomposition_segments(requirement_text, include_repos)   [新建 helper]
        │
        ├── try: aresolve() → default_model? → build_chat_model(streaming=False)
        │        with use_call_source(CallSource.PLAN_DECOMPOSE):       ← 指标/TTFT/上游错误自动按维度上报
        │            resp = await model.ainvoke([System, Human])
        │        segments = normalize(parse_json(resp.content))          ← 健壮 JSON 解析 + 字段防御
        │        log "plan_decompose_completed" (category=sampling, duration_ms)
        │        return segments  (list[dict] 结构化)
        │
        └── except Exception / 无 default_model / 解析空:                 ← fail-soft（绝不抛）
                 log "plan_decompose_failed"/"..._no_default_model"
                 return None
        ▼
  _decompose: segments = result if result else splitlines 回退        ← C. fail-soft 回退现状
        │  decomposition = {requirement_text, include_repos, segments}  ← 契约：前两键不变
        ▼
  PlanSessionService.transition(session, "decomposed", decomposition=…)  ← engine 不直接写 status
        ▼
PlanSession(status=ROUTING) → _route(RepoRouterV2Adapter)
        └── 只读 decomposition["requirement_text"] + ["include_repos"]   ← segments 不被读取
```

### Component Responsibilities

| 文件 | 职责 | 改动类型 |
|------|------|----------|
| `server/services/plan_orchestration/decompose_segments.py` | **新建** LLM 拆分 helper（镜像 clarification_questions.py） | 新增 |
| `server/services/plan_orchestration/engine.py` `_decompose` | 调 helper 取 segments + splitlines 回退 + 保留契约键 | 修改 |
| `server/agents/call_source.py` `CallSource` | 新增 `PLAN_DECOMPOSE = "plan_decompose"` + docstring 计数 30→32 | 修改 |
| `.planning/observability/LOGGING-SPEC.md` §4.1 | 登记 `plan_decompose`（顺手补 `plan_clarification`） | 文档 |
| `server/tests/services/test_plan_orchestration_engine.py` | 既有 decompose 用例 + 新增 LLM/fail-soft 用例 | 修改/新增 |

### Pattern 1: 入口无关 LLM helper（镜像 clarification_questions.py）
**What:** 纯函数 async helper，只接收原语（requirement_text/include_repos），不接 IO/session，best-effort 失败返回降级信号，绝不抛。
**When:** decompose LLM 拆分。
**Example（权威样板，逐段照搬 clarification_questions.py L132-177）:**
```python
# Source: server/services/plan_orchestration/clarification_questions.py
async def agenerate_clarification_questions(*, requirement, ...) -> list[dict]:
    if not (requirement or "").strip():
        return []
    try:
        from agents.call_source import CallSource, use_call_source
        from agents.llm_factory import build_chat_model
        from services.provider_config import ProviderConfigService
        resolved = await ProviderConfigService.aresolve()
        model_name = (getattr(resolved, "extra", None) or {}).get("default_model", "")
        if not model_name:
            logger.warning("clarification_questions_no_default_model", category="sampling")
            return []
        model = build_chat_model(resolved, model_name, streaming=False)
        with use_call_source(CallSource.PLAN_CLARIFICATION):   # decompose 换成 PLAN_DECOMPOSE
            response = await model.ainvoke(messages)
        raw = _parse_questions_json(_content_to_text(response.content))
        ...
        return normalize_...(raw)
    except Exception as exc:  # noqa: BLE001 — best-effort，绝不阻断编排
        logger.warning("..._failed", category="sampling", component="plan_orchestration", error=str(exc))
        return []
```

### Pattern 2: 健壮 JSON 解析（支持 ```json 代码块 / 裸 JSON）
直接复用 `clarification_questions._parse_questions_json` 的正则范式（`re.findall(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)` + 裸 text 兜底 + `json.loads` try/continue）。decompose 解析 `{"segments": [...]}`。

### Pattern 3: content 归一为文本
复用 `_content_to_text`（兼容 reasoning 模型返回的 content_blocks list）——`llm_factory.content_to_text` 已有同款（只拼 type=="text" block），二选一即可。

### Anti-Patterns to Avoid
- **让 decompose 异常落 FAILED**：`advance()` 的通用 `except` 会把未捕获异常 `transition("fail")`。CONTEXT C 要求回退而非失败 → helper 必须自包 fail-soft，`_decompose` 必须永远走到 `transition("decomposed")`。
- **改 `requirement_text`/`include_repos` 键名或删除**：会破坏 `_route` 契约（它只读这两个）。
- **在 engine.py 直接 `session.status = ...`**：有源码守护测试 `test_engine_does_not_write_status_directly`（grep `\.status\s*=`）。
- **高频 INFO 刷屏**：started/completed 用 `category="sampling"`（单轮内部步骤），避免 INFO 泛滥。

## Downstream Contract（关键发现 — 必读）

**已 grep 全 `server/` 确认 `segments` 的消费方：仅测试断言，无任何生产代码读取。**

- `_route` → `RepoRouterV2Adapter.route`（`repo_router_adapter.py:36`）：`query = (session.decomposition or {}).get("requirement_text", "")`；候选范围经 `_resolve_repository_ids` 读 `include_repos`。**完全不读 `segments`。**
- `segments` 在生产代码中的唯一写入点就是 `engine._decompose`（`engine.py:118-122`）。
- `segments` 的读取点：只有 `server/tests/services/test_plan_orchestration_engine.py:41` 断言 `decomposition["segments"] == ["做A", "做B"]`（list[str]）。其余 `test_plan_session_service.py:76` / `test_plan_session_models.py:58` 只是把 `segments` 当任意 JSON 存入 `PlanSession.decomposition`（JSONField）做 round-trip，与 decompose 行为无关。

**结论 → 契约只有两条**：
1. `decomposition` dict 必须保留 `requirement_text`、`include_repos` 两键（routing 读）。
2. `segments` schema 可自由演进（无生产消费方）；唯一约束是同步更新 `test_plan_orchestration_engine.py:41` 断言。

### Segment 结构建议（Claude's Discretion）

**推荐方案（异构 union，最小风险）：**
- **fail-soft 回退路径** = 严格保持「现状」list[str]（`[line.strip() for line in requirement_text.splitlines() if line.strip()]`）。这样既字面满足 CONTEXT C「回退现状按非空行切分」，又让既有断言 `segments == ["做A", "做B"]` 在测试环境（无 Provider 凭证 → `aresolve` 抛 → 回退）**继续通过、零改动**。
- **LLM 成功路径** = 结构化 `list[dict]`，每项建议字段：

```json
{
  "title": "登录页改造",           // 必填，拆分项标题（人类可读）
  "module": "用户中心",            // 业务线/模块名（可空）
  "layer": "frontend",            // frontend | backend | fullstack | infra（可空）
  "repo_hint": "web-portal"       // 候选仓库提示（来自 include_repos，可空）
}
```

`normalize_decomposition_segments` 防御非法字段（缺 title 跳过、layer 不在枚举回退空、字段强转 str/strip），上限（如 `_MAX_SEGMENTS = 20`）防 LLM 失控。

**备选方案（统一 schema）：** 两条路径都产 list[dict]（回退时 title=行文本、其余字段空），并把 `test_plan_orchestration_engine.py:41` 断言改为 dict 形态。更整洁但需改既有断言，且回退路径不再字面等于「现状」。**推荐 union 方案**——下游无消费方，异构成本为零，回退路径零行为变更最稳。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| LLM 调用来源标注 + 指标 | 手写 token/TTFT 统计 | `use_call_source(CallSource.PLAN_DECOMPOSE)` | chokepoint（acquire_llm_slot/Runner）读 contextvar 自动上报，无需逐层透参 |
| chat model 构造 | 直接 new ChatOpenAI/init_chat_model | `build_chat_model(resolved, model)` | 仓内唯一入口，处理 thinking/reasoning/timeout/SecretStr |
| Provider 解析 | 读 env/DB 凭证 | `ProviderConfigService.aresolve()` | 四层解析 + 加密；CLAUDE.md 强制不绕过 |
| LLM JSON 健壮解析 | `json.loads(resp)` 直解 | 复用 `_parse_questions_json` 正则范式 | LLM 常包 ```json 代码块 / reasoning 前缀，直解必崩 |
| content 取文本 | `str(resp.content)` | `content_to_text` / `_content_to_text` | reasoning 模型 content 是 block list，str() 得 Python repr 致 json 失败 |

**Key insight:** decompose 与 clarification 是同构问题（单轮 LLM 产结构化 JSON + fail-soft + call_source），clarification_questions.py 已解决全部边角；本 phase 本质是「复制 + 改 prompt/schema/枚举值」，不应重新发明任何机制。

## 观测埋点（LOGGING-SPEC 对齐）

### CallSource 登记
- `server/agents/call_source.py`：在 `CallSource` 末尾（`PLAN_CLARIFICATION` 后）新增：
  ```python
  # 方案编排拆分阶段：LLM 跨仓业务线/模块/前后端拆需求 → 结构化 segments（单轮，best-effort，
  # 失败回退按行切分），提升路由/调研精度（DECOMP-01）。
  PLAN_DECOMPOSE = "plan_decompose"
  ```
- 同步把类 docstring「30 值」与模块顶部 docstring 计数更新为 **32 值**（实测当前枚举 31 个成员，加 PLAN_DECOMPOSE → 32；`PLAN_CLARIFICATION` 此前加入时漏更计数）。`CallSource.normalize` 无需改（遍历成员，自动覆盖新值）。

### LOGGING-SPEC §4.1 表格登记（`.planning/observability/LOGGING-SPEC.md` L97 后追加）
```markdown
| `plan_clarification` | `clarification_questions` / ClarifyAdapter（v0.16.1 Phase 90） | 基于需求+路由+召回产结构化澄清问题（多题/单多选/推荐），单轮 |
| `plan_decompose` | `decompose_segments` / `PlanOrchestrationEngine._decompose`（v0.16.1 Phase 95） | LLM 跨仓业务线/模块/前后端拆需求 → 结构化 segments，单轮，best-effort 失败回退按行切分 |
```
（`plan_clarification` 行为补登：当前 spec 表止于 `branch_naming`，代码枚举已有 plan_clarification 但 spec 未登记，一并补齐。）

### category / component / 事件（CONTEXT B）
- **category = `sampling`**（采样类）：单轮内部 LLM 步骤，非用户可归因的一次完整调用入口；与 clarification_questions（`category="sampling"`）一致。**不要**用 `caller`（caller 是 MCP/对话/REST 写/webhook 等入口）。
- **component = `plan_orchestration`**（与 clarification_questions 一致）。
- **生命周期事件（结构化 structlog，非 _emit_event trace）**：
  - `plan_decompose_started`（category=sampling, component=plan_orchestration, requirement_len=…, include_repos_count=…）
  - `plan_decompose_completed`（… segment_count=…, duration_ms=…）— 用 `time.monotonic()` 起止算 duration_ms
  - `plan_decompose_failed` / `plan_decompose_no_default_model`（… error=str(exc), duration_ms=…）→ 触发回退
  - 回退发生时可补 `plan_decompose_fallback_splitlines`（对齐 clarification 的 `clarification_fallback_coarse_question` 范式，便于测试断言）
- **请求/token/TTFT/上游错误码**：经 `use_call_source` + `build_chat_model` 自动由 chokepoint 上报到 `ModelUsageRecord`（call_source=plan_decompose），helper 侧无需手写数值上报（§4.1 注：埋点在 acquire_llm_slot + Runner astream + ainvoke 站点）。
- **脱敏**：日志只记 `requirement_len`/计数，不落 requirement 原文；异常文本若入日志走 `redact_secrets_in_text`（best-effort，绝不反噬）。

> 注：现 `_decompose` 不发 `_emit_event` trace 事件（taxonomy 无 decompose 事件，`EVENT_*` 见 `event_taxonomy.py`）。CONTEXT B 的「started/completed/failed」用 structlog 生命周期事件即可满足，**无需**新增 `EVENT_DECOMPOSE` taxonomy 项（更轻、对齐 clarification_questions）。若 plan 想要 UI trace 可作为可选增强，非 DECOMP-01 必需。

## Common Pitfalls

### Pitfall 1: 测试环境无 Provider 凭证导致 LLM 路径必走回退
**What goes wrong:** `ProviderConfigService.aresolve()` 无系统默认凭证时抛 `ProviderConfigError`（`provider_config.py:891`）。
**Why:** 测试 DB 通常未建 ProviderCredential。
**How to avoid:** ① helper 的 `try/except Exception` 必须覆盖 `aresolve()` 调用（clarification_questions 已把 aresolve 放在 try 内 L149）。② 既有用例 `test_advance_from_decomposing_real_decompose` 正是靠此回退到 splitlines 得 list[str] → 保持回退路径产 list[str] 则该用例零改动通过。
**Warning signs:** 该用例红 → 说明回退路径 schema 变了或异常未被吞。

### Pitfall 2: 把 decompose 异常吞成 FAILED
**What goes wrong:** helper 抛 → `advance()` 通用 except → `transition("fail")` → session FAILED。违反 CONTEXT C。
**How to avoid:** helper 自包 `except Exception` 返回 None；`_decompose` 永远 `transition("decomposed")`。新增 fail-soft 测试断言 session 推进到 ROUTING（非 FAILED）。

### Pitfall 3: reasoning 模型 content 致 JSON 解析崩
**What goes wrong:** 经 anthropic 兼容代理的 reasoning 模型返回 content_blocks list，`str()` 得单引号 repr，`json.loads` 必失败。
**How to avoid:** 用 `content_to_text`/`_content_to_text` 只拼 text block（llm_factory.py:46 已实现）。

### Pitfall 4: call_source 枚举计数 docstring 漂移
**What goes wrong:** docstring 写「30 值」，实际枚举已 31，新增后 32，CLAUDE.md 规则还写「22 值」。
**How to avoid:** 改 docstring 时以**实际成员数**为准（32），不盲信旧文案；CLAUDE.md 的描述性计数非阻断、可不强改。

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.x + pytest-asyncio + pytest-django（`server/pyproject.toml` `[tool.pytest.ini_options]`） |
| Config | `DJANGO_SETTINGS_MODULE="friday.settings"`, `testpaths=["tests"]`, `asyncio_mode="auto"` |
| Quick run | `cd server && uv run pytest tests/services/test_plan_orchestration_engine.py -x` |
| Full suite | `cd server && uv run pytest` |
| 关键标记 | `@pytest.mark.django_db` + `@pytest.mark.asyncio`（每个 async DB 用例都要） |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DECOMP-01 | LLM 成功 → segments 为结构化 list[dict] | unit | `uv run pytest tests/services/test_plan_orchestration_engine.py -k decompose_llm -x` | ❌ Wave 0 |
| DECOMP-01 | fail-soft：LLM/解析失败 → 回退 splitlines list[str]，session 推进 ROUTING（非 FAILED） | unit | `… -k decompose_fail_soft -x` | ❌ Wave 0 |
| DECOMP-01 | 缺 default_model → 回退 + 记 no_default_model 事件 | unit | `… -k decompose_no_model -x` | ❌ Wave 0 |
| DECOMP-01 | 契约保持：decomposition 仍含 requirement_text/include_repos | unit | 既有 `test_advance_from_decomposing_real_decompose`（回退路径）+ 新 LLM 路径断言 | ✅（既有，回退路径）/ ❌（LLM 路径 Wave 0） |
| DECOMP-01 | call_source 标注（LLM 调用期 contextvar=plan_decompose） | unit | 可选：patch 后断言 `get_call_source()` 或 `use_call_source` 被进入 | ❌ Wave 0 |

### Test 范式（镜像 test_engine_clarify.py L183-276）
- 模块级常量 `_LLM_GEN = "services.plan_orchestration.decompose_segments.agenerate_decomposition_segments"`（若 `_decompose` 直接调 helper）或 patch helper 内部的 `build_chat_model`/`model.ainvoke`。
- **LLM 成功**：`with patch(_LLM_GEN, new=AsyncMock(return_value=[{...dict...}]))` → advance → 断言 `decomposition["segments"]` 为 dict 列表 + 推进 ROUTING。
- **fail-soft（返回 None/空）**：`patch(_LLM_GEN, new=AsyncMock(return_value=None))` → 断言回退 splitlines + session.status==ROUTING（非 FAILED）+ 回退事件日志（`patch(... .logger)` 断言事件名，如 test_engine_clarify L243）。
- **helper 自身单测**（可选独立文件）：patch `ProviderConfigService.aresolve`/`build_chat_model` 验证健壮 JSON 解析 + normalize 边角（缺字段/超限/非法 layer）。

### Sampling Rate
- **Per task commit:** `cd server && uv run pytest tests/services/test_plan_orchestration_engine.py -x`
- **Per wave merge:** `cd server && uv run pytest tests/services/ -x`
- **Phase gate:** `cd server && uv run pytest` 全绿后 `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/services/test_plan_orchestration_engine.py` 扩展 decompose LLM/fail-soft/no-model 用例（既有文件，新增用例）
- [ ] （可选）`tests/services/test_decompose_segments.py` — helper 解析/normalize 单测
- [ ] 复核既有 `test_advance_from_decomposing_real_decompose:41` 断言：回退方案保留 list[str] 则零改；统一方案需改为 dict 断言

## Security Domain

`security_enforcement: true`, `security_asvs_level: 1`。本 phase 是内部 LLM 服务调用，无外部输入入口、无新增鉴权面。

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | 无新增鉴权面（内部 stage handler） |
| V3 Session Management | no | 复用 PlanSession 状态机 |
| V4 Access Control | no | 编排内部，无新端点 |
| V5 Input Validation | yes | `normalize_decomposition_segments` 防御 LLM 输出（字段强转/枚举校验/上限）；健壮 JSON 解析容错 |
| V6 Cryptography | no | Provider api_key 经 `build_chat_model` SecretStr 包装（既有），不手碰密钥 |

### Known Threat Patterns
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| LLM 返回畸形/超大 JSON | Tampering/DoS | normalize + `_MAX_SEGMENTS` 上限 + 字段防御；解析失败 fail-soft 回退 |
| 凭证/上游响应泄漏进日志 | Info Disclosure | 日志只记长度/计数；异常文本走 `redact_secrets_in_text`；api_key SecretStr |
| call_source 维度基数失控 | Tampering | `CallSource.normalize` 受控枚举回退（既有机制） |

## Environment Availability
| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| LLM Provider 凭证（系统默认） | LLM 拆分成功路径 | 运行时配置（部署态有，测试态无） | — | **fail-soft 回退按行切分**（CONTEXT C 设计内，非阻断） |

**说明：** Provider 凭证缺失不阻断——正是 fail-soft 的核心场景。无需安装/探活任何外部工具。

## Assumptions Log
| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | 测试环境 `aresolve()` 因无凭证抛 `ProviderConfigError` → 既有 decompose 用例走回退得 list[str] | Pitfall 1 / Validation | 若 CI 配了默认凭证，既有用例可能走 LLM 路径而断言 list[str] 失败——plan 应让回退路径稳定产 list[str] 并/或 mock helper 隔离 |
| A2 | `category="sampling"` 为 decompose 合理取值 | 观测 | 与 clarification_questions 一致，低风险；若审计要求 caller 可调整 |
| A3 | segment dict 字段集（title/module/layer/repo_hint）为推荐而非强制 | Segment 结构 | Claude's Discretion 范围，plan 可调整字段；无下游消费方故风险低 |

## Open Questions
1. **segment schema：union(list[str]回退 + list[dict] LLM) vs 统一 list[dict]？**
   - 已知：无生产消费方，唯一约束是 `test_plan_orchestration_engine.py:41` 断言。
   - 推荐：union（回退保 list[str]，既有断言零改）；plan-phase 据团队口味定夺。
2. **是否需要 UI trace 事件（_emit_event）？**
   - 已知：CONTEXT B 只要 started/completed/failed，structlog 即满足；taxonomy 无 decompose 事件。
   - 推荐：仅 structlog 生命周期事件，不新增 taxonomy（更轻）。

## Project Constraints (from .cursor/rules/ + CLAUDE.md)
- **observability-logging.mdc（强制）**：`structlog.get_logger(__name__)`；事件 snake_case + started/completed/failed + `duration_ms`；设 `category`(sampling)/`component`(plan_orchestration)；新增 LLM 调用赋 `call_source`（PLAN_DECOMPOSE）并上报请求/token/TTFT/上游错误码；脱敏不可绕过；观测 best-effort 不反噬业务；高频循环禁 INFO 刷屏。
- **后台任务绑定触发用户**：decompose 在编排链内，`initiated_by_user_id` 由上游编排上下文承载（沿用既有 PlanSession 链路，不在本 helper 新引入入口）。
- **CLAUDE.md 约束**：复用 `ProviderCredential`/`ProviderConfigService`，不绕过加密；async ORM 经 `sync_to_async`；engine 不直接 mutate status（只经 `transition`）。

## State of the Art
| Old | Current | Impact |
|-----|---------|--------|
| `requirement_text.splitlines()` 按非空行切分 | LLM 跨仓业务线/模块/前后端结构化拆分 | 提升 routing/research 精度；旧行为降级为 fail-soft 回退 |

## Sources

### Primary (HIGH confidence — 代码实证)
- `server/services/plan_orchestration/engine.py` `_decompose` L106-124 / `advance` L70-104 — 现状 + 异常→FAILED 机制
- `server/services/plan_orchestration/repo_router_adapter.py` L29-67 — 确认 _route 只读 requirement_text/include_repos
- `server/services/plan_orchestration/clarification_questions.py` 全文 — 权威实现样板（CLARIFY-02）
- `server/agents/call_source.py` 全文 — CallSource 枚举（实测 31 值）+ use_call_source
- `server/agents/llm_factory.py` `build_chat_model` / `content_to_text` — chat model 构造 + content 归一
- `server/services/provider_config.py` `aresolve` L874-891 — 无凭证抛 ProviderConfigError
- `server/tests/services/test_plan_orchestration_engine.py` L29-42 — 既有 decompose 断言（list[str]）
- `server/tests/services/test_engine_clarify.py` L183-276 — LLM helper + fail-soft 测试范式
- `.planning/observability/LOGGING-SPEC.md` §4.1 L62-99 — call_source 表（止于 branch_naming，缺 plan_clarification）
- grep `segments` 全 server — 确认无生产消费方
- `.planning/config.json` — nyquist_validation:true, security_enforcement:true

### Secondary
- `server/pyproject.toml` `[tool.pytest.ini_options]` — 测试框架配置

## Metadata
**Confidence breakdown:**
- Standard stack: HIGH — 全部仓内既有模块，read 实证
- Architecture: HIGH — clarification_questions.py 提供 1:1 样板 + 契约 grep 确认
- Pitfalls: HIGH — 既有测试与 advance 异常机制实证

**Research date:** 2026-06-28
**Valid until:** 2026-07-28（稳定，纯内部复用，无快速变动外部依赖）
