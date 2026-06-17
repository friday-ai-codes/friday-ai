---
phase: 53-auditevent-emit
review_type: code-review
scope: "Phase 53 only (AuditEvent model + emit 地基). Excludes Phase 54 emit coverage, Phase 55 query/UI."
commits_reviewed:
  - 052d11ed6  # feat(53-01): audit app 骨架 + INSTALLED_APPS
  - 341b1b756  # feat(53-01): AuditEvent append-only 模型 + 守护 + 索引
  - d39471c88  # test(53-01): 0001_initial + append-only/字段/索引/标量-actor 测试
  - 941e3a8f4  # feat(53-02): taxonomy 稳定常量容器
  - 5ec064467  # feat(53-02): _redact_audit_payload (redaction.py)
  - 883d98401  # feat(53-02): AuditService emit/aemit + fail-soft + 强制脱敏
  - 2013739e0  # test(53-02): INV-6 grep 守护测试
files_reviewed:
  - server/audit/models/audit_event.py
  - server/audit/models/__init__.py
  - server/audit/apps.py
  - server/audit/migrations/0001_initial.py
  - server/audit/services/audit_service.py
  - server/audit/services/redaction.py
  - server/audit/services/taxonomy.py
  - server/audit/services/__init__.py
  - server/friday/settings.py (INSTALLED_APPS)
  - server/tests/audit/*
tests: "35 passed (tests/audit/) — verified locally via uv run pytest（含修复后新增 guard 测试）"
status: clean
findings_summary:
  blocker: 0
  high: 0
  medium: 3
  low: 3
findings_resolved:
  - MEDIUM-1  # 脱敏递归 tuple/set/frozenset（112e1ce7e）
  - MEDIUM-2  # 键名分段边界匹配（2a96573c4）
  - MEDIUM-3  # emit savepoint 隔离 + on_commit 强约束（18f304a77）
  - LOW-1     # target_id=None → 空串（50f3cd1af）
  - LOW-3     # before/after/metadata 假值语义保留（50f3cd1af）
findings_deferred:
  - LOW-2     # 值级脱敏 <40 字符无前缀明文：设计取舍，已知纵深防御边界，本 phase 不修
---

# Phase 53 Code Review — `AuditEvent` 模型 + emit 地基

## Verdict

地基整体扎实、契合 PLAN/CONTEXT 意图：append-only 双层守护（模型层 `save/delete` + INV-6
grep）、单一写入入口（`AuditService.emit/aemit`）、入口强制脱敏、fail-soft、actor 标量软引用
（无 FK 级联）、双时间戳、查询索引、taxonomy 稳定容器全部到位。`actor_id` 用 `UUIDField` 与
`accounts.User.id`（确认为 `UUIDField`，`server/accounts/models.py:39`）类型匹配，不存在
"actor 必失败→静默丢审计" 的隐患。28 个测试全绿。

无 BLOCKER / HIGH。发现 3 个 MEDIUM（脱敏边界 + fail-soft 事务语义）与 3 个 LOW（数据质量）。
所有问题均不阻断本 phase 交付，但 MEDIUM-1 / MEDIUM-3 建议在 Phase 54 接线前澄清/收敛。

---

## Findings

### MEDIUM-1 — 脱敏对 tuple/非 list 可迭代值不递归，明文可落库（PAT-02 边界绕过）
**文件**：`server/audit/services/redaction.py:99-122`

`_redact_audit_payload` 只递归 `dict` / `list`，对其他类型走 `return payload` 原样返回。
但 Django `JSONField` 默认 `json.dumps` 会把 **tuple 序列化为 JSON 数组**，于是 tuple 内的明文
密钥既未脱敏、又能成功落库。已本地复现：

```python
_redact_audit_payload({"data": ("ghp_AAAABBBBCCCCDDDDEEEE1234",)})
# -> {'data': ('ghp_...1234',)}   # 未脱敏；emit 后 JSONField 序列化为 ["ghp_...1234"] 落明文
```

这与 service docstring "调用方传明文也绝不落明文" 的强承诺、以及 CONTEXT 的 PAT-02 "绝不落明文
token" 约束相冲突。`set`/`bytes` 等不可 JSON 序列化类型会让 `create` 失败 → fail-soft 丢行（无
泄漏但丢审计），唯独 tuple 是"可落库 + 不脱敏"的真实泄漏路径。

**建议**：在递归中把 `tuple`（及 `Mapping`/`Sequence` 但排除 `str`/`bytes`）一并按 list/dict
处理，例如 `isinstance(payload, (list, tuple))` → 逐元素递归并返回 list。属本 phase 脱敏入口职责，
修复成本极低。

### MEDIUM-2 — 键名子串匹配过度脱敏常见非密钥字段（LLM 域数据质量）
**文件**：`server/audit/services/redaction.py:30-57`

`_is_sensitive_key` 用归一化后**子串**命中。`"token"` 会命中 `prompt_tokens` / `tokens_used` /
`token_count` 等，本项目（LLM/agent 平台）这类 metadata 非常常见。已复现：

```python
_redact_audit_payload({"prompt_tokens": 1500, "tokens_used": 42})
# -> {'prompt_tokens': '[已脱敏]', 'tokens_used': '[已脱敏]'}
```

虽"过度脱敏"安全方向正确（错向保守），但会在 Phase 54 埋点把有用的用量/计数审计抹成占位符，
削弱审计可读性。`"secret"`/`"credential"` 子串风险较小，`"token"` 是主要误伤源。

**建议**：对 `token` 这类高频词改为更精确的边界匹配（如要求与分隔符或词首/词尾相邻，区分
`access_token` vs `prompt_tokens`），或维护一个明确的"非敏感白名单后缀"（`_tokens`/`_count`）。
非阻断，但建议 Phase 54 前定调，避免大量埋点返工。

### MEDIUM-3 — fail-soft 在调用方事务内仍可能阻断主操作（事务被污染）
**文件**：`server/audit/services/audit_service.py:83-98`

`emit` 把 `AuditEvent.objects.create` 的异常整段吞掉，满足"emit 自身不冒泡"。但若调用方在
`@transaction.atomic` 块内、主操作写库之后调用 `emit`，而 `create` 抛 DB 级异常（约束冲突/连接
错误等），该异常会把当前数据库事务标记为 broken；emit 吞掉异常后主操作继续执行的后续 ORM 调用 /
最终 commit 会以 `TransactionManagementError`（"current transaction is aborted"）失败 → **主操作反
被 emit 间接阻断/回滚**，违背 "emit must never block main op"。

代码已通过 docstring 把事务边界（建议 `transaction.on_commit`）下放给 Phase 54 各调用方，属
"已知并显式 deferred"，故非本 phase BLOCKER。但这是 fail-soft 不变量的真实残余风险，且仅靠文档
约定、无机制兜底。

**建议**：在 docstring 升级为更强的约束措辞，或考虑 emit 默认走 `transaction.on_commit` 包装
（成功提交后才落审计）以从机制上闭合；至少在 Phase 54 接线评审中作为硬性检查项。

### LOW-1 — `target_id=None` 会被存成字面量字符串 "None"
**文件**：`server/audit/services/audit_service.py:89`

`target_id=str(target_id) if target_id != "" else ""`：当调用方显式传 `target_id=None` 时
`None != ""` 为真 → 落库 `"None"`（脏数据，污染 Phase 55 `(target_type,target_id)` 过滤）。默认值
为 `""` 时无问题，仅在显式传 None 时触发。建议判定改为 `if target_id not in ("", None)` 或
`"" if target_id in ("", None) else str(target_id)`。

### LOW-2 — 值级脱敏漏掉 <40 字符、非固定模式的明文密钥（已知纵深防御边界）
**文件**：`server/audit/services/redaction.py:60-96`

值级兜底仅覆盖：固定前缀模式（`ghp_`/`AKIA`/`xox`/PEM）、`key=value` 赋值形、以及长度 ≥40 的高熵
串。一个挂在**非敏感键名**下、<40 字符、无前缀的明文口令/对称密钥不会被抹（已复现
`{"value": "s3cr3tPass"}` → 原样）。这是设计上"key-name 为主、值级为兜底"的明确取舍，且现实凭证
载荷（`encrypted_config` / `token_hash` / `*_secret` 等）都走键名命中，覆盖到位。记录为已知边界，
不要求本 phase 修复。

### LOW-3 — `before/after/metadata` 的 falsy-but-meaningful 值被 `x or {}` 吞成 `{}`
**文件**：`server/audit/services/audit_service.py:91-95`

`before or {}` 对空 list `[]` / `0` / `False` 等"假值但有语义"的入参会替换成 `{}`，造成轻微语义
丢失（如 `after=[]` 表示"清空"被记成 `{}`）。当前字段语义以 dict 为主，影响很小。若 Phase 54 需要
区分"空集合"与"未提供"，建议改为 `{} if x is None else x`。

---

## Verified Good (no action)

- **append-only 模型层守护**：`save()` 用 `_state.adding` 放行首次 create、拦截既有行更新；
  `delete()` 直接 raise。`AuditEventImmutableError` 命名 + 负向前瞻在 INV-6 守护中正确排除。
- **INV-6 单一写入入口**：grep 守护正则覆盖 `objects.<write>` / 实例化 / 链式 save，排除
  writer/tests/migrations/models，并含 writer-actually-writes 反向断言，防"守护形同虚设"。读操作
  （filter/get）不被误判，为 Phase 55 查询留出空间。
- **async 正确性**：`aemit` 经 `sync_to_async(emit)` 桥接，actor 标量访问（`id`/`username`/
  `is_superuser`）全在同步块内，无 async 裸 lazy-FK 访问。
- **fail-soft 日志卫生**：`audit.emit_failed` warning 只记 `action`/`target_type`，不记
  `before/after/metadata`，避免失败路径泄漏明文（T-53-05）。
- **actor 软引用**：`actor_id` 用可空 `UUIDField` 非 FK，删用户不级联触碰审计行；与 `User.id`
  （`UUIDField`）类型一致，emit 携带 actor 不会因类型不匹配静默失败。
- **迁移**：`0001_initial` 与模型字段/索引/`db_table`/`ordering` 完全一致，`dependencies=[]`
  （actor 为标量无跨 app 依赖）。
- **redaction INV-3**：未 import `sensitive_detect`/`work_item_service`，正则复刻到本模块，符合
  "audit 叶子包不跨层硬依赖"。

---

## Status

**clean** — 0 BLOCKER / 0 HIGH。原 3 MEDIUM + LOW-1 / LOW-3 已全部修复并各自原子提交，新增
guard 测试覆盖；LOW-2 为设计取舍（值级 <40 字符无前缀明文，键名命中为主、值级兜底）记为已知边界、
本 phase 刻意 deferred。

### 修复记录（每项原子提交 + guard 测试）

- **MEDIUM-1**（`112e1ce7e`）：`_redact_audit_payload` 现对 `list/tuple/set/frozenset` 统一归一化
  为 list 后递归脱敏，封堵 tuple「可落库 + 不脱敏」明文绕过路径。
- **MEDIUM-2**（`2a96573c4`）：`_is_sensitive_key` 改为分段边界匹配——单词级敏感段要求整段相等、
  复合词归一化子串命中；`access_token`/`api_key`/`secret`/`password` 仍脱敏，`prompt_tokens`/
  `tokens_used`/`max_tokens` 等用量字段不再误伤。
- **MEDIUM-3**（`18f304a77`）：`emit` 的 `create` 包入 `transaction.atomic()` savepoint，调用方事务内
  失败仅回滚 savepoint 不污染外层事务；docstring 升级为强制 `transaction.on_commit` 约定（Phase 54
  接线评审硬性检查项）。新增以真实 DB 错误复现污染场景的 guard 测试。
- **LOW-1**（`50f3cd1af`）：`target_id=None` 落空串而非字面量 `"None"`。
- **LOW-3**（`50f3cd1af`）：`before/after/metadata` 仅 `None` 视作未提供补 `{}`，保留 `[]`/`0`/`False`
  等假值语义。
- **LOW-2**：deferred（已知纵深防御边界，设计上键名命中为主、值级为兜底；现实凭证载荷均走键名命中）。

验证：`uv run pytest tests/audit/ -q` 35 passed；`ruff format --check` / `ruff check` 通过；
`makemigrations --check --dry-run` 无变更。
