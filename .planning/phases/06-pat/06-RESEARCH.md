# Phase 6: PAT 模型增强与一次性明文 - Research

**Researched:** 2026-06-09
**Domain:** Django (adrf async) 模型/迁移增量 + DRF 序列化 + Vue 3 / Tailwind 4 / reka-ui 表单与列表
**Confidence:** HIGH（纯增量增强，全部基于仓库现有真实代码，无新外部依赖）

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
**数据模型增强**
- 新增 `note = models.CharField(max_length=500, blank=True, default="")` 可选备注字段。
- 新增 `token_suffix = models.CharField(max_length=8, default="")`，创建时存明文后 4 字符（与现有 `token_prefix` 对称）。
- 迁移只加列；历史 token 的 `token_suffix`/`note` 留空串（明文已丢无法回填），UI 对历史 token 仅展示 prefix。
- `AccessTokenSerializer` 新增 `note` + `token_suffix` 只读字段。

**创建表单与安全提示**
- 创建表单新增可选「备注」`Input`（≤500 字符）。
- 选择「永不过期」(never) 时，表单内 inline 非阻塞警告（icon + 黄色提示文案），不阻断提交。
- 备注本期仅创建时填写，不支持创建后编辑（不引入 PATCH）。
- 校验沿用 vee-validate + zod：name 必填 ≤200，note 可选 ≤500。

**列表展示**
- 列表新增「备注」列展示 note。
- 指纹展示格式 `friday_pat_xxx…abcd`（prefix + … + suffix）；无 suffix（历史 token）时仅展示 prefix。
- 时间列（创建/最后使用/过期）沿用现有展示，保持现状。
- 吊销交互保持现有确认弹窗 + revoke 流程。

### Claude's Discretion
- 警告文案具体措辞、备注列宽与截断、suffix 与 prefix 的具体 UI 排版，由实现时按既有组件风格决定。

### Deferred Ideas (OUT OF SCOPE)
- 令牌 rotate / 续期、细粒度 scope、IP allowlist（v2：PATX-01~04）。
- 备注创建后编辑（PATCH）——本期不做。
- 令牌认证语义（Phase 7）、scope 细分、rotate/续期（v2）。本期纯模型/序列化/前端增量，**不触碰认证链路**。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PAT-01 | 用户可创建访问令牌，必填名称、可选备注、可选有效期（不填即永久） | 名称/有效期三态**已具备**（`AccessTokenForm.vue` + `acreate`）；本期仅补 `note` 入参链路（zod → DTO → `AccessTokenCreateSerializer` → `acreate`） |
| PAT-02 | 明文仅一次性返回、可复制，DB 仅存 sha256，明文绝不落盘 | **已具备**（`acreate` 返回 `response_data["token"]`，`AccessTokenRevealDialog.vue`）；本期需保证新增字段不破坏脱敏链路（见 Common Pitfalls / Security） |
| PAT-03 | 列表展示名称、备注、时间、前缀+后缀指纹 | 现有列表展示 name/prefix/时间；本期补 `note` 列 + `token_suffix` 拼接为 `friday_pat_xxx…abcd` 指纹 |
| PAT-04 | 用户可删除（吊销）；不提供续期 | **已具备**（`revoke` action + 二次确认 AlertDialog），本期不改 |
| PAT-05 | 创建"永不过期"令牌时给出非阻塞安全提示 | 表单 `expiryStrategy === 'never'` 时 inline amber 警告（复用 `AccessTokenRevealDialog.vue` 既有 amber 样式范式） |
| PAT-06 | 用户只能查看/创建/删除自己的令牌 | **已具备**（`get_queryset` 强制 `created_by=request.user`，`test_cross_user_isolation`），本期不改 |
</phase_requirements>

## Summary

本期是对**已落地**的 `access_tokens` app 的小幅增量增强，不是 greenfield。后端模型、adrf 异步 ViewSet、一次性明文返回、按 owner 隔离、软吊销、防明文落盘的锁名测试全部已存在并通过。需求 PAT-02/04/06 **已满足**，本期实际新增工作集中在三处：

1. **模型 + 迁移**：给 `AccessToken` 加 `note`（CharField，blank/default=""）和 `token_suffix`（CharField，default=""）两个**带 default 的列**。因为两者都有 `default`，Django 生成的 `AddField` 迁移可对存量表无损执行，历史行自动获得空串（无需 data migration、无需 `RunPython`）。
2. **创建链路透传 note + 写 token_suffix**：`AccessTokenCreateSerializer` 加 `note`；`acreate` 写 `note` 与 `token_suffix=plaintext[-4:]`（与现有 `token_prefix=plaintext[:12]` 对称）；`AccessTokenSerializer` 暴露 `note` + `token_suffix` 只读。
3. **前端**：DTO 加 `note`/`token_suffix`；表单加可选「备注」`Input`（zod `max(500)`）+ never 选项 inline amber 警告；列表加「备注」列 + 指纹 `prefix…suffix`。

**Primary recommendation:** 用 `python manage.py makemigrations access_tokens` 生成纯 `AddField` 迁移（两字段均带 `default`，不可省略 default，否则 SQLite/PG 加非空列会报错）；明文后缀用 `plaintext[-4:]` 镜像现有 `plaintext[:12]`；前端 amber 警告直接复用 `AccessTokenRevealDialog.vue` 中已有的 `border-amber-200 bg-amber-50 ... dark:...` 类名范式，保持视觉一致。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 持久化 note / token_suffix | Database / Storage（Django 模型 + 迁移） | API（序列化） | 列结构与默认值是 ORM/迁移职责 |
| 写入 token_suffix（明文后缀截取） | API / Backend（`acreate`） | — | 明文仅在 server 端短暂存在，截取必须在创建端完成，绝不传到前端再回写 |
| note 入参校验 | API / Backend（`AccessTokenCreateSerializer` max_length） | Frontend（zod，UX 即时反馈） | 后端是权威校验边界（V5）；前端校验仅提升体验 |
| never-expire 非阻塞警告 | Frontend（`AccessTokenForm.vue`） | — | 纯 UX 提示，不影响后端语义 |
| 指纹拼接 `prefix…suffix` | Frontend（`AccessTokenListTable.vue`） | — | 展示逻辑，数据由 DTO 提供 |
| owner 隔离 / 一次性明文 / 软吊销 | API / Backend（**已具备**） | — | 本期不触碰，仅需回归不破坏 |

## Standard Stack

无新增依赖。全部沿用仓库既有栈：

### Core（已在用，不新增）
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Django | >=5.1（迁移头注释显示运行环境 Django 6.0.1） | ORM / 迁移 | 项目后端框架 [VERIFIED: server/access_tokens/migrations/0001_initial.py 头注释 "Django 6.0.1"] |
| adrf | >=0.1.12 | 异步 DRF ViewSet（`acreate`/`aget_object`/`asave`） | 项目 async 约束 [VERIFIED: server/access_tokens/views.py imports `adrf.viewsets.ModelViewSet`] |
| djangorestframework | >=3.15 | 序列化器 | [VERIFIED: serializers.py] |
| vue / vee-validate / zod | vue ^3.5.26 | 表单校验 | [VERIFIED: AccessTokenForm.vue imports `@vee-validate/zod`, `vee-validate`, `zod`] |
| reka-ui (Select/Dialog/Input via ~/components/ui) | — | 表单/弹窗原语 | [VERIFIED: AccessTokenForm.vue imports `~/components/ui/select`, `~/components/ui/form`, `~/components/ui/input`] |
| tailwindcss | ^4.1.18 | 样式（amber 警告、列样式） | [VERIFIED: CLAUDE.md STACK + 现有 .vue 类名] |

**Installation:** 无。本期不安装任何包。

> Package Legitimacy Audit、Environment Availability：**SKIPPED** — 本期为纯代码/迁移增量，不安装外部包、不引入新外部运行时依赖（迁移在既有 `manage.py` / DB 上执行）。

## Architecture Patterns

### 数据流（增量部分）

```
创建 PAT:
  [Vue 表单 AccessTokenForm]
     name (zod min1/max200) + note? (zod max500) + expiryStrategy
        └─ never → 表单内 inline amber 警告（非阻塞）
     → emit submit(payload: {name, note?, expires_at?})
  → [store.createToken] → [api.create POST /api/access-tokens/]
  → [acreate (adrf async)]
        plaintext = generate_pat()                    # friday_pat_ + token_urlsafe(32)
        token_hash   = hash_token(plaintext)          # 已有：sha256，唯一索引
        token_prefix = plaintext[:12]                 # 已有
        token_suffix = plaintext[-4:]                 # 新增（镜像 prefix）
        note         = data.get("note", "")           # 新增
        await AccessToken.objects.acreate(...)
     → response = AccessTokenSerializer(token).data    # 含 note + token_suffix（只读）
       response["token"] = plaintext                   # 仅此一次返回明文
  → [store 剥离 token，仅 meta 入列表] → [RevealDialog 一次性展示明文]

列表:
  GET → AccessTokenSerializer(many) → DTO(含 note, token_suffix)
  → [ListTable] 指纹 = token_suffix ? `${token_prefix}…${token_suffix}` : token_prefix
                备注列 = note
```

### Pattern 1: 带 default 的 AddField 迁移（对存量表安全）
**What:** 两个新字段均声明 `default=""`（`note` 另含 `blank=True`），`makemigrations` 生成 `migrations.AddField`，对已有 `access_tokens` 表的存量行直接填默认空串，无需 data migration。
**When to use:** 给已有表加列且不能停机/不能丢历史数据时。
**Example:**
```python
# 预期 makemigrations 自动生成（access_tokens/migrations/0002_*.py）
# Source: 模式镜像 0001_initial.py 中 token_prefix=models.CharField(default='', max_length=20)
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("access_tokens", "0001_initial")]
    operations = [
        migrations.AddField(
            model_name="accesstoken",
            name="note",
            field=models.CharField(blank=True, default="", max_length=500),
        ),
        migrations.AddField(
            model_name="accesstoken",
            name="token_suffix",
            field=models.CharField(default="", max_length=8),
        ),
    ]
```
**关键:** 不要省略 `default`。SQLite/Postgres 给已有行的表加 `NOT NULL` 列时，没有 default 会触发交互式 "provide a one-off default" 提示或迁移失败。CharField 在 Django 默认 `null=False`，`default=""` 即满足非空约束。[VERIFIED: 0001_initial.py 已用同样 `token_prefix=models.CharField(default='', ...)` 模式]

### Pattern 2: 明文后缀镜像现有前缀（在创建端截取）
**What:** `token_suffix = plaintext[-4:]`，与现有 `token_prefix = plaintext[:12]` 对称，二者都仅在 `acreate` 内部用 server 端尚存的明文计算后写库。
**Why:** 明文出 server 即不可复得，后缀必须此刻截取；绝不能把明文传到前端再回写后缀（会重新引入明文落盘/传输风险）。
**Example:**
```python
# Source: server/access_tokens/views.py acreate（现有 token_prefix=plaintext[:12]）
token = await AccessToken.objects.acreate(
    name=data["name"],
    note=data.get("note", ""),          # 新增
    token_hash=hash_token(plaintext),
    token_prefix=plaintext[:12],
    token_suffix=plaintext[-4:],        # 新增，镜像 prefix
    expires_at=expires_at,
    created_by=user,
)
```

### Pattern 3: inline 非阻塞 amber 警告（复用既有样式）
**What:** 在 `AccessTokenForm.vue` 过期 Select 下方，当 `expiryStrategy === 'never'` 时 `v-if` 渲染一个 amber 提示块（icon + 文案），不参与 zod 校验、不阻断 `onSubmit`。
**Example（复用 RevealDialog 已有类名范式）:**
```vue
<!-- Source: 类名取自 web/src/components/accessTokens/AccessTokenRevealDialog.vue:54 -->
<p
  v-if="expiryStrategy === 'never'"
  class="flex items-start gap-1.5 rounded-lg border border-amber-200 bg-amber-50 p-2.5 text-xs text-amber-700 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-400"
>
  <span class="icon-[lucide--alert-triangle] mt-0.5 shrink-0" aria-hidden="true" />
  <span>永不过期的令牌一旦泄露将长期有效，建议设置有效期；如确需永久令牌请妥善保管。</span>
</p>
```
图标库已在用 `icon-[lucide--*]`（见现有组件）。

### Pattern 4: zod schema 扩展 + payload 透传
**What:** 表单 schema 加 `note`，`name` 同时补 `max(200)` 对齐 PAT 约束（现仅 `min(1)`）。
**Example:**
```ts
// Source: 扩展 web/src/components/accessTokens/AccessTokenForm.vue:46
const formSchema = toTypedSchema(
  z.object({
    name: z.string().min(1, '请填写 Token 名称').max(200, '名称不超过 200 字符'),
    note: z.string().max(500, '备注不超过 500 字符').optional(),
  }),
)
// onSubmit：payload.note = values.note?.trim() || undefined（空串不发，省带宽且语义清晰）
```

### Anti-Patterns to Avoid
- **把明文回传前端再算 suffix**：必须在 `acreate` 内截取。
- **省略迁移 default 后用 RunPython 回填**：本期历史行就该是空串，无需 data migration；加 `default=""` 一步到位。
- **给 `AccessTokenSerializer` 加可写字段**：序列化器 `read_only_fields = fields` 是安全契约，新增的 `note`/`token_suffix` 必须进 `fields` 且保持只读（创建入参走独立的 `AccessTokenCreateSerializer`）。
- **note 列表渲染用裸 HTML**：保持 Vue 文本插值（自动转义），避免存储型 XSS（note 是用户可控字符串，见 Security V5）。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| 给存量表加列 | 手写 SQL ALTER | `makemigrations`/`migrate` 生成 `AddField` | Django 处理跨库（SQLite/PG/MySQL）差异 |
| sha256 哈希 | 新哈希函数 | `runners.models.hash_token`（已 import） | contract 锁定，禁止重写 [VERIFIED: models.py:18] |
| 表单校验 | 手写校验 | vee-validate + zod（既有） | 项目约定 |
| 明文一次性展示/复制 | 新弹窗 | `AccessTokenRevealDialog.vue`（既有） | 已通过安全测试 |

## Common Pitfalls

### Pitfall 1: 防明文落盘锁名测试因新字段误伤
**What goes wrong:** `test_list_never_returns_plaintext` 会遍历 `obj._meta.concrete_fields` 断言明文不在任何字段。新增 `token_suffix` 只存明文**最后 4 字符**——这是非敏感指纹（与现有 `token_prefix` 同性质，prefix 已存明文前 12 字符且测试通过）。
**Why it happens:** 该测试断言的是**完整明文**（`plaintext` 整串）不出现，4 字符子串不会命中整串断言。但需确认测试逻辑确实是 `plaintext not in str(...)`（是整串包含判断）。[VERIFIED: test_access_tokens.py:52-53 `assert plaintext not in str(getattr(obj, field.name))`]
**How to avoid:** 不改测试断言语义；新增字段后该测试应继续 GREEN。新增一条断言验证 `token_suffix == plaintext[-4:]`（正向）即可。

### Pitfall 2: `acreate` 缺省 note 的 KeyError
**What goes wrong:** `AccessTokenCreateSerializer` 中 `note` 若 `required=False` 且未传，`validated_data` 里无 `note` 键，`data["note"]` 抛 KeyError。
**How to avoid:** `acreate` 用 `data.get("note", "")`；或 serializer 字段加 `default=""`（DRF 会注入默认值）。推荐 serializer 侧 `note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")`，使 `validated_data` 恒含 `note`。

### Pitfall 3: DTO/序列化器字段不同步导致前端拿不到值
**What goes wrong:** 后端 `AccessTokenSerializer.fields` 加了 `note`/`token_suffix`，但 `web/src/types/accessToken.ts` 的 `AccessTokenDto` 未同步 → 前端类型缺字段、列表读 `undefined`。
**How to avoid:** 同一个 plan/commit 内同步：序列化器 `fields` + `AccessTokenDto` + `AccessTokenCreatePayload`（加 `note?`）。

### Pitfall 4: 指纹拼接对历史 token 的空 suffix 处理
**What goes wrong:** 历史 token `token_suffix === ""`，若无条件拼 `${prefix}…${suffix}` 会显示 `friday_pat_X…`（尾部空、悬挂省略号）。
**How to avoid:** `token_suffix ? \`${token_prefix}…${token_suffix}\` : token_prefix`（CONTEXT 明确：无 suffix 仅展示 prefix）。

### Pitfall 5: `name` zod 校验与后端不一致
**What goes wrong:** 后端 `CharField(max_length=200)`，前端现仅 `min(1)` 无 max → 用户输 >200 字符前端放行、后端 400。
**How to avoid:** 前端 `name` 补 `.max(200)`，note 加 `.max(500)`，对齐后端权威校验。

## Runtime State Inventory

> 本期含「加字段」的模型变更，但**不涉及重命名/迁移既有数据键**。逐项确认：

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `access_tokens` 表存量行将通过 `AddField default=""` 自动获得空 `note`/`token_suffix`。无键名/ID 重命名。 | 仅 schema 迁移（AddField），**无 data migration** |
| Live service config | None — 该 app 无外部服务侧配置（无 n8n/Datadog 等）。 | 无 |
| OS-registered state | None — 无 OS 级注册项依赖该字段。 | 无 |
| Secrets/env vars | None — 不新增/重命名任何 secret 或 env 变量；明文不入任何持久层（契约不变）。 | 无 |
| Build artifacts | None — 纯 Python/TS 源码与迁移文件，无编译产物/egg-info 依赖此变更。 | 无 |

**规范问题答复（存量表加列后还有何残留）:** 仅 DB 表结构需迁移；历史行业务上就应是空 note/空 suffix（明文已丢无法回填），这是预期行为，非遗漏。

## Code Examples

### 序列化器扩展（输出只读 + 创建入参）
```python
# Source: 扩展 server/access_tokens/serializers.py
class AccessTokenSerializer(serializers.ModelSerializer):
    is_valid = serializers.BooleanField(read_only=True)

    class Meta:
        model = AccessToken
        fields = [
            "id", "name", "note",            # 新增 note
            "token_prefix", "token_suffix",  # 新增 token_suffix
            "created_at", "expires_at", "revoked_at", "last_used_at", "is_valid",
        ]
        read_only_fields = fields            # 安全契约：输出全只读

class AccessTokenCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")  # 新增
    expires_at = serializers.DateTimeField(required=False, allow_null=True)
```

### 模型字段（镜像现有 token_prefix 注释风格，中文）
```python
# Source: 扩展 server/access_tokens/models.py
# 可选备注，便于用户区分用途；空串为默认（历史 token 无备注）。
note = models.CharField(max_length=500, blank=True, default="")
# 明文后 4 字符，与 token_prefix 对称形成 friday_pat_xxx…abcd 指纹（非敏感）。
token_suffix = models.CharField(max_length=8, default="")
```

### 前端 DTO 同步
```ts
// Source: 扩展 web/src/types/accessToken.ts
export interface AccessTokenDto {
  // ...existing...
  note: string            // 新增：备注，可能为空串
  token_suffix: string    // 新增：明文后 4 字符，空串=历史 token
}
export interface AccessTokenCreatePayload {
  name: string
  note?: string           // 新增，可选
  expires_at?: string | null
}
```

### 列表指纹列
```vue
<!-- Source: 扩展 web/src/components/accessTokens/AccessTokenListTable.vue -->
<span class="font-mono text-xs text-muted-foreground">
  {{ t.token_suffix ? `${t.token_prefix}…${t.token_suffix}` : t.token_prefix }}
</span>
```

## State of the Art

无范式迁移。本期沿用仓库既定模式（adrf async ViewSet、ModelSerializer 全只读输出、vee-validate+zod、reka-ui via `~/components/ui`）。GitHub/GitLab 风格 PAT 指纹（前缀+后缀）与非阻塞 never-expire 警告是成熟惯例，CONTEXT 已锁定采用。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `makemigrations` 会生成纯 `AddField`（两字段带 default，无交互式 default 提示） | Architecture Pattern 1 | 低——两字段均显式 `default=""`，CharField 默认 `null=False`，default 满足非空。若错，迁移仍可手写（示例已给）。`makemigrations` 实跑可证伪。[ASSUMED — 基于 0001 中 token_prefix 同模式] |
| A2 | 现有防泄漏测试断言整串明文，故 4 字符 suffix 不误伤 | Pitfall 1 | 低——[VERIFIED] 测试源码为 `plaintext not in str(...)`，整串包含判断 |
| A3 | 前端 amber 警告复用 RevealDialog 类名即与设计系统一致 | Pattern 3 | 极低——类名直接取自同目录现有组件 [VERIFIED] |

**所有高风险项均已 VERIFIED；A1 可在执行时用 `makemigrations --check`/实跑证伪，无阻断。**

## Open Questions

1. **note 是否需要 trim / 去除首尾空白？**
   - What we know: CONTEXT 仅要求 ≤500、可选、不可后期编辑。
   - What's unclear: 是否对纯空白 note 归一为空串。
   - Recommendation: 前端 `values.note?.trim() || undefined`；后端 `allow_blank=True default=""`。属 Claude's Discretion，无需用户确认。

2. **`token_suffix` 列宽 8 但只存 4 字符** —— CONTEXT 明确 `max_length=8` 存后 4 字符，留余量。按 CONTEXT 原样实现，不质疑。

## Validation Architecture

> nyquist_validation = true（config.json），本节适用。

### Test Framework
| Property | Value |
|----------|-------|
| Backend framework | pytest + pytest-django + pytest-asyncio [VERIFIED: STACK + test 文件] |
| Backend config | `server/pyproject.toml`（ruff/mypy/pytest），fixtures 在 `server/tests/conftest.py`（`make_access_token`） |
| Backend quick run | `cd server && pytest tests/test_access_tokens.py -x` |
| Backend full | `cd server && pytest` |
| Frontend framework | vitest + @vue/test-utils + happy-dom [VERIFIED: STACK + spec 文件] |
| Frontend quick run | `cd web && pnpm vitest run src/components/accessTokens` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PAT-01 | 创建含 note，note 入库 | unit (django_db) | `pytest tests/test_access_tokens.py -k create -x` | ✅ 扩展现有 `test_create_returns_plaintext_once` |
| PAT-02 | 明文一次性、不落盘（新字段不破坏） | unit | `pytest tests/test_access_tokens.py::test_list_never_returns_plaintext -x` | ✅ 现有，须保持 GREEN |
| PAT-02 | token_suffix == plaintext[-4:] 正向断言 | unit | `pytest tests/test_access_tokens.py -k suffix -x` | ❌ Wave 0（新增断言/用例） |
| PAT-03 | 序列化器输出含 note + token_suffix 只读 | unit | `pytest tests/test_access_tokens.py -k serializer -x` | ❌ Wave 0（可加序列化器断言） |
| PAT-03 | 指纹拼接 / 历史空 suffix 仅显示 prefix | unit (vitest) | `pnpm vitest run src/components/accessTokens` | ❌ Wave 0（扩展 ListTable spec） |
| PAT-05 | never 选项显示 inline 警告且不阻断提交 | unit (vitest) | `pnpm vitest run src/components/accessTokens` | ❌ Wave 0（扩展 Form/Settings spec） |
| PAT-04/06 | 吊销 + owner 隔离 | unit | `pytest tests/test_access_tokens.py -k "revoke or isolation" -x` | ✅ 现有，不改 |

### Sampling Rate
- **Per task commit:** 对应 quick run（后端/前端按改动范围）
- **Per wave merge:** `cd server && pytest tests/test_access_tokens.py tests/test_no_plaintext_token_in_db.py` + `cd web && pnpm vitest run src/components/accessTokens`
- **Phase gate:** 后端全量 `pytest` + 前端 `pnpm vitest run` 全绿，且 `migrate` 在干净 DB 与含存量行 DB 上均成功

### Wave 0 Gaps
- [ ] `server/tests/test_access_tokens.py` — 加 `token_suffix == plaintext[-4:]`、note 持久化、序列化器含 note/token_suffix 只读 的断言
- [ ] `web/src/components/accessTokens/__tests__/AccessTokenListTable.spec.ts` — 新建：指纹拼接 + 备注列 + 历史空 suffix 降级
- [ ] 扩展 `AccessTokenSettings.spec.ts` / Form 测试 — never 警告渲染、note 透传到 createToken payload
- [ ] 迁移冒烟：`cd server && python manage.py makemigrations access_tokens --check`（CI 守护无漏迁移）

## Security Domain

> security_enforcement = true, ASVS level 1。

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no（本期不碰认证，Phase 7） | — |
| V3 Session Management | no | — |
| V4 Access Control | yes（保持） | `get_queryset` 强制 `created_by=request.user`（已具备，`test_cross_user_isolation`） |
| V5 Input Validation | yes | `note` 后端 `max_length=500`（DRF 权威校验）+ 前端 zod；列表 note 用 Vue 文本插值（自动转义，防存储型 XSS） |
| V6 Cryptography | yes（保持） | sha256 经 `hash_token`（禁重写）；明文绝不落盘；`token_suffix` 仅明文后 4 字符（非敏感指纹，不可反推） |

### Known Threat Patterns
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| note 存储型 XSS | Tampering | Vue 文本插值自动 HTML 转义；不使用 `v-html` 渲染 note |
| 明文经新字段意外泄漏（日志/序列化/store/localStorage） | Information Disclosure | 序列化器输出全 `read_only`；store 仍剥离 `token` 不入 state（已具备）；新字段不参与明文链路；`test_no_plaintext_token_in_db` / `test_list_never_returns_plaintext` 守护；前端 `does_not_log_plaintext` spec 守护 |
| token_suffix 暴露过多明文 | Information Disclosure | 仅存/暴露 4 字符（与已通过测试的 12 字符 prefix 同性质，远不足以暴力还原 256bit 随机串） |
| 跨用户读/吊销 | Elevation of Privilege | owner 过滤已具备，本期不放宽 |

## Sources

### Primary (HIGH confidence)
- 仓库源码（直接读取）：`server/access_tokens/{models,serializers,views}.py`、`server/access_tokens/migrations/0001_initial.py`、`server/tests/test_access_tokens.py`、`server/tests/test_no_plaintext_token_in_db.py`、`server/tests/conftest.py`（`make_access_token`）、`web/src/types/accessToken.ts`、`web/src/components/accessTokens/*.vue`、`web/src/{stores,api}/accessTokens.ts`、`web/src/components/accessTokens/__tests__/*.spec.ts`
- `.planning/phases/06-pat/06-CONTEXT.md`（用户锁定决策）、`.planning/REQUIREMENTS.md`、`.planning/STATE.md`、`.planning/config.json`、`CLAUDE.md`（栈与 async 约束）

### Secondary (MEDIUM confidence)
- 无（本期无需外部检索）

### Tertiary (LOW confidence)
- 无

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 全部为仓库在用、源码可证
- Architecture/migration: HIGH — 迁移模式镜像现有 `token_prefix=CharField(default='')`，仅 A1（makemigrations 输出形态）为可证伪假设
- Pitfalls: HIGH — 关键断言（防泄漏测试语义）已读源码确认

**Research date:** 2026-06-09
**Valid until:** 2026-07-09（稳定增量，30 天）
