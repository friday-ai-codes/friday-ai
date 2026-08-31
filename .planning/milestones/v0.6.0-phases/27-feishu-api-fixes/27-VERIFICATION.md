---
phase: 27-feishu-api-fixes
verified: 2026-06-15T12:30:00Z
status: human_needed
score: 12/12 must-haves verified (4/4 ROADMAP success criteria structurally verified)
overrides_applied: 0
human_verification:

  - test: "用真实飞书凭证调 get_comments(project_key, work_item_id, work_item_type) 拉取一个已知有评论的工作项（如 example_platform issue 1000000006）"
    expected: "返回非空评论列表，逐条含 id/content/created_at/author/thread_parent_id；若端点路径/鉴权已变更则 fail-soft 返回 [] 并记 warning（不崩）"
    why_human: "真实端点路径/鉴权正确性（PF-11）需带真实凭证人工验收；自动测试仅以 respx mock 覆盖响应形状，无法验证 live 端点是否仍有效。CONTEXT 已明确记入 human-UAT。"

  - test: "（已知限制，非本 phase 范围）容器型工作项（URL 段 type=project）取数"
    expected: "本 phase 不支持容器型；真实 type_key 未知，按 REQUIREMENTS Out of Scope 处理。需待查\"工作项类型\"接口或字段反推后由后续 phase 补。"
    why_human: "PF-09 实测 type=project 返回 WorkItem Not Found(30005)；容器型真实 type_key 映射显式 Out of Scope，仅在此登记供人工知晓，非 gap。"
deferred:

  - truth: "WorkItemRelation / WorkItem 落库与 WorkItemService.upsert（关系/字段实际写库）"
    addressed_in: "Phase 28"
    evidence: "Phase 28 Goal: 立起操作态脊柱——canonical WorkItem + WorkItemService.upsert + WorkItemRelation 字段派生 + WorkItemStatusEvent；本 phase 仅产出派生 RelationSpec 结构不落库（CONTEXT 决策 + REQUIREMENTS WIT-04 映射 Phase 28）"

  - truth: "评论事件流 append-only WorkItemCommentEvent 摄取"
    addressed_in: "Phase 29"
    evidence: "Phase 29 Goal: 工作项评论以 append-only WorkItemCommentEvent 流式入库；本 phase 仅返回扁平评论列表 + 解析（REQUIREMENTS CMT-01/02 映射 Phase 29）"
audit_acknowledged:
  milestone: v0.25.0
  at: 2026-08-31
  status: human_needed
---

# Phase 27: 飞书接口前置修复 Verification Report

**Phase Goal:** 修对 4 个飞书工作项/评论接口缺陷（PF-09/10/11/12），为 `WorkItemService.upsert`（Phase 28）提供可靠的真实数据回源。纯 API/解析层修复，向后兼容，无 DB 模型/迁移。
**Verified:** 2026-06-15T12:30:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1 | 非 JSON 飞书响应（HTML/空/Extra data）经防御解析不抛崩，返回 None 并记 warning | ✓ VERIFIED | `safe_response_json` content-type 校验 + try/except（feishu_parsing.py L60-100），test_feishu_parsing 覆盖 |
| 2 | 完整 fields[] 对象（field_key/name/value/type_key/alias）被保留不丢元数据 | ✓ VERIFIED | `build_feishu_fields` 保留 5 键（L238-263）；两份 client 双写 `feishu_fields`+`flatten_fields` |
| 3 | 从 work_item_related_multi_select 字段能派生 belongs_to_project/sprint/version/related | ✓ VERIFIED | `derive_relations_from_fields` + `RELATION_TYPE_BY_FIELD`（L411-468）；fixture `field_000008=[1000000004]` 断言 |
| 4 | 能按 alias/key 从 feishu_fields 取 prd_url 与 select label | ✓ VERIFIED | `extract_prd_url`/`extract_select_label`（L311-377），test 覆盖 alias `prd_url` + `{label}` |
| 5 | get_work_item / get_comments 不传 work_item_type 时 fail-loud（TypeError） | ✓ VERIFIED | 两份 client 签名 `work_item_type: str`（无默认，feishu.py L122/L312, client.py L132/L304）；TypeError 测试 |
| 6 | WorkItemInfo 新增 feishu_fields 完整数组，旧 fields 拍平 dict 保留（向后兼容） | ✓ VERIFIED | `feishu_fields: list[dict] = field(default_factory=list)`（feishu.py L34, client.py L44），respx 断言 |
| 7 | get_comments 遇非 JSON fail-soft 返回 []+warning，正常响应正确解析 | ✓ VERIFIED | `safe_response_json`+`parse_comments`（feishu.py L340-352, client.py L286-298），双 client 测试 |
| 8 | get_work_item_relations 遇非 JSON（Extra data）降级返回 []+warning，绝不抛 | ✓ VERIFIED | `safe_response_json`，`data is None → []`（feishu.py L241-248）；origin="feishu_relation_api" 标注 |
| 9 | feishu/client.py 与 services/feishu.py 解析行为一致（同源 helper 无漂移） | ✓ VERIFIED | 两份 client 均 `from services.feishu_parsing import ...`；test_feishu_api_client 与 test_feishu_service 同输入同输出 |
| 10 | get_work_item 硬路径非 JSON 抛 FeishuResponseError（不静默落错） | ✓ VERIFIED | `strict_response_json`（feishu.py L162, client.py L172）+ get_plugin_token；异常消息脱敏 body[:200] |
| 11 | rich_text → Markdown 解析行为等价上移、两 client 委托同一实现 | ✓ VERIFIED | `rich_text_to_markdown`+`_paragraph_to_text`（L153-232），`_parse_rich_text` 改薄封装 |
| 12 | parse_comments 容错：None/缺键/形状不符 → [] 不抛 | ✓ VERIFIED | `parse_comments` 三层 isinstance 守卫（L488-498），test 覆盖 |

**Score:** 12/12 truths verified

### ROADMAP Success Criteria

| #   | Success Criterion | Status | Evidence |
| --- | ----------------- | ------ | -------- |
| 1 | 按真实 work_item_type 拉取，不再默认 story | ✓ VERIFIED (live 端容器型见 human) | type 必填 fail-loud；容器型 Out of Scope |
| 2 | get_work_item 保留完整 fields[] 对象不丢元数据 | ✓ VERIFIED | build_feishu_fields + 双写 |
| 3 | get_comments 修复后能拉取并解析评论 | ✓ VERIFIED（解析层）/ ⚠ live 端点需人工 | parse_comments + fail-soft；真实端点正确性 human-UAT |
| 4 | 关系可从 related_multi_select 读出 + relation 端点降级为可选 | ✓ VERIFIED | derive_relations_from_fields + safe_response_json 降级 |

### Deferred Items

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | WorkItemRelation/WorkItem 落库与 upsert | Phase 28 | WIT-04 映射 Phase 28；本 phase 仅产 RelationSpec 不落库 |
| 2 | 评论事件流 append-only 摄取 | Phase 29 | CMT-01/02 映射 Phase 29；本 phase 仅返回扁平列表 |

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `server/services/feishu_parsing.py` | 防御解析+字段保留/提取+关系派生+评论解析 helper | ✓ VERIFIED | 517 行，含 `derive_relations_from_fields`，无 Django 依赖 |
| `server/tests/services/test_feishu_parsing.py` | helper 全函数单测（DOMAIN §16 fixture） | ✓ VERIFIED | 26 用例全绿，含 `field_000008` fixture |
| `server/services/feishu.py` | canonical client FIX-01/02/03/04 | ✓ VERIFIED | import 共享 helper，feishu_fields/双写/fail-soft 接线 |
| `server/tests/services/test_feishu_service.py` | canonical client respx 单测 | ✓ VERIFIED | 9 用例全绿，respx mock |
| `server/feishu/client.py` | near-dup client FIX-01/03/04 | ✓ VERIFIED | import 同源 helper，行为对齐 |
| `server/tests/test_feishu_api_client.py` | feishu.client respx 单测 | ✓ VERIFIED | 7 用例全绿，与 service 测试同输出 |
| `server/feishu/models.py` | KeyFields 反向 import helper 常量 | ✓ VERIFIED | `from services.feishu_parsing import PRD_URL_FIELD_KEY, ...`（避免层级倒置） |

### Key Link Verification

| From | To | Via | Status |
| ---- | -- | --- | ------ |
| services/feishu.py | services/feishu_parsing.py | `from services.feishu_parsing import` (L11) | ✓ WIRED |
| feishu/client.py | services/feishu_parsing.py | `from services.feishu_parsing import` (L11) | ✓ WIRED |
| services/feishu.py get_work_item | WorkItemInfo.feishu_fields | `build_feishu_fields(raw_fields)` (L180→L203) | ✓ WIRED |
| feishu/client.py get_work_item | WorkItemInfo.feishu_fields | `build_feishu_fields(raw_fields)` (L190→L213) | ✓ WIRED |
| feishu/models.py KeyFields | feishu_parsing 常量 | reverse import (L186-189) | ✓ WIRED |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| FIX-01 | 27-02, 27-03 | 按真实 work_item_type 取数，不默认 story | ✓ SATISFIED | type 必填 fail-loud；容器型 live 验收记 human |
| FIX-02 | 27-01, 27-02 | 关系从关联字段派生 + relation 端点降级 | ✓ SATISFIED | derive_relations_from_fields + safe_response_json |
| FIX-03 | 27-01, 27-02, 27-03 | get_comments 修复拉取/解析评论 | ✓ SATISFIED（解析层）| parse_comments + fail-soft；live 端点 human-UAT |
| FIX-04 | 27-01, 27-02, 27-03 | 保留完整 fields[] 对象元数据 | ✓ SATISFIED | build_feishu_fields 5 键保留 |

无孤儿需求：REQUIREMENTS.md 将 FIX-01..04 全部映射 Phase 27，且均被至少一个 plan 的 `requirements` frontmatter 声明覆盖。

### Anti-Patterns Found

| File | Pattern | Severity | Impact |
| ---- | ------- | -------- | ------ |
| （无） | TODO/FIXME/XXX/TBD/HACK/placeholder/残留 `="story"` 默认 | — | 三份修改文件全扫描无命中 |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| 三套测试全绿（纯解析 + 双 client respx，socket 隔离） | `pytest tests/services/test_feishu_parsing.py tests/services/test_feishu_service.py tests/test_feishu_api_client.py --disable-socket` | 42 passed | ✓ PASS |

预存无关失败 `tests/knowledge/test_triggers.py::...delivers_once`（coding-trigger UUID）父提交 `dccb2f54` 即失败，确认与本 phase 无关，不计入。

### Human Verification Required

#### 1. get_comments live 端点正确性（PF-11）

**Test:** 用真实飞书凭证对已知有评论的工作项调 `get_comments`。
**Expected:** 返回非空评论列表（逐条 id/content/created_at/author/thread_parent_id）；端点若变更则 fail-soft 返回 `[]` + warning 不崩。
**Why human:** 真实端点路径/鉴权正确性需 live 凭证；自动测试仅 respx mock 覆盖响应形状。CONTEXT 已记 human-UAT。

#### 2. 容器型工作项（已知限制，Out of Scope）

**Test:** 容器型（URL 段 type=project）取数。
**Expected:** 本 phase 不支持；真实 type_key 未知，REQUIREMENTS Out of Scope，待后续 phase 补。
**Why human:** PF-09 实测返回 30005；仅登记供知晓，非 gap。

### Gaps Summary

无阻塞性 gap。4 个修复（FIX-01..04）的可自动验证部分全部落地：纯解析 helper 单一事实源、两份 client 同源接入消除漂移、type 必填 fail-loud、完整 fields[] 保留、关系字段派生、评论/relation 端点防御式 fail-soft、硬路径 fail-loud + 日志脱敏。42/42 单测绿，向后兼容（仅去默认 + 仅加带默认属性），无 DB 模型/迁移，无残留 stub/debt marker。

按 CONTEXT 明确约定，**get_comments 真实端点正确性**与**容器型工作项支持**为 human-UAT / Out of Scope，据此判定 `status: human_needed`（非 gaps_found）。落库/upsert/评论事件流为 Phase 28/29 deferred，不计入本 phase。

---

_Verified: 2026-06-15T12:30:00Z_
_Verifier: Claude (gsd-verifier)_
