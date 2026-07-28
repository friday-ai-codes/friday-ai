---
phase: quick-260728-ppb-start-feature-solution
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - server/prompts/migrations/0011_resync_coding_guidance_feature_solution.py
  - server/prompts/builtin_contract.py
  - server/prompts/management/__init__.py
  - server/prompts/management/commands/__init__.py
  - server/prompts/management/commands/check_builtin_prompt_drift.py
  - server/tests/test_prompts_migration_contract.py
  - server/tests/test_resync_coding_guidance_feature_solution.py
  - server/tests/test_check_builtin_prompt_drift.py
  - server/chat/config.py
  - server/tests/test_project_context_line.py
autonomous: true
requirements: [QUICK-PPB]
must_haves:
  truths:
    - "部署后执行 `python manage.py migrate prompts` 时，0011 把已部署实例上漂移的 `chat.coding_guidance` / `chat.strategy.default` active body 幂等 resync 到当前 Python 字面量；resync 后 active body 含 `start_feature_solution`"
    - "`python manage.py check_builtin_prompt_drift` 在容器内可跑：零漂移 exit 0；有漂移打印 slug 清单并以非零退出；`--fix` 走与 resync migration 相同的 append+切 active"
    - "slug→常量映射只有 `prompts.builtin_contract.BUILTIN_CONTRACT_SLUGS` 一处来源；契约测试与 drift command 都从该模块导入，禁止再维护第二份清单"
    - "项目级对话 `_build_project_context_line` 明确：成批功能点 / 明确要技术方案 → `start_feature_solution`；只读项目工具只取上下文不能替代方案产出；与 `_CODING_GUIDANCE` 三路分流一致（零散→`create_coding_plan`，跨仓自然语言→`start_plan_research`，成批/技术方案→`start_feature_solution`）"
    - "未改 `chat_runner.py` 工具白名单；未做 task_category 兜底路由 / 澄清护栏（第二批）"
  artifacts:
    - path: "server/prompts/migrations/0011_resync_coding_guidance_feature_solution.py"
      provides: "双 slug 幂等 resync data migration（coding_guidance + strategy.default）"
      contains: "start_feature_solution"
    - path: "server/prompts/builtin_contract.py"
      provides: "BUILTIN_CONTRACT_SLUGS + resolve/detect/resync 共享逻辑"
      exports: ["BUILTIN_CONTRACT_SLUGS", "resolve_builtin_constant", "detect_builtin_prompt_drift", "resync_builtin_prompt_drift"]
    - path: "server/prompts/management/commands/check_builtin_prompt_drift.py"
      provides: "生产可跑的漂移检测 / 可选 --fix"
    - path: "server/chat/config.py"
      provides: "_build_project_context_line 含 start_feature_solution 引导"
      contains: "start_feature_solution"
  key_links:
    - from: "prompts/migrations/0011_*.py"
      to: "chat.conversation_service._CODING_GUIDANCE / _STRATEGY_DEFAULT"
      via: "动态 import 字面量 → PromptVersion.append + active_version 切换"
      pattern: "from chat.conversation_service import _CODING_GUIDANCE"
    - from: "check_builtin_prompt_drift"
      to: "prompts.builtin_contract.BUILTIN_CONTRACT_SLUGS"
      via: "detect / optional --fix resync"
      pattern: "BUILTIN_CONTRACT_SLUGS"
    - from: "test_prompts_migration_contract.py"
      to: "prompts.builtin_contract.BUILTIN_CONTRACT_SLUGS"
      via: "import 共享清单，不再本地定义 CONTRACT_SLUGS 副本"
      pattern: "from prompts.builtin_contract import"
    - from: "chat.config._build_project_context_line"
      to: "_build_system_prompt project_line 装配位（coding_guidance 之前）"
      via: "无 slug，改动即对所有实例生效"
      pattern: "_build_project_context_line"
---

<objective>
修复「生成技术方案」不走 `start_feature_solution` 的根因：已部署实例 Prompt Center builtin body 漂移（DB active 停在旧 seed，代码字面量新增的 feature-solution 指令从未注入）；同时补项目级对话的方案工具引导，并落地生产可检测的 builtin drift 防护。

Purpose: `render_prompt` 命中 DB 时 fallback 不生效；生产 `chat.coding_guidance` v1（880 字符）不含 `start_feature_solution`，而本地字面量 1274 字符含该指令。必须用 resync migration 修复已部署 DB，并用可运维命令防止同类静默失效再次发生。

Output: prompts `0011` data migration + `builtin_contract` 单一来源 + `check_builtin_prompt_drift` management command + `_build_project_context_line` 方案工具引导 + 对应测试。

**明确不做：**
- 不改 `server/agents/chat_runner.py` 工具白名单（工具当时已挂载，已排除）。
- 不做 task_category 枚举化 / 兜底路由 / 澄清护栏（第二批）。
- 不碰生产数据库；migration 只由部署流程的 `migrate` 执行。
- 默认不 resync 未漂移的 chat slug / `ai_node.*` / `aux.*` / `repo.summary_generator`（仅处理已确认漂移的两个 chat slug）。
</objective>

<execution_context>
@/Users/zaneliu/Projects/open-source/friday-clean/.cursor/gsd-core/workflows/execute-plan.md
@/Users/zaneliu/Projects/open-source/friday-clean/.cursor/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.cursor/rules/observability-logging.mdc
@server/chat/conversation_service.py
@server/chat/config.py
@server/prompts/services.py
@server/prompts/migrations/0009_resync_plan_generation_clarification.py
@server/prompts/migrations/0008_resync_chat_strategy_route_first.py
@server/prompts/migrations/0006_intent_priority_resync.py
@server/prompts/migrations/0010_rename_project_to_space.py
@server/tests/test_prompts_migration_contract.py
@server/tests/test_chat_strategy_route_first_migration.py
@server/projects/management/commands/check_v81_legacy_residue.py
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task A: resync 两个漂移的 builtin prompt（0011 migration）</name>
  <files>server/prompts/migrations/0011_resync_coding_guidance_feature_solution.py, server/tests/test_resync_coding_guidance_feature_solution.py</files>
  <behavior>
    - 对 `chat.coding_guidance`：active body 设为旧文案（不含 `start_feature_solution`）时，调用 `forwards` 后 active body == `_CODING_GUIDANCE` 且含 `start_feature_solution`
    - 对 `chat.strategy.default`：active body 设为旧文案时，`forwards` 后 active body == `_STRATEGY_DEFAULT`
    - 幂等：active body 已等于当前字面量时再跑 `forwards`，不新增 PromptVersion（version 数不变）
    - Prompt 不存在时 `forwards` 静默 skip（不抛）
  </behavior>
  <action>
按 `0009_resync_plan_generation_clarification.py` / `0006_intent_priority_resync.py` 模式新增 `server/prompts/migrations/0011_resync_coding_guidance_feature_solution.py`（D-根因修复：漏配的 start_feature_solution 字面量改动配套 resync）。

硬性约束：
- `dependencies = [("prompts", "0010_rename_project_to_space")]`。0010 已把 FK `project` 重命名为 `space`；历史模型字段是 `space`。查询继续用 `Prompt.objects.get(slug=..., scope="system")`（与 0008/0009 一致），不要写已删除的 `project=`。
- 只处理两个已确认漂移 slug：`chat.coding_guidance`（动态 `from chat.conversation_service import _CODING_GUIDANCE`）与 `chat.strategy.default`（动态 import `_STRATEGY_DEFAULT`）。可抽 `_resync_one` 辅助（照抄 0006），避免复制两遍。
- 幂等：`active is not None and active.body == body` → return；否则 `version = max+1`，`PromptVersion.objects.create(..., change_note=...)`，再 `prompt.active_version = new_version` + `save(update_fields=["active_version", "updated_at"])`。
- `change_note` 中文说明 why：例如 coding_guidance 用「Resync coding_guidance: 注入 start_feature_solution 成批技术方案指引」；strategy.default 用与字面量差对应的简短 note（字节级对齐当前 `_STRATEGY_DEFAULT`）。
- `reverse` 为 no-op（docstring 中文说明：仅 append+切指针，回滚请手动选历史版本）。
- docstring 用中文解释 why（DB hit 路径使 fallback 失效；已部署实例停在旧 seed），不解释 what 机械步骤。
- 不要改 Python 字面量本身；migration 只把 DB 拉齐到现有字面量。
- 配套测试照 `test_chat_strategy_route_first_migration.py`：`importlib` 加载 0011 模块，fixture 把两个 slug 的 active body 写成 stale，断言 `forwards` 后等于常量且 coding_guidance 含 `start_feature_solution`；再测幂等不增 version。

生产生效方式（写进 SUMMARY，勿在本任务连生产库）：升级部署跑 `cd server && uv run python manage.py migrate prompts` 时 0011 自动执行；验证可在部署后查 active body 是否含 `start_feature_solution`，或跑 Task B 的 `check_builtin_prompt_drift`（应 exit 0）。
  </action>
  <verify>
    <automated>cd server && uv run pytest tests/test_resync_coding_guidance_feature_solution.py -q && uv run ruff check prompts/migrations/0011_resync_coding_guidance_feature_solution.py tests/test_resync_coding_guidance_feature_solution.py && uv run ruff format --check prompts/migrations/0011_resync_coding_guidance_feature_solution.py tests/test_resync_coding_guidance_feature_solution.py</automated>
  </verify>
  <done>0011 存在且依赖 0010；两 slug 幂等 resync；测试红→绿证明 stale→current（含 start_feature_solution）与幂等；ruff 通过。</done>
</task>

<task type="auto" tdd="true">
  <name>Task B: check_builtin_prompt_drift 命令 + 单一契约来源</name>
  <files>server/prompts/builtin_contract.py, server/prompts/management/__init__.py, server/prompts/management/commands/__init__.py, server/prompts/management/commands/check_builtin_prompt_drift.py, server/tests/test_prompts_migration_contract.py, server/tests/test_check_builtin_prompt_drift.py</files>
  <behavior>
    - `detect_builtin_prompt_drift()`：DB active body sha256 ≠ Python 常量 → 返回含该 slug 的漂移项；一致 → 空列表
    - `check_builtin_prompt_drift` 无漂移 stdout 说明并 SystemExit/CommandError 路径外 exit code 0；有漂移打印清单并以非零退出（`CommandError` 或 `sys.exit(1)`，与仓库既有 management command 风格一致）
    - `--fix`：对漂移 slug 执行 append PromptVersion + 切 active；修完后再 detect 应为空
    - `test_prompts_migration_contract.py` 从 `prompts.builtin_contract` 导入清单，本地不再定义第二份 `CONTRACT_SLUGS`
  </behavior>
  <action>
选定方案：**Django management command**（不用 `render_prompt` 热路径告警）。理由：零热路径风险、可在容器直接跑、非零退出码便于运维/CI、可选 `--fix` 与 migration 同逻辑；热路径告警即使采样仍增加 chat 主链路耦合，本任务优先运维可观测。

1. 新建 `server/prompts/builtin_contract.py` 作为单一来源：
   - 把现有 `CONTRACT_SLUGS` 原样迁入，命名为 `BUILTIN_CONTRACT_SLUGS`（元组形状不变：`(slug, module_path, attr_name, dict_key_or_None)`）。
   - 提供 `resolve_builtin_constant(module_path, attr_name, dict_key)`（从现有测试 `_resolve_constant` 抽出）。
   - 提供 `detect_builtin_prompt_drift()`：对每个 slug 查 `Prompt.objects.select_related("active_version").get(slug=..., scope=PromptScope.SYSTEM, space=None)`，比较 body 与常量字节级；返回结构化漂移列表（至少含 slug、py_sha256、db_sha256；可含 body 长度）。缺 Prompt / 无 active_version 也视为漂移项（带 reason），不要静默跳过。
   - 提供 `resync_builtin_prompt_drift(slugs: list[str] | None = None)`：对指定或全部漂移项执行与 migration 相同的 append+切 active（用 ORM 现模型，字段名 `space`）。返回修复的 slug 列表。中文 docstring 只写 why。

2. 新建 `server/prompts/management/commands/check_builtin_prompt_drift.py`（需 `__init__.py` 两层空文件，Django 才能发现命令）：
   - `python manage.py check_builtin_prompt_drift`：调用 detect；零漂移成功输出；有漂移打印 slug 清单并以非零退出。
   - `--fix`：先 detect，再 resync，再 detect 校验；仍有漂移则非零退出。
   - 遵守 observability-logging.mdc：`structlog.get_logger(__name__)`；事件名 snake_case（如 `builtin_prompt_drift_check_started` / `builtin_prompt_drift_check_completed` / `builtin_prompt_drift_detected` / `builtin_prompt_drift_fix_completed`）；kv 字段（slug、drift_count、duration_ms、fixed_count）；`category="sampling"`、`component="prompts"`；`user_id`/`initiated_by` 记 `system`；禁止把完整 prompt body 打进日志（只打 slug / hash / length）。观测 best-effort，`except: pass` 不得打断命令主流程的退出码语义（日志失败吞掉，业务退出码仍按漂移结果）。
   - help / 模块 docstring 中文说明 why（契约测试 fresh migrate 抓不住已部署漂移）。

3. 改 `server/tests/test_prompts_migration_contract.py`：删除本地 `CONTRACT_SLUGS` / `_resolve_constant`，改为 `from prompts.builtin_contract import BUILTIN_CONTRACT_SLUGS as CONTRACT_SLUGS, resolve_builtin_constant`（或直接用新名改测试引用），行为不变。

4. 新建 `server/tests/test_check_builtin_prompt_drift.py`：用 `call_command` + 故意 stale body 断言非零退出与输出含 slug；`--fix` 后 body 对齐且再跑 exit 0。

不要在 `render_prompt` 加告警。不要复制第二份 slug 清单。
  </action>
  <verify>
    <automated>cd server && uv run pytest tests/test_prompts_migration_contract.py tests/test_check_builtin_prompt_drift.py -q && uv run python manage.py check_builtin_prompt_drift && uv run ruff check prompts/builtin_contract.py prompts/management/commands/check_builtin_prompt_drift.py tests/test_prompts_migration_contract.py tests/test_check_builtin_prompt_drift.py && uv run ruff format --check prompts/builtin_contract.py prompts/management/commands/check_builtin_prompt_drift.py tests/test_prompts_migration_contract.py tests/test_check_builtin_prompt_drift.py</automated>
  </verify>
  <done>共享契约模块存在；契约测试仍绿；command 可在 server/ 下直接跑；漂移非零退出、`--fix` 可修；日志字段合规且不落 body 明文；ruff 通过。</done>
</task>

<task type="auto" tdd="true">
  <name>Task C: 项目级对话补 start_feature_solution 引导</name>
  <files>server/chat/config.py, server/tests/test_project_context_line.py</files>
  <behavior>
    - `_build_project_context_line(project)` 返回字符串含 `start_feature_solution`
    - 返回字符串仍含既有只读工具名（`get_project_overview` / `list_project_features` 等）
    - 返回字符串表达「只读工具取上下文，不能替代方案产出」之意（可用关键子串断言，如「不能替代」或「只用于」）
    - 三路分流不冲突：文案点名成批/技术方案 → `start_feature_solution`，不把零散需求导向该工具替代 `create_coding_plan`
  </behavior>
  <action>
在 `server/chat/config.py` 的 `_build_project_context_line` 中追加简短中文引导（D-项目级方案工具引导）：

内容要求：
- 用户要「技术方案 / 整体方案 / 成批功能点方案」时调用 `start_feature_solution`（会跑新增-vs-改造分类并强制确认关联仓库，产出分仓+整体方案）。
- 明确：项目只读工具（现有 `get_project_overview` / `list_project_features` / …）只用于取上下文，不能替代方案产出。
- 与 `_CODING_GUIDANCE` 一致、勿冲突：单个零散需求 → `create_coding_plan`；跨仓自然语言需求 → `start_plan_research`；成批功能点 / 明确要技术方案 → `start_feature_solution`。
- 保持现有中文行文风格与信息密度，不要写成长篇；在现有「需要更多项目信息时…」段落后追加 1–2 行即可，不要重写整段身份说明。
- 该函数无 Prompt Center slug，改动即对所有实例生效；无需 migration。
- 已 grep：当前无测试断言 `_build_project_context_line` 全文。新建 `server/tests/test_project_context_line.py`，用简单 namespace/Mock project 对象测上述 behavior（勿依赖 DB）。
- 注释只解释 why（项目级对话装配在 coding_guidance 之前，缺方案工具点名会导致 LLM 只走只读工具）；中文。
- 禁止改 `chat_runner.py`。
  </action>
  <verify>
    <automated>cd server && uv run pytest tests/test_project_context_line.py -q && uv run ruff check chat/config.py tests/test_project_context_line.py && uv run ruff format --check chat/config.py tests/test_project_context_line.py</automated>
  </verify>
  <done>`_build_project_context_line` 含 `start_feature_solution` 与只读工具边界；测试覆盖关键子串；与 coding_guidance 三路分流一致；ruff 通过。</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| ops → manage.py | 运维在容器内执行 drift check / `--fix`；可改 system builtin active 指针 |
| deploy → migrate 0011 | 部署流程写 PromptVersion；影响后续 chat system prompt 内容 |
| chat → LLM | project_context_line / coding_guidance 注入模型上下文（非用户任意写库） |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-ppb-01 | Tampering | check_builtin_prompt_drift --fix | mitigate | 仅运维可进容器执行；`--fix` 只 append 新 version 不删历史，可手动回滚 active 指针 |
| T-ppb-02 | Information Disclosure | drift 日志 / stdout | mitigate | 日志只打 slug/hash/length，禁止完整 body；stdout 清单同样只列 slug 与 hash |
| T-ppb-03 | Denial of Service | render_prompt 热路径 | accept | 本方案刻意不在 render_prompt 加漂移检查，避免 chat 主链路额外 DB/CPU |
| T-ppb-04 | Elevation of Privilege | management command | accept | 与既有 manage.py 命令同权；无新网络暴露面 |
| T-ppb-SC | Tampering | 无新 pip/npm 包 | accept | 本计划无 package install |
</threat_model>

<verification>
全量本任务相关测试与命令：

```bash
cd server && uv run pytest \
  tests/test_resync_coding_guidance_feature_solution.py \
  tests/test_prompts_migration_contract.py \
  tests/test_check_builtin_prompt_drift.py \
  tests/test_project_context_line.py -q

cd server && uv run python manage.py check_builtin_prompt_drift
cd server && uv run ruff check \
  prompts/migrations/0011_resync_coding_guidance_feature_solution.py \
  prompts/builtin_contract.py \
  prompts/management/commands/check_builtin_prompt_drift.py \
  chat/config.py \
  tests/test_resync_coding_guidance_feature_solution.py \
  tests/test_prompts_migration_contract.py \
  tests/test_check_builtin_prompt_drift.py \
  tests/test_project_context_line.py
```

生产验证（部署流水线执行，本任务不直连生产库）：`migrate prompts` 后 `check_builtin_prompt_drift` exit 0；或 SQL/admin 确认 `chat.coding_guidance` active body 含 `start_feature_solution`。
</verification>

<success_criteria>
- 0011 migration 幂等 resync 两个漂移 slug；部署 migrate 后生产 DB 注入 `start_feature_solution` 指引
- `check_builtin_prompt_drift` 可在容器检测漂移并以非零退出；`--fix` 可修；契约清单单一来源
- 项目级对话 context line 引导技术方案工具，且不与 coding_guidance 三路分流冲突
- 未改工具白名单；未做第二批路由/护栏；ruff 通过；相关 pytest 绿
</success_criteria>

<output>
Create `.planning/quick/260728-ppb-start-feature-solution/260728-ppb-SUMMARY.md` when done
</output>
