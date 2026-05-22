/**
 * 系统内置 Prompt 调用位置/场景映射 — 前端单一事实来源。
 *
 * 同步约束：本映射的 key 与 `server/prompts/keys.py:PromptSlugs` 一一对应；
 * 后端新增 slug 时必须同步在本文件登记一项。`getPromptUsage` 对未登记的 slug
 * 返回 null，UI 会优雅地降级为不展示「调用位置」卡片，不影响主流程。
 *
 * 数据来源：
 * - server/prompts/keys.py（16 个 slug 常量）
 * - server/prompts/migrations/0002_seed_system_defaults.py（seed 标题与分类）
 * - server/tests/test_prompts_migration_contract.py（slug ↔ 业务模块映射契约）
 * - server/chat / server/workflows / server/repositories 实际 render_prompt 调用点
 */
export interface PromptUsageEntry {
 /** 场景一句话描述（用于 UI 顶部高亮，强调"在哪里用"） */
 scenario: string
 /** 触发条件 / 被调用时机的具体描述 */
 trigger: string
 /** 实际调用 render_prompt 的源码位置（相对 server/ 路径） */
 callsite: string
 /**
 * 调用方业务模块归类（Chat / 工作流节点 / 仓库摘要 等），
 * 在 UI 上以小徽章呈现，便于跨场景识别。
 */
 domain: 'chat' | 'workflow' | 'aux' | 'feishu' | 'repo'
 /**
 * 当 slug 暂未被生产代码消费、仅作占位时设为 true；
 * UI 会显示「保留位 · 暂未启用」灰态徽章。
 */
 reserved?: boolean
}
const DOMAIN_LABEL: Record<PromptUsageEntry['domain'], string> = {
 chat: '对话服务',
 workflow: '工作流节点',
 aux: '辅助小模型',
 feishu: '飞书机器人',
 repo: '仓库摘要',
}
const DOMAIN_ICON: Record<PromptUsageEntry['domain'], string> = {
 chat: 'icon-[lucide--messages-square]',
 workflow: 'icon-[lucide--workflow]',
 aux: 'icon-[lucide--sparkles]',
 feishu: 'icon-[lucide--bot]',
 repo: 'icon-[lucide--folder-git-2]',
}
export function getPromptUsageDomainLabel(domain: PromptUsageEntry['domain']): string {
 return DOMAIN_LABEL[domain]
}
export function getPromptUsageDomainIcon(domain: PromptUsageEntry['domain']): string {
 return DOMAIN_ICON[domain]
}
/**
 * slug → 调用元数据。键来自 server/prompts/keys.py:PromptSlugs；
 * 任何新增 slug 都应在此登记一项，否则前端只能显示 fallback 卡片。
 */
const PROMPT_USAGE_MAP: Record<string, PromptUsageEntry> = {
 // ─────────────────────── Chat Agent（5 角色） ───────────────────────
 'chat.system.developer': {
 domain: 'chat',
 scenario: '聊天 — 「开发者」角色的系统提示词',
 trigger: '用户在会话设置中选择「开发者」角色时拼装到系统消息开头',
 callsite: 'chat/conversation_service.py · ROLE_PROMPTS["developer"]',
 },
 'chat.system.pm': {
 domain: 'chat',
 scenario: '聊天 — 「产品经理」角色的系统提示词',
 trigger: '用户在会话设置中选择「PM」角色时拼装到系统消息开头',
 callsite: 'chat/conversation_service.py · ROLE_PROMPTS["pm"]',
 },
 'chat.system.designer': {
 domain: 'chat',
 scenario: '聊天 — 「设计师」角色的系统提示词',
 trigger: '用户在会话设置中选择「设计师」角色时拼装到系统消息开头',
 callsite: 'chat/conversation_service.py · ROLE_PROMPTS["designer"]',
 },
 'chat.system.qa': {
 domain: 'chat',
 scenario: '聊天 — 「QA」角色的系统提示词',
 trigger: '用户在会话设置中选择「QA」角色时拼装到系统消息开头',
 callsite: 'chat/conversation_service.py · ROLE_PROMPTS["qa"]',
 },
 'chat.system.general': {
 domain: 'chat',
 scenario: '聊天 — 「通用助手」角色的系统提示词（默认）',
 trigger: '未指定角色或角色未匹配时的兜底系统提示词',
 callsite: 'chat/conversation_service.py · ROLE_PROMPTS["general"]',
 },
 // ─────────────────────── Chat Agent（2 策略 + 1 编码指引） ───────────────────────
 'chat.strategy.default': {
 domain: 'chat',
 scenario: '聊天 — 默认推理策略片段',
 trigger: '常规会话拼装时追加在系统提示词末尾，约束回答风格与结构',
 callsite: 'chat/conversation_service.py · _STRATEGY_DEFAULT',
 },
 'chat.strategy.deep_analysis': {
 domain: 'chat',
 scenario: '聊天 — 深度分析策略片段',
 trigger: '用户开启「深度分析」开关时替换默认策略片段',
 callsite: 'chat/conversation_service.py · _STRATEGY_DEEP_ANALYSIS',
 },
 'chat.coding_guidance': {
 domain: 'chat',
 scenario: '聊天 — 编码任务指引片段',
 trigger: '检测到会话涉及编码任务时追加到系统提示末尾',
 callsite: 'chat/conversation_service.py · _CODING_GUIDANCE',
 },
 // ─────────────────────── 辅助小模型 ───────────────────────
 'aux.title_generation': {
 domain: 'aux',
 scenario: '辅助小模型 — 自动生成会话标题',
 trigger: '会话产生首条 AI 回复后由 title_service 异步触发',
 callsite: 'chat/title_service.py · TITLE_PROMPT',
 },
 'aux.commit_message': {
 domain: 'aux',
 scenario: '辅助小模型 — 自动生成 Git Commit Message',
 trigger: '执行编码任务、需要生成 commit message 时调用（v19+ 接入中）',
 callsite: 'aux.commit_message（保留占位，等待接入）',
 reserved: true,
 },
 // ─────────────────────── 工作流 AI 节点 ───────────────────────
 'ai_node.prompt.default_system': {
 domain: 'workflow',
 scenario: '工作流 · AI Prompt 节点 — 默认系统提示词',
 trigger: '工作流执行到 AI Prompt 节点且未自定义 system prompt 时使用',
 callsite: 'ai_node.prompt.default_system（保留占位，等待接入）',
 reserved: true,
 },
 'ai_node.code_review.system': {
 domain: 'workflow',
 scenario: '工作流 · AI 代码审查节点 — 系统提示词',
 trigger: 'AI Code Review 节点执行时作为系统提示词组装到模型输入',
 callsite: 'workflows/nodes/ai/code_review.py · REVIEW_SYSTEM_PROMPT',
 },
 'ai_node.plan_generation.system': {
 domain: 'workflow',
 scenario: '工作流 · AI 方案生成节点 — 系统提示词',
 trigger: 'AI Plan Generation 节点执行时作为基础系统提示词',
 callsite: 'workflows/nodes/ai/plan_generation.py · _PLAN_GENERATION_BASE_PROMPT',
 },
 'ai_node.variable_extractor.template': {
 domain: 'workflow',
 scenario: '工作流 · 变量提取节点 — 提示词模板',
 trigger: 'AI Variable Extractor 节点执行时按 schema 渲染抽取指令',
 callsite: 'workflows/nodes/ai/variable_extractor.py · EXTRACTION_PROMPT_TEMPLATE',
 },
 // ─────────────────────── 飞书机器人 ───────────────────────
 'feishu.group_chat.system': {
 domain: 'feishu',
 scenario: '飞书群聊机器人 — 系统提示词',
 trigger: '飞书群聊 @机器人 时作为系统提示组装到模型输入（v19+ 接入中）',
 callsite: 'feishu.group_chat.system（保留占位，等待接入）',
 reserved: true,
 },
 // ─────────────────────── 仓库摘要 ───────────────────────
 'repo.summary_generator': {
 domain: 'repo',
 scenario: '仓库摘要 — 自动生成代码仓库说明',
 trigger: '仓库索引完成或用户手动触发摘要时调用',
 callsite: 'repositories/summary_service.py · render_prompt(REPO_SUMMARY_GENERATOR)',
 },
}
/**
 * 根据 slug 查询调用元数据。未登记返回 null。
 */
export function getPromptUsage(slug: string | undefined | null): PromptUsageEntry | null {
 if (!slug)
 return null
 return PROMPT_USAGE_MAP[slug] ?? null
}
