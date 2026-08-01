---
phase: 111-schema
status: passed
score: 24/24
verified: 2026-07-29
verifier: gsd-verifier (goal-backward)
re_verification: false
deferred:
  - truth: "AI 打回率/人审修改量/澄清轮次三指标有真实数据"
    addressed_in: "Phase 112–114"
    evidence: "CONTEXT 锁定「本相位留函数接口，数据由后续相位填充」；ROADMAP Phase 114 goal 覆盖归因打回/澄清回灌/人工 block 编辑"
  - truth: "一个项目一份活跃蓝图的唯一性守卫（SCHEMA-07 前半）"
    addressed_in: "Phase 112"
    evidence: "PLAN 111-02 P10 备注「唯一性守卫由 112 的创建入口负责」；Phase 112 为蓝图编排创建入口相位"
  - truth: "blueprint_anchor / BlueprintLifecycleService / blueprint.stage.* 常量 / 7 个 call_source 值的生产调用方"
    addressed_in: "Phase 112–114"
    evidence: "CONTEXT「重锚定算法…114 消费」「前 7 值调用点在 112–114 落地」；本相位边界即「只做数据与服务底座，不做编排流水线」"
---

# Phase 111: 蓝图底座 Verification Report

**Phase Goal:** 蓝图的一切结构与状态有了权威地基——blueprint/v1 schema 由 jsonschema 强制、11 态生命周期有守卫可追溯、划线线程与评审人模型就位、仓库章程模型与 AI 起草管道可用、execution_plan 可确定性派生、golden set 质量基线建立。
**Verified:** 2026-07-29
**Status:** passed（24/24 must-haves：5 条 ROADMAP SC + 19 条 PLAN truths 全数 VERIFIED）
**行为证据基线:** `cd server && uv run pytest tests/services/test_blueprint_schema.py tests/services/test_blueprint_execution.py tests/services/test_blueprint_quality.py tests/services/test_event_taxonomy_alignment.py tests/delivery/ tests/repositories/ -q` → **938 passed, 0 failed**（97.65s）；`uv run python manage.py evaluate_blueprint_golden` → **exit 0**；`makemigrations --check --dry-run` → exit 0。

## 5 条 Success Criteria 逐条判定

| # | Success Criterion | 判定 | 证据 |
|---|-------------------|------|------|
| 1 | 缺段/缺必填被 jsonschema 拒绝；六段齐全样例落 ArtifactVersion；两版本可产 block 级 diff | ✓ PASS | `validate_blueprint` 六段 required + 引用完整性后置检查（blueprint_schema.py:765，28 例 schema 测试）；`builtin_types.py:22-25` 判别分支接进 ArtifactService 强制门——`test_blueprint_missing_section_rejected` 断言 `ArtifactContentInvalid`、`test_blueprint_content_creates_artifact_v1` 断言 schema_version=blueprint/v1 落库；diff 端到端 `test_add_version_supersedes_and_block_diff_end_to_end` + 集成 `test_add_version_block_diff_hits_exactly_changed_block`（modified 恰命中被改 block_id）。全部通过 |
| 2 | 11 态转移由 BlueprintLifecycleService 单点收口；open+blocking 阻塞 confirm；失败/废弃显式终态且失败可重试；每次转移落 ConvergenceSessionEvent（新增 blueprint_* 类型不改既有） | ✓ PASS | `_ALLOWED_TRANSITIONS` 与 DESIGN §4.2 逐边比对 **25/25 边完全一致**（含 ""→researching 入口、failed→researching 重试、archived/superseded 零出边）；confirm 守卫 `blocking=True` aexists（lifecycle_service.py:176）；CAS `filter(id, blueprint_status=from).update` + `ConcurrentBlueprintTransitionError`（:226）；事件 `EVENT_BLUEPRINT_STATUS_TRANSITIONED`（:266）best-effort try/except；event_taxonomy diff **+28/−0 纯追加**、BLUEPRINT_EVENTS 独立 frozenset 不进 ALL_EVENTS（`test_event_taxonomy_alignment` 绿）；INV-6 旁路写守护（模型级+字段级+守护的守护）3 例绿；集成 `test_lifecycle_trunk_confirm_gate_and_reviewer_roster` / `test_transition_with_session_emits_blueprint_event_row` 通过 |
| 3 | 确认动作自动进评审人名单，可查、可手动增补，署名与时间留痕 | ✓ PASS | transition 内 `BlueprintReviewer.objects.aget_or_create(defaults={"first_action": "final_approve"})`（:186，首插不覆盖）；`add_reviewer` 手动增补（:203）；`user` FK + `first_action` + `created_at` + UniqueConstraint(artifact,user)（blueprint_reviewer.py，migration 0031）；related_name=blueprint_reviewers 可查。lifecycle 40 例 + 集成 DB 重读断言通过 |
| 4 | RepoCharter 可由 AI 三源蒸馏出草案，人工 confirm 生效（source=human_confirmed）；人工确认过的章程 AI 只能提修订草案不能覆盖 | ✓ PASS | `adraft_charter` 三源（overview_text/facets + MR 20 条 + verified/rejected RepoAssociation）→ LLM（`use_call_source(BLUEPRINT_CHARTER_DRAFT)` :303）→ normalize 白名单；human_confirmed 分支只写 `draft_content`（:339-341）；`aconfirm_charter` 置 HUMAN_CONFIRMED/version+1/confirmed_by/draft 清空（:391-405）。不变量专测 `test_ai_never_overwrites_human_confirmed`（服务层快照逐字段）+ `test_draft_after_confirm_only_writes_draft_content`（API 层）通过；REST 三端点 IsAuthenticated + 401/404/503 分支 14 例 API 测试绿 |
| 5 | golden set 离线可跑：高三提分专项首条 case，输出引用覆盖率/目标仓命中率/审查打回率等指标，同输入重复运行一致 | ✓ PASS | 实跑 `manage.py evaluate_blueprint_golden` → `gaokao_boost: citation_coverage=1.0 target_repo_hit_rate=1.0 → PASS`，exit 0，caller 事件带 duration_ms；确定性双跑内建门槛（command:77-81 逐字节比对）+ `test_evaluate_blueprint_golden` 8 例（含连续两次输出一致、坏 case CommandError 非零退出）；fixture 含 onion-learning/study-course/onion-practice 三 direct 仓。打回率/人审修改量/澄清轮次为 CONTEXT 锁定的占位接口（数据 112–114 填充，见 deferred） |

## Observable Truths（PLAN must_haves，19/19）

| # | Truth（按 plan 归组） | 状态 | 证据 |
|---|------|------|------|
| 01-1 | 缺段/缺必填被 validate_blueprint 拒绝并给可读错误 | ✓ | 参数化缺段测试（json_path: message 格式），28 例绿 |
| 01-2 | 合法样例经 ArtifactService.create 落 ArtifactVersion | ✓ | test_blueprint_content_creates_artifact_v1 |
| 01-3 | v0 content 行为零变化仍走 validate_technical_plan | ✓ | builtin_types 分支 else 路径 + test_v0_content_still_passes / test_v0_invalid_content_still_rejected + test_artifact_service.py 回归绿 |
| 01-4 | 两版本产出 block 级 diff 三分类可辨识 | ✓ | diff_blueprint_blocks（sorted 确定性）+ 端到端/集成双测 |
| 01-5 | derive_execution_plan 确定性且输出过 validate_technical_plan | ✓ | 复用 import（execution.py:23），零 dict_to_technical_plan；双跑逐字节测试 + command 内建门槛 |
| 02-1 | 11 态单点收口，非法转移抛 ValueError 状态不变 | ✓ | 转移表 25 边 = DESIGN §4.2；非法边参数化测试 + DB 未变断言 |
| 02-2 | open+blocking 阻塞 confirm，resolved 后可确认 | ✓ | :176 守卫 + lifecycle/集成双测 |
| 02-3 | 确认用户自动入名单（first_action 首插不覆盖），可手动增补 | ✓ | aget_or_create 语义测试 |
| 02-4 | failed/superseded 显式终态；failed→researching 可重试；archived/superseded 无出边 | ✓ | 转移表 + 参数化用例 |
| 02-5 | 并发双写被 CAS 拒绝；事件 best-effort 不反噬 | ✓ | ConcurrentBlueprintTransitionError 测试；session=None 零事件行仍成功 |
| 02-6 | 重锚定三分支（精确/≥0.85 模糊/orphaned 不删线程） | ✓ | blueprint_anchor.py（SIMILARITY_THRESHOLD=0.85，stdlib difflib，零 ORM）+ 10 例含阈值边界 |
| 03-1 | AI 三源蒸馏草案（source=ai_draft）；LLM 不可用返回 None 零副作用 | ✓ | provider 缺失/坏 JSON → None 且 count==0 测试 |
| 03-2 | confirm 后 source=human_confirmed/version+1/署名；再起草只写 draft_content 正式字段逐字节不变 | ✓ | P11 不变量双层专测 |
| 03-3 | 三端点 IsAuthenticated 可用；无章程 GET 404 | ✓ | urls.py:328-340 三条 path + TestCharterAuth/Detail/Draft/Confirm 14 例 |
| 03-4 | LLM 调用带 call_source=blueprint_charter_draft，8 值登记 LOGGING-SPEC §4.1 | ✓ | :303 包 ainvoke；CallSource 实测 count=44；LOGGING-SPEC 命中 |
| 04-1 | golden command 离线可跑，未过门槛非零退出 | ✓ | 实跑 exit 0；CommandError 路径 3 例测试 |
| 04-2 | 首条 case 高三提分专项，机制级断言 | ✓ | expected: direct_repos 三仓/required fp/min 阈值（非逐仓全等） |
| 04-3 | 同输入重复运行结果一致 | ✓ | command 内建双跑 + 测试连续两次输出逐字节一致 |
| 04-4 | schema→落库→11 态→派生全链路冒烟通过 | ✓ | test_blueprint_integration.py 5 例全绿（golden fixture 单一事实源驱动） |

## Artifacts 检查表（存在 / 非 stub / 导出面 / 接线）

| Artifact | 行数 | 导出面核验 | 状态 |
|----------|------|-----------|------|
| `server/services/process_runtime/blueprint_schema.py` | 972 | BLUEPRINT_SCHEMA_VERSION/BLUEPRINT_JSON_SCHEMA/validate_blueprint/iter_blocks/diff_blueprint_blocks + 预编译 Draft202012Validator，零 django/delivery import | ✓ VERIFIED+WIRED |
| `server/services/process_runtime/blueprint_execution.py` | 210 | derive_execution_plan/derive_technical_plan_document/DEFAULT_BRANCH_STRATEGY，remove→delete 映射 | ✓ VERIFIED+WIRED |
| `server/services/process_runtime/blueprint_quality.py` | 140 | citation_coverage/target_repo_hit_rate 实装 + 3 占位签名（CONTEXT 锁定），顶层零 ORM | ✓ VERIFIED+WIRED |
| `server/delivery/artifacts/builtin_types.py`（修改） | +12/−1 | schema_version 判别分支 + 懒 import validate_blueprint；−1 仅 docstring 行 | ✓ WIRED |
| `server/delivery/models/artifact.py`（修改） | — | BlueprintStatus 11 值（max_length=32）+ 组合索引 | ✓ VERIFIED |
| `server/delivery/models/blueprint_thread.py` | 159 | anchor/anchor_status/kind/severity/blocking/options/status/return_stage/initiated_by_user_id/created_on_version——DESIGN §6.1 全字段 + (artifact,status,blocking) 索引 | ✓ VERIFIED |
| `server/delivery/models/blueprint_reviewer.py` | 53 | artifact+user UniqueConstraint + first_action + created_at | ✓ VERIFIED |
| `server/delivery/migrations/0031_blueprint_models.py` | 114 | 三 CreateModel + AddField blueprint_status + AddIndex；makemigrations --check 干净 | ✓ VERIFIED |
| `server/delivery/services/blueprint_lifecycle_service.py` | 282 | BlueprintLifecycleService/ConcurrentBlueprintTransitionError；Artifact 写零 .save() 全 CAS | ✓ VERIFIED+WIRED |
| `server/delivery/services/blueprint_anchor.py` | 106 | reanchor/SIMILARITY_THRESHOLD=0.85，stdlib only | ✓ VERIFIED（消费方 114，见 deferred） |
| `server/delivery/services/event_taxonomy.py`（修改） | +28/−0 | 4 常量 + BLUEPRINT_EVENTS 独立 frozenset，纯追加 | ✓ VERIFIED |
| `server/repositories/models.py`（修改） | — | class RepoCharter（OneToOne related_name=charter + Source/Evolution + 七结构化字段 + draft_content） | ✓ VERIFIED |
| `server/repositories/migrations/0040_repo_charter.py` | 81 | CreateModel RepoCharter | ✓ VERIFIED |
| `server/repositories/services/charter_service.py` | 418 | adraft_charter/aconfirm_charter/normalize_charter_draft + redact_secrets_in_text + 四观测事件 | ✓ VERIFIED+WIRED |
| `server/repositories/charter_views.py` | 106 | 三 adrf APIView（IsAuthenticated×3、sync_to_async .data、零 RepoCharter 写） | ✓ VERIFIED+WIRED |
| `server/agents/call_source.py`（修改） | +30/−3 | 8 个 BLUEPRINT_* 值；−3 为两处「36 值」计数改 44；实测 len==44 | ✓ VERIFIED |
| `server/delivery/management/commands/evaluate_blueprint_golden.py` | 199 | 六道门槛 + 双跑一致性 + CommandError 非零退出，算法零内联 | ✓ VERIFIED+WIRED |
| `server/tests/fixtures/blueprint_golden/gaokao_boost.json` | 634 | 过 validate_blueprint；含 onion-learning/study-course/onion-practice + study-plan indirect；目录独立仅 1 个 json | ✓ VERIFIED |
| `server/tests/helpers/blueprint_samples.py` | 356 | make_blueprint 工厂，被 111-04/schema/execution 测试复用 | ✓ VERIFIED+WIRED |

## Key Links 检查表

| From | To | Via | 状态 | 证据 |
|------|----|-----|------|------|
| builtin_types.py | blueprint_schema | schema_version 判别分支（函数内懒 import） | ✓ WIRED | builtin_types.py:22-25 |
| blueprint_execution.py | technical_plan.py | 复用 validate_technical_plan 不自写第二份 schema | ✓ WIRED | execution.py:23；dict_to_technical_plan 零命中 |
| lifecycle_service | Artifact.blueprint_status | CAS filter().update() 唯一字段级 writer | ✓ WIRED | :226 + INV-6 字段级守护测试 |
| lifecycle_service | BlueprintThread | confirm 守卫 open+blocking aexists | ✓ WIRED | :176 |
| lifecycle_service | event_taxonomy | EVENT_BLUEPRINT_STATUS_TRANSITIONED | ✓ WIRED | :57/:266 |
| charter_service | call_source | use_call_source(BLUEPRINT_CHARTER_DRAFT) 包 ainvoke | ✓ WIRED | charter_service.py:303 |
| charter_views | charter_service | 视图零 ORM 写全委托 service | ✓ WIRED | :62/:65/:92/:99；RepoCharter.objects.(create\|update) 零命中 |
| urls.py | charter_views | 三条 <uuid:repository_id>/charter/ path | ✓ WIRED | urls.py:328-340 |
| evaluate_blueprint_golden | blueprint_schema/execution/quality | validate→derive→指标，command 零算法 | ✓ WIRED | 实跑通过 |
| test_blueprint_integration | ArtifactService+LifecycleService+execution | golden fixture 驱动端到端 | ✓ WIRED | 5 例集成测试绿 |

## Requirements Coverage（8/8 SATISFIED）

| Requirement | 判定 | 证据 |
|-------------|------|------|
| SCHEMA-01 六段 schema 强制入库 | ✓ SATISFIED | SC1 证据链；缺段无法过 ArtifactService 强制门 |
| SCHEMA-06 execution_plan 确定性派生兼容现行 schema | ✓ SATISFIED | 派生输出过既有 validate_technical_plan；确定性双跑；派生为机械聚合，天然无周排期 |
| SCHEMA-07 项目级多版本 + block 级 diff | ✓ SATISFIED | 版本链（v2 supersedes v1）+ diff 三分类；「一项目一份活跃蓝图」唯一性守卫按 plan P10 归 112 创建入口（deferred，非 gap） |
| LIFE-01 11 态生命周期有守卫可追溯 | ✓ SATISFIED | SC2 证据链；structlog caller 事件绑定 initiated_by_user_id + duration_ms |
| LIFE-02 阻塞澄清挡确认 + 评审人名单 | ✓ SATISFIED | SC2/SC3 证据链（通知定向归后续消费相位） |
| LIFE-03 显式终态 + 失败可重试 | ✓ SATISFIED | failed/superseded 终态建模 + failed→researching 边 |
| CHARTER-01 版本化章程 AI 起草人工确认不被覆盖 | ✓ SATISFIED | SC4 证据链（P11 不变量双层专测） |
| GATE-02 golden set 与质量指标基线 | ✓ SATISFIED | SC5 证据链；打回率/修改量/轮次接口占位为 CONTEXT 锁定范围（deferred 数据填充） |

无孤儿需求：REQUIREMENTS.md 映射 Phase 111 的 8 条 ID 与四个 plan 声明的并集完全一致。

## Anti-Patterns

| 项 | 结果 | 严重度 |
|----|------|--------|
| 冻结面（repo_router_v2 / process_runtime 六冻结文件 / technical_plan.py / convergence_session*） | 全 phase commits（e1fedeaf..79faa593）diff 零触碰 | — CLEAN |
| event_taxonomy / call_source / builtin_types 改动面 | +28/−0 纯追加；−3 仅计数 docstring；−1 仅 docstring 行——均在 plan 授权内 | — CLEAN |
| TODO/FIXME/XXX | blueprint_quality.py 3 处 `TODO(Phase 112–114)`——plan 明确授权的占位接口，引用正式后续 phase | ℹ️ Info（deferred） |
| 孤儿代码 | blueprint_anchor / lifecycle_service 无生产调用方——相位边界即底座交付，消费方 112/114（集成测试已消费） | ℹ️ Info（deferred） |
| 11 态转移表完整性 | 与 DESIGN §4.2 逐边核对 25/25 一致，无缺边无私加边 | — CLEAN |
| 事件面污染 | blueprint 常量不进 ALL_EVENTS；test_event_taxonomy_alignment 守护绿 | — CLEAN |

## Gaps

无。

---

_Verified: 2026-07-29 · 938 tests passed / evaluate_blueprint_golden exit 0 / makemigrations --check clean / 冻结面零触碰_
_Verifier: gsd-verifier (goal-backward)_
