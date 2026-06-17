# Phase 53: `AuditEvent` 模型 + emit 地基 — Research

**Researched:** 2026-06-17
**Phase goal:** 立起统一不可篡改审计模型与 fail-soft emit 地基，供后续所有敏感操作复用。
**Requirements:** AUDIT-01, AUDIT-02
**Question answered:** "What do I need to know to PLAN this phase well?"

---

## TL;DR — Plan-shaping conclusions

1. **新建轻量 `audit` app**（而非塞进 `delivery` / `system`）。理由见 §1：audit 是横切叶子包，需被任意 app 无环 import；`delivery` 是高耦合 hub（import feishu/knowledge/projects），`system` 是 config 语义。新 app = 干净 bounded context（对齐「Django app = bounded context」约定），代价仅一条 `0001_initial` migration + INSTALLED_APPS 注册。
2. **单一写入入口 = `AuditService` service helper（非 Django signal）**。emit 经 `AuditService.emit()`（sync）+ `aemit()`（async via `sync_to_async`），INV-6 grep 守护精确锚定（signal receiver 解耦会让 grep 守护失效）。脱敏在入口内强制执行，调用方无法绕过。
3. **`actor` 用可空标量 `actor_id`（UUID）+ `actor_repr` 快照，不建 FK** — 对齐本仓既有「刻意不用 FK 避免级联」范式（`ProviderCredential.scope_id`、`PlanSessionEvent.work_item`）。这是最纯的 append-only/不可篡改选择：删用户绝不触碰审计行。Phase 55 仍可按 `actor_id` 标量过滤。
4. **append-only 双层守护**：模型层 `save()` override 拒绝 update（`_state.adding is False` → raise）+ `delete()` raise；源码层 INV-6 grep 守护（镜像 `test_sdd_spec_inv6_guard.py`）。
5. **fail-soft emit**：`emit()` 整段 `try/except` 吞异常 + `logger.warning`，绝不冒泡（对齐 `_run_sensitive_detection` / `record_produced_artifacts` 范式）。
6. **action taxonomy**：模块级 `Final[str]` 常量容器 + `verb.object` 命名（镜像 `delivery/services/event_taxonomy.py`），本 phase 仅定义稳定容器 + 种子/预留常量，具体 action 值由 Phase 54 补充。
7. **脱敏**：在 emit 入口内对 `before`/`after`/`metadata` 递归走 key-name 命中 + 值级高熵/密钥模式兜底，**语义对齐**（不 import）`sensitive_detect._SECRET_PATTERNS` + `work_item_service._SECRET_KV_RE`（守 INV-3）。

---

## 1. App 选址决策（agent's Discretion → 推荐 NEW `audit` app）

CONTEXT 给的裁量：复用 `system` / 新建轻量 `audit` / 优先复用。研究结论倾向**新建 `audit`**，理由具体如下：

| 选项 | 优点 | 致命问题 |
|------|------|----------|
| 塞 `delivery` | 已有 append-only 范式现成 | `delivery` 是高耦合 hub（顶部/惰性 import `feishu`/`knowledge`/`projects`/`services.feishu`）。audit 要被**任意 app**（accounts/system/repositories/feishu/access_tokens…）emit；若 emit helper 落 delivery，这些 app → delivery 形成不该有的依赖箭头 + 潜在环。语义也不符（delivery = 飞书 work-item 脊柱）。 |
| 塞 `system` | config/治理语义沾边；INSTALLED_APPS 位置靠前（低层 sink） | `system` 当前是 SystemSetting/ProviderCredential/向导，混入横切审计会让 `system` 变隐性 hub；且 `system` 不含 append-only 范式。 |
| **新建 `audit`（推荐）** | 干净叶子包，**零业务依赖**（只依赖 `django.db` + `accounts.User` 标量引用 + `common.logging`），任意 app 可无环 import emit helper；对齐「app = bounded context」约定；为 Phase 55 查询 API 自持 `api/`+`urls.py` 留位 | 代价：一条 `0001_initial` migration + INSTALLED_APPS 注册一行（极小） |

**INSTALLED_APPS 注册位置**：建议放在 `accounts` 之后、其余业务 app 之前（audit 仅标量引用 `accounts.User`，是低层 sink）。`server/friday/settings.py:89` 的 `INSTALLED_APPS` 列表，在 `"system"` 附近插入 `"audit"`。

**新 app 骨架**（最小集）：
- `server/audit/__init__.py`
- `server/audit/apps.py`（`AuditConfig`，`default_auto_field = "django.db.models.BigAutoField"`，`verbose_name = "操作审计"`）
- `server/audit/models/__init__.py`（curated re-export，对齐 delivery 范式）
- `server/audit/models/audit_event.py`
- `server/audit/services/__init__.py`
- `server/audit/services/audit_service.py`（单一写入入口 + 脱敏 + action taxonomy 或拆 `taxonomy.py`）
- `server/audit/migrations/0001_initial.py`（`makemigrations` 自动生成）

> 备选：若 plan-phase 坚持 reuse-first 硬约束，则落 `system` app（次优），但务必保持 emit helper 模块零业务 import。

---

## 2. `AuditEvent` 模型设计（AUDIT-01）

字段集合以 AUDIT-01 为准：`actor / action / target_type / target_id / target_repr / before / after / source / occurred_at / metadata`。逐项镜像 `WorkItemStatusEvent`（`server/delivery/models/status_event.py`）/ `PlanSessionEvent`（`server/delivery/models/plan_session_event.py`）形状。

### 推荐字段表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `UUIDField(primary_key, default=uuid4, editable=False)` | 对齐全仓 append-only 模型 PK 范式 |
| `actor_id` | `UUIDField(null=True, blank=True, db_index=True)` | 软引用 `accounts.User.id`；null = 系统/匿名 actor。**不建 FK**（见 §2.1） |
| `actor_repr` | `CharField(max_length=255, blank=True, default="")` | 人类可读 actor 快照（如 `"zhangsan (superuser)"`），删用户后仍可读 |
| `action` | `CharField(max_length=64, db_index=True)` | taxonomy 稳定常量值（`verb.object`，见 §4），开放 CharField 不强制 DB 枚举 |
| `target_type` | `CharField(max_length=64, blank=True, default="")` | 目标实体类型（如 `"user"` / `"provider_credential"` / `"repository"`） |
| `target_id` | `CharField(max_length=128, blank=True, default="")` | **字符串**存（容纳 UUID / int / 复合键，避免类型锁死） |
| `target_repr` | `CharField(max_length=255, blank=True, default="")` | 人类可读目标快照（如 `"仓库 friday-ai"`），关联对象删除后审计仍可读（per CONTEXT specifics） |
| `before` | `JSONField(default=dict, blank=True)` | 操作前值快照（**经脱敏入口**） |
| `after` | `JSONField(default=dict, blank=True)` | 操作后值快照（**经脱敏入口**） |
| `source` | `CharField(max_length=32, blank=True, default="")` | 审计来源（`web`/`api`/`feishu`/`workflow`/`system`，per CONTEXT specifics），Phase 55 过滤维度 |
| `occurred_at` | `DateTimeField(default=timezone.now, db_index=True)` | 业务事件发生时间（emit 端可传入，默认 now）。**非** `auto_now_add`——对齐 `PlanSessionEvent.ts` 可传入语义 |
| `recorded_at` | `DateTimeField(auto_now_add=True)` | DB 落库时刻（不可变插入戳）。对齐 `PlanSessionEvent.created_at` / `status_event.ingested_at` |
| `metadata` | `JSONField(default=dict, blank=True)` | 附加上下文（IP / request_id / 链路 id 等，**经脱敏入口**） |

> `occurred_at` + `recorded_at` 双时间戳：前者语义事件时间（可由调用方提供），后者不可变插入时间。AUDIT-01 仅列 `occurred_at`，`recorded_at` 作为不可篡改插入审计戳补充（与 `PlanSessionEvent` 的 `ts` + `created_at` 双戳一致）。

### 2.1 为何 `actor` 用标量而非 FK（关键决策）

CONTEXT 把「FK vs 冗余标量」列为裁量项。研究结论：**标量 `actor_id` + `actor_repr`，不建 FK**：

- **本仓既有范式**：`ProviderCredential.scope_id` 注释明写「刻意不用 FK，避免 Project 级联删除导致凭证消失」；`PlanSessionEvent.work_item = UUIDField(null)` 软引用「不建 FK——避免与 WorkItem 删除耦合」。审计行同理——删用户绝不能级联删/改审计。
- **最纯不可篡改**：FK + `on_delete=SET_NULL` 会在删用户时 **UPDATE 审计行**（把 actor 置 null），这与 append-only/不可篡改语义冲突（即便是框架级 cascade）。标量引用则删用户**完全不触碰**审计行。
- **可读性**：`actor_repr` 快照保证 actor 身份在用户删除后仍可读（与 `target_repr` 同理）。
- **Phase 55 查询**：按 `actor_id` 标量 `.filter(actor_id=...)` 即可，无需 FK join。

### 2.2 Meta（索引为 Phase 55 铺底）

```python
class Meta:
    db_table = "audit_event"
    verbose_name = "审计事件"
    verbose_name_plural = "审计事件"
    ordering = ["-occurred_at"]  # 查询默认最近优先
    indexes = [
        models.Index(fields=["action"]),
        models.Index(fields=["target_type", "target_id"]),
        models.Index(fields=["actor_id"]),
        models.Index(fields=["occurred_at"]),
        models.Index(fields=["action", "occurred_at"]),  # 常用「某类操作 + 时间范围」组合
    ]
```

索引维度严格对齐 CONTEXT「按 actor / action / target_type+target_id / occurred_at 建索引」。

### 2.3 模型层 append-only 守护（AUDIT-01「模型层守护」）

模型层 override 拒绝就地改写 / 删除（业务路径无 update/delete）：

```python
def save(self, *args, **kwargs):
    if not self._state.adding:
        raise AuditEventImmutableError("AuditEvent 不可更新（append-only）")
    super().save(*args, **kwargs)

def delete(self, *args, **kwargs):
    raise AuditEventImmutableError("AuditEvent 不可删除（append-only）")
```

- `_state.adding is False` = 既有行再 save = update → 拒绝；首次 create（`adding=True`）放行。
- 注意 `.objects.update()` / `bulk_*` 绕过 `save()` → 由 §3 INV-6 grep 守护兜底（双层防御）。
- 异常类 `AuditEventImmutableError` 放模型模块；这是设计上**不期望被触发**的护栏（正常路径只 create）。

---

## 3. 单一写入入口 + INV-6 守护（AUDIT-01）

### 3.1 `AuditService` 单一写入入口

镜像 `SddSpecService`（`server/delivery/services/sdd_spec_service.py`）/ `CommentEventService.append_events` 范式：所有 `AuditEvent` 落库只经 `AuditService`，提供 sync + async 双面。

```python
class AuditService:
    @staticmethod
    def emit(*, action, actor=None, target_type="", target_id="", target_repr="",
             before=None, after=None, source="", occurred_at=None, metadata=None) -> None:
        """单一写入入口（INV-6）+ 强制脱敏 + fail-soft。同步面。"""
        try:
            AuditEvent.objects.create(
                actor_id=_actor_id(actor),
                actor_repr=_actor_repr(actor),
                action=action,
                target_type=target_type,
                target_id=str(target_id),
                target_repr=target_repr,
                before=_redact_audit_payload(before or {}),   # 服务端强制脱敏
                after=_redact_audit_payload(after or {}),
                source=source,
                occurred_at=occurred_at or timezone.now(),
                metadata=_redact_audit_payload(metadata or {}),
            )
        except Exception:  # noqa: BLE001 — fail-soft，绝不阻断主操作
            logger.warning("audit.emit_failed", action=action, target_type=target_type)

    @staticmethod
    async def aemit(**kwargs) -> None:
        """async 面：sync_to_async 桥接 ORM（adrf/channels 调用方用）。"""
        await sync_to_async(AuditService.emit)(**kwargs)
```

设计要点：
- **脱敏在入口内强制**（CONTEXT「脱敏经统一构造入口…禁止调用方各自手工脱敏后再传入而无服务端兜底」）。即便调用方传明文，入口兜底脱敏。
- **fail-soft 在入口内**：emit 异常吞掉 + warning。调用方无需自己裹 try/except（但建议调用方仍在 `transaction.on_commit` 或主流程末尾 best-effort 调用，避免 emit 与主操作同事务回滚）。
- **actor 解析**：`emit(actor=...)` 接受 `User` 实例 / None；内部取 `actor.id` 标量（async 安全，不裸访问 lazy-FK）+ 构造 `actor_repr`。**注意 async 上下文**：若调用方传 `User` 实例，访问 `actor.id` / `actor.username` 在 `sync_to_async` 内安全；若在纯 async 上下文，调用方应传已物化标量或在 sync 块内取。plan 需明确 `aemit` 内的 actor 字段访问全在 `sync_to_async(emit)` 同步块内发生。
- **emit 失败不应在同一 DB 事务内**：若主操作与 emit 同事务，emit 的 create 失败被吞但事务可能已 marked-for-rollback。plan 应建议调用方在主操作**提交后**（`transaction.on_commit` 或 await 主操作完成后）emit，或 emit 用独立连接语义。本 phase 提供入口即可，事务边界由 Phase 54 各调用方按场景处理；研究标注此风险供 plan 决策（建议入口 docstring 写明「应在主操作成功后调用」）。

### 3.2 INV-6 grep 守护测试（镜像 `test_sdd_spec_inv6_guard.py`）

新建 `server/tests/audit/test_audit_event_inv6_guard.py`，逐行镜像 `test_sdd_spec_inv6_guard.py`：

- 扫 `server/` 源码（剪 `.venv`/缓存 + 排除 `tests/` / `migrations/` / `audit/models/` 与唯一 writer 自身）。
- 正则锚定：`AuditEvent.objects.(create|bulk_create|get_or_create|update_or_create|update)` / 直接实例化 `AuditEvent(` / 链式 `.save(`。
- 负向前瞻排除更长符号（如 `AuditEventImmutableError(` / `AuditEventSerializer(`）：`\bAuditEvent(?!Immutable|Serializer|...)\s*\(`。
- 唯一允许 writer = `audit/services/audit_service.py`。
- 配「writer-actually-writes」反向测试：断言 writer 确含 `AuditEvent.objects.create`，防守护形同虚设。

---

## 4. action taxonomy（AUDIT-02）

镜像 `delivery/services/event_taxonomy.py` 范式：模块级 `Final[str]` 稳定常量 + `frozenset` 容器 + 守护测试。

```python
# audit/services/taxonomy.py（或并入 audit_service.py）
ACTION_MEMBER_CREATED: Final[str] = "member.created"
ACTION_CREDENTIAL_UPDATED: Final[str] = "credential.updated"
ACTION_PAT_REVOKED: Final[str] = "pat.revoked"
# ... Phase 54 各埋点补充具体值
ALL_ACTIONS: Final[frozenset[str]] = frozenset({...})  # 守护测试基准
```

- **命名规范**：`verb.object` / `object.verb` 取**对象在前**风格（`member.created` / `credential.updated` / `pat.revoked` / `feishu_sync.triggered` / `exclusion_rule.changed` / `purge.started` / `purge.completed`）——对齐既有 `purge.started` / `repo.research.started` / `spec.drafted` 既成事实。
- **本 phase 只定义稳定容器 + 种子/预留常量**（CONTEXT：「至少定义稳定常量容器，具体 action 值由 Phase 54 各埋点补充」）。可预留 `RESERVED`/`ALL_ACTIONS` 区分，对齐 event_taxonomy 的 `ALL_EVENTS` / `RESERVED_EVENTS`。
- **v0.5 既有埋点收口预留**（Phase 54 落地，非本 phase）：`purge.started` / `purge.completed`（`server/services/purge_reconcile.py:240,254` — 注释已明写「供审计里程碑复用 T-23-09」）、`TriggerLog`（feishu）、`ActionLog`（subagent）。本 phase taxonomy 可预留这些常量名但不接线。

---

## 5. 脱敏实现（AUDIT-02）

CONTEXT：字段名敏感词匹配 + 值级高熵/密钥模式兜底，**语义对齐** `sensitive_detect._SECRET_PATTERNS`（可不 import，守 INV-3 不跨层硬依赖）。

### 推荐：`audit/services/redaction.py` 自持 `_redact_audit_payload`

复刻（非 import）两处既有范式：
1. **key-name 命中**（参考 `work_item_service._SECRET_KV_RE` 的键名集）：`token` / `secret` / `password` / `passwd` / `api_key` / `apikey` / `access_token` / `refresh_token` / `access_key` / `secret_key` / `private_key` / `credential` / `authorization` / `encrypted_config` / `token_hash` 等 → 值整体替换为 `"[已脱敏]"`。
2. **值级高熵/密钥模式兜底**（参考 `sensitive_detect._SECRET_PATTERNS` + `_HIGH_ENTROPY_TOKEN_RE` + Shannon ≥ 4.0）：对 str 叶子值跑私钥块 / AKIA / gh[pousr]_ / xox / 通用赋值 / 高熵串 → 替换 `"[已脱敏]"`。
3. **递归遍历** dict / list 嵌套结构（参考 Phase 23 `_redact_value` 只替换命中叶子、保留同载荷其余字段），保留结构与非敏感字段。

要点：
- **绝不回填明文**：覆盖凭证场景 = `ProviderCredential.encrypted_config`（Fernet 密文，本身也不该入 before/after 明文）、`GitInstanceCredential` token、`AccessToken.token_hash` / PAT 明文、飞书 `app_secret`。**绝不**对这些字段记原值——脱敏入口对 key-name 命中直接抹值。
- **结构化只记安全字段**：plan 应指导 Phase 54 调用方传 before/after 时**只传需审计的非敏感字段差异**（如「凭证从有→无」记 `{"has_token": true}` → `{"has_token": false}`，而非 token 值）。入口脱敏是**纵深防御兜底**，不是放任调用方传明文。
- **INV-3 守护**：不 `import sensitive_detect`（那在 `services/` 层，audit app 不应硬依赖）；复刻正则常量到 `audit/services/redaction.py`。语义对齐即可（CONTEXT 明许）。

---

## 6. async 约束

- 后端 async-first（adrf + channels）；emit 调用方可能在 sync（Django admin / signal / DRF sync view）或 async（adrf view / channels consumer / 编排）上下文。
- `AuditService.emit`（sync，`.objects.create`）+ `AuditService.aemit`（`sync_to_async(emit)`）双面，对齐既有 service async 范式（`sdd_spec_service` / `comment_event_service` 全用 `sync_to_async` 桥接 ORM）。
- actor 字段访问（`actor.id` / `actor.username`）必须在 `sync_to_async` 同步块内或调用方传标量，规避 async 裸访问 lazy-FK（参考 `build_envelope` 用 `session.work_item_id` 标量的注释、Phase 38 CR-01 类问题）。

---

## 7. Migration

- `makemigrations audit` 自动生成 `audit/migrations/0001_initial.py`（新 app 无前序依赖，除 `accounts` 已建——但 `actor_id` 是标量 UUID 非 FK，故 **无跨 app migration 依赖**，更干净）。
- Gate：`makemigrations --check` 干净（CONTEXT established patterns）。
- 若落 `system` app（备选）则为 `system/migrations/0008_auditevent.py`（前序 `0007_providercredential_is_default`）。

---

## Validation Architecture

为 Nyquist 验证策略，逐 success criterion 给可验证测试方法（全部后端 pytest，无需真实容器/外部系统）：

### SC-1 — `AuditEvent` 表落库 + 单一 service 入口（INV-6 精神）
- **migration gate**：`python manage.py makemigrations --check --dry-run` 干净（CI gate）。
- **字段持久化测试**（`test_audit_event_model.py`）：经 `AuditService.emit(...)` 写一行，重新 `AuditEvent.objects.get(...)` 断言全字段（actor_id / action / target_* / before / after / source / occurred_at / recorded_at / metadata）逐项落库正确。
- **INV-6 grep 守护**（`test_audit_event_inv6_guard.py`，镜像 `test_sdd_spec_inv6_guard.py`）：扫 `server/` 源码断言除 `AuditService` 外无旁路 `AuditEvent.objects.<write>` / 实例化 / `.save()`；命中即 fail 列 `文件:行`。
- **writer-actually-writes 反向测试**：断言 `audit/services/audit_service.py` 确含 `AuditEvent.objects.create`，防守护形同虚设。
- **索引存在性测试**（可选）：`AuditEvent._meta.indexes` 断言含 action / (target_type,target_id) / actor_id / occurred_at 维度（为 Phase 55 铺底）。

### SC-2 — append-only 不可篡改（无 update/delete 业务路径）
- **模型层守护测试**：`emit` 落一行后，取实例改字段调 `.save()` → `pytest.raises(AuditEventImmutableError)`；调 `.delete()` → `pytest.raises(AuditEventImmutableError)`。
- **grep 守护**（同 SC-1 的 INV-6 测试，正则集已含 `update` / `delete` 旁路检测）：断言源码无 `AuditEvent.objects.update/delete` 业务路径。
- **首次 create 放行测试**：断言 `emit` 的首次 create（`_state.adding=True`）正常落库（守护不误伤正常写入）。

### SC-3 — emit helper / 信号可被任意敏感操作调用 + fail-soft
- **sync + async 双面测试**：`AuditService.emit(...)`（sync）落库；`await AuditService.aemit(...)`（async，pytest-asyncio）落库——两面均产一行且字段一致。
- **fail-soft 测试**：monkeypatch `AuditEvent.objects.create` 抛异常 → 断言 `emit()` **不冒泡**（无异常逃逸）、返回 None、记 `audit.emit_failed` warning（用 caplog / structlog capture 断言）；模拟「主操作 + emit 失败」断言主操作返回值/状态不受影响。
- **任意调用方可用**：构造一个最小调用方（sync 与 async 各一）证明无需特殊上下文即可 emit（证明地基通用性，非具体覆盖——具体覆盖是 Phase 54）。

### SC-4 — 凭证/密钥/明文 token 在 before/after 脱敏不落明文
- **key-name 命中脱敏测试**：emit `before={"access_token": "<明文>", "name": "x"}` → 落库后断言 `access_token` 值 == `"[已脱敏]"`、`name` 值保留。覆盖 token/secret/password/api_key/access_token/private_key/credential/encrypted_config/token_hash 等键名。
- **值级高熵/密钥模式兜底测试**：emit 含未命中键名但值为私钥块 / `AKIA...` / `ghp_...` / 高熵 base64 串 → 断言值被替换 `"[已脱敏]"`。
- **嵌套结构测试**：dict/list 嵌套含敏感叶子 → 断言只命中叶子被抹、同载荷非敏感字段保留（参考 Phase 23 `_redact_value` 行为）。
- **DB 无明文断言**：脱敏后 `AuditEvent.objects.get(...)` 的 `before`/`after`/`metadata` JSON 序列化串中 `assert "<明文 token>" not in serialized`（终极防线断言）。
- **入口强制脱敏测试**：直接传明文给 `emit`（模拟调用方未自行脱敏）→ 断言入口仍兜底脱敏（证明「禁绕过服务端兜底」CONTEXT 约束）。

---

## Key files referenced（ground truth）

| 范式 | 文件 |
|------|------|
| append-only 模型形状（UUID PK / auto_now_add / 复合索引 / 模型层无业务方法） | `server/delivery/models/status_event.py`, `server/delivery/models/comment_event.py`, `server/delivery/models/plan_session_event.py` |
| 单一写入入口 service（sync+async、`sync_to_async` 桥接、INV-6） | `server/delivery/services/sdd_spec_service.py`, `server/delivery/services/comment_event_service.py` |
| INV-6 grep 守护测试（精确锚定 + 负向前瞻 + writer-actually-writes） | `server/tests/delivery/test_sdd_spec_inv6_guard.py` |
| 稳定 taxonomy 常量容器 + 守护基准集 | `server/delivery/services/event_taxonomy.py` |
| fail-soft best-effort（整段 try/except 吞异常 + warning） | `server/services/sensitive_detect.py` (`detect_sensitive_files`), `server/services/plan_orchestration/artifact_extraction.py`, `server/services/indexer.py` (`_run_sensitive_detection`) |
| 脱敏（key-name + 高熵 + 密钥正则 + 递归叶子替换、绝不回填明文） | `server/services/sensitive_detect.py` (`_SECRET_PATTERNS` / `_HIGH_ENTROPY_TOKEN_RE` / Shannon), `server/delivery/services/work_item_service.py` (`_redact_secrets` / `_SECRET_KV_RE` / `_BEARER_RE`) |
| 「刻意不用 FK 避免级联」软引用范式 | `server/system/models.py` (`ProviderCredential.scope_id`), `server/delivery/models/plan_session_event.py` (`work_item` UUID 软引用) |
| 凭证/密钥不落明文 | `server/system/models.py` (`ProviderCredential` Fernet), `server/access_tokens/models.py` (PAT sha256), `server/repositories/` (`GitInstanceCredential`) |
| v0.5 既有埋点（Phase 54 收口，非本 phase） | `server/services/purge_reconcile.py` (`log_purge_event` / `purge.started`/`purge.completed`), `server/subagent/models.py` (`ActionLog`), `server/feishu/models.py` (`TriggerLog`) |
| app 注册 / AUTH_USER_MODEL | `server/friday/settings.py:89` (INSTALLED_APPS), `:230` (`AUTH_USER_MODEL = "accounts.User"`) |
| app 配置范式 | `server/delivery/apps.py`, `server/delivery/models/__init__.py`（curated re-export） |

## Open items for plan-phase to decide (non-blocking)

- **事务边界**：emit 与主操作的事务关系（建议入口 docstring 写明「主操作成功后调用」，Phase 54 各调用方按场景用 `transaction.on_commit`）——本 phase 提供入口即可。
- **taxonomy 拆分**：`taxonomy.py` 独立 vs 并入 `audit_service.py`（建议独立，对齐 `event_taxonomy.py`）。
- **种子 action 常量集**：本 phase 定义多少个种子常量（建议覆盖 Phase 54 已知维度的预留常量 + `ALL_ACTIONS`/`RESERVED` 区分，但不强求全集）。
- **app 选址最终拍板**：推荐新 `audit` app；若硬 reuse-first 则 `system`（次优，保持 emit helper 零业务 import）。

## RESEARCH COMPLETE
