---
phase: 111-schema
plan: 04
requirements: [GATE-02]
provides:
  - "blueprint_quality：citation_coverage / target_repo_hit_rate 纯函数 + ai_rejection_rate / human_edit_volume / clarification_rounds DB 统计占位（112–116 每相位回归复用）"
  - "evaluate_blueprint_golden management command：golden set 离线评估入口（validate→derive→确定性双跑→覆盖率/命中率/必备功能点门槛，任一 FAIL 非零退出）"
  - "tests/fixtures/blueprint_golden/gaokao_boost.json：高三提分专项首条 golden case（DESIGN §5.7 实证语料，独立目录不混 0.19 路由 golden）"
  - "test_blueprint_integration.py：schema→落库→11 态→派生全链路冒烟（wave-1 三 plan 接缝的回归锚）"
affects:
  - "Phase 112–116 每相位产出退化（schema 拒绝/派生漂移/覆盖率跌破/命中率跌破）可由 `manage.py evaluate_blueprint_golden` 非零退出检出"
  - "112–114 实装打回率/人审修改量/澄清轮次时填 blueprint_quality 占位函数体（签名与口径已锁）"
key-files:
  created:
    - server/services/process_runtime/blueprint_quality.py
    - server/tests/services/test_blueprint_quality.py
    - server/tests/fixtures/blueprint_golden/gaokao_boost.json
    - server/delivery/management/__init__.py
    - server/delivery/management/commands/__init__.py
    - server/delivery/management/commands/evaluate_blueprint_golden.py
    - server/tests/delivery/test_evaluate_blueprint_golden.py
    - server/tests/delivery/test_blueprint_integration.py
  modified: []
completed: 2026-07-29
---

# Phase 111 Plan 04: 蓝图质量基线 + golden 评估 command + 全链路冒烟 Summary

**一行结论**：GATE-02 质量标尺全部就位——引用覆盖率/目标仓命中率纯函数（+三个 DB 统计接口占位）、高三提分专项首条 golden case（§5.7 实证语料：onion-learning 培优课占位入口 brownfield / study-course 专项学习页 greenfield / onion-practice 专项练习三 direct 仓 + study-plan 章程边界 indirect）、evaluate_blueprint_golden 离线评估 command（确定性双跑内建门槛、未过门槛 CommandError 非零退出），并以 golden fixture 驱动 schema→落库→11 态状态机→execution_plan 派生的全链路集成冒烟，三个 wave-1 底座接缝无断裂。

## Accomplishments

- **指标纯函数（GATE-02 可用标尺）**：`citation_coverage` 三类关键结论条目（findings / rationale 级 repo_associations / affected_features）非空 citations 占比，分母为 0 按约定回 1.0；`target_repo_hit_rate` direct 仓名集合对期望集合命中率，expected 空回 1.0；半可信输入逐字段 `.get` 防御绝不抛。占位接口 `ai_rejection_rate`/`human_edit_volume`/`clarification_rounds` 签名 + 口径 docstring 锁定，返回 None，顶层零 ORM import（rg 验收零命中）。
- **首条 golden case（Q3 口径）**：`gaokao_boost.json` 完整 blueprint/v1（3 feature_points、4 repo_associations、4 仓 findings、3 implementation items 覆盖 modify/create、api_contracts provided+consumed、interaction_flows 3 步、citations 池 6 条 repo_file/knowledge_entity/repo_charter 混合）；onion-learning finding 引用「培优课（即将上线）占位入口 learn-textbook-sync」实证、study-plan rationale 注明「权益鉴权归 study-course 场景鉴权模块」的不选 direct 理由；expected 断言机制级阈值（min_citation_coverage 0.9 / min_repo_hit_rate 1.0 / required fp_01+fp_02），非逐仓全等。
- **离线评估 command（T-111-11 防静默放水）**：镜像 measure_extractor_precision 分层（add_arguments / 逐 case 行 + 汇总 JSON report / 非零退出）；六道门槛（validate→derive→确定性双跑逐字节→覆盖率→命中率→必备功能点）；坏 JSON 容错为单 case 失败不 crash 全局，目录缺失/为空是硬 CommandError（golden 基线缺失不做 advisory 跳过）；指标算法零内联；无 LLM/网络/DB 写，天然过 `--disable-socket`；structlog `blueprint_golden_evaluated`（category=caller、component=process_runtime、initiated_by_user_id=system、duration_ms）。
- **全链路集成冒烟（wave-1 接缝验收）**：golden fixture 单一事实源驱动五段——①落库 + 缺 must_haves 被 `ArtifactContentInvalid` 拒；②主干 `""→researching→drafting→ai_reviewing→pending_review`，open+blocking repo_confirmation 线程阻塞 confirm，resolved 后放行且 acting_user 入 BlueprintReviewer（DB 重读 first_action=final_approve）；③confirmed 后派生 execution_plan 仓集合 == expected.direct_repos 三仓且双跑一致；④add_version 改一个 finding text → diff modified 恰命中该 block_id；⑤真实 ConvergenceSession 落 `blueprint.status.transitioned` 事件行（既有事件类型零改动共存证明）。

## Task Commits

| Task | Commit | 内容 |
| ---- | ------ | ---- |
| 1 | `d553b14f` | blueprint_quality 两指标纯函数 + 三 DB 统计占位 + 单测 11 例 |
| 2 | `18bad349` | gaokao_boost golden fixture + evaluate_blueprint_golden command + delivery management 包 + command 测试 8 例 |
| 3 | `fa3d6853` | 全链路集成冒烟 5 例 + 相位门（三目录全量/migration/冻结面）验收 |

## Files

- `server/services/process_runtime/blueprint_quality.py`（新建：纯函数节 + DB 统计占位节，stdlib only，顶层零 ORM/Django import）
- `server/delivery/management/commands/evaluate_blueprint_golden.py`（新建：delivery 首个 management command；`--fixtures-dir` 默认 server/tests/fixtures/blueprint_golden、`--output-json` 可选）+ management 两枚 `__init__.py`
- `server/tests/fixtures/blueprint_golden/gaokao_boost.json`（新建：独立目录，只此一个 json，不混 hybrid_graph_capable_golden / layered_search_golden 等 0.19 golden）
- 测试三件：`test_blueprint_quality.py`（11）/ `test_evaluate_blueprint_golden.py`（8）/ `test_blueprint_integration.py`（5）

## Decisions

- citation_coverage 的 repo_associations 条目按 rationale 级计数（citations 取 `rationale.citations`），indirect 仓同样计入分母——golden 口径是「已写下的选仓理由必须有据」，与 role 无关。
- command 的 stdout 输出（逐 case 行 + report JSON）设计为完全确定性（sorted 文件序、round(4) 指标、不含时间戳/耗时），使「连续两次运行输出逐字节一致」可直接作为测试断言；duration_ms 只进 structlog 事件。
- expected 门槛字段做 isinstance 防御：缺失门槛跳过该项判定而非 crash（fixture 半可信，T-111-10 同源）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - 计划假设修正] `make_blueprint()` 并非全引用样例，coverage==1.0 断言改在补齐后样例上做**
- **Found during:** Task 1（写 coverage 测试时核对工厂形状）
- **Issue:** plan 预期「`make_blueprint()` 全引用样例 → coverage == 1.0」，但 111-01 工厂的 indirect 仓（repo-shared）`rationale` 无 `citations` 键，按锁定口径实际 coverage = 5/6。
- **Fix:** 测试内 `_fully_cited_blueprint()` 补齐该处 citations 后断言 1.0；另保留一条「工厂原样 == 5/6」断言，把口径对 indirect rationale 同样生效这一事实固化为回归。
- **Files modified:** server/tests/services/test_blueprint_quality.py
- **Commit:** d553b14f

**2. [Rule 3 - 验收命令修正] fixture 合法性一行验收命令需 django.setup() 前缀**
- **Found during:** Task 2（执行 acceptance criteria）
- **Issue:** plan 给的 `uv run python -c "…from services.process_runtime.blueprint_schema import…"` 原样跑不通——`services/process_runtime/__init__.py` 级联 import `architect_merge_adapter → delivery.models`，无 DJANGO_SETTINGS_MODULE 即 ImproperlyConfigured。
- **Fix:** 等价验证改为前缀 `django.setup()` 后执行同断言，通过（validate True / derive ok / coverage 1.0 / hit_rate 1.0 / 双跑一致）。
- **Files modified:** 无（验证方式调整，未改代码）
- **Commit:** —

## Known Stubs

| Stub | File | 状态 |
|------|------|------|
| `ai_rejection_rate` 返回 None | server/services/process_runtime/blueprint_quality.py | **计划内占位**（CONTEXT 锁定「本相位留函数接口，数据由后续相位填充」）；Phase 114 审查循环落地后实装 |
| `human_edit_volume` 返回 None | 同上 | 计划内占位；Phase 114 人工编辑链路实装 |
| `clarification_rounds` 返回 None | 同上 | 计划内占位；Phase 112–114 澄清线程写入后实装 |

三者不阻碍本 plan 目标（GATE-02 两个可用指标 + 接口占位即为交付物），command 不消费它们。

## 测试与验证

- `tests/services/test_blueprint_quality.py`：11 passed
- `tests/delivery/test_evaluate_blueprint_golden.py`：8 passed
- `tests/delivery/test_blueprint_integration.py`：5 passed
- `uv run python manage.py evaluate_blueprint_golden`：exit 0，stdout 含 `gaokao_boost … → PASS` + report JSON
- **相位门**：`tests/delivery/ tests/repositories/ tests/services/` 全量 **1745 passed, 1 skipped**；`makemigrations --check --dry-run` No changes detected（本 plan migration 零新增）；冻结面终检 `git diff --name-only $(merge-base)..HEAD -- server/ | rg "repo_router_v2|六冻结文件|convergence_session_event"` 零命中（rg exit 1）
- fixture 验收：validate_blueprint (True, None)；rg -c onion-learning=22、study-course=24；golden 目录 `grep -vc json` = 0
- 观测面自检：command 记 caller 事件（component/initiated_by_user_id=system/duration_ms 齐）；纯函数模块按「高频循环禁 INFO」不加日志；无凭证/上游响应触点无需脱敏
- 环境备注：Task 2 期间两次 plain `python -c` 出现 `workflows.schemas` 瞬态 ModuleNotFoundError 后自愈（疑 uv 环境同步/pycache 竞态），pytest/manage.py 全程不受影响

## Next Phase Readiness

- 112–116 每相位收口可直接跑 `cd server && uv run python manage.py evaluate_blueprint_golden` 做退化回归；新增 golden case 只需往 `tests/fixtures/blueprint_golden/` 落 `{name, description, blueprint, expected}` 形状的 json。
- 112（blueprint_route）产出的装配蓝图可复用 `target_repo_hit_rate` 做路由命中评估；`citation_coverage` 供 113 merge 装配与 114 审查规则（引用覆盖 BLOCKER/WARNING）同口径复用。
- 114 实装打回率/人审修改量、112–114 实装澄清轮次时，直接填 `blueprint_quality` 三个占位函数体（懒 import delivery models），签名不改则 command/调用方零变更。
- Phase 111 五条 Success Criteria 的机器全部就位（schema 拒绝 / 状态机守卫 / 章程 / 派生确定性 / golden 基线），集成冒烟串通——可交 verifier。

## Self-Check: PASSED

- 8 created 文件全部存在于工作区 ✓
- commits `d553b14f` / `18bad349` / `fa3d6853` 均在 git log ✓
- 24 例新增测试全绿 + 相位门 1745 passed ✓；makemigrations 干净 ✓；冻结面零命中 ✓
