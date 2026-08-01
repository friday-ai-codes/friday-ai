---
phase: 114-ai
plan: 02
requirements: [FLOW-07]
provides:
  - "`server/services/process_runtime/blueprint_review.py` —— 六类机械规则纯函数 + 总入口 + goal-backward LLM 一类 + finding 归一/去重。**顶层零 ORM / 零 Django import**（AST 实测顶层 import 只有 `__future__` / `json` / `re` / `time` / `typing` / `structlog` / `common.logging` / `delivery.services.blueprint_anchor` / `services.process_runtime.blueprint_schema`）"
  - "`__all__` 全清单（14 项）：`STAGE_STATE_KEY` / `SEVERITY_BLOCKER` / `SEVERITY_WARNING` / `SEVERITY_INFO` / `check_preconditions` / `check_schema` / `check_citations` / `check_roles` / `check_api_closure` / `check_prohibitions` / `check_charters` / `check_gate_lock` / `run_mechanical_rules` / `agoal_backward_review` / `normalize_review_findings` / `finding_dedupe_key`"
  - "逐字签名（`inspect.signature` 实测）：`check_preconditions(content: Any) -> list[dict]` / `check_schema(content: Any) -> list[dict]` / `check_citations(content: Any) -> list[dict]` / `check_roles(content: Any) -> list[dict]` / `check_api_closure(content: Any) -> list[dict]` / `check_prohibitions(content: Any) -> list[dict]` / `check_charters(content: Any, *, charters: dict[str, dict] | None = None) -> list[dict]` / `check_gate_lock(content: Any, *, locked_snapshot: Any = None) -> list[dict]` / `run_mechanical_rules(content: Any, *, charters: dict[str, dict] | None = None, locked_snapshot: Any = None) -> list[dict]` / `normalize_review_findings(raw: Any) -> list[dict]` / `finding_dedupe_key(finding: Any) -> str`"
  - "⭐ `async def agoal_backward_review(*, feature_points: list[dict[str, Any]], impl_items: list[dict[str, Any]], constraints: Any = None, test_strategy: Any = None, must_haves: Any = None, key_links: Any = None, session_id: str = '') -> list[dict] | None` —— **全 keyword-only**（实测断言）；`None` 语义 = 「goal-backward 一类不可得」，**绝不是「无问题」**"
  - "finding **恒定六键**：`{rule_id, severity, section_path, block_id, repository_id, detail}`，全部为 str；`detail` 截断至 `_MAX_DETAIL_CHARS=500`"
  - "`STAGE_STATE_KEY = \"ai_review\"`（实测 ≠ `blueprint_merge.STAGE_STATE_KEY == \"merge\"`，测试锁死）；`SEVERITY_BLOCKER=\"blocker\"` / `SEVERITY_WARNING=\"warning\"` / `SEVERITY_INFO=\"info\"`（与 `ThreadSeverity` 三值等值，测试锁死）"
  - "`normalize_review_findings(None)` 的 meta finding 逐字：`{'rule_id': 'goal_backward_unavailable', 'severity': 'warning', 'section_path': '', 'block_id': '', 'repository_id': '', 'detail': 'goal-backward 审查未能执行（LLM 不可得），本轮不据此打回，请人审关注'}`"
  - "`finding_dedupe_key(finding) -> f\"{rule_id}|{block_id or section_path}\"`（`block_id` 优先，因块被编辑后 section_path 会漂移；`finding_dedupe_key(None) == \"|\"`）"
  - "上界常量实测值：`_MAX_FINDINGS=50` / `_MAX_DETAIL_CHARS=500` / `_MAX_SNIPPET_CHARS=80` / `_MAX_CONSTRAINTS=20` / `_MAX_CONSTRAINT_TEXT_CHARS=300` / `_MAX_PROMPT_CHARS=6000` / `_MAX_DIGEST_ITEMS=200` / `_MAX_TITLE_CHARS=200` / `_MAX_NARRATIVE_CHARS=1000`"
  - "`_constraints_digest(raw) -> list[dict]` 投影键 = `{id, kind, text}`（`text[:300]`，条数 ≤20；`None` / 非 list / 元素非 dict → `[]`）；`_NO_CONSTRAINTS_NOTICE = \"（无约束清单，本项不可判）\"`"
  - "goal-backward digest 六节（fresh context，**不带任何起草/融合会话历史**）：功能点与验收标准 / 实现项 / 约束清单 / 测试策略 / 验收锚点 truths / 关键链接 key_links，每节独立截断至 `_MAX_PROMPT_CHARS`"
  - "观测事件四条（全 `category=\"sampling\"` / `component=\"process_runtime\"`）：`blueprint_review_goal_backward_started`（`session_id`/`feature_point_count`/`impl_item_count`/**`constraint_count`**/`has_must_haves`/`has_key_links`）、`blueprint_review_goal_backward_no_default_model`（warning + `duration_ms`）、`blueprint_review_goal_backward_failed`（warning，`reason=\"unparsable_response\"` 或 `error=redact_secrets_in_text(...)` + `duration_ms`）、`blueprint_review_goal_backward_completed`（`finding_count`/`blocker_count`/`warning_count`/`info_count`/`duration_ms`）。**finding 正文与蓝图正文一律不进日志**"
  - "`call_source = CallSource.BLUEPRINT_AI_REVIEW`（111 已注册，`agents/call_source.py` **零改动**）"
affects:
  - "114-03（ai_review stage adapter）：直接消费 `run_mechanical_rules(content, charters=…, locked_snapshot=…)` / `agoal_backward_review(..., constraints=…)` / `normalize_review_findings(raw)` / `finding_dedupe_key(finding)` / `STAGE_STATE_KEY`。落线程时 **`severity` 与 `blocking` 必须成对**（114-01 不变式：`blocker/True`、`warning/False`、`info/False` 是仅有三种合法组合）；第 N 轮复检留痕**只能**用 `append_note`"
  - "114-03：`agoal_backward_review` 返 `None` 时**必须**走 `normalize_review_findings(None)` 记 warning meta finding，**绝不当作「无问题」放行**；`locked_snapshot` 传 `session.stage_state[\"confirmation\"]`；`charters` 传 `blueprint_charter_match.aload_charters(...)` 的返回"
  - "114-05（人审呈现）：按下方 rule_id × severity 全表对齐呈现与筛选；WARNING/INFO 只作参考不打回"
key-files:
  created:
    - server/services/process_runtime/blueprint_review.py
    - server/tests/services/process_runtime/test_blueprint_review_rules.py
  modified: []
completed: 2026-07-31
---

# Phase 114 Plan 02: 审查判定内核（六类机械规则 + goal-backward LLM 一类）Summary

**一行结论**：新建 `blueprint_review.py`（868 行）与 `test_blueprint_review_rules.py`（52 例），六类机械规则在**无 LLM、无 DB、无网络**下产确定性分级 findings —— 三条既有假通过陷阱（`validate_blueprint` 的 v0 pass-through / `citation_coverage` 分母为 0 返 1.0 / `direction` 枚举误写）在实现与测试两侧同时堵死，空/半成品蓝图走 `precondition_missing` 短路而非产出 `[]` 假通过，goal-backward 一类用已注册的 `blueprint_ai_review` 且不可得时 fail-closed 成 `goal_backward_unavailable` warning meta finding；**本 plan 对既有代码零改动**（`git diff --name-only HEAD~3 HEAD` 只含两个新建文件），`tests/services/process_runtime/` **550 passed** + `tests/delivery/` **639 passed**（合计 1189，= 114-01 收官的 1137 + 本 plan 新增 52，零回归），`makemigrations --check` 退出码 **0**。

## Accomplishments

- **六类机械规则纯函数化，且每条的判定档位按可证伪度分档**：纯集合运算判 BLOCKER，自由文本/文本包含判 WARNING。全模块只有**一个**模糊匹配项（`capability_unreferenced`），它被测试显式锁死在 WARNING —— 强判 BLOCKER 会产生不可复现的假阳性。
- **三条假通过陷阱写死在实现里，并各有正反并列断言**：
  - `check_schema` **先自断言** `schema_version == BLUEPRINT_SCHEMA_VERSION` 再调 `validate_blueprint`。测试同时断言同一份缺字段 content 喂 `validate_blueprint` **返回 `(True, None)`** —— 把 `blueprint_schema.py:809-810` 的 pass-through 语义写进测试，防将来有人「简化」掉自断言。
  - `check_citations` 走**条目级**走查，`rg 'citation_coverage\('` 零命中（模块对该函数**零调用、零 import**）。测试并列断言空文档 `citation_coverage({}) == 1.0` 而 `check_citations({}) == []`，「空文档不假通过」由前置短路兜住而非靠比率。
  - `check_api_closure` 只认 `provided` / `consumed` 两个字面量；测试构造一条把 `direction` 写成 `"produced"` 的契约，断言它**不进 consumed 分支**（不产 `support_repo_missing`），再改回 `consumed` 立刻命中 —— 锁死「实现里误用第三个词就恒通过」的回归面。
- **前置完整性短路**：`repo_associations` / `implementation_overview.items` / `requirement_spec.feature_points` 三段任一为空 → 单条 `precondition_missing` BLOCKER 且**后七条一律不跑**。测试断言恰好一条且不含 `role_mismatch` / `api_ref_dangling`（证明短路真的生效，没跑出一片恒真噪声）。
- **⭐ B5 落地：规则⑤第三条「不得与 constraints 冲突」不再落空**，且降级分工逐字写进两处 docstring —— 机械层只覆盖引用悬空（`constraint_ref_dangling`，纯集合运算），语义层归 `agoal_backward_review`（`constraints` 形参 → `_constraints_digest` → prompt「约束核对」节 → 模型回报 `rule_id="constraint_conflict"`）。测试构造一条「实现项文本明显违背某条 `constraints[].text` 但引用合法」的样例，断言机械层**不产 BLOCKER**（防将来有人塞进模糊文本匹配），同用例断言 `constraints` 在签名里、且 `_constraints_digest` 真的把该 constraint 的 id 与正文投进 digest —— **不是形参摆设**。
- **两级降级都显式可见，绝不静默落空**：`constraints` 缺失 ⇒ digest 该节写死 `（无约束清单，本项不可判）` 且 `*_started` 事件带 `constraint_count=0`；LLM 不可得 ⇒ `normalize_review_findings(None)` 产一条 `goal_backward_unavailable` WARNING（测试断言**不是 `[]`、也不是 BLOCKER**）。
- **确认门锁定校验复用既有投影做基线**：`check_gate_lock` 函数内 lazy import `blueprint_repo_plan._normalize_locked_repos`（先 `rg -n "def _normalize_locked_repos"` 实测其定义在 `:1087`，与 PLAN 的实测标注一致），未自写第二套投影；`block_id` 用 112 写入侧的稳定命名 `blk_gate_resp_{rid}`（`blueprint_confirm_gate.py:299` 实测）。
- **确定性可回归**：集合运算前一律 `sorted()`，调用顺序固定；测试用一份注入四类缺陷的蓝图连调两次 `run_mechanical_rules`，断言结果**逐字相等（含顺序）**且非空。
- **观测合规**：唯一 LLM 调用点四条事件全带 `category="sampling"` / `component="process_runtime"` / `duration_ms`，只记计数与分级分布；异常文本走 `redact_secrets_in_text`；`rg 'objects\.(create|update|filter|bulk_)'` 与 `rg 'record_answer'` 均零命中（INV-6 + 留痕通道纪律）。

## Task Commits

| Task | Commit | 内容 |
| ---- | ------ | ---- |
| 1 | `31e150a4` | 模块骨架（四段 docstring 契约书 + 常量 + finding 六键 + `_append` / `normalize_review_findings` / `finding_dedupe_key`）+ `check_preconditions` 短路 + 规则①②③ |
| 2 | `e8445308` | 规则④⑤⑥ + `check_gate_lock` + `run_mechanical_rules` 总入口 + `agoal_backward_review`（LLM 一类，fail-closed）+ 内部投影/解析 helper |
| 3 | `d5803117` | `test_blueprint_review_rules.py`：「守十二件事」52 例（零 DB、零 mock） |

## Files

- `server/services/process_runtime/blueprint_review.py`（新建，868 行）
- `server/tests/services/process_runtime/test_blueprint_review_rules.py`（新建，52 例 / 39 个 `def test_`）

## rule_id × severity 全表（114-03 落线程、114-05 呈现按此对齐）

### 机械规则节（`run_mechanical_rules` 产出）

| rule_id | severity | 产出函数 | 判据 |
| ------- | -------- | -------- | ---- |
| `precondition_missing` | **blocker** | `check_preconditions` | 三段必备内容任一为空（命中即短路） |
| `schema_version_missing` | **blocker** | `check_schema` | `schema_version` 缺失或 ≠ `blueprint/v1`（自断言，不靠 `validate_blueprint`） |
| `schema_invalid` | **blocker** | `check_schema` | `validate_blueprint` 返 `False`（`detail` 为其已脱敏截断的报错） |
| `citation_missing` | **blocker** | `check_citations` | 三类关键结论条目 `citations` 空 |
| `citation_missing_weak` | warning | `check_citations` | 事实性断言条目（`items[]` / `api_contracts[]`）`citations` 空 |
| `role_mismatch` | **blocker** | `check_roles` | direct 仓零实现项 **或** 实现项落在 indirect 仓（两种形态同一 rule_id，`detail` 区分） |
| `capability_unreferenced` | warning | `check_roles` | indirect 仓 `capabilities_used` 未被引用（**唯一模糊匹配项**） |
| `api_ref_dangling` | **blocker** | `check_api_closure` | `steps[].api_ref` ∉ `api_contracts[].id` |
| `support_repo_missing` | **blocker** | `check_api_closure` | `consumed` + `needs_support` 但 `support_repository_id` 缺失/不在 `repo_associations` |
| `forbidden_schedule` | **blocker** | `check_prohibitions` | block 文本命中 `\d+\s*个?\s*周` 或 `\bweeks?\b`（IGNORECASE） |
| `out_of_scope_introduced` | warning | `check_prohibitions` | `boundaries.out_of_scope` 词条出现在 block 文本（**排除 `deferred_ideas` 段**） |
| `constraint_ref_dangling` | **blocker** | `check_prohibitions` | `rationale.constraint_refs` ∉ `constraints[].id` |
| `charter_violation` | **blocker** | `check_charters` | direct 仓 `evolution ∈ {maintenance_only, deprecated}` 且 `decision_log` 无该仓支撑 |
| `charter_boundary_risk` | warning | `check_charters` | 该仓有明文 `boundaries[].rule` 且本轮无决策记录支撑（自由文本，需人审核对） |
| `gate_lock_violation` | **blocker** | `check_gate_lock` | 锁定仓消失 / `role` 偏离 / `responsibility` 文本偏离（三种形态同一 rule_id） |

### LLM 节（`agoal_backward_review` → `normalize_review_findings`）

| rule_id | severity | 来源 |
| ------- | -------- | ---- |
| `goal_backward_unavailable` | warning | **本模块产出**的 meta finding：`normalize_review_findings(None)`，即 LLM 不可得的 fail-closed 落点 |
| `acceptance_uncovered` | 模型给（非法值回落 warning） | prompt 要求：功能点验收标准无实现项/测试策略覆盖 |
| `truth_unsupported` | 同上 | prompt 要求：`must_haves.truths` 无实现项支撑 |
| `key_link_broken` | 同上 | prompt 要求：`key_links` 两端有一端不存在 |
| `constraint_conflict` | 同上 | ⭐ **B5 语义层**：实现项/契约与某条 `constraints[].text` 实质冲突 |

## B5 降级范围登记（逐字写进 `check_prohibitions` 与 `agoal_backward_review` 的 docstring）

| 层 | 覆盖什么 | 判据性质 | 不可得时的可见方式 |
| -- | -------- | -------- | ------------------ |
| 机械层 | 「引用了不存在的 constraint id」→ `constraint_ref_dangling` **BLOCKER** | 纯集合运算，可复现、可单测 | 不存在降级（无 IO 依赖） |
| 语义层 | 「实现项/契约与某条 `constraints[].text` 实质冲突」→ `constraint_conflict` | LLM 判定（自由文本语义） | ① `constraints` 缺失 ⇒ digest 显式写 `（无约束清单，本项不可判）` + `*_started` 事件 `constraint_count=0`；② LLM 不可得 ⇒ `goal_backward_unavailable` warning meta finding |

**为什么不让机械层做语义判定**：自由文本的语义比对强判 BLOCKER 会产生不可复现的假阳性（A4），而 BLOCKER 直接决定「打回还是升人审」—— 误钉的代价是无端重跑整轮融合。

## Decisions

- **`_iter_conclusion_entries` 的弱判据类选 `items[].citations` / `api_contracts[].citations` 而非 PLAN 举例的 `items[].rationale`**：schema 实测 `implementation_overview.items[]` 有 `citations` 字段（`blueprint_schema.py:494-498`）而**没有** `rationale` 字段（`rationale` 只在 `repo_associations[]` 下）。按 PLAN 字面写会读到一个恒不存在的键 ⇒ `citation_missing_weak` 永不触发，等于白写一条规则。改用 schema 里真实存在的 `citations` 字段，判据语义（「事实性断言无据」）逐字保持。
- **`charter_boundary_risk` 的触发条件绑定「无 decision_log 支撑」**：PLAN 只写「违背 `boundaries[].rule` → WARNING」，但自由文本无法机械判「违背」。若对每条 rule 无条件出 WARNING，该判定恒真、毫无信息量；改为「该仓有明文边界且本轮无决策记录支撑」⇒ 与 `charter_violation` 同一条降噪判据，补上 `decision_log` 后两条一起消失（测试 `test_decision_log_support_clears_charter_violation` 断言 `check_charters(...) == []`，证明非恒真）。
- **`role` 非法/缺失回落 `direct`**：与 `blueprint_repo_plan._normalize_locked_repos` 同源（把「要改的仓」误判成「不用改」的代价远高于反过来）；`role` 的合法性本身由规则①的 jsonschema enum 承担，不在规则③重复判。
- **`_MAX_SNIPPET_CHARS = 80` 独立于 `_MAX_DETAIL_CHARS`**：`detail` 整体上界 500 是防正文外泄的兜底，而排期/词条命中只需指认「命中了什么」—— 片段 80 字符足够定位，且把「整块正文进线程 body」的外泄面压到最小（T-114-10）。

## Deviations from Plan

共 3 处：2 处为 PLAN 内部「action 措辞 vs 验收命令」自相矛盾的判读，1 处为环境问题（与代码无关）。无功能性偏离。

**1. [Rule 3 - PLAN 自相矛盾] `rg citation_coverage` / `rg draft_content` 的「零命中」验收与 action 要求的 docstring 文案冲突，按「代码零引用」判读**

- **Found during:** Task 1 acceptance / Task 2 acceptance
- **Issue:** PLAN `<action>` 明确要求模块 docstring 第 4 段 (b) 写出「`citation_coverage` 分母为 0 返回 1.0」、`check_citations` docstring 写「不看 `citation_coverage` 比率」、`check_charters` docstring 写「绝不读 `draft_content`」；而 `<acceptance_criteria>` 又要求 `rg -n "citation_coverage"` / `rg -n "draft_content"` **零命中**。两者不可能同时满足 —— 按字面执行验收就必须删掉 PLAN 亲自指定的纠偏文案。
- **Fix:** 按验收条目的**意图**（「本模块不依赖那两个东西做判定」）判读为**代码层零引用**，并逐条实测坐实：`rg -c 'citation_coverage\('` = **0**、`rg -c '^from services.process_runtime.blueprint_quality'` = **0**、`rg -n 'draft_content'` 的 2 处命中**全在 docstring 行**（`:546` / `:1216`，均以 ``` `` ``` 包裹的说明文字）。纠偏文案保留 —— 那正是防将来有人「优化」掉自断言的唯一书面依据。
- **Files modified:** 无（判读差异，非代码改动）
- **Commit:** —

**2. [Rule 3 - PLAN verify 命令缺 Django 初始化] Task 1/2 的 `uv run python -c "from services.process_runtime import blueprint_review"` 需补 `DJANGO_SETTINGS_MODULE` + `django.setup()`**

- **Found during:** Task 1 verify
- **Issue:** `services/process_runtime/__init__.py:8` 会 eager import `architect_merge_adapter` → `delivery.models`，故**任何**从该包导入的裸 `python -c` 都抛 `ImproperlyConfigured: Requested setting INSTALLED_APPS`。这是包级既有副作用，与本模块的顶层零 ORM 纪律无关（本模块自身顶层 import 已由 AST 断言证明干净）。
- **Fix:** 全部 verify / acceptance 命令改为 `DJANGO_SETTINGS_MODULE=friday.settings uv run python -c "import django; django.setup(); ..."`，断言内容逐字不变，全部通过。pytest 侧无此问题（pytest-django 已在 conftest 完成 setup）。
- **Files modified:** 无
- **Commit:** —

**3. [Rule 3 - 环境，非代码] worktree 内 `server/.venv` 不存在，且 `uv sync` 因 `mysqlclient` 缺 pkg-config 失败**

- **Found during:** Task 1 verify
- **Issue:** 本 worktree 无 `.venv`；`uv sync --frozen` 在 `mysqlclient==2.2.7` 的 `get_config_posix` 阶段报 `Can not find valid pkg-config name`（brew 的 `mysql-client` 是 keg-only，pkgconfig 目录不在默认搜索路径）。
- **Fix:** `export PKG_CONFIG_PATH=/opt/homebrew/opt/mysql-client/lib/pkgconfig` 后 `uv sync --frozen` 成功（`server/.venv` 已被 `.gitignore` 覆盖，`git status` 干净）。另：`tests/services/process_runtime/test_blueprint_merge_gate.py::test_merged_blueprint_is_golden_measurable` 在**沙箱内**因 `path.write_text` 被文件系统策略拒绝而 fail，沙箱外同一用例 **42 passed** —— 纯环境现象，与本 plan 无关（本 plan 未触碰 `blueprint_merge` 及其测试）。
- **Files modified:** 无
- **Commit:** —

## 测试与验证

- `tests/services/process_runtime/test_blueprint_review_rules.py`：**52 passed**（39 个 `def test_`，其中 3 条参数化用例展开为 3+3+3 例）。零 `django_db` 标记（`rg -c django_db` = 0），零 mock。
- **PLAN verification 全套**：
  - `uv run pytest tests/services/process_runtime/ -q` → **550 passed**（动工前 498 + 本 plan 52，111/112/113 的 reconcile / merge / stage 断言全绿）
  - `uv run pytest tests/delivery/ -q` → **639 passed**（与 114-01 收官值逐字一致 ⇒ 线程底座零回归）
  - 合计 **1189 passed** = 114-01 SUMMARY 记录的 1137 + 52，**零新增失败**
  - `uv run python manage.py makemigrations --check --dry-run` → `No changes detected`，退出码 **0**（零 migration）
  - `uv run ruff check` + `ruff format --check` 两文件均通过（新文件跑了 `ruff format`，非受限面）
- ⭐ **变异验证（证伪能力实测，非声明）**：
  1. 把 `check_schema` 的 `schema_version` 自断言拆掉（只留 `isinstance` 判断）→ `test_missing_schema_version_is_blocker_although_validate_blueprint_passes` **fail**（1 failed / 51 passed）⇒ 该用例真的在挡「靠 v0 pass-through 假通过」这条回归。
  2. 把 `run_mechanical_rules` 的短路改成「追加后继续跑」→ `test_empty_blueprint_short_circuits_into_single_precondition_blocker` 与 `test_empty_document_coverage_is_one_but_never_counts_as_pass` **两条同时 fail**（2 failed / 50 passed）⇒ 短路语义被测试真实约束。
  3. 两次变异均已还原，`git diff --stat -- server/services/process_runtime/blueprint_review.py` **输出为空**后才提交 Task 3；复跑 52 passed。
- **冻结面 / 受限面自检**：`git diff --name-only HEAD~3 HEAD` **只含两个新建文件**；对 `repo_router_v2 / decompose_segments / research_adapter / architect_merge_adapter / merged_plan / clarify_adapter / render / resume / builtin_processes / blueprint_resume / blueprint_quality / blueprint_schema / blueprint_merge / blueprint_confirm_gate / blueprint_spec_gate / blueprint_lifecycle_service / charter_service / call_source / event_taxonomy / task/ / web/` 的 grep **零命中**。
- **INV-6 / 留痕通道自检**：`rg -c 'objects\.(create|update|filter|bulk_)'` = **0**、`rg -c 'record_answer'` = **0**、AST 顶层 import 断言通过（无 `delivery.models` / `repositories.models` / `django` 前缀）。
- **枚举纠偏自检**：`rg -c '"produced"'` = **0**（实现）/ **3**（测试，防回归用例）；`rg -c '"consumed"|"provided"'` = 2（常量定义）。
- **兜底密度**：`rg -c 'noqa: BLE001'` = **10**（9 个公开判定函数各一 + `agoal_backward_review`）。

## Self-Check: PASSED

- 文件存在：`server/services/process_runtime/blueprint_review.py` ✓、`server/tests/services/process_runtime/test_blueprint_review_rules.py` ✓
- commit 存在：`31e150a4` / `e8445308` / `d5803117` 均在 `git log`
- artifacts `contains` 断言：`def run_mechanical_rules` ∈ 模块 ✓（`:690`）；`run_mechanical_rules` ∈ 测试文件 ✓（多处）
- key_links 断言：`iter_blocks` ∈ 模块 ✓（顶层 import + `check_prohibitions` 内调用）；`_normalize_locked_repos` ∈ 模块 ✓（`:620` lazy import）；`BLUEPRINT_AI_REVIEW` ∈ 模块 ✓（`:896`）
- must_haves truths 逐条：确定性（两次逐字相等）✓ / finding 六键与 `ThreadSeverity` 等值 ✓ / 六类各一条证伪样例 ✓ / 前置短路 ✓ / `schema_version` 不假通过 ✓ / 缺章程仓跳过 ✓ / 唯一模糊项判 WARNING ✓ / `deferred_ideas` 不误报 ✓ / 恒不抛 ✓ / LLM 一类 fresh context + fail-closed ✓ / B5 `constraints` 进签名与 digest ✓ / 降级范围写进 docstring ✓ / 有界追加 ✓ / `finding_dedupe_key` 存在 ✓

## Next Phase Readiness

- **114-03 可直接消费五个稳定契约**：`run_mechanical_rules(content, charters=…, locked_snapshot=…)`、`agoal_backward_review(..., constraints=…)`、`normalize_review_findings(raw)`、`finding_dedupe_key(finding)`、`STAGE_STATE_KEY`。全部为纯函数或 best-effort async，**无 ORM、无 migration、无新 CallSource 枚举值**。
- **落线程的硬约束（违反即 `ValueError`，见 114-01）**：`open_thread(kind=ThreadKind.AI_REVIEW_FINDING, severity=…, blocking=…)` 必须成对给值 —— 本模块的 `severity` 字面量与 `ThreadSeverity` 已由测试锁死等值，直接透传即可；`blocking` 取 `severity == SEVERITY_BLOCKER`。
- **幂等落库路径**：先 `finding_dedupe_key(finding)` 查既有 `kind=ai_review_finding` 且 `status ∈ {open, answered}` 的线程 → 命中走 `append_note("第 N 轮仍存在…")`，未命中才 `open_thread`。**绝不用 `record_answer` 留痕**（会污染线程状态、让 `ahas_open_blocking_threads` 失真）。
- **`stage_state` 桶**：114-03 写 `{STAGE_STATE_KEY: {...}}` 即 `{"ai_review": {...}}`，**绝不复用 `"merge"` 桶**（测试 `test_stage_state_key_never_reuses_merge_bucket` 已就位，写错会 fail）。
- **给后续 writer 的纪律**：新增机械规则请在本模块内加 `check_*` 纯函数并挂进 `run_mechanical_rules` 的**固定顺序尾部**（顺序即确定性契约，插在中间会让「第 N 轮仍存在」的比对失真）；集合运算前必须 `sorted()`；新增 finding 必须走 `_finding` + `_append`（六键形状与上界由它们统一保证）；**语义类判定一律下沉 `agoal_backward_review`，不要在机械层引入文本相似度**。
