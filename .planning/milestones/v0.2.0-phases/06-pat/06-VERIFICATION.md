---
phase: 06-pat
verified: 2026-06-09T11:59:00Z
status: human_needed
score: 4/4 must-have truth-groups verified (PAT-01..06 satisfied)
overrides_applied: 0
re_verification: # No — initial verification
human_verification:

  - test: "浏览器创建令牌 → 在创建响应弹窗点「复制」→ 粘贴到别处校验"
    expected: "一次性明文 token 被完整复制到剪贴板；弹窗关闭后明文不可再获取"
    why_human: "剪贴板交互在 jsdom 下不稳定，需真实浏览器验证（06-VALIDATION Manual-Only）"

  - test: "创建表单中过期策略选「永不过期」"
    expected: "出现 amber 非阻塞风险提示文案，且「创建」按钮仍可点击提交（不被阻断）"
    why_human: "视觉呈现（颜色/图标/布局）需人工确认（06-VALIDATION Manual-Only）"
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  status: human_needed
---

# Phase 6: PAT 模型增强与一次性明文 Verification Report

**Phase Goal:** 用户能创建带名称/备注/可选有效期的个人访问令牌，明文仅展示一次，列表可按前后缀区分并自助吊销。
**Verified:** 2026-06-09T11:59:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1 | `note` + `token_suffix` 列存在，均 `default=""`（无数据迁移，历史行得空串） | ✓ VERIFIED | `models.py:44` `note = CharField(max_length=500, blank=True, default="")`；`models.py:47` `token_suffix = CharField(max_length=8, default="")`；迁移仅 2 个 `AddField` |
| 2 | 创建令牌时 `token_suffix = plaintext[-4:]` 服务端派生且 `note` 持久化 | ✓ VERIFIED | `views.py:62-66` `acreate` 写 `note=data.get("note","")` + `token_suffix=plaintext[-4:]`；test `token.token_suffix == plaintext[-4:]`、`token.note == "ci pipeline"` 通过 |
| 3 | `AccessTokenSerializer` 只读暴露 `note` + `token_suffix`，绝不含明文/`token_hash` | ✓ VERIFIED | `serializers.py:20-32` fields 含 note/token_suffix，`read_only_fields = fields`；test 断言 `token_hash`/`token` 不在输出且 `read_only_fields == fields` 通过 |
| 4 | 明文仅创建响应一次性返回，绝不落盘；sha256 唯一索引完好 | ✓ VERIFIED | `views.py:71-74` 仅 `response_data["token"]=plaintext`；`models.py:40` `token_hash unique=True, db_index=True` 复用 `hash_token`；`test_no_plaintext_token_in_db` + `test_list_never_returns_plaintext`（遍历所有 concrete_fields）通过 |
| 5 | 表单含可选 `note`（≤500）+ 永不过期非阻塞 amber 警告，note 流入 payload | ✓ VERIFIED | `AccessTokenForm.vue:50` zod `note.max(500)`；`:158-164` `v-if="never"` amber 警告（不参与校验）；`:76-78` `payload.note` trim 后非空才发送；test `never_expiry..._still_creates` + `note_value_flows_into_createToken_payload` 通过 |
| 6 | 列表展示 note 列 + `prefix…suffix` 指纹（无 suffix 降级为 prefix-only），无续期入口 | ✓ VERIFIED | `AccessTokenListTable.vue:89` `t.token_suffix ? prefix…suffix : prefix`（U+2026）；`:93-95` note 经文本插值；操作列仅 `revoke`（`:130-141`），无 renew；test `friday_pat_ab\u2026WXYZ` + prefix-only + note 转义通过 |
| 7 | owner 隔离 + 软吊销保持不变，revoke 幂等 | ✓ VERIFIED | `views.py:40-44` `get_queryset` filter `created_by=request.user`；`:82-84` revoke 守卫 `revoked_at is None`（幂等保留首次时间戳）；cross-user isolation + idempotent-revoke test 通过 |

**Score:** 4/4 must-have truth-groups verified (映射全部 PAT-01..06)

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `server/access_tokens/models.py` | note + token_suffix fields | ✓ VERIFIED | 两字段均带 `default=""`，Chinese 注释合规 |
| `server/access_tokens/migrations/0002_accesstoken_note_accesstoken_token_suffix.py` | AddField-only migration | ✓ VERIFIED | 恰好 2 个 `AddField`，依赖 `0001_initial`，无 RunPython |
| `server/access_tokens/serializers.py` | read-only note + token_suffix；create 接受可选 note | ✓ VERIFIED | output `read_only_fields = fields`；`AccessTokenCreateSerializer.note` `required=False, allow_blank=True, default=""`；无 token_suffix 入参 |
| `server/access_tokens/views.py` | acreate 派生 token_suffix=plaintext[-4:] | ✓ VERIFIED | 明文仅内存派生；明文一次性回传保持原样 |
| `web/src/types/accessToken.ts` | DTO note + token_suffix；create payload 可选 note | ✓ VERIFIED | `AccessTokenDto.note/token_suffix: string`；`AccessTokenCreatePayload.note?: string` |
| `web/src/components/accessTokens/AccessTokenForm.vue` | note 输入 + zod 对齐 + never 警告 | ✓ VERIFIED | name max(200) + note max(500)；amber 警告非阻塞 |
| `web/src/components/accessTokens/AccessTokenListTable.vue` | note 列 + 指纹，无续期 | ✓ VERIFIED | colspan=8 与 8 列匹配；仅 revoke 操作 |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | --- | --- | ------ | ------- |
| `views.py` | `AccessToken.objects.acreate` | `token_suffix=plaintext[-4:], note=...` | ✓ WIRED | `views.py:62-66` |
| `serializers.py` | model fields | `Meta.fields` 含两新字段，`read_only_fields = fields` | ✓ WIRED | `serializers.py:20-32` |
| `AccessTokenForm.vue` | `AccessTokenCreatePayload.note` | `payload.note = values.note?.trim() || (omit)` | ✓ WIRED | `AccessTokenForm.vue:76-78` |
| `AccessTokenListTable.vue` | `AccessTokenDto.token_suffix` | `t.token_suffix ? prefix…suffix : prefix` | ✓ WIRED | `AccessTokenListTable.vue:89` |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| 后端契约（suffix/note/serializer/no-leak/isolation/idempotent-revoke） | `uv run pytest tests/test_access_tokens.py tests/test_no_plaintext_token_in_db.py -q` | 9 passed | ✓ PASS |
| 前端（指纹/note 列/never 警告/note payload/clear-plaintext） | `pnpm vitest run src/components/accessTokens` | 12 passed (3 files) | ✓ PASS |
| 迁移已提交无待生成 | `makemigrations access_tokens --check --dry-run` | No changes detected (exit 0) | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| PAT-01 | 06-01/02/03 | 创建：名称必填、备注可选、有效期可选 | ✓ SATISFIED | note 全链路 + 三态过期；test_create_persists_note / note payload |
| PAT-02 | 06-01/02 | 明文一次性展示可复制，DB 仅 sha256 | ✓ SATISFIED (自动部分) | acreate 一次性返回；no-plaintext-in-db；复制体验见人工项 |
| PAT-03 | 06-01/02/03 | 列表展示元数据 + 前后缀指纹 | ✓ SATISFIED | prefix…suffix 指纹 + note 列；ListTable spec |
| PAT-04 | 06-02/03 | 可吊销，不提供续期 | ✓ SATISFIED | revoke action；列表无 renew 控件 |
| PAT-05 | 06-01/03 | 永不过期非阻塞安全提示 | ✓ SATISFIED (自动部分) | amber 警告非阻塞；视觉呈现见人工项 |
| PAT-06 | 06-02 | 仅能管理自己的令牌 | ✓ SATISFIED | get_queryset owner 过滤；cross-user isolation test |

所有 PLAN frontmatter 声明的 ID（PAT-01..06）均被覆盖；REQUIREMENTS.md 将 PAT-01..06 映射至 Phase 6，无 ORPHANED 需求。

### Anti-Patterns Found

无阻塞性反模式。代码评审（06-REVIEW.md）状态 clean：2 个 warning（WR-01 revoke 幂等、WR-02 自定义过期本地日终）均已 resolved 并经测试覆盖；2 个 info（IN-01/IN-02）已 acknowledged 接受。未发现 TBD/FIXME/XXX 调试标记，无 stub、无 `v-html`、无明文落盘路径。

### Human Verification Required

阶段 06-VALIDATION.md 明确声明 2 项 Manual-Only 验证，本质需真实浏览器/人工确认：

#### 1. 一次性明文复制体验 (PAT-02)

**Test:** 浏览器创建令牌 → 在创建响应弹窗点「复制」→ 粘贴到别处校验。
**Expected:** 一次性明文 token 被完整复制到剪贴板；弹窗关闭后明文不可再获取。
**Why human:** 剪贴板交互在 jsdom 下不稳定，需真实浏览器验证。

#### 2. 永不过期非阻塞提示可见性 (PAT-05)

**Test:** 创建表单过期策略选「永不过期」。
**Expected:** 出现 amber 非阻塞风险提示文案，「创建」按钮仍可点击提交（不被阻断）。
**Why human:** 视觉呈现（颜色/图标/布局）需人工确认。

### Gaps Summary

无自动化层面的差距。所有可程序化验证的 must-have（模型/迁移/序列化器/视图/DTO/表单/列表 + 安全契约 + 21 项后端/前端测试）全部 VERIFIED 通过。剩余仅为两项天然需要人工/浏览器确认的视觉与剪贴板交互项，故整体状态为 `human_needed`。

---

_Verified: 2026-06-09T11:59:00Z_
_Verifier: Claude (gsd-verifier)_
