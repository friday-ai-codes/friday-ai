/**
 * Friday MCP 工具定义（19 个），与服务端 server/mcp_tools/serializers.py 对齐。
 *
 * 每个工具对应一个 HTTP 端点 POST {baseUrl}/api/mcp/tools/{name}/。
 * inputSchema 为 JSON Schema（MCP 标准），字段约束镜像 DRF serializer。
 * 服务端是校验唯一真源，schema 漂移时以服务端 400 错误为准。
 */

export interface FridayToolDefinition {
  name: string
  description: string
  inputSchema: Record<string, unknown>
}

const uuid = (description: string) => ({ type: 'string', format: 'uuid', description })
const str = (description: string) => ({ type: 'string', description })
const int = (description: string, opts: { min?: number, max?: number, default?: number } = {}) => ({
  type: 'integer',
  description,
  ...(opts.min !== undefined ? { minimum: opts.min } : {}),
  ...(opts.max !== undefined ? { maximum: opts.max } : {}),
  ...(opts.default !== undefined ? { default: opts.default } : {}),
})
const bool = (description: string, def?: boolean) => ({
  type: 'boolean',
  description,
  ...(def !== undefined ? { default: def } : {}),
})
const strList = (description: string) => ({
  type: 'array',
  items: { type: 'string' },
  description,
})
const dictList = (description: string) => ({
  type: 'array',
  items: { type: 'object' },
  description,
})

export const FRIDAY_TOOLS: FridayToolDefinition[] = [
  {
    name: 'route_repositories',
    description: '根据需求描述路由到最相关的已索引仓库，返回排序后的候选仓库与索引健康度。仓库发现的第一步。',
    inputSchema: {
      type: 'object',
      properties: {
        query: str('需求 / 问题描述（<=1000 字符）'),
        top_k: int('返回候选仓库数', { min: 1, max: 10, default: 3 }),
      },
      required: ['query'],
    },
  },
  {
    name: 'search_rag_chunks',
    description: '在指定仓库做 Graph RAG 混合检索（语义 + 关键词 + 图谱扩散），返回相关代码块与关系边。代码证据收集的主力工具。',
    inputSchema: {
      type: 'object',
      properties: {
        repository_id: uuid('仓库 UUID（来自 route_repositories / get_repository）'),
        query: str('检索语句（<=1000 字符）'),
        branch: str('分支名，省略用默认分支'),
        top_k: int('召回 chunk 数', { min: 1, max: 50, default: 30 }),
        max_tokens: int('返回内容 token 预算', { min: 1, max: 32000, default: 8000 }),
      },
      required: ['repository_id', 'query'],
    },
  },
  {
    name: 'get_repository',
    description: '查询单个仓库的元数据与索引状态（默认分支、索引健康度等）。',
    inputSchema: {
      type: 'object',
      properties: { repository_id: uuid('仓库 UUID') },
      required: ['repository_id'],
    },
  },
  {
    name: 'list_repository_files',
    description: '列出仓库目录结构（支持分页与递归）。用于浏览项目布局。',
    inputSchema: {
      type: 'object',
      properties: {
        repository_id: uuid('仓库 UUID'),
        branch: str('分支名，省略用默认分支'),
        path: str('起始目录路径，默认仓库根'),
        recursive: bool('是否递归列出子目录', false),
        page: int('页码', { min: 1, default: 1 }),
        page_size: int('每页条数', { min: 1, max: 200, default: 50 }),
      },
      required: ['repository_id'],
    },
  },
  {
    name: 'get_repository_file',
    description: '读取仓库内单个文件内容（支持行范围截取）。',
    inputSchema: {
      type: 'object',
      properties: {
        repository_id: uuid('仓库 UUID'),
        file_path: str('文件路径（相对仓库根，<=1000 字符）'),
        branch: str('分支名，省略用默认分支'),
        start_line: int('起始行（1-based）', { min: 1 }),
        end_line: int('结束行（>= start_line）', { min: 1 }),
        max_lines: int('最大返回行数', { min: 1, max: 2000, default: 500 }),
      },
      required: ['repository_id', 'file_path'],
    },
  },
  {
    name: 'find_related_chunks',
    description: '沿代码图谱查找相关代码块（调用 / 被调用 / 导入等关系，1-2 跳扩散）。chunk_id、file_path、symbol_name 三者必须且只能提供一个。用于影响面与调用链分析。',
    inputSchema: {
      type: 'object',
      properties: {
        repository_id: uuid('仓库 UUID'),
        branch: str('分支名，省略用默认分支'),
        chunk_id: uuid('起点 chunk UUID（与 file_path / symbol_name 三选一）'),
        file_path: str('起点文件路径（三选一）'),
        symbol_name: str('起点符号名（三选一）'),
        relation_types: strList('关系类型过滤（如 calls / imports），空为全部'),
        hops: int('图谱扩散跳数', { min: 0, max: 2, default: 1 }),
        direction: {
          type: 'string',
          enum: ['downstream', 'upstream', 'both'],
          default: 'both',
          description: '扩散方向：downstream 被依赖方 / upstream 依赖方 / both 双向',
        },
        limit: int('返回上限', { min: 1, max: 50, default: 20 }),
      },
      required: ['repository_id'],
    },
  },
  {
    name: 'analyze_repository',
    description: '对仓库做结构化分析（架构、风险、测试建议），可带 focus 聚焦特定主题，返回 analysis_id 供 create_coding_plan 复用证据。',
    inputSchema: {
      type: 'object',
      properties: {
        repository_id: uuid('仓库 UUID'),
        branch: str('分支名，省略用默认分支'),
        focus: str('聚焦主题（<=1000 字符），如某个需求或模块'),
        context_chunks: dictList('补充上下文 chunk 列表（来自 search_rag_chunks 结果，<=20 条）'),
        max_files: int('分析文件数上限', { min: 1, max: 200, default: 80 }),
      },
      required: ['repository_id'],
    },
  },
  {
    name: 'create_coding_plan',
    description: '根据需求与代码证据生成结构化编码计划（分步骤、含风险与测试建议），返回 plan_id / version_id。执行编码前的必经步骤。',
    inputSchema: {
      type: 'object',
      properties: {
        repository_id: uuid('仓库 UUID'),
        branch: str('分支名，省略用默认分支'),
        requirement: str('需求描述（<=8000 字符）'),
        analysis_id: uuid('analyze_repository 返回的分析 ID（可选，复用证据）'),
        context_chunks: dictList('补充上下文 chunk 列表（<=20 条）'),
        max_steps: int('计划步骤数上限', { min: 1, max: 20, default: 8 }),
      },
      required: ['repository_id', 'requirement'],
    },
  },
  {
    name: 'improve_coding_plan',
    description: '根据反馈修订既有编码计划，生成新版本（返回新 version_id 与 change_summary / risk_delta）。',
    inputSchema: {
      type: 'object',
      properties: {
        plan_id: uuid('计划 UUID（来自 create_coding_plan）'),
        feedback: str('修订反馈（<=8000 字符）'),
        context_chunks: dictList('补充上下文 chunk 列表（<=20 条）'),
        max_steps: int('计划步骤数上限', { min: 1, max: 30, default: 10 }),
      },
      required: ['plan_id', 'feedback'],
    },
  },
  {
    name: 'execute_coding_plan',
    description: '在 Friday Runner 的隔离容器中执行已确认的编码计划（Claude Code 实际写代码、跑测试、推分支）。耗时长（默认超时 1 小时），返回 execution_id 供轮询。执行前必须先经用户确认计划内容。',
    inputSchema: {
      type: 'object',
      properties: {
        plan_id: uuid('计划 UUID'),
        version_id: uuid('计划版本 UUID（可选，默认最新版本）'),
        branch_name: str('工作分支名（可选，默认自动生成）'),
        target_branch: str('目标分支（可选，默认仓库默认分支）'),
        retry_of_execution_id: uuid('重试来源 execution UUID（可选）'),
        timeout_seconds: int('执行超时秒数', { min: 60, max: 21600, default: 3600 }),
      },
      required: ['plan_id'],
    },
  },
  {
    name: 'get_coding_execution',
    description: '查询编码执行状态与产物（status / commit_sha / file_changes / test_results / last_diff / runner_logs / recovery_state）。执行后轮询与失败诊断用。',
    inputSchema: {
      type: 'object',
      properties: { execution_id: uuid('执行 UUID') },
      required: ['execution_id'],
    },
  },
  {
    name: 'summarize_branch',
    description: '对比分支差异并生成可读摘要与 MR 草稿。提供 execution_id，或同时提供 repository_id + source_branch + target_branch。',
    inputSchema: {
      type: 'object',
      properties: {
        execution_id: uuid('执行 UUID（与下三项二选一）'),
        repository_id: uuid('仓库 UUID'),
        source_branch: str('源分支'),
        target_branch: str('目标分支'),
        max_files: int('摘要文件数上限', { min: 1, max: 200, default: 50 }),
      },
    },
  },
  {
    name: 'create_merge_request',
    description: '在 GitHub / GitLab 创建 PR / MR。提供 execution_id，或同时提供 repository_id + source_branch + target_branch。title/description 省略时复用 summarize_branch 草稿。',
    inputSchema: {
      type: 'object',
      properties: {
        execution_id: uuid('执行 UUID（与 repository_id 组合二选一）'),
        repository_id: uuid('仓库 UUID'),
        source_branch: str('源分支'),
        target_branch: str('目标分支'),
        title: str('MR 标题（<=200 字符，可选）'),
        description: str('MR 描述（<=20000 字符，可选）'),
        reviewer_usernames: strList('评审人用户名列表（<=20 个）'),
        remove_source_branch: bool('合并后删除源分支', true),
      },
    },
  },
  {
    name: 'get_feishu_work_item_context',
    description: '聚合飞书工作项上下文：字段、关系、关联文档与评论，返回 context_id 供 create_feishu_technical_plan 使用。project_id 与 project_key 至少提供一个。',
    inputSchema: {
      type: 'object',
      properties: {
        project_id: uuid('Friday 项目 UUID（与 project_key 二选一）'),
        project_key: str('飞书项目 key（二选一）'),
        work_item_type: { type: 'string', default: 'story', description: '工作项类型，默认 story' },
        work_item_id: int('飞书工作项 ID', { min: 1 }),
        fields: strList('需要拉取的字段列表（<=80 个，空为默认字段）'),
        include_comments: bool('是否包含评论', false),
      },
      required: ['work_item_id'],
    },
  },
  {
    name: 'create_feishu_technical_plan',
    description: '基于工作项上下文与代码证据生成技术方案，可写回飞书文档与评论。返回 technical_plan_id 供建任务 / 执行。',
    inputSchema: {
      type: 'object',
      properties: {
        context_id: uuid('get_feishu_work_item_context 返回的 context UUID'),
        repository_ids: { type: 'array', items: { type: 'string', format: 'uuid' }, description: '限定仓库 UUID 列表（<=10 个，可选）' },
        repo_hints: strList('仓库提示词（<=20 个，可选，辅助路由）'),
        context_chunks: dictList('补充代码证据 chunk（<=30 条）'),
        similar_cases: dictList('相似历史案例（来自 search_learning_cases，<=20 条）'),
        title: str('方案标题（<=240 字符，可选）'),
        folder_token: str('飞书文档目录 token（可选）'),
        create_document: bool('是否创建飞书文档', true),
        write_comment: bool('是否写回工作项评论', true),
      },
      required: ['context_id'],
    },
  },
  {
    name: 'create_work_item_repo_tasks',
    description: '把技术方案拆解为按仓库划分的任务矩阵（跨仓需求拆分）。',
    inputSchema: {
      type: 'object',
      properties: { technical_plan_id: uuid('技术方案 UUID') },
      required: ['technical_plan_id'],
    },
  },
  {
    name: 'execute_work_item_repo_tasks',
    description: '批量执行技术方案下的仓库任务（派发编码、建 MR、回写飞书）。technical_plan_id 与 task_ids 至少提供一个。耗时长，执行前必须经用户确认。',
    inputSchema: {
      type: 'object',
      properties: {
        technical_plan_id: uuid('技术方案 UUID（与 task_ids 二选一）'),
        task_ids: { type: 'array', items: { type: 'string', format: 'uuid' }, description: '指定任务 UUID 列表（<=20 个，二选一）' },
        create_missing: bool('缺任务时自动补建', true),
        dispatch: bool('是否实际派发编码执行', true),
        create_merge_requests: bool('完成后自动建 MR', true),
        write_back: bool('结果回写飞书', true),
        timeout_seconds: int('单任务超时秒数', { min: 60, max: 21600, default: 3600 }),
        reviewer_usernames: strList('MR 评审人用户名列表（<=20 个）'),
      },
    },
  },
  {
    name: 'create_learning_case',
    description: '把一次技术方案 / 执行的经验沉淀为学习案例（根因、解法、测试），供未来相似需求检索复用。',
    inputSchema: {
      type: 'object',
      properties: {
        technical_plan_id: uuid('技术方案 UUID'),
        outcome: { type: 'string', default: 'unknown', description: '结果标签（如 success / failed / unknown）' },
        root_cause: str('根因记录（<=5000 字符）'),
        solution_notes: str('解法笔记（<=10000 字符）'),
        tests: strList('相关测试列表（<=50 条）'),
      },
      required: ['technical_plan_id'],
    },
  },
  {
    name: 'search_learning_cases',
    description: '检索历史学习案例（按语义 + 仓库 / 文件 / 符号提示），在生成新方案前查相似经验。',
    inputSchema: {
      type: 'object',
      properties: {
        query: str('检索语句（<=2000 字符）'),
        work_item_type: str('工作项类型过滤（可选）'),
        repo_hints: strList('仓库提示（<=20 个）'),
        file_hints: strList('文件路径提示（<=50 个）'),
        symbol_hints: strList('符号名提示（<=50 个）'),
        limit: int('返回上限', { min: 1, max: 20, default: 5 }),
      },
    },
  },
]
