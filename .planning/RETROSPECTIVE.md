# Retrospective

## Milestone: v0.1.0 — 首启初始化向导

**Shipped:** 2026-06-09
**Phases:** 5 | **Plans:** 9

### What Was Built
用「首次访问引导用户自设账号」替代启动期自动建管理员：首启门禁（fail-closed 防重入）、管理员自设+自动登录、Anthropic 兼容供应商一键预设（Fernet 加密 + 健康校验 + 绑 Claude Code）、安全密钥校验、可选飞书/RAG 步骤、entrypoint 去自动建号且向后兼容。

### What Worked
- 严格复用既有 `ProviderConfigService` / `ProviderCredential` / `SystemSetting` / Fernet 加密路径，未重写既有系统，集成风险低。
- fail-closed 安全门禁（仅无 superuser 可用）从 Phase 1 就锁定为独立权限类，后续阶段直接复用。
- 一键模型预设以「anthropic 类型 + base_url 覆盖」统一接入第三方模型，前端常量化，扩展简单。

### What Was Inefficient
- Phase 01/02 的人工验收（UAT）签字未闭环，里程碑关闭时作为 deferred 项带走。
- SUMMARY.md 的 one-liner 格式与 SDK summary-extract 不匹配，归档成果摘要需手动补全。

### Patterns Established
- 敏感配置一律走加密落库（`is_encrypted=True` + `SettingKeys.*`），不走通用明文 PUT /settings/。
- 薄编排端点（IsSuperUser）承担「校验→加密→落库→绑定」的组合写操作。

### Key Lessons
- 向导类需求要尽早把「安全门禁 + 向后兼容」作为一等公民，避免收尾阶段返工。
- 人工验收门应在每个 Phase 完成时即时签字，避免堆积到里程碑关闭。

## Milestone: v0.8.0 — 多仓串行编码 → 融合 PR

**Shipped:** 2026-06-17
**Phases:** 5 (43–47) | **Plans:** 16 | **Tasks:** 38

### What Was Built
把 v0.7 产的 `MergedPlan.execution_plan` + 跨仓依赖 DAG 真正落成多仓代码：PF-06 workflow 编码 dispatch env 对齐 chat 基线（私有仓 clone + 正确目标分支）+ 入口无关 resume 续驱 helper（消化 v0.7 audit D-2）；`RepoCodingTask` 操作态模型 + `execution_plan[].dependencies` graphlib 拓扑分层成 wave + `aadvance_coding_waves` 推进（wave N done → N+1，失败隔离不死锁）+ `AICodingNode` 按 wave 分批 dispatch 经 callback 重入自驱；上游产物提取（OpenAPI/契约/diff）注入下游 wave；各仓 MR 锚定各仓 `default_branch` + 跨仓 PR cross-ref + 追溯 `TechnicalPlan`/`WorkItem`；编码遇阻 `ask_user` 抛 question 给人（容器心跳保活）+ resume 续跑，非全自动 replan。

### What Worked
- **「不造两套」贯穿全程**：续驱 helper（节点/工具/回调三处同源）、wave 推进、单一写入入口（INV-6）全部复用底座，跨阶段集成审计直接判 integration_ok。
- **复用既有 `waiting_event` + callback resume 扩成多 wave**，未另造调度器（`while True`→有界 `for`，无 sleep/timer/apscheduler），liveness 风险可控。
- **liveness 命门前置识别**：传递闭包阻断必在任何 early-return 前完成（T-44-DEADLOCK），从设计阶段就锁死避免死锁。
- **空依赖退化全并行的零回归命门**贯穿 wave 分层/调度/产物注入，保证存量单仓/同 default 多仓字节级等价。
- **mock IO 边界的单测/集成测试**充分覆盖拓扑分层、wave gating、失败隔离、幂等、产物传递、PR cross-ref、HITL 全链，本地无 runner/Docker 也能验收到 accepted level。

### What Was Inefficient
- **STATE.md 在收官前未及时回写**：Phase 47 实际已完成验证，但 STATE.md 仍停在「Phase 47 未开始 / 80%」，autonomous 收尾时需先辨明磁盘真实状态（roadmap.analyze 权威）才能继续。
- **REQUIREMENTS.md traceability 表滞后**：PF-06/WAVE-01/WAVE-02 已交付但表中仍标 Pending/未勾选，靠 3 源交叉（VERIFICATION + SUMMARY + traceability）才确认满足。
- **Phase 45 SUMMARY 缺 `requirements-completed` frontmatter 字段**，ARTIFACT-01/02 覆盖只能从 VERIFICATION 需求表确认。
- **Phase 26 遗留 `test_batch_pr.py` 5 例 stale patch target 失败**跨里程碑悬挂未清。

### Patterns Established
- **wave 分层用 task 级 DAG（`execution_plan[].dependencies`）+ 仓 wave 取 task 层级 max**，环检测复用 `plan_validator.validate_plan` 不重写。
- **wave 失败部分回滚语义**：done 出 MR、failed/blocked 如实标注 `upstream_failed`、不自动回滚（v0.8 非目标）。
- **per-repo MR `target_branch` fallback 链** `default_branch or base_branch or "main"`，保单仓/同 default 多仓零回归。
- **跨仓 PR cross-ref `successful_mrs ≥2` 守门 + 全程 fail-soft**（绝不上抛回灌 5xx），追溯链 `plan_version → TechnicalPlan → WorkItem` 逐跳 afirst 链断返空。
- **编码遇阻 HITL：容器 `ask_user` + 心跳保活 RUNNING + `answer.json` 共享卷回灌**，复用既有 question 协议，no-replan 守护测试坐实。

### Key Lessons
- **收官前先以 roadmap.analyze（磁盘权威）核对真实状态**，STATE.md / REQUIREMENTS.md 可能滞后；状态文件回写应作为 phase 收尾一等公民。
- **「不造两套」从设计阶段就锁死单源 helper / 单一写入入口**，是跨阶段集成零缝隙的根本原因，值得在后续里程碑继续坚持。
- **liveness / 死锁风险在并发 wave 调度里要前置到设计**（阻断顺序、early-return 时机），不能留到测试才发现。
- **真实 runner+Docker 容器 E2E 是结构性 deferred**（本地无法闭环），mock IO 边界覆盖应明确标注为 accepted verification level，避免反复回炉。

### Cost Observations
- Sessions: 跨多会话执行（v0.8.0 收官于 autonomous lifecycle 单会话）。
- Notable: phase 内多以 mock IO 边界测试收敛，单 plan 多在 5–25min 量级（见 STATE.md Performance Metrics）。

## Milestone: v0.16.3 — 外部依赖接入知识体系（可检索 + 知识树 + 关联图谱）

**Shipped:** 2026-07-01
**Phases:** 4（96–99） | **Plans:** 15 | **Requirements:** 12/12（KDEP-01~12）| **Audit:** tech_debt

### What Was Built
把项目外部依赖（`Artifact`）完整接入「知识」体系：全类型工件登记可发现（非 ragable 元数据-only 实体+边）+ 搜索标类型可跳查看 + 知识总览「交付文档」区块（P96）；`/knowledge` 并行「交付文档」树 + 树内搜索/查看 + 后端树 API（P97）；RepoRouterV2 路由工件正文落 `RELATES_TO` 边 + verified `RepoAssociation` 单向派生 + 双向关联查询（P98）；星图纳入 artifact/capability 节点边 + 实体详情双向关联展示 + 作战室↔知识闭环（P99）。

### What Worked
- **research 基线先行**：里程碑立项时已产出详尽的现状探查 + 架构决策锁定（复用 Artifact / delivery_knowledge / RepoRouterV2 / RepoAssociation / graph_store，不新建真相源），使 smart-discuss 几乎无灰区、plan/execute 直接落到复用点，返工极少。
- **严格复用 + 单一写入入口（INV-6）**：四阶段层层复用上游产物（P97 镜像 P96 的 access_scope/截断范式、P99 只读消费 P98 查询服务），跨阶段 integration_ok 一次通过。
- **全自动 discuss→plan→execute→verify→review→fix 流水线**：每阶段 review 都抓到真实"好用/优雅"缺陷（dep_type 预筛未生效、空态连坐隐藏、陈旧路由边累积、type_key 生显）并即时修复，质量门控发挥作用。

### What Was Inefficient
- **规划文档与工具链契约漂移**：里程碑 Phase 详情初始只放在 `milestones/v0.16.3-ROADMAP.md`，顶层 ROADMAP 缺 `### Phase N:` 明细块，导致 `roadmap.get-phase` 找不到阶段，须先回填明细块工具链才识别。教训：立项即在顶层 ROADMAP 内联当前里程碑 Phase 明细。
- **共享常量事后抽取**：徽标/载体图标常量在 P96/P97/P99 三处复制，到集成检查才抽 `artifactDisplay.ts`。教训：跨阶段复用的展示常量应在首个阶段就建共享模块。

### Patterns Established
- 非 ragable 工件「元数据-only 知识实体登记」（建 document 实体 + REFERENCES 边、零向量、幂等）——为无正文工件提供可发现性的通用范式。
- 关联边 metadata 承载关键词/能力（不建独立实体表）+ 唯一真相源单向派生 + 重摄取陈旧边收敛。

### Key Lessons
- LLM 非确定性路由必须配"陈旧边失效收敛"，否则关联随重摄取累积污染查询——已在 P98 补齐并加收敛测试。
- 自动化验证 human_needed（真机/浏览器）是结构性 deferred，代码层 must-haves + 自动化测试全绿即可 accept tech_debt 归档，勿反复回炉。

### Cost Observations
- Sessions: 单会话全自动执行（$gsd-autonomous），中途 2 次用户中断后 `继续` 无缝续跑（阶段产物已提交，幂等续接）。
- Notable: 每阶段 planner→executor→verifier→reviewer→fixer 子代理链隔离上下文，主编排上下文保持精简。

## Cross-Milestone Trends

| Milestone | Phases | Plans | Shipped |
|-----------|--------|-------|---------|
| v0.1.0 首启初始化向导 | 5 | 9 | 2026-06-09 |
| v0.8.0 多仓串行编码 → 融合 PR | 5 | 16 | 2026-06-17 |
