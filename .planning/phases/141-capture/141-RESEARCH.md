# Phase 141: Capture 账本与仓库挂钩 - Research

**Researched:** 2026-08-28
**Domain:** Django 独立 Capture 账本 / INV-6 唯一写入 / 仓库挂钩 / 脱敏与 caller 观测
**Confidence:** HIGH（接缝均对照当前 `server/` 源码与 CONTEXT 锁定决策；git 多命中文案与未挂 Space 仓库的挂钩 reason 为 MEDIUM 推荐）

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- 模型放在 `initiatives` app，命名为 `SessionCapture`，数据库表命名为 `initiative_session_captures`；它是独立 Capture 账本，不复用 `ProjectMemory` 或 Interaction Ledger。
- `project` 与 `repository` 外键都允许为空；以仓库为主挂钩，项目仅为可选上下文。
- 正文只保存结构化 `question`、可见 `answer` 精华和标量元数据；不保存完整 transcript、隐藏思维链或 Ledger payload。
- 状态机预留 `pending_eval`、`eval_failed`、`ingest_pending` 等后续阶段所需状态；本阶段新建记录只进入 `pending_eval`。
- 幂等键采用触发用户、`session_id` 与规范化问题哈希的组合；重复提交返回既有 Capture，不重复落账。
- `session_id` 缺失时仍接受写入，并为该次 Capture 使用稳定可审计的后备标识，不以缺少会话号拒绝数据。
- 仓库解析顺序固定为显式 `repository_id`、规范化 `git_url`，再结合可选 `project_id` 校验上下文；任何解析失败都保留 Capture，并写明确 `reason`。
- 提交者不是项目成员或无权访问目标仓库时，不建立未授权外键关系，但仍保存归属于该用户的 Capture 和拒绝挂钩原因；读取与回放继续按仓库可见性和本人归属 fail-closed。
- Phase 141 仅定义持久化所需状态字段与初始 `pending_eval`，不调用 LLM、不计算 high/medium/low。
- Phase 143 才负责持久化后的 durable 评估调度、失败重试和触发用户上下文重绑定。
- Phase 141 不调用 `aschedule_ingestion`、`background_runner`、`MemoryService.append` 或 `record_hook_writeback`。
- 原始问题与答案永远是 Capture 回放数据；后续只有评估产生的可检索精华可作为 `source_kind=session_capture` 入图。
- 所有写入只能经 INV-6 `CaptureService`；增加静态 grep 守卫，禁止业务代码旁路调用 `SessionCapture.objects.create`、`bulk_create`、`get_or_create`、`update_or_create` 或直接更新状态。
- `CaptureService` 在落库前统一调用现有脱敏能力；未知的 model、provider、token 字段保存为字面值 `unknown`，服务端不猜测。
- 持久化记录 `session_capture_persist_started/completed/failed` caller 事件，统一 `component=knowledge`，completed/failed 带 `duration_ms`、`initiated_by_user_id`、Capture/挂钩结果等非敏感关联字段。
- 日志与 Interaction Ledger 只记录审计元数据，不复制问题/答案正文；观测写入 best-effort，失败不得反噬 Capture 持久化。

### Claude's Discretion
- 具体字段长度、索引名称、枚举实现和内部 helper 拆分由实现者按现有 Django 约定决定。
- 可在不改变上述契约的前提下提取共享 git URL 规范化工具，避免继续复制私有实现。

### Deferred Ideas (OUT OF SCOPE)
- MCP serializer、snapshot 与 npm 工具契约延后到 Phase 142。
- LLM 价值评估、durable 调度和 medium/high 入图延后到 Phase 143。
- 仓库召回、Capture 回放和默认分支 lookup 修复延后到 Phase 144。
- Cursor / Claude Code hooks 与安装器延后到 Phase 145。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| STORE-01 | 结构化问答落入独立 Capture 账本（问题、可见答案精华、模型、仓库、分支、会话、可选项目），不写入 `ProjectMemory` 或 Interaction Ledger 正文 | 新模型 `SessionCapture` + `CaptureService.persist`；行为测试断言无 `ProjectMemory` 行、无 Ledger input 复制问答；INV-6 禁止旁路写。`[VERIFIED: REQUIREMENTS.md; memory.py; interactions/ledger.py]` |
| STORE-02 | `project_id` 与 `repository_id` 均可空；缺项目不得拒绝落库 | 两 FK `null=True, on_delete=SET_NULL`；测试无项目/无仓仍 `status=pending_eval`。`[VERIFIED: CONTEXT.md; RepoAssociation SET_NULL 先例]` |
| STORE-03 | 全部写入只经 INV-6 `CaptureService`（脱敏、`initiated_by_user_id`、禁止旁路 `objects.create`） | 复制 `test_memory_inv6_guard.py` 形态并扩展状态 `.update(`；writer 内 `redact_secrets_in_text`。`[VERIFIED: test_memory_inv6_guard.py; memory_service.py]` |
| STORE-04 | git remote / `git_url` 归一化后尽量挂钩已有 `Repository`；解析失败仍落库并记录显式 `reason`（如 `repo_unresolved`） | 解析序：显式 id → 规范化 URL；失败写 `link_reason` 仍 persist；禁止 `_resolve_report_project_id`。`[VERIFIED: mcp_tools/views.py:_resolve_report_project_id; serializers.ssh_git_url_to_https]` |
| STORE-05 | 拿不到的模型名、provider、token 计数字段记字面值 `unknown`，服务端不得猜测 | 三字段用 `CharField` 默认 `"unknown"`，空/None 归一为该字面值；禁止按问答推断模型。`[VERIFIED: CONTEXT.md; REQUIREMENTS.md]` |
| OBS-01 | 持久化生命周期 `category=caller` 的 started/completed/failed，含 `duration_ms` 与触发用户；评估/入图步骤用 `sampling` | 本阶段只实现 persist 三事件；评估/入图 sampling **不实现**（Phase 143）。对照 `test_query_observability.py`。`[VERIFIED: query_service.py; LOGGING-SPEC.md; CONTEXT.md]` |
| OBS-02 | 入库前强制脱敏；凭证、token、密钥不得出现在 Capture、Ledger、日志 | persist 前 `redact_secrets_in_text`；日志/返回值禁问答正文；观测 `except: pass`。`[VERIFIED: common/logging.py; interactions/redaction.py]` |
</phase_requirements>

## Summary

Phase 141 只交付 **INV-6 写入面**：在 `initiatives` 新增 `SessionCapture`（表 `initiative_session_captures`）与唯一 writer `CaptureService.persist`。MCP 工具、LLM 评估、入图、召回均不在本阶段。成功标准是：任意授权用户提交结构化问答后一定有一行 Capture；挂钩失败只体现在 `link_reason`，绝不表现为「未收」。

实现必须对着既有 INV-6 守卫、`MemoryService` 脱敏、`knowledge.access_scope` fail-closed、以及 `GraphQueryService` 的 caller 日志形态做，而不是复制 `report_project_knowledge` 的 `branch_unresolved` 跳过写库。仓库 REST 权限目前是「任意登录用户可读存在且未删的仓」，但 **Capture 挂钩必须更严**：用与召回相同的 Space/`ProjectMember` 可见性决定是否写 FK，避免落下用户日后无法召回的外键。

**Primary recommendation:** 实现 `CaptureService.persist(...) -> CapturePersistResult`（async + `sync_to_async` 事务）、migration `0015`、INV-6 grep 守卫、挂钩 reason 闭集、以及 persist caller 日志/脱敏行为测试；禁止新增 Python 依赖、禁止 MCP 视图、禁止调用记忆/入图入口。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Capture 行持久化 | API / Backend (`initiatives`) | Database / Storage | 操作态账本属于 Django ORM；本阶段无 MCP/REST 对外入口 |
| 脱敏 | API / Backend | — | `redact_secrets_in_text` 必须在 `objects.create` 之前，不可下放到 DB |
| 仓库/项目挂钩 | API / Backend | Database / Storage | 解析与授权在 service；FK 可空 |
| 幂等 | Database / Storage | API / Backend | `UniqueConstraint` + IntegrityError 回读 |
| 权限（写 FK / 读归属） | API / Backend | — | 写：不绑未授权 FK；读契约为本人 `initiated_by_user_id` ∪ 仓库可见性（回放 API 在 144） |
| caller 生命周期日志 | API / Backend | — | structlog；best-effort |
| Interaction Ledger | —（本阶段不写） | API / Backend（142） | CONTEXT 禁止把问答当 Ledger 正文；141 连 run 都不建 |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Django | 6.0.1 `[VERIFIED: uv run]` | ORM 模型、migration、`TextChoices`、`UniqueConstraint` | 本仓后端事实栈（CLAUDE.md 写 ≥5.1） |
| Python | 3.14.2 `[VERIFIED: python3 --version]` | runtime | `server/.python-version` |
| pytest + pytest-django + pytest-asyncio | pytest 9.0.2 `[VERIFIED: uv run]` | 行为测试 + INV-6 静态扫描 | `server/pyproject.toml` `testpaths=tests` |
| structlog | 已在 `server/uv.lock` | 结构化日志 | LOGGING-SPEC 强制 |
| asgiref `sync_to_async` | Django 捆绑 | async service 调 ORM | `MemoryService` 既有模式 |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `hashlib.sha256` | stdlib | `question_hash` | 幂等键，勿引入 extra hash 库 |
| `common.logging.redact_secrets_in_text` | in-repo | 问答入库脱敏 | persist 必经 |
| `knowledge.access_scope.resolve_allowed_*` | in-repo | 挂钩授权 | 决定是否写 FK，不决定是否落行 |
| `repositories.serializers.ssh_git_url_to_https` | in-repo | SSH→HTTPS | URL 挂钩第一步 |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| 独立 `SessionCapture` | 复用 `ProjectMemory` / Ledger | **禁止**（锁定三层分离） |
| `component=knowledge` | `component=initiatives` | Memory 用 `initiatives`；CONTEXT 锁定 knowledge |
| `resolve_allowed_repository_ids` | `RepositoryPermission`（任意登录用户） | REST 更宽；挂钩若跟 REST 会绑上用户召回不到的仓。挂钩跟召回 scope |
| 抽取 `services/git_url.py` | 继续复制 `_normalize_repo_url` | CONTEXT 允许抽取；应抽，避免第三份副本 |

**Installation:** 无新包。不要 `pip`/`uv add`。

**Version verification:** Django 6.0.1、pytest 9.0.2、Python 3.14.2（本机 `uv run` / `python3 --version`，2026-08-28）。

## Package Legitimacy Audit

> 本阶段 **不安装** 外部包。slopcheck 不适用。

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| — | — | — | — | — | — | 无候选包 |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

*无新依赖；planner 不得加入 `checkpoint:human-verify` 安装任务。*

## Architecture Patterns

### System Architecture Diagram

```text
调用方（本阶段 = 单测 / 后续 Phase 142 MCP）
    │  question, answer, repository_id?, git_url?, project_id?,
    │  session_id?, branch?, response_model?, provider?, token 字段?,
    │  actor user
    ▼
CaptureService.persist
    ├─ bind initiated_by_user_id（缺则 "system"）
    ├─ log session_capture_persist_started (caller, component=knowledge)  ──┐
    ├─ redact_secrets_in_text(question/answer)                              │ best-effort
    ├─ unknown 归一（model/provider/token 字段）                             │ 失败不抛
    ├─ question_hash = sha256(NFKC(strip(question)))
    ├─ session_key = session_id.strip() or "unspecified"
    ├─ 挂钩：id → git_url 规范化匹配 → 可选 project 上下文
    │     未授权 / 未解析 → FK=null + link_reason，仍继续
    ├─ transaction.atomic:
    │     UniqueConstraint 命中 → 返回既有行（不改正文）
    │     否则 SessionCapture.objects.create(status=pending_eval)
    ├─ log completed (duration_ms, capture_id, reasons, bound flags)
    └─ 禁止：MemoryService / aschedule_ingestion / background_runner / Ledger._record
         │
         ▼
initiative_session_captures
  question/answer（已脱敏）+ 标量元数据 + 可空 FK
```

### Recommended Project Structure

```
server/initiatives/
├── models/session_capture.py      # NEW SessionCapture + TextChoices
├── models/__init__.py             # 导出模型与枚举
├── services/capture_service.py    # NEW INV-6 唯一 writer
├── services/__init__.py           # 导出 CaptureService / 结果类型 / 错误
├── migrations/0015_session_capture.py
server/services/git_url.py         # NEW 可选：normalize_git_url 包装 ssh_git_url_to_https
server/tests/initiatives/
├── test_capture_inv6_guard.py     # NEW 静态扫描
├── test_capture_service.py        # NEW persist / 挂钩 / 幂等 / unknown / 脱敏
└── test_capture_observability.py  # NEW caller 日志、无正文、best-effort
.planning/observability/LOGGING-SPEC.md  # 登记三事件（§5 已有 component=knowledge）
```

本阶段 **不** 改 `mcp_tools/views.py`、`mcp/src/tools.ts`、`CallSource`、knowledge `sources/`。

### Pattern 1: INV-6 唯一 writer（照 MemoryService）

**What:** 模型 docstring 声明无业务写方法；全部 `objects.create` 只出现在 `capture_service.py`；grep 守卫排除 tests/migrations/models/writer。
**When to use:** 所有 Capture 插入与状态字段变更。
**Example:**

```python
# Source: server/initiatives/services/memory_service.py（对照，勿复制 append 语义）
redacted = redact_secrets_in_text(content or "")
with transaction.atomic():
    memory = ProjectMemory.objects.create(...)
```

Capture 应对齐：`persist` 内 create；**不要**提供 `_skip_member_check` 之类会让未授权 FK 写进去的后门。

### Pattern 2: 挂钩失败仍落行（反模式是 report_project_knowledge）

**What:** `_resolve_report_project_id` 在无唯一项目时返回 `branch_unresolved` 且调用方 **不写库**。Capture **禁止** import 或调用该函数。`branch_name` 只存元数据。
**When to use:** 永远。
**Verified skip 语义（禁止复制）:** `[VERIFIED: server/mcp_tools/views.py:3719-3738, 4043-4045]`

### Pattern 3: caller 日志 best-effort（照 GraphQueryService）

**What:** `started` 无 `duration_ms`；`completed`/`failed` 有；`try/except Exception: pass` 包住每一处 logger 调用；业务异常原样抛出。
**When to use:** persist 生命周期。
**Example:** `[VERIFIED: server/services/code_graph/query_service.py:146-157]`

### Pattern 4: 授权挂钩用 knowledge scope，不是 RepositoryPermission

**What:** `RepositoryPermission` = 登录 + 仓存在未删。`resolve_allowed_repository_ids` = Space M2M ∩ 用户可见项目。挂钩 FK 必须走后者（及项目 `ProjectMember` / `resolve_allowed_project_ids`），否则会绑上 144 召回看不到的仓。
**When to use:** 决定是否赋值 `repository_id`/`project_id`。
**Verified:** `[VERIFIED: repositories/permissions.py:12-16; knowledge/access_scope.py:97-139]`

### Anti-Patterns to Avoid

- **把 `branch_unresolved` 当未收：** 141 甚至不返回 MCP `accepted`；测试以「有 Capture 行」为准。
- **`on_delete=CASCADE` 到 Project/Repository：** 删项目会物理丢掉 Capture，违反永不丢失。必须 `SET_NULL`。`[VERIFIED: 对照 RepoAssociation 对 work_item 的 SET_NULL；此处更严]`
- **token 计数字段用 IntegerField：** `unknown` 是字面字符串，必须 `CharField`。
- **幂等键含 answer：** 锁定仅为 user + session + question_hash；重复提交 **不更新** 已有答案（first write wins）。
- **在 persist 里调度 durable/eval：** 143 的事。
- **日志 kv 拼进 message：** `logger.info("session_capture_persist_completed", capture_id=..., ...)`。
- **`component=initiatives`：** 锁定 `knowledge`。
- **guard 漏 `.update(` / `.save(`：** CONTEXT 明确禁止直接更新状态。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 问答脱敏 | 新正则 | `redact_secrets_in_text` | 与 structlog processor 同源；漏 `friday_pat_` 时 Ledger 路径另有 `redact_for_ledger`（141 不写 Ledger） |
| SSH git URL | 第三份 regex | `ssh_git_url_to_https` + 共享 `normalize_git_url` | serializers 已覆盖 scp / `ssh://` |
| 仓库可见性 | 新 ACL 表 | `resolve_allowed_repository_ids` | 与 RAG 召回一致 |
| 项目成员 | 手写 exists 散落 | `ProjectMember.objects.filter` 如 MemoryService，或 `resolve_allowed_project_ids` | fail-closed 已有测试 |
| 幂等 | 应用层先 get 再 create 无约束 | DB `UniqueConstraint` + IntegrityError | 并发双插 |
| 日志用户上下文 | 自建 threadlocal | `initiated_by_user_id` kv + 已有 `bind_request_context` | LOGGING-SPEC |
| UUID 校验 | 裸字符串当 FK | `uuid.UUID(str)` 失败则当未解析 | 对照 `ensure_repository_readable` |

**Key insight:** 本阶段复杂度在 **契约与守卫**，不在新框架。手写 ACL、脱敏或跳过写库都会直接打穿 STORE/OBS。

## Common Pitfalls

### Pitfall 1: 复制 `branch_unresolved` 跳过写库
**What goes wrong:** 无项目时零行，仪表盘以为工具成功。
**Why it happens:** `test_report_project_knowledge.py` 正向断言 skip。`[VERIFIED: .planning/research/PITFALLS.md Pitfall 1]`
**How to avoid:** Capture 测试断言无项目仍 `acount()==1`；禁止调用 `_resolve_report_project_id`。
**Warning signs:** persist 返回 None；reason 当异常抛出。

### Pitfall 2: 默认分支当项目主键
**What goes wrong:** `main`/`master`/`develop` 误绑项目。
**Why it happens:** lookup 第三源。锁定：141 不调用 `lookup_project_by_branch`；修复属 144。
**How to avoid:** `branch_name` 只写入字段。
**Warning signs:** persist 内部 import mcp lookup。

### Pitfall 3: INV-6 守卫形同虚设
**What goes wrong:** writer 不用 `objects.create`，守卫只扫 create 则永远绿。
**Why it happens:** 用 `SessionCapture(...)` + `.save()` 或 QuerySet.update。
**How to avoid:** 守卫同时扫 create/bulk/get_or_create/update_or_create、`SessionCapture(` 实例化、`.objects.filter(...).update(`、`link_status=`/`status=` 赋值（writer 豁免）；另测 writer 文件确实含 `SessionCapture.objects.create`。
**Warning signs:** 只有 guard 文件、无 writer 自检。

### Pitfall 4: 问答进入日志或 Ledger
**What goes wrong:** OBS-02 失败；密钥在 system log。
**Why it happens:** `logger.info(..., question=q[:80])` 或 141 误调 `arecord_tool_call`。
**How to avoid:** 日志字段白名单：`capture_id`、`link_reason`、`repository_bound`、`project_bound`、`session_present`（bool，不要把 session 当问题）、`initiated_by_user_id`、`duration_ms`、`idempotent_hit`。测试用 sentinel 问答断言不出现在 `json.dumps(captured)`。
**Warning signs:** 截断 `question[:100]`（Phase 140 已判为泄漏）。

### Pitfall 5: 未授权仍写 FK
**What goes wrong:** 陌生人挂钩到别人的项目/仓。
**Why it happens:** 只检查仓存在。
**How to avoid:** 仓不在 `resolve_allowed_repository_ids(user)` → FK null + `repo_unauthorized`；项目不在允许集合 → `project_unauthorized`。行仍创建，归属 `initiated_by_user_id`。
**Warning signs:** 非成员测试 `capture.project_id is not None`。

### Pitfall 6: Integer token 字段无法存 `unknown`
**What goes wrong:** STORE-05 无法落地。
**How to avoid:** `response_model`/`provider`/`input_tokens`/`output_tokens` 均为 `CharField(max_length=64, default="unknown")`（token 计数字段同样存十进制字符串或 `unknown`，143 再解析）。空串/None/`guess-me` 输入一律写成 `unknown`，不填默认模型名。
**Warning signs:** `null=True` IntegerField。

### Pitfall 7: 观测失败打断 persist
**What goes wrong:** logger 抛错导致问答丢失。
**How to avoid:** 每处 log `except Exception: pass`；测试 monkeypatch logger 仍返回 Capture。`[VERIFIED: test_query_observability.py:199-214]`
**Warning signs:** persist 外层无 try、日志在 create 前且未吞异常导致 create 未执行。推荐顺序：started（吞）→ 业务 create（不吞）→ completed（吞）。create 失败再 failed（吞）后重新 raise。

### Pitfall 8: CASCADE 删除账本
**What goes wrong:** 删 Repository 级联删 Capture。
**How to avoid:** `ForeignKey(..., null=True, on_delete=models.SET_NULL)`。
**Warning signs:** migration 里 `CASCADE` 指向 repositories/initiatives.Project。

### Pitfall 9: git 归一化不一致导致挂不上
**What goes wrong:** DB 存 HTTPS，客户端报 `git@host:group/repo.git`。
**How to avoid:** `ssh_git_url_to_https` → strip → lower → 去尾 `/` → 去 `.git`；对候选 `Repository.git_url` 做同样归一后比较。先精确变体 filter（原串、https、带/不带 .git），避免全表加载。多命中：`repo_ambiguous`、不绑 FK。软删仓（`is_deleted=True`）视为不存在 → `repo_unresolved`。
**Warning signs:** 只 `iexact` 原始 SSH 串。

### Pitfall 10: 幂等更新了答案
**What goes wrong:** 重试覆盖精华，评测基线漂。
**How to avoid:** Unique 命中后 **原样返回**，不 `save` 新 answer。
**Warning signs:** `update_or_create`。

## Code Examples

### Capture 状态枚举（预留后续相位）

```python
# Source: 对照 server/initiatives/models/memory.py ProjectMemoryStatus
class SessionCaptureStatus(models.TextChoices):
    PENDING_EVAL = "pending_eval", "待评估"
    EVAL_FAILED = "eval_failed", "评估失败"
    INGEST_PENDING = "ingest_pending", "待入图"
    EVALUATED = "evaluated", "已评估"  # 143 使用；141 不写入
```

141 **只写入** `PENDING_EVAL`。枚举必须含后续值以免 143 再改约束。

### persist 挂钩顺序

```python
# Source: CONTEXT 锁定顺序；授权对照 knowledge/access_scope.py
# 1. 显式 repository_id 且 UUID 合法且未软删
# 2. 否则 normalize_git_url(git_url) 匹配 Repository.git_url
# 3. 可选 project_id：存在性 + resolve_allowed_project_ids
# 4. 若仓与项目都解析到：项目 space.repositories 含该仓或存在 RepoAssociation，否则不绑项目
# 5. 仓/项目不在用户允许集合 → 对应 FK 置空 + reason，仍 create
```

### 推荐 reason 闭集（字符串存库，非 MCP 响应）

| reason | 含义 | FK |
|--------|------|-----|
| `linked` | 仓已绑（项目可空） | repository 有值 |
| `linked_with_project` | 仓+项目均绑 | 两者有值 |
| `repo_unresolved` | id/url 无法唯一命中未删仓 | 均空或仅项目（若项目单独合法——**推荐仍不单独绑项目**，仓为主挂钩） |
| `repo_ambiguous` | 归一化后多仓 | 不绑仓 |
| `repo_unauthorized` | 仓存在但用户 scope 外 | 不绑仓 |
| `project_unauthorized` | 仓可绑但项目不可 | 只绑仓 |
| `project_unresolved` | project_id 非法/不存在 | 只绑仓（若有） |
| `project_repo_mismatch` | 项目与仓无 Space/RepoAssociation 关系 | 只绑仓 |
| `unanchored` | 无 id 无 url 无项目 | 均空 |

**推荐：** 无仓时即使给了合法 `project_id` 也可以绑项目作为可选上下文（CONTEXT：项目仅为可选上下文）。与「仓为主」不冲突。无仓 + 有项目：`reason=linked_project_only`（增补）或 `unanchored` 不绑项目。**选定：无仓时仍允许授权项目 FK，reason=`project_only`。** `[RECOMMENDATION]`

### INV-6 守卫骨架

```python
# Source: server/tests/initiatives/test_memory_inv6_guard.py
_ALLOWED_WRITER = "initiatives/services/capture_service.py"
_MODELS = ("SessionCapture",)
# 另加：
# rf"\bSessionCapture\.objects\.(?:filter|all)\([^)]*\)\.update\b"
# rf"\bSessionCapture\.objects\.update\b"
```

扫描范围与 memory 守卫相同：排除 `tests/`、`/migrations/`、`initiatives/models/`、writer 自身。

### 观测字段（completed）

```python
logger.info(
    "session_capture_persist_completed",
    category="caller",
    component="knowledge",
    duration_ms=duration_ms,
    initiated_by_user_id=initiated_by_user_id,
    capture_id=str(capture.id),
    link_reason=reason,
    repository_bound=bool(capture.repository_id),
    project_bound=bool(capture.project_id),
    idempotent_hit=idempotent_hit,
)
```

不要传 `question`/`answer`/`git_url`/`token`。`error=` 必须先 `redact_secrets_in_text`。

### 幂等约束

```python
models.UniqueConstraint(
    fields=["initiated_by_user_id", "session_id", "question_hash"],
    name="uniq_session_capture_user_session_question",
)
```

`session_id` 使用非空 CharField：缺失输入存字面 `"unspecified"`（**不要**用 `unknown`，以免与 STORE-05 语义混用）。SQLite/Postgres 下非空唯一约束对重复提交生效。`question_hash` = `sha256(unicodedata.normalize("NFKC", question.strip()).encode("utf-8")).hexdigest()`（64 hex）。`[RECOMMENDATION: NFKC — ASSUMED 规范化形式，实现者可改为仅 strip]`

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| 项目记忆硬挂钩 + `branch_unresolved` 跳过 | 独立 Capture，挂钩失败仍落行 | v0.25.0 锁定 | 141 必须新表 |
| Ledger 当检索语料 | Ledger 仅审计 | v0.17 | 141 不写问答进 Ledger |
| REST 任意登录可读仓 | 知识召回按 Space | Phase 15 access_scope | 挂钩跟召回 |

**Deprecated/outdated:**
- 在 Capture 写路径调用 `_resolve_report_project_id` / `lookup_project_by_branch`
- 把 persist 放进 `ReportProjectKnowledgeView`

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | 无 `session_id` 时存字面 `unspecified` 并参与唯一约束 | 幂等 | 无会话的相同问题会被去重；若产品要每次新行，应改为 per-call UUID 后备（仍可审计）但失去「缺 session 的幂等」 |
| A2 | git 多命中用 `repo_ambiguous` | STORE-04 | 文案需与 142 MCP `reason` 对齐；141 先锁闭集 |
| A3 | 挂钩授权用 `resolve_allowed_repository_ids` 而非 REST 宽权限 | Pattern 4 | 未挂任何 Space 的仓对普通用户永远 `repo_unauthorized`（仍落行） |
| A4 | question 哈希用 NFKC | 幂等 | 仅 strip 也可能够；选一种写测试钉死 |
| A5 | 141 完全不创建 InteractionRun | OBS-02 | 若 planner 希望提前打审计点，只允许 metadata-only 且无问答键 |

**If this table is empty:** 不适用。

## Open Questions

1. **无 session 的幂等粒度**
   - What we know: 锁定键是 user + session_id + question_hash；缺 session 必须有后备标识。
   - What's unclear: 后备是稳定字面 `unspecified`（同用户同问题去重）还是 per-request UUID（永不去重）。
   - Recommendation: 用 `unspecified`（A1）；planner 若选 UUID，测试改为「缺 session 两次提交两行」。

2. **无仓时是否绑项目**
   - Recommendation: 绑（`project_only`），因项目是可选上下文。

3. **LOGGING-SPEC §10 目录**
   - 应追加 persist 三事件。§4.1 CallSource **不要**在 141 增加 `session_capture_eval`（143）。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | 实现/测试 | ✓ | 3.14.2 | — |
| Django (uv env) | ORM/migration | ✓ | 6.0.1 | — |
| pytest | Nyquist | ✓ | 9.0.2 | — |
| uv | `cd server && uv run pytest` | ✓ | present | — |
| PostgreSQL | 本阶段单测默认 SQLite | 非必须 | — | Django test SQLite |
| 新 PyPI 包 | — | n/a | — | 禁止安装 |

**Missing dependencies with no fallback:** none

**Missing dependencies with fallback:** none

Step 2.6: 有运行时（pytest/Django），无新外部服务。

## Validation Architecture

Nyquist 启用（`.planning/config.json` `workflow.nyquist_validation`: true）。

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 + pytest-django + pytest-asyncio（`asyncio_mode=auto`） |
| Config file | `server/pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `cd server && uv run pytest tests/initiatives/test_capture_inv6_guard.py tests/initiatives/test_capture_service.py tests/initiatives/test_capture_observability.py -x -q` |
| Full suite command | `cd server && uv run pytest tests/initiatives/test_capture_inv6_guard.py tests/initiatives/test_capture_service.py tests/initiatives/test_capture_observability.py tests/initiatives/test_memory_inv6_guard.py tests/initiatives/test_memory_service.py tests/mcp_tools/test_report_project_knowledge.py -q` |

`addopts` 已 `--disable-socket`；新测试不得外网。async 写库用 `pytest.mark.django_db(transaction=True)`，对照 `test_memory_service.py`。`[VERIFIED: server/tests/initiatives/test_memory_service.py:28]`

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| STORE-01 | persist 后 `SessionCapture` 有 question/answer/元数据；`ProjectMemory` 计数不变；无 `arecord_tool_call` | unit | `uv run pytest tests/initiatives/test_capture_service.py::test_persist_does_not_write_memory_or_ledger -x` | ❌ Wave 0 |
| STORE-02 | 无 project、无 repository 仍插入 `pending_eval` | unit | `uv run pytest tests/initiatives/test_capture_service.py::test_persist_without_project_or_repo -x` | ❌ Wave 0 |
| STORE-03 | 源码无旁路 create/update；writer 含 create；脱敏 + `initiated_by_user_id` | unit + static | `uv run pytest tests/initiatives/test_capture_inv6_guard.py tests/initiatives/test_capture_service.py::test_redaction_and_actor -x` | ❌ Wave 0 |
| STORE-04 | HTTPS/SSH URL 挂钩；未知 URL → 行存在且 `link_reason=repo_unresolved`；显式 id 优先 | unit | `uv run pytest tests/initiatives/test_capture_service.py -k link -x` | ❌ Wave 0 |
| STORE-04 | 未授权仓/非成员项目：有行、对应 FK 空、reason 明确 | unit | `uv run pytest tests/initiatives/test_capture_service.py::test_unauthorized_does_not_set_fk -x` | ❌ Wave 0 |
| STORE-05 | 缺 model/provider/tokens → 字面 `unknown`；不猜测 | unit | `uv run pytest tests/initiatives/test_capture_service.py::test_unknown_scalars -x` | ❌ Wave 0 |
| STORE-03/01 | 同 user+session+question_hash 第二次返回同一 id，不新增行、不改 answer | unit | `uv run pytest tests/initiatives/test_capture_service.py::test_idempotent_returns_existing -x` | ❌ Wave 0 |
| STORE-03 | capture_service 源码不含 `aschedule_ingestion`/`MemoryService`/`record_hook_writeback`/`background_runner` | static | `uv run pytest tests/initiatives/test_capture_inv6_guard.py::test_writer_does_not_call_deferred_sinks -x` | ❌ Wave 0 |
| OBS-01 | 成功：started+completed，`category=caller`，`component=knowledge`，completed 有 `duration_ms` 与 `initiated_by_user_id`；无 failed | unit | `uv run pytest tests/initiatives/test_capture_observability.py::test_success_caller_lifecycle -x` | ❌ Wave 0 |
| OBS-01 | 业务失败：started+failed 含 duration；异常原样 | unit | `uv run pytest tests/initiatives/test_capture_observability.py::test_failure_caller_lifecycle -x` | ❌ Wave 0 |
| OBS-01 | 本阶段无 eval/ingest sampling 事件名 | unit | `uv run pytest tests/initiatives/test_capture_observability.py::test_no_eval_sampling_events -x` | ❌ Wave 0 |
| OBS-02 | sentinel 问答与 `sk-ant-...` 不出现在 capture_logs JSON；DB 正文已 REDACTED | unit | `uv run pytest tests/initiatives/test_capture_observability.py::test_no_body_or_secrets_in_logs tests/initiatives/test_capture_service.py::test_redaction_and_actor -x` | ❌ Wave 0 |
| OBS-02 | logger.info 抛错仍返回 Capture | unit | `uv run pytest tests/initiatives/test_capture_observability.py::test_logger_failure_does_not_drop_capture -x` | ❌ Wave 0 |
| 回归 | 旧 `report_project_knowledge` skip 语义不变 | unit | `uv run pytest tests/mcp_tools/test_report_project_knowledge.py -q` | ✅ 已有 |

手工-only：无。本阶段无 UI。

### Sampling Rate

- **Per task commit:** Quick run command（上述 capture 三文件）
- **Per wave merge:** Full suite command（capture + memory INV-6/service + report_project_knowledge）
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `server/tests/initiatives/test_capture_inv6_guard.py` — STORE-03 / 禁止延迟入口
- [ ] `server/tests/initiatives/test_capture_service.py` — STORE-01..05 行为
- [ ] `server/tests/initiatives/test_capture_observability.py` — OBS-01/02
- [ ] 可选 fixture：在 `tests/initiatives/conftest.py` 增加经 `CaptureService` 的工厂（**禁止**测试里 `SessionCapture.objects.create`，否则要给 tests 豁免——守卫已排除 tests/，测试可以 create，但 **不要** 养成旁路习惯；工厂应走 service）
- [ ] Framework install: 无

现有基础设施足够：`django_db`、User/Space/ProjectService/Repository.objects.create 工厂先例（`test_project_branch_service.py`）。守卫排除 tests，故测试文件内 ORM 不会被 INV-6 误杀。

## Security Domain

`security_enforcement` 启用，ASVS L1，block on high。

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no（141 无 HTTP 入口） | Phase 142 PAT/JWT |
| V3 Session Management | no | — |
| V4 Access Control | yes | 挂钩 FK：`resolve_allowed_*` + `ProjectMember`；不绑未授权关系；行归属 `initiated_by_user_id` |
| V5 Input Validation | yes | UUID 解析失败 → unresolved；问答 TextField；标量闭集 `unknown` |
| V6 Cryptography | no new crypto | sha256 仅指纹；脱敏复用现有 |

### Known Threat Patterns for Capture persist

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| 问答含 API key | Information Disclosure | `redact_secrets_in_text` 后再 create；日志无正文 |
| 非成员绑他人项目 | Elevation of Privilege | 不写 project FK；仍落本人 Capture |
| 伪造 repository_id | Tampering / Info Disclosure | 非法 UUID / 软删 / scope 外 → 不绑 FK，不泄漏「存在但不可见」差异（reason 统一 `repo_unresolved` 或 `repo_unauthorized`：scope 外用 unauthorized，不存在用 unresolved，避免 IDOR 枚举——**推荐不存在与未授权同一对外 reason `repo_unresolved`，内部日志可分**）`[RECOMMENDATION]` |
| 旁路 ORM 写未脱敏行 | Tampering | INV-6 grep |
| 日志反噬导致未落库 | Denial of Service | 观测 swallow |
| 唯一键竞态双行 | Tampering of ledger integrity | UniqueConstraint + IntegrityError |

不要用手搓加密。不要把 PAT 写入 Capture 字段。

## Project Constraints (from .cursor/rules/)

来源：`.cursor/rules/observability-logging.mdc`（仓库内唯一 alwaysApply mdc）。

- `structlog.get_logger(__name__)`；事件名 snake_case `*_started/completed/failed`；字段 kv，禁止把变量拼进 message。
- 脱敏：`redact_credentials` processor + `redact_secrets_in_text`；Ledger 用 `redact_for_ledger`（141 若写 Ledger 必须走它；推荐不写）。
- 绑定触发用户：`initiated_by_user_id`；无用户记 `system`。
- 指标与留痕分离：141 不新增 RequestMetric 入口（无 HTTP）；不要把问答复制进 Ledger。
- 观测 best-effort，`except: pass`，不反噬。
- `category` 二选一：persist = `caller`；评估/入图 sampling 留给 143。
- 新 LLM 调用需 `call_source`：**141 无 LLM，不改枚举。**
- 高频循环禁止 INFO：persist 每调用一次三事件，允许 INFO。

Planner 不得建议绕过上述规则的「先打日志再脱敏」。

## Sources

### Primary (HIGH confidence)

- `.planning/REQUIREMENTS.md` STORE-01..05 OBS-01/02
- `.planning/phases/141-capture/141-CONTEXT.md` 锁定决策
- `server/initiatives/models/memory.py`、`services/memory_service.py`
- `server/tests/initiatives/test_memory_inv6_guard.py`、`test_memory_service.py`
- `server/mcp_tools/views.py` `_resolve_report_project_id`（反模式）
- `server/repositories/serializers.py` `ssh_git_url_to_https`
- `server/knowledge/access_scope.py`、`server/repositories/permissions.py`
- `server/common/logging.py`、`server/interactions/redaction.py`
- `server/services/code_graph/query_service.py`、`server/tests/services/code_graph/test_query_observability.py`
- `.planning/observability/LOGGING-SPEC.md` §3/§5 `knowledge` component
- `.planning/research/ARCHITECTURE.md`、`PITFALLS.md`
- `server/pyproject.toml` pytest；Django 6.0.1 本机验证

### Secondary (MEDIUM confidence)

- git 多命中 / 无仓绑项目 / 缺 session 去重粒度（见 Assumptions）
- 对外 reason 折叠未授权 vs 不存在（防枚举）

### Tertiary (LOW confidence)

- 无。未使用 WebSearch 猜测第三方库。

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 无新依赖；版本本机验证
- Architecture: HIGH — 模型落点、INV-6、反模式、授权函数均有源码
- Pitfalls: HIGH — 对照 PITFALLS.md 与现行 skip/脱敏/观测测试

**Research date:** 2026-08-28
**Valid until:** 2026-09-27（Django 内部约定稳定，30 天）
