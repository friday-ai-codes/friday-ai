# Phase 90: 澄清能力层 (clarification-capability) - Research

**Researched:** 2026-06-27
**Domain:** Django ORM 模型扩展 + 迁移 / LLM 接线 / plan_orchestration 编排能力
**Confidence:** HIGH（全部基于本仓真实代码核对，无外部依赖；签名/行号已逐一核验）

## Summary

本 phase 把「澄清」从 `delivery.Clarification` 的单 `question`/`answer` 文本行升级为**结构化父子模型**：轮次容器（沿用/扩展 `Clarification`）+ 问题行子表（新增 `ClarificationQuestion`，承载 `type`/`options`/`recommended` + 按题答案 + **持久化 `recommendation_adopted` 信号**）。同时把已写好待接线的 `clarification_questions.py`（LLM 多问题生成器）接入 `ClarifyAdapter.clarify`（静态 policy 判「要不要问」→ LLM 判「问什么」→ fail-soft 回退粗问题），并提供入口无关的统一 `ask_clarification` helper（写 `delivery.Clarification`，守 INV-6，携带 `origin_repo`）。

三条 CLARIFY 需求都落在既有 `plan_orchestration` 底座上，**严禁造第二套**。最小迁移成本是关键约束：保留现有字段（`question`/`answer`/`answered_at`/`affected_partials` M2M）不删、新增字段一律 nullable、新增子表，旧单题行读时兼容映射为「单题轮次」、迁移**不强制回填**。pending 判定从「`answered_at IS NULL`」升级为「轮次内存在未答问题」，需同步改 `ClarifyAdapter`、`resume.adrive_plan_session_to_pause_or_terminal`、`engine` 测试与 e2e 驱动 helper。

**关键风险提示**：仓内已存在**两套澄清系统**——(1) `delivery.Clarification` + `ClarificationService`（plan_orchestration，本 phase 目标）；(2) `chat.ConversationIntentTrace` + `agents/tools/clarification.py` 的 `ask_clarification` **chat tool**（LangGraph interrupt 路径，不写 delivery）。本 phase 新增的统一 `ask_clarification` helper 名称与既有 chat tool **同名**，必须用模块路径/命名区分，避免混淆（见 Pitfall 1）。

**Primary recommendation:** 用「扩展 `Clarification` 为轮次容器 + 新建 `ClarificationQuestion` 子表」的最小迁移方案；`ClarificationService` 扩展为唯一写入入口（建轮/建多问题/按题答案 + 一次性算 `recommendation_adopted`）；`ClarifyAdapter.clarify` 内接 `agenerate_clarification_questions`（fail-soft 回退现状粗问题）；`ask_clarification` helper 落 `plan_orchestration`、薄封装 `ClarificationService`。

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**A. Clarification 数据模型（核心）**
- **「推荐采纳率」必须建模**：每题带推荐答案，作答时**一次性算清并持久化** `recommendation_adopted`（bool/nullable，「用户最终选择是否=推荐」），供采纳率聚合；不靠日志事后拼、不事后重算。
- **结构化父子模型 + 绑定技术方案**：
  - 轮次容器（沿用/扩展 `Clarification`，1 个 PlanSession 可多轮 → 支撑 91 多轮）：`session` FK、`round_no`、`status`（pending/answered/skipped）、`origin_repo`（nullable，CLARIFY-03 可携带）、时间戳。
  - 问题行（新增 `ClarificationQuestion`，FK 轮次容器）：`order`、`question`(text)、`type`(single/multi)、`options`(JSON)、`recommended`(JSON：single=str / multi=list)、`origin_repo`(nullable)。
  - 答案落问题行（便于按题统计）：`selected`(JSON：single=str / multi=list[str])、`freeform_text`、`answered_at`、`recommendation_adopted`(bool/nullable)。
  - 绑定技术方案：经 `PlanSession` 关联 `TechnicalPlan`/`PlanVersion`（`session.current_plan_version`）。为采纳率分析便利，可在轮次容器上**冗余一个 nullable plan 关联**（canonical 绑定仍是 session）。
- **单一写入入口（INV-6）**：所有澄清/问题/答案写入只经 `ClarificationService`（扩展现有），不旁路写表；status 流转仍只经 `PlanSessionService.transition`。
- **向后兼容**：保留现有 `Clarification.question`/`answer`/`answered_at`/`affected_partials`(M2M) 字段不删；新增字段 nullable、新增子表；旧单题数据读时兼容映射为「单题轮次」。迁移**不强制回填历史**，但提供读取兼容层（旧行 → 1 问 1 答视图）。pending 判定从「`answered_at IS NULL`」升级为「轮次内存在未答问题」。

**B. LLM 澄清问题生成接线**
- 接入点：`ClarifyAdapter.clarify` 内——先静态 policy（routing 无 high/medium、`decomposition.ambiguous`）判「是否需澄清」，需要时再调 `agenerate_clarification_questions` 产结构化多题，经 `ClarificationService` 写入新模型。
- 职责切分：静态 policy 决定「要不要问」，LLM 只决定「问什么」（省 token、确定性可控）。
- fail-soft：LLM 返回 `[]` 或异常时，回退到现状粗问题（`default_needs_clarification` 的 hint），绝不阻断编排主流程。
- 观测：LLM 调用赋 `call_source=plan_clarification`（已存在），上报请求/token/TTFT/上游错误码；事件 `clarification_questions_generated`（category=sampling, component=plan_orchestration）。

**C. 统一 ask_clarification 能力**
- 能力落点：`plan_orchestration` 内入口无关的 `ask_clarification` helper，写 `delivery.Clarification`（INV-6），编排任意点（架构师融合 / 调研容器卡住）可调用产出结构化澄清请求。
- `origin_repo`：经轮次容器/问题行的 `origin_repo` 字段携带。
- 入口无关：工作流与对话复用同一 helper + 同一模型，不造两套。

### Claude's Discretion
- 子表命名、字段精确类型、迁移编号、采纳率聚合查询的具体 SQL/serializer 形态由 plan-phase 定。
- 「轮次容器」直接复用 `Clarification` 还是新建 `ClarificationRound`，由 plan-phase 按**最小迁移成本**定，但必须满足：多轮、多问题、按题答案 + 推荐采纳信号、绑定技术方案、INV-6。

### Deferred Ideas (OUT OF SCOPE)
- 采纳率运维大盘可视化（观测大盘范畴；本 phase 只保证数据可统计，不做新前端图表）。
- 出口面渲染/回流/多轮续推 resume → Phase 91（CLARIFY-04/05/06）。
- 入口收口（MCP/对话/工作流口径归一）→ Phase 94。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CLARIFY-01 | 结构化澄清数据模型——`Clarification` 扩展支持多问题（单/多选 + 选项 + 推荐项）+ 多答案的结构化存储（INV-6） | §Standard Stack（模型扩展方案）、§Architecture Pattern 1（父子模型 + 迁移）、§Architecture Pattern 4（recommendation_adopted 持久化）、§Common Pitfall 2（向后兼容读层） |
| CLARIFY-02 | LLM 结构化澄清问题生成——基于需求 + 路由 + 召回产多问题，`call_source=plan_clarification` | §Architecture Pattern 2（`clarification_questions.py` 接入 `ClarifyAdapter`，fail-soft）、`clarification_questions.py` 已就绪（only 接线 + 落库） |
| CLARIFY-03 | 统一「提问能力」——编排任意点经一个 `ask_clarification` 能力产结构化澄清，入口无关、携带 origin_repo | §Architecture Pattern 3（helper 落点 + 签名）、§Common Pitfall 1（与既有 chat tool 同名冲突） |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 结构化澄清持久化（轮/问题/答案/采纳信号） | Database / Storage（`delivery` app models + migration） | API/Backend（`ClarificationService` 写入收口） | 模型是 §6/§12 操作态脊柱；写入只经 service（INV-6） |
| 采纳率信号计算（`recommendation_adopted`） | API/Backend（`ClarificationService.answer`） | — | 作答时一次性算清，与答案写入同事务，避免事后重算歧义 |
| LLM 多问题生成 | API/Backend（`plan_orchestration` 纯函数 + LLM chokepoint） | — | 入口无关、只接原语不接 IO；observability 经 call_source |
| 「要不要澄清」判定 policy | API/Backend（`ClarifyAdapter` + `default_needs_clarification`） | — | 静态规则跑在编排引擎层，省 token + 确定性 |
| 统一 ask_clarification 能力 | API/Backend（`plan_orchestration` helper） | Database（写 `delivery.Clarification`） | 入口无关 helper，薄封装 service 写入 |
| pending 判定（轮次内未答） | API/Backend（`ClarifyAdapter`/`resume` 查询升级） | — | 状态机派生判定，不上模型加方法 |

## Standard Stack

本 phase **无外部新依赖**——全部复用仓内既有栈与既有模式。

### Core（既有，复用）
| 组件 | 位置 | 用途 | 为何标准 |
|------|------|------|---------|
| Django ORM `models.JSONField` | `django>=5.1`（已装） | `options`/`recommended`/`selected` 多值结构化存储 | 仓内 `PlanVersion.content`/`PlanSession.routing` 等已大量用 JSONField 存半结构化 |
| Django migrations | `delivery/migrations/` | 新增子表 + 容器新字段（nullable 不破坏旧行） | 仓标准；`makemigrations` 自动生成（含子表 FK） |
| `ClarificationService` | `server/delivery/services/clarification_service.py` | 澄清唯一写入入口（INV-6） | 已存在 `create_clarification`/`answer_clarification`，扩展即可 |
| `agenerate_clarification_questions` | `server/services/plan_orchestration/clarification_questions.py` | LLM 多问题生成（已就绪，待接线） | 已实现 normalize + fail-soft + `call_source=plan_clarification` |
| `ClarifyAdapter` | `server/services/plan_orchestration/clarify_adapter.py` | 澄清 stage 编排（policy + 落库 + emit） | 已有单轮短路 CR-01；接线点 |
| `CallSource.PLAN_CLARIFICATION` | `server/agents/call_source.py:89` | LLM 调用来源标签（已登记 30 值枚举） | 观测规范要求，已就绪 |
| `structlog` | `common.logging` | 结构化埋点（started/completed/failed + category/component） | 仓强制可观测性规范 |

### Supporting（既有，复用）
| 组件 | 位置 | 用途 |
|------|------|------|
| `build_chat_model` / `ProviderConfigService.aresolve` | `agents/llm_factory` / `services/provider_config` | LLM 模型构建 + provider 解析（`clarification_questions.py` 已用） |
| `sync_to_async` | `asgiref.sync` | async ORM 桥接（写入须包同步块，禁裸 lazy-FK） |
| `PlanSessionService.transition` | `delivery/services/plan_session_service.py:153` | status 唯一变更入口（白名单 + `ConcurrentTransitionError` 并发守卫） |
| `_emit_event` / event_taxonomy | `delivery/services/...` | `clarification.asked`/`clarification.answered` 事件（best-effort） |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| 新建 `ClarificationQuestion` 子表 | 在 `Clarification` 上加 `questions` JSONField（无子表） | JSON 内嵌**无法按题 SQL 聚合采纳率**（CONTEXT 强诉求要可统计），且按题答案/索引困难 → 否决 |
| 沿用 `Clarification` 作轮次容器 | 新建 `ClarificationRound` | 新表迁移成本更高、需迁现有 FK/测试；沿用 `Clarification` + 加 `round_no`/`status`/`origin_repo` 字段是最小迁移（CONTEXT Claude's Discretion 倾向最小成本）→ **推荐沿用** |
| `recommendation_adopted` 作答时算 | 查询时按 `selected==recommended` 现算 | 多选「命中」语义有歧义（全等/子集/交集？）、recommended 可能随轮次演化 → 作答时一次性定格更可靠（CONTEXT 锁定） |

**Installation:** 无需安装任何包（纯 Django 模型 + 迁移 + Python 接线）。

**Version verification:** 不适用（无外部包引入）。本 phase 仅新增 `delivery` 子表与 `plan_orchestration` 接线代码。

## Package Legitimacy Audit

**N/A** — 本 phase 不安装任何外部包（纯仓内模型扩展 + 迁移 + Python 接线）。无 `pip install` / `npm install` 步骤。

## Architecture Patterns

### System Architecture Diagram

```text
                ┌─────────────────────────────────────────────────────────┐
   编排引擎      │  PlanOrchestrationEngine.advance(session)                │
 (engine.py)    │    status==CLARIFYING → _clarify(session)                │
                └───────────────┬─────────────────────────────────────────┘
                                │ await self.clarify.clarify(session)
                                ▼
        ┌──────────────────────────────────────────────────────────┐
        │ ClarifyAdapter.clarify(session)   (clarify_adapter.py)     │
        │  1. 有轮内未答问题? ── yes ─► {needs:True, pending:True}    │ ◄── pending 判定升级
        │  2. 已存在已答轮? ──── yes ─► {needs:False}  (CR-01 短路)   │     (旧:answered_at IS NULL
        │  3. 首轮: static policy 判「要不要问」                       │      新:轮次内有未答问题)
        │       needs == False ─► {needs:False}                       │
        │       needs == True  ─► [B] LLM 问什么                       │
        └───────────────────────┬────────────────────────────────────┘
                                │ agenerate_clarification_questions(
                                │   requirement, routing, recall_hits)   [CLARIFY-02]
                                ▼
        ┌──────────────────────────────────────────────────────────┐
        │ clarification_questions.py (LLM, call_source=plan_clarif.) │
        │   返回 [] 或异常 ──► fail-soft 回退 policy 粗问题(单题)      │
        │   返回 [{question,type,options,recommended}, ...]           │
        └───────────────────────┬────────────────────────────────────┘
                                │ 经 ClarificationService 写入 (INV-6)
                                ▼
        ┌──────────────────────────────────────────────────────────┐
        │ ClarificationService (clarification_service.py) [CLARIFY-01]│
        │   create_round(session, questions[], origin_repo)          │
        │   ├─ Clarification(轮次容器: round_no/status/origin_repo)    │
        │   └─ ClarificationQuestion×N(order/type/options/recommended)│
        │   answer_round(round, [{question_id, selected, freeform}])  │
        │   └─ 按题写 selected/freeform/answered_at                   │
        │      + 一次性算 recommendation_adopted  ◄── [CLARIFY-04 信号]│
        └───────────────────────┬────────────────────────────────────┘
                                │ emit clarification.asked / .answered (best-effort)
                                ▼
                       delivery_clarification (轮)
                       delivery_clarification_question (问+答)  ── SQL 聚合采纳率

   统一能力 [CLARIFY-03]: plan_orchestration.ask_clarification(session, questions,
       *, origin_repo=None) — 入口无关 helper，薄封装 ClarificationService.create_round。
       编排任意点(架构师融合/调研容器卡住)调用；工作流+对话复用同一 helper+同一模型。

   续推短路: resume.adrive_plan_session_to_pause_or_terminal(engine, session)
       CLARIFYING 且「轮内有未答问题」→ 立即短路返回(保护 HITL)  ◄── 判定同步升级
```

### Recommended Project Structure（变更落点，全部既有文件 + 1 新模型文件）
```
server/delivery/
├── models/
│   ├── clarification.py          # 扩展 Clarification(容器) + 新增 ClarificationQuestion
│   └── __init__.py               # re-export ClarificationQuestion
├── migrations/
│   └── 0026_clarification_questions.py   # 新迁移(依赖 0025)，nullable 字段 + 子表
└── services/
    └── clarification_service.py  # 扩展: create_round / answer_round / 兼容旧 API

server/services/plan_orchestration/
├── clarify_adapter.py            # 接线 clarification_questions + pending 判定升级
├── clarification_questions.py    # 已就绪(无需改逻辑，仅被调用)
├── ask_clarification.py          # 新增统一 helper(CLARIFY-03)  或并入既有模块
└── resume.py                     # pending 短路判定升级
```

### Pattern 1: 父子模型 + 最小迁移（CLARIFY-01）
**What:** 沿用 `Clarification` 作轮次容器（加 `round_no`/`status`/`origin_repo`/可选 `plan_version_id` nullable 字段），新建 `ClarificationQuestion` 子表（FK 容器 + `order`/`question`/`type`/`options`/`recommended`/`origin_repo`/`selected`/`freeform_text`/`answered_at`/`recommendation_adopted`）。
**When to use:** 需要「按题 SQL 聚合」时——JSON 内嵌无法满足。
**关键迁移约束（VERIFIED: 本仓 migrations）:**
- delivery app **最新迁移 = `0025_rename_project_to_space`**（单一 head，无未合并分支）。新迁移编号 **`0026_*`，`dependencies = [('delivery', '0025_rename_project_to_space')]`**。
- 现有 `Clarification` 表 `delivery_clarification`（migration `0016_clarification`），含 `question`/`answer`/`answered_at`/`affected_partials`(M2M)/`session`(FK CASCADE)。新增字段**一律 `null=True, blank=True`**（旧行不强制回填，不破坏 0016 schema）。
- 子表 FK 容器用 `on_delete=CASCADE` + `related_name="questions"`，对齐 `Clarification.session` 范式。
**Example（模型骨架，plan-phase 定精确字段类型）:**
```python
# server/delivery/models/clarification.py
class Clarification(models.Model):  # 复用为轮次容器
    # ... 既有字段保留不删 ...
    round_no = models.PositiveIntegerField(null=True, blank=True)        # 多轮序号
    container_status = models.CharField(max_length=16, null=True, blank=True)  # pending/answered/skipped
    origin_repo = models.CharField(max_length=255, null=True, blank=True)      # CLARIFY-03
    plan_version_id = models.UUIDField(null=True, blank=True)            # 冗余绑定(canonical 仍 session)

class ClarificationQuestion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    clarification = models.ForeignKey("delivery.Clarification", on_delete=models.CASCADE,
                                      related_name="questions")
    order = models.PositiveIntegerField(default=0)
    question = models.TextField()
    qtype = models.CharField(max_length=8, default="single")  # single/multi  (避开 type 关键字)
    options = models.JSONField(default=list)
    recommended = models.JSONField(default=list)              # single 存 [str]/multi 存 list
    origin_repo = models.CharField(max_length=255, null=True, blank=True)
    selected = models.JSONField(null=True, blank=True)        # 答案: single=str / multi=list
    freeform_text = models.TextField(blank=True, default="")
    answered_at = models.DateTimeField(null=True, blank=True)
    recommendation_adopted = models.BooleanField(null=True, blank=True)  # 作答时定格
```
> **注意（避免误判 status 字段名）**：`Clarification` 上不要直接叫 `status`（避免与 `PlanSession.status` 语义混淆，也避免迁移把它当状态机字段）；用 `container_status` 等命名由 plan-phase 定。`type` 是 Python 内建，字段名用 `qtype`/`question_type` 规避。

### Pattern 2: `clarification_questions.py` 接入 `ClarifyAdapter`（CLARIFY-02）
**What:** `ClarifyAdapter.clarify` 第 3 步（首轮 needs==True）后，调 `agenerate_clarification_questions(requirement, routing, recall_hits)` 取结构化多题；空/异常 fail-soft 回退 `default_needs_clarification` 的单粗问题。
**关键既有签名（VERIFIED: clarification_questions.py:132）:**
```python
async def agenerate_clarification_questions(
    *, requirement: str, routing: dict|None=None, recall_hits: list|None=None,
    max_questions: int = 5,
) -> list[dict]:  # [{question,type,options,recommended}]，best-effort 绝不抛，信息足/失败返回 []
```
**接入点上下文（clarify_adapter.py:109-118 现状）:** 首轮 `needs, question, affected = self.policy(session)`，需澄清时 `create_clarification(session, question, affected)` 建**单题**。改造为：
1. `requirement` 取 `session.decomposition.get("requirement_text")`（engine.py:114 已是此源）。
2. `routing` 取 `session.routing`（dict）；`recall_hits` 取 `session.recall_context`（list，PlanSession.recall_context default=list）。
3. `questions = await agenerate_clarification_questions(requirement=..., routing=..., recall_hits=...)`。
4. `questions` 非空 → `ClarificationService.create_round(session, questions, origin_repo=None)`；空 → fail-soft 回退建单题轮（用 policy 的 `question` 文本，1 题 type=single 无 options）。
5. emit `clarification.asked`（payload 升级为多题摘要，best-effort）。
**fail-soft 边界:** `agenerate_clarification_questions` 自身已 try/except 返回 `[]`（绝不抛）；adapter 侧只需「`[]` → 回退粗问题」一处分支即可。**绝不**因 LLM 失败让 clarify stage 抛异常（否则 engine.advance 通用 except 会落 `failed`）。
**观测:** LLM 调用埋点 `clarification_questions_generated`（已在 `clarification_questions.py:163` 实现，category=sampling/component=plan_orchestration）；adapter 侧新增「回退」时记 `clarification_fallback_coarse_question`（category=sampling）。

### Pattern 3: 统一 ask_clarification helper（CLARIFY-03）
**What:** `plan_orchestration` 内入口无关 helper，薄封装 `ClarificationService` 写入轮次容器 + 多问题，携带 `origin_repo`。编排任意点（`ArchitectMergeAdapter` 融合卡住 / 某调研容器卡住）调用。
**建议签名（plan-phase 定细节）:**
```python
# server/services/plan_orchestration/ask_clarification.py
async def ask_clarification(
    session: PlanSession,
    questions: list[dict],            # [{question,type,options,recommended,origin_repo?}]
    *,
    origin_repo: str | None = None,
    clarification_service: ClarificationService | None = None,
) -> Clarification:
    """入口无关：写 delivery.Clarification 轮 + 多问题(INV-6)。不驱动 advance/不挂起。"""
```
**入口无关原则（VERIFIED: STATE.md:251-252、resume.py docstring）:** helper 只**建澄清请求**（写库），**不**驱动 engine.advance、**不**做挂起 marker（挂起是入口私有：工作流 waiting_event / chat interrupt）。对齐 `entrypoint.py`「驱动是入口私有」精神。
**与 ClarifyAdapter 的关系:** `ClarifyAdapter.clarify` 走的是「engine 自动澄清」路径；`ask_clarification` helper 是「编排代码主动发问」路径。两者都最终落 `ClarificationService.create_round`（同一写入收口），不造两套写库逻辑。

### Pattern 4: recommendation_adopted 持久化 + 可查询（CLARIFY-01 强诉求）
**What:** 作答时（`answer_round`）按题计算「selected 是否命中 recommended」并写入 `ClarificationQuestion.recommendation_adopted`（bool/nullable）。nullable 语义：未作答 / 无推荐项 / freeform-only → `None`（不计入分母）。
**命中判定（plan-phase 定，建议）:**
- `single`: `selected == recommended[0]`（recommended 存为 `[str]` 或 str）。
- `multi`: `set(selected) == set(recommended)`（全等；CONTEXT 未指定子集语义，全等最无歧义；plan-phase 可调）。
- 无 `recommended` 或纯 freeform → `None`。
**可查询（聚合采纳率 SQL，无需新前端）:**
```python
from django.db.models import Count, Q
ClarificationQuestion.objects.filter(recommendation_adopted__isnull=False).aggregate(
    total=Count("id"),
    adopted=Count("id", filter=Q(recommendation_adopted=True)),
)  # 采纳率 = adopted / total
```
> 本 phase 只保证「数据可统计」——聚合查询/serializer 形态由 plan-phase 定；大盘可视化是 Phase 91+ 范畴（CONTEXT Deferred）。

### Pattern 5: pending 判定升级（answered_at IS NULL → 轮内有未答问题）
**What:** 三处「pending = `answered_at IS NULL`」查询升级为「轮次内存在 `ClarificationQuestion.answered_at IS NULL`」。
**需同步的三处（VERIFIED: 行号）:**
1. `clarify_adapter.py:91-94`（`has_pending`）、`:103-105`（`has_answered`）。
2. `resume.py:63-68`（CLARIFYING 短路 `has_pending`）。
3. `clarification_service.py:92-94`（`answer` 的条件更新前置 `answered_at__isnull=True`）→ 升级为按题条件更新。
**向后兼容查询:** 旧单题行无子表 question 时，pending 判定须把「容器有 `answered_at IS NULL` 且无任何 question 子行」也视作旧式单题 pending（读兼容层，见 Pitfall 2）。建议用 service 上的统一谓词函数 `ahas_pending(session_id)` 收口，三处都调它（避免判定逻辑散落漂移）。

### Anti-Patterns to Avoid
- **把 `recommendation_adopted` 留给查询时现算**：多选命中语义随推荐演化会漂移 → 必须作答时定格（CONTEXT 锁定）。
- **JSON 内嵌问题数组**：无法按题 SQL 聚合采纳率 → 必须子表。
- **旁路写 `Clarification.objects.create`/`.save`**：违反 INV-6（有 grep 守护测试 `test_inv6_clarification_single_write_entry`，会失败）→ 只经 `ClarificationService`。
- **clarify stage 让 LLM 异常上抛**：会被 engine 落 `failed` → 必须 fail-soft（`clarification_questions.py` 已 best-effort，adapter 侧勿再加抛点）。
- **新 helper 与 chat tool 同名混用**：见 Pitfall 1。
- **async 裸 lazy-FK**：`clarification.session` 等同步 lazy-FK 在 async 上下文会崩（Phase 38 CR-01 类）→ 用 `session_id` 标量 / `.values_list` / `sync_to_async` 同步块。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| LLM 多问题生成 + JSON 健壮解析 + normalize | 新写 prompt/解析器 | `agenerate_clarification_questions` / `normalize_clarification_questions`（`clarification_questions.py` 已就绪） | 已实现 ```json 代码块/裸 JSON 提取、type/options/recommended 防御归一、fail-soft、call_source 埋点 |
| LLM provider 解析 + model 构建 | 直接 import SDK | `ProviderConfigService.aresolve` + `build_chat_model` | 仓统一凭证(加密)/provider 解析；`clarification_questions.py` 已用 |
| call_source 上报 | 手写指标标签 | `use_call_source(CallSource.PLAN_CLARIFICATION)` | 已登记枚举 + chokepoint 自动上报 token/TTFT/错误码 |
| status 流转 | 直接 `session.status = ...` | `PlanSessionService.transition` | 白名单校验 + `ConcurrentTransitionError` 并发守卫 + 事件 emit |
| 澄清写库 | `Clarification.objects.create` 散落 | `ClarificationService`（扩展） | INV-6 单一写入，有 grep 守护测试 |
| 事件信封 | 手拼 dict | `_emit_event` + `event_taxonomy.EVENT_CLARIFICATION_*` | best-effort 落 `PlanSessionEvent`，绝不阻断主流程 |

**Key insight:** 本 phase 90% 是「接线 + 模型扩展」，几乎所有难点（LLM 解析、fail-soft、observability、状态机、并发守卫、INV-6）都已在仓内有现成基建。最大工作量在**模型迁移 + service 扩展 + 三处 pending 判定升级 + 测试同步**，而非新算法。

## Runtime State Inventory

> 本 phase 含模型迁移（rename/扩展类），按 researcher 协议逐类核对。

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `delivery_clarification` 表既有行（旧单 `question`/`answer` 单题语义）。本地/已部署可能有历史澄清行。 | **读兼容层**（旧行 → 1 问 1 答视图）；CONTEXT 锁定**不强制回填**。新字段 nullable 保证旧行 migrate 后仍可读。 |
| Live service config | None — 澄清数据全在 DB，不在外部 UI/服务配置中。无 n8n/Datadog/Tailscale 等外部注册。 | 无 |
| OS-registered state | None — 无 Task Scheduler/launchd/systemd/pm2 引用澄清。 | 无 |
| Secrets/env vars | None — 澄清模型不引用任何 secret/env 名；LLM 凭证经 `ProviderCredential`（既有，不改）。 | 无 |
| Build artifacts | None — 无 egg-info/编译产物绑定澄清字符串；新增子表由 `makemigrations` 自动产出。 | 迁移后跑 `migrate` 建子表（部署/CI 自动执行）。 |

**关键迁移依赖（再次强调）:** 新迁移 `0026_*` 依赖 `delivery.0025_rename_project_to_space`（当前单一 head）。子表 + 容器新字段在一个迁移内建（FK/索引由 `makemigrations` 自动）。

## Common Pitfalls

### Pitfall 1: 与既有 chat `ask_clarification` tool 同名冲突
**What goes wrong:** 仓内已有 `server/agents/tools/clarification.py` 的 `ask_clarification`（`@tool` 装饰、`CLARIFICATION_PENDING_MARKER="ask_clarification"`、写 `chat.ConversationIntentTrace` 不写 delivery、走 LangGraph interrupt）。CLARIFY-03 要的是 `plan_orchestration` 内**写 `delivery.Clarification`** 的另一个能力，若同名同导出会引发 import 混淆 / 误调。
**Why it happens:** 两套澄清子系统并存（chat tool 路径 vs plan_orchestration 路径）；命名空间撞车。
**How to avoid:** 新 helper 放 `services/plan_orchestration/`（不同包），导出名可保留 `ask_clarification` 但**通过模块路径区分**（`from services.plan_orchestration import ask_clarification`）；或显式命名 `ask_plan_clarification` 由 plan-phase 定。**绝不**改/复用 `agents/tools/clarification.py`（那是 chat 入口资产，Phase 94 才统一）。
**Warning signs:** import 报错 / 测试拿到错的 `ask_clarification` / chat clarification 行为漂移。

### Pitfall 2: 向后兼容读层缺失导致旧行被判「无 pending」
**What goes wrong:** pending 判定升级为「轮内有未答 question 子行」后，**旧单题行没有任何 `ClarificationQuestion` 子行**，会被新查询判为「无 pending」→ 历史挂起的旧澄清被误放行。
**Why it happens:** 旧行只有容器 `answered_at`，无子表。
**How to avoid:** 统一 pending 谓词须兼容两形态：`(容器有 answered_at IS NULL 子题) OR (容器 answered_at IS NULL 且无任何子题)`。建议 service 收口 `ahas_pending(session_id)`，三处调它（见 Pattern 5）。读兼容层把旧行映射为「1 问 1 答」视图（`question`→单题、`answer`/`answered_at`→该题答案）。
**Warning signs:** 历史澄清 session resume 时直接跳过 clarifying。

### Pitfall 3: INV-6 grep 守护误判 / 漏守新模型
**What goes wrong:** `test_inv6_clarification_single_write_entry`（`test_clarification_service.py:146`）grep 全仓 `Clarification.objects.create` 仅许 `clarification_service.py`。新增 `ClarificationQuestion.objects.create` 旁路写也须守护，否则 INV-6 出现缺口。
**Why it happens:** 守护测试当前只 grep `Clarification.objects.create`，未覆盖子模型。
**How to avoid:** 扩展守护断言覆盖 `ClarificationQuestion.objects.create`/`.save`（或正则覆盖两模型）；所有子表写入只经 `ClarificationService`。docstring 内若出现 `ClarificationQuestion(...)` 字面用全角括号避 grep 误判（STATE.md:275 有先例）。
**Warning signs:** grep 守护测试红 / 出现 service 外的子表写入。

### Pitfall 4: async 上下文裸 lazy-FK（Phase 38 CR-01 类）
**What goes wrong:** 在 async 服务里 `clarification.session.xxx` / `question.clarification.xxx` 裸访问同步 lazy-FK → `SynchronousOnlyOperation`。
**How to avoid:** 用 `*_id` 标量、`.values_list(..., flat=True)`、`.afirst()`/`.aexists()`、写入包 `sync_to_async` 同步块（`clarification_service.py` 既有范式：`_create_sync`/`_answer_sync`）。
**Warning signs:** 测试/运行时 `SynchronousOnlyOperation`。

### Pitfall 5: `recommended` 与 `options` 不一致 / 多选语义
**What goes wrong:** LLM 给的 `recommended` 不在 `options` 内，或多选命中判定语义不清 → 采纳率统计失真。
**How to avoid:** `normalize_clarification_questions`（已实现，`clarification_questions.py:62`）已过滤 `recommended` 必须 ∈ `options`、multi 归一为 list、single 归一为 str；写库前**必经 normalize**。多选命中用 `set(selected)==set(recommended)`（全等），plan-phase 锁定语义并写进 docstring。
**Warning signs:** 采纳率 >100% / `recommendation_adopted` 异常分布。

## Code Examples

### 扩展 ClarificationService：建轮 + 多问题（INV-6，async 安全）
```python
# server/delivery/services/clarification_service.py（扩展，plan-phase 定细节）
class ClarificationService:
    async def create_round(
        self, session, questions: list[dict], *, origin_repo: str | None = None,
        round_no: int | None = None, plan_version_id=None,
    ) -> Clarification:
        return await self._create_round_sync(session, questions, origin_repo, round_no, plan_version_id)

    @sync_to_async
    def _create_round_sync(self, session, questions, origin_repo, round_no, plan_version_id):
        clar = Clarification.objects.create(
            session=session, question="", origin_repo=origin_repo,
            round_no=round_no, plan_version_id=plan_version_id,
        )  # question="" 占位保旧 NOT NULL 列；真身在子表
        ClarificationQuestion.objects.bulk_create([
            ClarificationQuestion(
                clarification=clar, order=i, question=q["question"],
                qtype=q.get("type", "single"), options=q.get("options", []),
                recommended=q.get("recommended", []), origin_repo=origin_repo,
            ) for i, q in enumerate(questions)
        ])
        return clar
```

### 作答 + 定格 recommendation_adopted（按题）
```python
    @sync_to_async
    def _answer_question_sync(self, question_id, selected, freeform_text) -> bool:
        q = ClarificationQuestion.objects.filter(id=question_id, answered_at__isnull=True).first()
        if q is None:
            return False  # 幂等 no-op（已答）
        adopted = None
        rec = q.recommended or []
        if rec:  # 有推荐才计入采纳率分母
            if q.qtype == "multi":
                adopted = set(selected or []) == set(rec)
            else:
                want = rec[0] if isinstance(rec, list) else rec
                adopted = (selected == want)
        ClarificationQuestion.objects.filter(id=question_id, answered_at__isnull=True).update(
            selected=selected, freeform_text=freeform_text or "",
            answered_at=timezone.now(), recommendation_adopted=adopted,
        )
        return True
```

### 接线 ClarifyAdapter（fail-soft 回退）
```python
# clarify_adapter.py 首轮分支改造（needs==True 后）
questions = await agenerate_clarification_questions(
    requirement=(session.decomposition or {}).get("requirement_text", ""),
    routing=session.routing if isinstance(session.routing, dict) else None,
    recall_hits=session.recall_context if isinstance(session.recall_context, list) else None,
)
if questions:
    clar = await self.clarification_service.create_round(session, questions, origin_repo=None)
else:  # fail-soft 回退现状粗问题（policy 给的单题）
    logger.info("clarification_fallback_coarse_question", category="sampling",
                component="plan_orchestration", session_id=str(session.id))
    clar = await self.clarification_service.create_round(
        session, [{"question": question, "type": "single", "options": [], "recommended": []}],
    )
await self._emit_asked(session, clar, question)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `Clarification` 单 `question`/`answer` 文本行 | 轮次容器 + `ClarificationQuestion` 子表（多问题/单多选/推荐/按题答案/采纳信号） | 本 phase 90 | 支撑多轮(91)、出口面卡片、采纳率统计 |
| `ClarifyAdapter` 只产 1 句粗问题（`default_needs_clarification` hint） | static policy 判「要不要」+ LLM 判「问什么」(结构化多题) | 本 phase 90 | 澄清更聚焦、可交互；fail-soft 保底 |
| pending = 容器 `answered_at IS NULL` | pending = 轮内有未答 `ClarificationQuestion`（兼容旧行） | 本 phase 90 | 支撑多题部分作答语义 |
| 编排无统一主动发问能力 | `plan_orchestration.ask_clarification` 入口无关 helper | 本 phase 90 | 任意编排点可发结构化澄清 |

**Deprecated/outdated:** 无删除项——全部向后兼容（旧字段/旧 API 保留）。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | 沿用 `Clarification` 作轮次容器（而非新建 `ClarificationRound`）是最小迁移 | Pattern 1 | 若团队偏好独立轮表，需调整迁移（CONTEXT 已授权 plan-phase 定，低风险） |
| A2 | 多选命中判定用 `set(selected)==set(recommended)`（全等语义） | Pattern 4 | 若期望子集/交集语义，采纳率口径不同（plan-phase 锁定即可，低风险） |
| A3 | 旧单题 pending 兼容须 `(无子题 且容器 answered_at IS NULL)` 也算 pending | Pitfall 2 | 若误，历史挂起澄清被跳过（中风险，已给收口方案） |
| A4 | helper 命名沿用 `ask_clarification` 但靠模块路径区分（或改名 `ask_plan_clarification`） | Pitfall 1 | 命名撞车致 import 混淆（低风险，plan-phase 决策） |

**说明:** 以上均为「实现形态选择」类假设，CONTEXT 已把这些显式划入 Claude's Discretion / plan-phase 决策，无需用户额外确认；功能契约（多轮/多题/按题答案+采纳信号/绑定方案/INV-6）已锁定。

## Open Questions

1. **`question=""` 占位 vs 容器 question 字段可空化**
   - What we know: 旧 `Clarification.question` 是 `TextField()`（NOT NULL，无 default）。新轮次容器真身在子表。
   - What's unclear: 容器 `question` 留空串占位，还是迁移改为 `null=True`？
   - Recommendation: 留 `default=""` 占位（不改旧列约束，零风险）；plan-phase 可选改 nullable。

2. **多轮 round_no 的分配 / 是否本 phase 真正产生多轮**
   - What we know: CONTEXT 说「支撑 91 多轮」，91 才做多轮 resume。
   - What's unclear: 本 phase 是否需要写 `round_no` 递增逻辑，还是先恒为 1（首轮）。
   - Recommendation: 本 phase 建模支持 `round_no`，service 写入时按 `session` 已有轮数 +1（最小实现），多轮续推交 91。

## Environment Availability

> SKIPPED — 本 phase 无新增外部依赖（纯 Django 模型/迁移 + Python 接线）。LLM 调用复用既有 `ProviderConfigService`/`build_chat_model`（已在 `clarification_questions.py` 使用，运行时由部署 provider 凭证保障，非本 phase 引入）。无新工具/服务/CLI/runtime 需探测。

## Validation Architecture

> `workflow.nyquist_validation = true`（config.json 已确认）→ 本节适用。

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `pytest>=9.0.2` + `pytest-asyncio` + `pytest-django>=4.8`（VERIFIED: `server/pyproject.toml` / CLAUDE.md STACK） |
| Config file | `server/pyproject.toml`（`[tool.pytest.ini_options]`） |
| Quick run command | `cd server && uv run pytest tests/delivery/test_clarification_service.py tests/services/test_engine_clarify.py -x` |
| Full suite command | `cd server && uv run pytest`（delivery + plan_orchestration 相关全跑） |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CLARIFY-01 | 建轮 + 多问题子表 + 按题答案落库 | unit | `uv run pytest tests/delivery/test_clarification_service.py -x` | ✅ 扩展（现 5 测） |
| CLARIFY-01 | `recommendation_adopted` 作答时定格（single/multi/无推荐→None） | unit | `uv run pytest tests/delivery/test_clarification_service.py -k adopted -x` | ❌ Wave 0（新增用例） |
| CLARIFY-01 | 采纳率聚合查询（adopted/total） | unit | `uv run pytest tests/delivery/test_clarification_service.py -k adoption_rate -x` | ❌ Wave 0 |
| CLARIFY-01 | 向后兼容：旧单题行读映射 + 仍判 pending | unit | `uv run pytest tests/delivery/test_clarification_service.py -k legacy -x` | ❌ Wave 0 |
| CLARIFY-01 | INV-6 grep 守护扩展覆盖 `ClarificationQuestion` | unit | `uv run pytest tests/delivery/test_clarification_service.py -k inv6 -x` | ✅ 改造（现 `test_inv6_clarification_single_write_entry`） |
| CLARIFY-02 | `ClarifyAdapter` 接 LLM 多题 + 写轮 | unit | `uv run pytest tests/services/test_engine_clarify.py -x` | ✅ 扩展（现 8 测） |
| CLARIFY-02 | fail-soft：LLM 返回 `[]`/异常 → 回退粗单题、不抛 | unit | `uv run pytest tests/services/test_engine_clarify.py -k fail_soft -x` | ❌ Wave 0 |
| CLARIFY-02 | pending 判定升级（轮内未答）+ CR-01 单轮短路零回归 | unit | `uv run pytest tests/services/test_engine_clarify.py -x` | ✅ 改造 |
| CLARIFY-03 | `ask_clarification` helper 写 delivery.Clarification（INV-6、origin_repo） | unit | `uv run pytest tests/services/test_ask_clarification_helper.py -x` | ❌ Wave 0（新建，勿与 `test_ask_clarification_tool.py` 混淆） |
| CLARIFY-01/02 | resume 短路：CLARIFYING 轮内未答 → 短路返回 | unit | `uv run pytest tests/services/test_plan_research_e2e.py -k clarif -x` | ✅ e2e 驱动 helper 同步升级 |

### Sampling Rate
- **Per task commit:** `cd server && uv run pytest tests/delivery/test_clarification_service.py tests/services/test_engine_clarify.py -x`
- **Per wave merge:** `cd server && uv run pytest tests/delivery/ tests/services/ -q`
- **Phase gate:** `cd server && uv run pytest` 全绿 + INV-6 grep 守护通过 + plan_orchestration e2e 零回归。

### Wave 0 Gaps
- [ ] `tests/delivery/test_clarification_service.py` — 新增 `recommendation_adopted`（single/multi/无推荐/freeform→None）、采纳率聚合、向后兼容旧行、按题幂等作答用例；改造 INV-6 守护覆盖子模型。
- [ ] `tests/services/test_engine_clarify.py` — 新增 LLM 多题接线（mock `agenerate_clarification_questions`）、fail-soft 回退、pending 判定升级用例；保 CR-01 单轮短路 8 测零回归。
- [ ] `tests/services/test_ask_clarification_helper.py` — 新建（CLARIFY-03 helper，写 delivery + origin_repo + INV-6），**文件名/导入须与既有 `tests/test_ask_clarification_tool.py`（chat tool）显式区分**。
- [ ] `tests/services/test_plan_research_e2e.py` — `_drive_*` helper 的 CLARIFYING pending 查询（行 178-184）从 `Clarification.answered_at IS NULL` 升级为「轮内未答 question」；保 `test_e2e_clarification_loop_reruns_only_affected` 绿。
- Framework install: 无（pytest 既装）。

## Security Domain

> `security_enforcement = true`、`security_asvs_level = 1`、`security_block_on = "high"`（config.json 确认）。

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | 本 phase 不引入认证逻辑（答复 endpoint 鉴权是 Phase 91） |
| V3 Session Management | no | 复用既有 JWT/会话，不改 |
| V4 Access Control | no（本 phase） | 答复回流/owner gate 在 Phase 91（CLARIFY-04/06 endpoint）；本 phase 仅模型 + service 写入 |
| V5 Input Validation | **yes** | `normalize_clarification_questions`（已实现）防御 LLM 产出非法字段；`selected` 写库前校验 ∈ `options`（plan-phase 加） |
| V6 Cryptography | no | 无新凭证；LLM 凭证经既有 `ProviderCredential` Fernet 加密（不改） |
| V7 Error/Logging | **yes** | 观测埋点脱敏（needs/question 文本非凭证，但日志走 `redact_credentials` processor）；事件 best-effort 不反噬 |

### Known Threat Patterns for plan_orchestration + LLM
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| LLM 产出注入非法/超量问题（DoS/脏数据） | Tampering / DoS | `normalize_clarification_questions` 截断 `max_questions=5` + 字段防御归一（已实现） |
| `recommendation_adopted` 被外部输入污染采纳率维度 | Tampering | server 端作答时计算（不接受客户端传入 adopted），与答案写入同事务 |
| 上游 LLM 响应体/异常文本泄漏到日志 | Info Disclosure | `clarification_questions.py` 异常只记 `str(exc)`，遵 `redact_secrets_in_text`；question 文本非密钥 |
| 旁路写绕过 INV-6 收口 | Tampering | grep 守护测试（扩展覆盖子模型） |
| async 裸 lazy-FK 崩主流程 | DoS（可用性） | 标量 `*_id` + `sync_to_async` 同步块（既有范式） |

> 本 phase 不涉及对外 endpoint（答复回流在 91），故 V4 访问控制不在本 phase 范围；security_block_on=high 下本 phase 主要风险面是 V5 输入校验（已有 normalize 兜底）。

## Sources

### Primary (HIGH confidence) — 全部本仓真实代码
- `server/delivery/models/clarification.py`（现 Clarification 单题模型 + INV-6 docstring）
- `server/delivery/services/clarification_service.py`（create/answer，`answered_at IS NULL` 条件更新）
- `server/delivery/models/plan_session.py`（PlanSession 8 态机、`current_plan_version` 软引用、`recall_context` default=list）
- `server/delivery/models/technical_plan.py`（TechnicalPlan/PlanVersion/PlanExternalRef）
- `server/services/plan_orchestration/clarify_adapter.py`（policy + CR-01 单轮短路 + pending 判定行 91-105）
- `server/services/plan_orchestration/clarification_questions.py`（LLM 多问题生成器，已就绪：签名行 132、normalize 行 62、埋点行 163）
- `server/services/plan_orchestration/engine.py`（`_clarify` 行 170-195、requirement 源行 114）
- `server/services/plan_orchestration/resume.py`（CLARIFYING 短路行 63-68）
- `server/agents/call_source.py`（`CallSource.PLAN_CLARIFICATION` 行 89，30 值枚举）
- `server/agents/tools/clarification.py`（**既有同名 chat tool**——撞名风险源，行 36/163）
- `server/delivery/services/plan_session_service.py`（transition 行 153、_emit_event 行 265、ConcurrentTransitionError）
- `server/delivery/services/event_taxonomy.py`（`EVENT_CLARIFICATION_ASKED/ANSWERED` 行 54-55）
- migrations：`delivery` 最新 head = `0025_rename_project_to_space`（`0016_clarification` 建表）
- tests：`test_clarification_service.py`(INV-6 守护)、`test_engine_clarify.py`(8 测)、`test_plan_research_e2e.py`(e2e 驱动 helper)、`test_ask_clarification_tool.py`(chat tool，**勿混淆**)、`test_clarification_resume.py`/`test_clarification_answer_endpoint.py`(chat 侧 ConversationIntentTrace 路径)
- `.planning/REQUIREMENTS.md`（CLARIFY-01/02/03 行 23-25）、`.planning/STATE.md`（INV-6/plan_orchestration 约束）、`.planning/config.json`（nyquist/security）
- `./AGENTS.md`（可观测性强制规范）

### Secondary / Tertiary
- 无（本 phase 不依赖外部文档/网络源）。

## Project Constraints (from .cursor/rules/ + AGENTS.md)

强制可观测性/日志规范（`.cursor/rules/observability-logging.mdc` + AGENTS.md）——本 phase 必须遵守：
- 新增 LLM 调用赋 `call_source=plan_clarification`（已有），上报请求数/token/TTFT/上游错误码；事件 `clarification_questions_generated`（category=sampling, component=plan_orchestration，已实现）。
- 关键生命周期 started/completed/failed 结构化事件 + `duration_ms`（澄清生成/作答）。
- `category`（caller/sampling）+ `component` 必设；澄清 LLM 步骤属 `sampling`。
- 绑定触发用户：编排后台任务带 `initiated_by_user_id`，无触发用户标 `system`。
- 脱敏不可绕过：凭证/上游响应/异常文本走 `redact_credentials`/`redact_secrets_in_text`。
- 写入收口 INV-6（澄清/问题/答案只经 `ClarificationService`）；status 只经 `PlanSessionService.transition`。
- async ORM 走 `sync_to_async`，禁裸 lazy-FK。
- 观测代码 best-effort，绝不反噬业务（事件 emit 失败只 warning）。
- i18n 默认中文（澄清问题/选项文案中文优先）。
- 高频循环禁 INFO 刷屏。

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 无外部依赖，全部既有基建，签名/行号逐一核验。
- Architecture: HIGH — 接入点/数据流/迁移依赖均基于真实代码，迁移 head 已确认 0025。
- Pitfalls: HIGH — 同名 tool 冲突、INV-6 守护、向后兼容、async lazy-FK 均有代码佐证。
- Validation: HIGH — 测试现状逐文件核对（INV-6 守护/8 测/e2e 驱动 helper 行号确认）。

**Research date:** 2026-06-27
**Valid until:** 30 天（仓内稳定代码；唯一时效项是 delivery migration head——执行前用 `ls server/delivery/migrations/` 复核是否仍为 0025）。




