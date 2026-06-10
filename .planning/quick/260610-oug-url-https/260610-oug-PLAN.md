---
phase: quick/260610-oug-url-https
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - web/src/components/repository/CreateRepositoryModal.vue
  - web/src/components/repository/EditRepositoryModal.vue
  - web/src/types/workflow/schemas.ts
  - web/src/types/workflow/node-definitions/categories/action.ts
  - web/src/types/workflow/node-definitions/categories/trigger.ts
  - web/src/types/workflow/node-definitions/categories/integration.ts
  - web/src/types/workflow/node-definitions/categories/control.ts
  - web/src/components/settings/VectorIndexSettings.vue
  - web/src/api/client.ts
  - web/src/api/prompts.ts
autonomous: true
requirements: [QUICK-260610-OUG]

must_haves:
  truths:
    - "仓库创建/编辑弹窗的 Git URL 帮助文案声明仅支持 HTTPS，并简要说明原因（认证基于 Access Token）"
    - "工作流节点配置校验失败时，用户看到的 zod 校验消息为中文（数字范围消息带界值）"
    - "Embedding 健康检查缺 URL 时提示中文「请输入 Embedding API URL」"
    - "API 请求失败兜底文案显示「请求失败」而非 'Request failed'"
  artifacts:
    - path: "web/src/components/repository/CreateRepositoryModal.vue"
      provides: "仅支持 HTTPS 的帮助文案"
      contains: "仅支持 HTTPS"
    - path: "web/src/types/workflow/schemas.ts"
      provides: "全部 min/max/uuid 校验带中文 message"
    - path: "web/src/api/client.ts"
      provides: "中文兜底错误文案「请求失败」"
  key_links:
    - from: "web/src/composables/useConfigModel.ts"
      to: "web/src/types/workflow/schemas.ts"
      via: "validate() 展示 zod issue.message 给用户"
      pattern: "safeParse|issues"
---

<objective>
修复仓库 URL 帮助文案与实际后端行为不一致的问题（后端仅接受 http(s) URL，但前端写着「支持 HTTPS 或 SSH 格式」），并将所有面向用户的英文校验/错误提示汉化（zod 校验消息、硬编码英文提示、API 兜底文案）。

Purpose: 消除误导性文案，统一中文用户体验（D：用户已决策「全部改」、不实现 SSH）。
Output: 10 个前端文件的文案/校验消息修改，前端测试通过。
</objective>

<execution_context>
@/Users/zaneliu/Projects/open-source/friday-ai/.cursor/gsd-core/workflows/execute-plan.md
@/Users/zaneliu/Projects/open-source/friday-ai/.cursor/gsd-core/templates/summary.md
</execution_context>

<context>
@web/src/types/workflow/schemas.ts
@web/src/types/workflow/node-definitions/categories/control.ts

**已确认事实（不要重复调查）：**
- zod 主版本为 v4（`web/pnpm-workspace.yaml` catalog 锁 `zod: ^4.3.5`）。zod v4 支持字符串简写作为错误消息：`z.number().min(1, '不能小于 1')`、`z.string().uuid('凭证 ID 格式无效')`、`z.enum([...], '请选择有效的选项')` 均合法。
- 项目已有中文 message 风格参考：`schemas.ts` 第 148 行 `z.string().min(1, 'JSONPath 路径不能为空')`。
- 测试中无英文 zod 消息断言（已 grep `web/src/**/*.{spec,test}.ts` 确认无 `Invalid uuid` / `must be` / `Request failed` 等断言）；`AIModelConfig.spec.ts` 断言的均为中文文案，不受影响。
- 校验消息经 `web/src/composables/useConfigModel.ts` 的 validate() 直接展示给用户。
</context>

<tasks>

<task type="auto">
  <name>Task 1: 修复仓库弹窗 Git URL 帮助文案为仅支持 HTTPS</name>
  <files>web/src/components/repository/CreateRepositoryModal.vue, web/src/components/repository/EditRepositoryModal.vue</files>
  <action>
    将两个弹窗中 Git URL 输入框下方的帮助文案「支持 HTTPS 或 SSH 格式」（CreateRepositoryModal.vue 第 228 行、EditRepositoryModal.vue 第 257 行）改为：「仅支持 HTTPS 格式（认证基于 Access Token，暂不支持 SSH）」。

    依据用户决策：系统有意只支持 HTTPS（后端 serializers/views 拒绝非 http(s) URL 且有测试锁定），不实现 SSH，仅改文案。专有名词 HTTPS、SSH、Access Token 保留英文。
  </action>
  <verify>
    <automated>grep -c '仅支持 HTTPS' web/src/components/repository/CreateRepositoryModal.vue web/src/components/repository/EditRepositoryModal.vue && ! grep -rn '支持 HTTPS 或 SSH' web/src/components/repository/</automated>
  </verify>
  <done>两个弹窗帮助文案均为「仅支持 HTTPS 格式」且说明原因，不再出现「HTTPS 或 SSH」。</done>
</task>

<task type="auto">
  <name>Task 2: 为工作流 zod schema 补全中文校验消息</name>
  <files>web/src/types/workflow/schemas.ts, web/src/types/workflow/node-definitions/categories/action.ts, web/src/types/workflow/node-definitions/categories/trigger.ts, web/src/types/workflow/node-definitions/categories/integration.ts, web/src/types/workflow/node-definitions/categories/control.ts</files>
  <action>
    为所有缺自定义消息的 zod 校验补中文 message（zod v4 字符串简写），遵循 `extractionRuleSchema` 既有风格：

    **schemas.ts：**
    - 4 处 `provider_credential_id: z.string().uuid()`（第 103、175、275、300 行）→ `z.string().uuid('凭证 ID 格式无效')`
    - 所有 `z.number().min()/max()` 带界值消息，例如：
      - `temperature: z.number().min(0, '不能小于 0').max(2, '不能大于 2')`
      - `max_tokens: z.number().min(100, '不能小于 100').max(100000, '不能大于 100000')`
      - 同样处理 max_thinking_tokens（1024–128000，两处）、max_budget_usd（0.01–100，两处）、top_k（1–50）、score_threshold（0–1）、max_iterations（10–200 与 1–100 两处）、timeout_seconds（60–7200）、polling_interval（5–60）
    - `z.enum()` 各处（output_format、work_item_type、filter_work_item_type、identifier_type、operator、logic、timeout_action 等）：zod v4 直接支持 `z.enum([...], '请选择有效的选项')`，加上即可；enum 由 select 控件驱动几乎不会触发，若个别处加消息引发类型问题则跳过该处并在 SUMMARY 中说明。

    **categories/*.ts：**
    - action.ts：timeout_seconds（1–300）
    - integration.ts：timeout（1–300）、message_type / method enum
    - control.ts：delay_seconds（1–86400）、wait_count（min 1）、timeout（min 0，消息「不能小于 0」）、timeout_hours（min 1）、max_concurrency（1–50）、operator / wait_mode / merge_strategy / execution_mode / on_iteration_error enum
    - trigger.ts：method enum

    消息格式统一：min → 「不能小于 {界值}」，max → 「不能大于 {界值}」。不改动任何校验逻辑（界值、default、int()、nullable 等保持原样），只加 message。
  </action>
  <verify>
    <automated>cd web && pnpm vitest run src/components/workflow --reporter=basic</automated>
  </verify>
  <done>schemas.ts 与 4 个 category 文件中所有 min/max/uuid 校验均带中文消息（enum 尽力补全），既有 workflow 相关测试全部通过。</done>
</task>

<task type="auto">
  <name>Task 3: 汉化硬编码英文错误文案并跑全量前端测试</name>
  <files>web/src/components/settings/VectorIndexSettings.vue, web/src/api/client.ts, web/src/api/prompts.ts</files>
  <action>
    - VectorIndexSettings.vue 第 218 行：`'Embedding API URL is required'` → `'请输入 Embedding API URL'`
    - client.ts 第 183、184、220、221、237 行：5 处 `'Request failed'` → `'请求失败'`
    - prompts.ts 第 135 行：`'Request failed'` → `'请求失败'`

    专有名词（Embedding、API、URL）保留英文。改完运行全量前端测试与类型检查确认无回归。
  </action>
  <verify>
    <automated>cd web && ! grep -rn "Request failed\|Embedding API URL is required" src/ && pnpm vitest run --reporter=basic</automated>
  </verify>
  <done>src/ 下不再出现 'Request failed' 与 'Embedding API URL is required'，全量 vitest 通过。</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| 无新增 | 纯前端文案/校验消息修改，不改变校验逻辑与任何信任边界 |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-quick-01 | Tampering | zod schemas 校验逻辑 | mitigate | 仅添加 message 参数，不修改界值/类型/default；Task 2 verify 跑 workflow 测试锁定行为不变 |
</threat_model>

<verification>
- `grep` 确认无残留误导文案与英文兜底文案
- `pnpm -C web vitest run` 全量通过（含 `AIModelConfig.spec.ts` 等既有中文断言）
</verification>

<success_criteria>
- 仓库创建/编辑弹窗帮助文案为「仅支持 HTTPS 格式」并说明原因
- schemas.ts + 4 个 category 文件的 min/max/uuid 校验全部带中文消息（数字消息含界值），enum 尽力补全
- 'Request failed'（6 处）与 'Embedding API URL is required'（1 处）全部汉化
- 全量前端测试通过，校验逻辑（界值/default）零变更
</success_criteria>

<output>
完成后创建 `.planning/quick/260610-oug-url-https/260610-oug-SUMMARY.md`
</output>
