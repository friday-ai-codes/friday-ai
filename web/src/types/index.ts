// ============================================================================
// 枚举类型
// ============================================================================
/**
 * Git 平台类型
 */
export type GitPlatform = 'github' | 'gitlab' | 'gitea' | 'bitbucket'
/**
 * 认证类型
 */
export type AuthType = 'ssh_key' | 'access_token' | 'deploy_key'
// ============================================================================
// 用户认证相关类型
// ============================================================================
/**
 * 用户信息
 */
export interface User {
 id: string
 username: string
 display_name: string | null
 is_active: boolean
 is_superuser: boolean
 created_at: string
 updated_at: string
}
/**
 * 登录请求
 */
export interface LoginRequest {
 username: string
 password: string
}
/**
 * 登录响应
 */
export interface LoginResponse {
 access_token: string
 token_type: string
 user: User
 must_change_password: boolean
}
/**
 * Token 刷新响应
 */
export interface RefreshResponse {
 access_token: string
 token_type: string
}
/**
 * 修改密码请求
 */
export interface ChangePasswordRequest {
 old_password: string
 new_password: string
}
/**
 * 强制修改密码请求
 */
export interface ForceChangePasswordRequest {
 new_password: string
}
/**
 * 管理员资料
 */
export interface AdminProfile {
 id: string
 username: string
 display_name: string
 is_superuser: boolean
 created_at: string
 updated_at: string
}
/**
 * 管理员资料更新请求
 */
export interface AdminProfileUpdate {
 username?: string
 display_name?: string
}
// ============================================================================
// 仓库相关类型
// ============================================================================
/**
 * 项目摘要信息（用于仓库关联展示）
 */
export interface ProjectSummary {
 id: string
 name: string
}
/**
 * 仓库基础字段
 */
export interface RepositoryBase {
 name: string
 git_url: string
 git_platform: GitPlatform
 default_branch: string
 description?: string
}
/**
 * 仓库完整类型
 */
export interface Repository extends RepositoryBase {
 id: string
 created_at: string
 updated_at: string
 has_credential: boolean
 projects: ProjectSummary
 proxy_url?: string
}
/**
 * 创建仓库请求（包含必填的 Access Token）
 */
export interface RepositoryCreate extends RepositoryBase {
 access_token: string
 git_user_name?: string
 git_user_email?: string
}
/**
 * 更新仓库请求
 */
export interface RepositoryUpdate {
 name?: string
 git_url?: string
 git_platform?: GitPlatform
 default_branch?: string
 description?: string
}
// ============================================================================
// 项目相关类型
// ============================================================================
/**
 * 项目基础字段
 */
export interface ProjectBase {
 name: string
 description?: string
 feishu_project_key: string | null
}
/**
 * 项目完整类型（来自 API）
 */
export interface Project extends ProjectBase {
 id: string
 created_at: string
 updated_at: string
 has_feishu_config: boolean
 webhook_token: string
 repositories?: Repository
}
/**
 * 创建项目请求
 */
export interface ProjectCreate extends ProjectBase {}
/**
 * 更新项目请求
 */
export interface ProjectUpdate {
 name?: string
 description?: string
 feishu_project_key?: string | null
}
// ============================================================================
// 凭证相关类型
// ============================================================================
/**
 * Git 凭证（来自 API，不含敏感信息）
 */
export interface GitCredential {
 id: string
 repository_id: string
 auth_type: AuthType
 git_user_name: string
 git_user_email: string
 created_at: string
}
// ============================================================================
// 飞书配置相关类型
// ============================================================================
/**
 * 飞书配置创建请求
 * 飞书项目使用「插件」凭证而非「应用」凭证来获取工作项详情
 * 注意：webhook_token 不再在此处配置，它在项目级别独立管理
 */
export interface FeishuConfigCreate {
 plugin_id: string
 plugin_secret: string
 user_key: string
}
/**
 * 飞书配置读取响应（不含敏感信息，webhook_token 由 Project 接口返回）
 */
export interface FeishuConfig {
 project_key: string | null
 plugin_id: string | null
 user_key: string | null
 has_plugin_secret: boolean
 is_configured: boolean
}
/**
 * 飞书配置测试请求（用于传入临时配置进行测试）
 */
export interface FeishuConfigTest {
 plugin_id?: string | null
 plugin_secret?: string | null
 user_key?: string | null
}
/**
 * 飞书配置测试结果
 */
export interface FeishuConfigTestResult {
 success: boolean
 message: string
 plugin_token_valid: boolean
 project_accessible: boolean
}
/**
 * Webhook Token 更新请求
 */
export interface WebhookTokenUpdate {
 token: string
}
/**
 * Webhook Token 读取响应
 */
export interface WebhookTokenRead {
 webhook_token: string
}
// ============================================================================
// API 通用类型
// ============================================================================
/**
 * API 错误响应
 */
export interface ApiErrorResponse {
 detail: string
}
/**
 * 健康检查响应
 */
export interface HealthResponse {
 status: string
 app: string
}
// ============================================================================
// 工作流节点类型
// ============================================================================
/**
 * 飞书事件触发节点数据
 */
export interface FeishuEventTriggerNodeData {
 event_types: string
 filter_project_key?: string
 filter_work_item_type?: 'story' | 'task' | 'bug' | ''
 filter_status?: string
}
/**
 * 获取工作项详情节点数据
 */
export interface FetchWorkItemNodeData {
 work_item_id: string
 work_item_type: 'story' | 'task' | 'bug'
 extract_fields: string
 set_global_params: boolean
 include_project_info: boolean
 include_repositories: boolean
}
/**
 * AI Prompt 节点数据
 */
export interface AIPromptNodeData {
 system_prompt: string
 user_prompt: string
 model: string
 temperature: number
 max_tokens: number
 output_format: 'text' | 'json' | 'markdown'
}
/**
 * AI 编码指派器节点数据
 */
export interface AICodingDispatcherNodeData {
 analysis_model: string
 max_tasks: number
 task_granularity: 'fine' | 'medium' | 'coarse'
 include_tests: boolean
 auto_assign_repos: boolean
}
/**
 * 触发器事件类型
 */
export type TriggerEventType
 = | 'WorkitemCreateEvent'
 | 'WorkitemStatusEvent'
 | 'WorkitemCommentEvent'
 | 'WorkitemUpdateEvent'
 | 'WorkFlowNodeStatusEvent'
/**
 * 工作流触发器
 */
export interface WorkflowTrigger {
 id: string
 workflow: string
 event_type: TriggerEventType
 event_type_display: string
 filter_config: Record<string, any>
 input_schema: Record<string, any>
 is_active: boolean
 name: string
 description: string
 created_at: string
 updated_at: string
}
/**
 * 创建触发器请求
 */
export interface WorkflowTriggerCreate {
 event_type: TriggerEventType
 filter_config?: Record<string, any>
 input_schema?: Record<string, any>
 is_active?: boolean
 name?: string
 description?: string
}
/**
 * 编码任务状态
 */
export type CodingTaskStatus
 = | 'pending'
 | 'planning'
 | 'plan_review'
 | 'executing'
 | 'code_review'
 | 'merged'
 | 'failed'
/**
 * 编码任务
 */
export interface CodingTask {
 id: string
 workflow_execution: string
 repository: string
 repository_name: string
 name: string
 prompt: string
 description: string
 status: CodingTaskStatus
 status_display: string
 session_id: string
 plan_output: string
 human_feedback: string
 branch_name: string
 commit_sha: string
 pr_url: string
 error_message: string
 retry_count: number
 metadata: Record<string, any>
 duration: number | null
 created_at: string
 updated_at: string
 started_at: string | null
 completed_at: string | null
}
/**
 * 执行上下文快照
 */
export interface ExecutionContext {
 execution_id: string
 status: string
 progress: number
 is_manual_trigger: boolean
 trigger_data: Record<string, any>
 input_data: Record<string, any>
 global_params: Record<string, any>
 node_outputs: Record<string, any>
}
/**
 * 手动触发请求
 */
export interface ManualTriggerRequest {
 event_type?: TriggerEventType
 input_data?: Record<string, any>
}
/**
 * 手动触发响应
 */
export interface ManualTriggerResponse {
 execution_id: string
 status: string
 message: string
}
// ============================================================================
// UI 辅助类型
// ============================================================================
/**
 * Git 平台中文名称映射
 */
export const PLATFORM_LABELS: Record<GitPlatform, string> = {
 github: 'GitHub',
 gitlab: 'GitLab',
 gitea: 'Gitea',
 bitbucket: 'Bitbucket',
}
