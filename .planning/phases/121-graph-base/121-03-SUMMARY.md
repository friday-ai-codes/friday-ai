---
phase: 121-graph-base
plan: 03
subsystem: infra
tags: [code_graph, exclusion, fail-closed, access-control, memoization, observability, ast-guard]

# Dependency graph
requires:
  - phase: 121-01
    provides: "tests/services/code_graph/ 测试包、indexed_repo / exclusion_rule_factory fixture、autouse 的 _reset_code_graph_state、LOGGING-SPEC §5 的 code_graph 组件登记"
  - phase: 121-02
    provides: "GraphAccessDenied / GraphNotIndexed 两个 fail-closed 异常类"
provides:
  - "ensure_repository_readable(user, repository_id)：仓库可读性的单一 async 校验点（UUID 解析 / 软删与不存在合并出口 / 索引态 / ACL 扩展点）"
  - "build_matcher_and_fingerprint(repository_id)：同步 matcher 构造 + 16 位有效规则集指纹，失败整仓 raise"
  - "invalidate_matcher_fingerprint_cache(repository_id=None)：本模块 60s TTL memo 的主动失效钩子"
  - "make_path_exclusion_memo(matcher)：按 file_path 记忆化的排除判定闭包，附 excluded_files 只读集合"
  - "_check_user_acl(user, repo)：per-user ACL 空实现扩展点"
  - "test_observability_contract：对 services/code_graph/*.py 的 AST 观测契约守护，随包增长自动生效"
affects: [121-04, 121-05, 121-06, 121-07, 121-08, 121-09, 121-10, 122, 123, 124, 125, 126, 127]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "同步侧自建加锁 TTL memo，TTL 常量与被复用模块严格对齐并用测试锁死"
    - "fail-closed 优先于缓存：构造失败不写 memo、不返回旧对象，用「连抛两次 + spy call_count」回归"
    - "观测规范用 AST 契约测试守护，glob 遍历包目录，后续 plan 新增模块自动受管"

key-files:
  created:
    - server/services/code_graph/access.py
  modified:
    - server/tests/services/code_graph/test_access.py
    - server/tests/services/code_graph/conftest.py

key-decisions:
  - "观测契约测试对「事件名不得拼变量」按「能否静态解析成字面量」判定，而非要求 emit 点写裸字符串——Task 1 要求用 Final[str] 常量（本仓既有形态），两条要求只有这样才同时成立"
  - "excluded_files 用实现 collections.abc.Set 的活动只读视图，而不是暴露裸 set 或返回快照 frozenset：loader 需要边装配边读计数，快照会读到 0"
  - "make_path_exclusion_memo 不再包一层 try/except：ExclusionMatcher.is_excluded 自身已对运行期异常 fail-closed 返回 True，再包一层只会多出一个看起来像降级分支的 except"
  - "把 Wave 0 的 test_matcher_fingerprint_memo_ttl 桩转成「TTL 与 exclusion.py 对齐」的真实断言，而不是删掉——VALIDATION 的 -k memo 选择器要留住，且这条对齐本身就是威胁模型里 accept 的前提"

requirements-completed: []

# Metrics
duration: 16min
completed: 2026-08-09
---

# Phase 121 Plan 03: 读取层 fail-closed 收口 Summary

**`services/code_graph/access.py` 落地：仓库可读性单一校验点（四道判定全 raise，零「返回空结果」出口）+ exclusion 同步收口（精确规则指纹 / 加锁 60s TTL memo / 不刷屏的热路径记忆化），外加一条随包增长自动生效的 AST 观测契约守护**

## Performance

- **Duration:** 约 16 分钟
- **Started:** 2026-08-09T05:37:00Z
- **Completed:** 2026-08-09T05:53:11Z
- **Tasks:** 3
- **Files modified:** 3（1 新建 + 2 修改）

## Accomplishments

- **可读性校验收口成一个函数**：`ensure_repository_readable` 把 UUID 解析、软删/不存在、索引态、ACL 扩展点四道串成一条链，每道的出口都是显式异常。「不存在」与「已软删」刻意共用同一句文案与同一个异常类型，用例直接对两者的 `message` 做相等断言——这条断言会挡住后人「顺手把 404 和 403 分开」的改动，那等于把仓库存在性泄漏给调用方。
- **「绝不返回空图」有签名级证据**：`test_not_indexed_raises` 除了断 `GraphNotIndexed`，还断 `ensure_repository_readable` 的返回注解恒为 `None`——这个函数在物理上就没有能返回图对象的出口，不是靠调用方自律。
- **规则指纹覆盖三个来源**：指纹对**有效规则集**（`_resolve_effective_specs` 的产物）哈希，同时覆盖 per-repo `RepoExclusionRule`、`SystemSetting` 全局 JSON、`BUILTIN_GLOBAL_DEFAULTS` 的代码变更。两个被否决的替代方案（`count + MAX(updated_at)`、拿 `_matcher_cache` 的 TTL 当版本号）连同否决理由写进了 `_compute_rules_fingerprint` 的 docstring，防后人「优化」回去。
- **memo 是性能刚需，不是可选项**：同步路径拿不到 `build_matcher_for_repo` 的 `_matcher_cache`（那份只有 async 入口读），所以自建了一份加锁的对等 memo。`test_matcher_fingerprint_memo_resolves_once` 用 spy 断 `call_count == 1` 且两次拿到**同一个 matcher 对象**——后者比只断调用次数更强，能证明 glob/regex 确实没重编译。
- **fail-closed 优先于缓存有回归**：`test_fail_closed_on_matcher_build_error` 连调两次都抛，且 `_resolve_effective_specs` 的 spy `call_count == 2`——同时证明了「失败没写进 memo」与「第二次没返回上一轮旧 matcher」两件事。
- **热路径不刷屏**：`make_path_exclusion_memo` 对同一 `file_path` 判定 10 次只穿透 matcher 一次，`log_exclusion_blocked`（INFO 级）总共只打一次。用例把这两个计数都断死了，10 万级装配循环刷爆 stdout 的历史教训不会重演。
- **观测规范从人眼升级为 CI**：`test_observability_contract` 用 `ast` 遍历 `services/code_graph/*.py`（`glob`，不写死清单），逐条校验事件名可静态解析 / snake_case / `code_graph_` 前缀 / `component` / `category` / `error=` 已脱敏，违规信息带 `文件:行号:事件名`。Plan 121-04~121-09 新增的模块自动被这条契约管住。

## Task Commits

1. **Task 1: `ensure_repository_readable` 仓库可读性单一校验点** — `f7cabadb` (feat)
2. **Task 2: exclusion 同步收口——matcher 构造、规则指纹、TTL memo 与热路径记忆化** — `071ee892` (feat)
3. **Task 3: 观测契约守护测试** — `ba84f063` (test)

**Plan metadata:** 见本文件的收尾 docs 提交。

## Files Created/Modified

- `server/services/code_graph/access.py`（新建，349 行）— 三段式模块 docstring（含残余风险段）/ 2 个 `Final[str]` 事件名常量 / 加锁 memo 三件套 / 5 个公开或半公开函数 / `_LiveReadOnlySet`
- `server/tests/services/code_graph/test_access.py` — 5 个桩转真实断言 + 7 个新增用例，共 12 passed
- `server/tests/services/code_graph/conftest.py` — autouse `_reset_code_graph_state` 改为同时清两份 memo，新模块用 `try/except ImportError` 兜住

## Decisions Made

- **观测契约与「用常量声明事件名」的调和**（见下文 Deviations 的机械化澄清）：Task 3 的条款 ① 字面要求「第一个位置实参是字符串字面量」，Task 1 的 action 则明确要求事件名声明为 `Final[str]` 常量（照 `codegraph/lsp/volar_pool.py` 的既有形态）。两条字面冲突。取 ① 的**意图**——「事件名不得拼变量」——实现为「必须能静态解析成字面量」：接受 `ast.Constant` 字符串，也接受能在模块级解析到字符串字面量的 `ast.Name`；f-string、拼接、函数调用一律解析不出来，照样判违规。理由写进了 `_module_string_constants` 的 docstring。
- **`excluded_files` 用活动只读视图，不用裸 set 也不用快照**：loader 要边装配边累计 `GraphMeta.excluded_file_count`，返回 `frozenset` 快照会永远读到 0；直接暴露底层 `set` 又让调用方能往里塞。实现了一个 `collections.abc.Set` 子类包住活动集合，`len()` / `in` / 迭代都实时，`add` 直接 `AttributeError`（用例断言了这一点）。
- **记忆化闭包不再包一层 `try/except`**：`ExclusionMatcher.is_excluded` 自身对运行期任何异常已 fail-closed 返回 `True`（`exclusion.py` L230–236），再包一层既无收益，又会在 `grep 'except Exception'` 的人工核对里多出一个看起来像降级分支的东西。语义继承关系写进了闭包的 docstring。
- **Wave 0 的 `test_matcher_fingerprint_memo_ttl` 桩转成真实断言而非删除**：VALIDATION 的 `-k memo` 选择器要留住落点，且「本模块 TTL 与 `exclusion._MATCHER_CACHE_TTL_SECONDS` 严格对齐」这件事本身就是威胁模型里 `T-121-陈旧规则` 判定为 accept 的前提——把它锁进用例，后人单方面改一处会立刻红。plan 要求的 `test_matcher_fingerprint_memo_resolves_once` 另立一个用例。

## Deviations from Plan

**None — plan executed exactly as written.**

三个 task 的 action 与验收条款逐条落地，无 Rule 1–4 触发，无 scope creep。一处需要说明的**验收条款字面冲突的机械化澄清**：

**Task 3 条款 ①「事件名必须是字符串字面量」 vs Task 1 action「事件名声明为 `Final[str]` 常量」**

两条不可能同时按字面满足。取条款 ① 的语义意图（「不得拼变量」），实现为「必须能静态解析成模块级字符串字面量」。精确判据：

```
ast.Constant(str)                          → 通过
ast.Name → 模块级 NAME = "字面量" 能解析     → 通过（本模块的两个 Final[str] 常量走这条）
f-string / BinOp 拼接 / Call / 其他         → 违规
```

这个判据**严格强于**只允许裸字面量的版本在实践中的效果：它同时挡住了「常量名拼错指向一个不存在的名字」（解析不到 → 违规）。

## Issues Encountered

**反证已按验收条款手工执行两次，均如期失败：**

1. 临时删掉 `_EVENT_ACCESS_DENIED` 调用的 `category="sampling"` → `test_observability_contract` 失败，报 `access.py:108:code_graph_access_denied 缺少 category="sampling"`。
2. 临时把 `error=redact_secrets_in_text(str(exc))[:500]` 改回 `error=str(exc)[:500]` → 失败，报 `access.py:246:code_graph_exclusion_matcher_failed 的 error= 未过 redact_secrets_in_text`。

两次改动均已还原，`git diff` 干净。

**降级分支人工核对（Task 2 验收条款）：** `grep -n -A2 'except Exception' services/code_graph/access.py` 命中 3 处——两处是观测埋点的 best-effort 吞异常（`# noqa` 注释里显式标注「不是安全降级分支」），第三处 `except Exception as exc` 的块尾是 `raise GraphAccessDenied`。**没有**任何 `except` 之后直接 `pass`/`return matcher` 放行的路径。

**Lint / 类型检查：**

- `uv run ruff check services/code_graph/ tests/services/code_graph/` → All checks passed。
- `uv run mypy services/code_graph/` → 唯一 1 条错误落在 `workflows/schemas/technical_plan.py:268`（预存在，Plan 121-01 / 121-02 已两次登记），本 plan 的文件 0 错误。

**测试范围：** 按本 plan 的测试预算只跑了 `tests/services/code_graph`（26 passed / 22 skipped）与 plan `<verification>` 点名的三个 exclusion 回归文件（`test_exclusion_matcher.py` / `test_retrieval_exclusion.py` / `test_find_chunk_at.py`，47 passed，零回归，确认未改动 exclusion 既有语义）。全量 `pytest` 与 `tests/codegraph tests/code_relations` 的 18 分钟回归已排期为 Plan 121-10 的相位闸门；Wave 0 登记的 4 条预存在失败与本 plan 无关，未处理。

## User Setup Required

None — 纯 service 层模块，无外部服务、无配置项、无迁移。

## Next Phase Readiness

**已就绪：**

- **Plan 121-04（`signature.py`）**：`build_matcher_and_fingerprint` 返回的 16 位指纹可直接作为复合签名的 `excl:` 分量；指纹稳定性与敏感性都已有回归。
- **Plan 121-05（loader 装配）**：`make_path_exclusion_memo(matcher)` 拿去做节点准入判定即可，闭包的 `excluded_files` 直接喂 `GraphMeta.excluded_file_count`。装配循环内**不要**再自己调 `log_exclusion_blocked`——闭包已按「每个新的被排除 file_path 至多一次」打过点。
- **Plan 121-07/121-09（`GraphService`）**：`ensure_repository_readable` 必须在**每次** `get_graph` 都调（不因缓存命中而跳过）——这是威胁模型里 `T-121-ACL撤销滞后` 判定为 accept 的唯一前提；`GraphService.invalidate` 需要同时调 `invalidate_matcher_fingerprint_cache(repository_id)` 与 `exclusion.invalidate_matcher_cache(repository_id)`，只清一份会读到另一份的 60s 旧值。
- **Plan 121-04~121-09 全体**：新增模块里的每个 `logger.*` 调用都会被 `test_observability_contract` 自动扫到，`component="code_graph"` / `category="sampling"` / `code_graph_` 前缀 / `error=` 脱敏四条缺一即红。

**留给后续 plan 的显式待办：**

- **Plan 121-05**：节点丢弃（被排除符号连同邻接边一并消失）由该 plan 落地，`test_exclusion_hides_symbols_and_edges` 的桩还在原位等填充。威胁 `T-121-泄漏` 的 mitigation 本 plan 只交付了判定函数，过滤动作本身尚未发生。
- **Plan 121-07**：`GraphService._reset_for_tests()` 交付后回填进 `conftest.py::_reset_code_graph_state`（该 fixture 现在清两份 memo，届时是第三项）。

## Threat Flags

无——本 plan 未引入 `<threat_model>` 之外的新安全面（零新增网络入口、零新增鉴权路径、零文件访问、零 schema 变更）。

## Self-Check: PASSED

- `server/services/code_graph/access.py` FOUND（349 行 ≥ plan 要求的 110）
- `server/tests/services/code_graph/test_access.py` FOUND
- `server/tests/services/code_graph/conftest.py` FOUND
- 提交 `f7cabadb` / `071ee892` / `ba84f063` 均在 git 历史中可查
- `grep -c '_check_user_acl' access.py` → 4（≥ 2）
- 四个导出名 `ensure_repository_readable` / `build_matcher_and_fingerprint` / `invalidate_matcher_fingerprint_cache` / `make_path_exclusion_memo` 均在 `__all__` 内
- `cd server && uv run pytest tests/services/code_graph -q` → **26 passed, 22 skipped**
- 工作区内与本 plan 无关的预存在改动保持未提交、未修改

---
*Phase: 121-graph-base*
*Completed: 2026-08-09*
