// ============================================================================
// X6-Compatible Store Types
// ============================================================================

import type { GraphBuildStatus } from '~/api/codegraph'

export type { WorkflowEdgeStore, WorkflowNodeStore } from './workflow/store'

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
 * 空间成员关系摘要（嵌入 /me 响应）
 */
export interface SpaceMembershipBrief {
  space_id: string
  space_name: string
  role: 'admin' | 'member' | 'viewer'
}

/**
 * 当前用户完整信息（含 gravatar 和空间列表）
 */
export interface MeUser {
  id: string
  username: string
  email: string
  display_name: string
  gravatar_url: string | null
  is_superuser: boolean
  is_active: boolean
  space_memberships: SpaceMembershipBrief[]
  created_at: string
}

/**
 * 用户来源（与后端 UserSource 枚举一致）
 */
export type UserSource
  = | 'feishu'
    | 'google'
    | 'github'
    | 'oidc_other'
    | 'invitation'
    | 'admin'
    | 'system'

/**
 * 系统用户（管理员视角）
 */
export interface SystemUser {
  id: string
  username: string
  display_name: string
  is_active: boolean
  is_superuser: boolean
  source: UserSource
  created_at: string
}

/**
 * 邀请令牌
 */
export interface Invitation {
  id: string
  token: string
  email: string
  expires_at: string
  created_at: string
}

/**
 * 空间成员关系（空间成员管理 API）
 */
export interface SpaceMembership {
  id: string
  user: {
    id: string
    username: string
    display_name: string
    email: string
    is_active: boolean
  }
  role: 'admin' | 'member' | 'viewer'
  joined_at: string
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
 * 空间摘要信息（用于仓库关联展示）
 */
export interface SpaceSummary {
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
  base_branch?: string | null
}

/**
 * 仓库完整类型
 */
export interface Repository extends RepositoryBase {
  id: string
  created_at: string
  updated_at: string
  has_credential: boolean
  spaces: SpaceSummary[]
  proxy_url?: string
  auto_index_enabled: boolean
  webhook_secret?: string | null
  linked_spaces_count?: number
  index_status: 'not_indexed' | 'indexing' | 'indexed' | 'failed' | 'cancelled'
  last_indexed_at: string | null
  /** 远端 HEAD 所在分支（ls-remote --symref 探测缓存，UI 展示 HEAD 标签用） */
  remote_head_branch?: string | null
  // freshness 字段（/，后端 新增）
  remote_head_sha?: string | null
  remote_head_checked_at?: string | null
  behind_commits?: number | null
  last_indexed_commit_sha?: string | null
  // ：per-repo 自动构图开关（PATCH-able）
  auto_build_graph_enabled: boolean
  // ：6 个图谱进度只读字段
  graph_build_status: GraphBuildStatus
  graph_stage: string
  current_graph_file: string
  graph_files_processed: number
  graph_files_total: number
  graph_last_built_at: string | null
  /** SDD-02：从 facets.methodology 派生的只读方法论标记（如 "SDD"）；无 facets 时为 null */
  methodology?: string | null
}

/**
 * 创建仓库请求（包含必填的 Access Token）
 */
export interface RepositoryCreate extends RepositoryBase {
  access_token: string
  git_user_name?: string
  git_user_email?: string
  /** 必填：所有仓库都必须至少关联一个空间 */
  space_ids: string[]
  /** test-connection 探测到的 HEAD 分支（display-only 缓存） */
  remote_head_branch?: string | null
}

/**
 * 更新仓库请求
 */
export interface RepositoryUpdate {
  name?: string
  git_url?: string
  git_platform?: GitPlatform
  default_branch?: string
  base_branch?: string | null
  auto_index_enabled?: boolean
  auto_build_graph_enabled?: boolean
}

// ============================================================================
// 仓库关联权限相关类型
// ============================================================================

/**
 * 仓库关联权限级别
 */
export type RepositoryPermissionLevel = 'read_write' | 'read_only'

/**
 * 空间仓库关联（API 响应）
 */
export interface SpaceRepositoryLink {
  id: string
  repository_id: string
  repository_name: string
  permission_level: RepositoryPermissionLevel
  created_at: string
}

/**
 * 批量关联仓库请求
 */
export interface SpaceRepositoryLinkCreate {
  repository_ids: string[]
}

/**
 * 修改关联权限请求
 */
export interface SpaceRepositoryLinkUpdate {
  permission_level: RepositoryPermissionLevel
}

// ============================================================================
// 空间相关类型
// ============================================================================

/**
 * 空间基础字段
 */
export interface SpaceBase {
  name: string
  description?: string
  feishu_project_key: string | null
}

/**
 * 空间完整类型（来自 API）
 */
export interface Space extends SpaceBase {
  id: string
  created_at: string
  updated_at: string
  has_feishu_config: boolean
  webhook_token: string
  repositories?: Repository[]
  execution_count?: number
  recent_work_items?: Array<{ id: string, name: string }>
}

/**
 * 创建空间请求
 */
export interface SpaceCreate extends SpaceBase {}

/**
 * 更新空间请求
 */
export interface SpaceUpdate {
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
 * 注意：webhook_token 不再在此处配置，它在空间级别独立管理
 */
export interface FeishuConfigCreate {
  plugin_id: string
  plugin_secret: string
  user_key: string
}

/**
 * 飞书配置读取响应（不含敏感信息，webhook_token 由 Space 接口返回）
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
  event_types: string[]
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
  extract_fields: string[]
  set_global_params: boolean
  include_space_info: boolean
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
    | 'partial_success'
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
  execution_plan_ids: string[]
  mr_has_conflicts?: boolean
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
  debug_mode?: boolean
}

/**
 * 手动触发响应
 */
export interface ManualTriggerResponse {
  execution_id: string
  status: string
  message: string
  is_debug?: boolean
}

// ============================================================================
// Runner 相关类型
// ============================================================================

/**
 * Runner 当前执行任务的精简信息
 */
export interface RunnerTaskBrief {
  id: string
  name: string
  status: string
}

/**
 * Runner 完整类型（与后端 RunnerSerializer 字段对齐）
 */
export interface Runner {
  id: string
  name: string
  token_prefix: string
  scope: 'global' | 'project'
  concurrent: number
  status: 'online' | 'offline'
  version: string
  is_active: boolean
  is_paused: boolean
  is_protected: boolean
  run_untagged: boolean
  max_timeout: number | null
  description: string
  last_heartbeat: string | null
  ip_address: string | null
  registered_at: string
  tags: string[]
  current_tasks: number
  current_task_list: RunnerTaskBrief[]
}

/**
 * DRF 分页响应
 */
export interface PaginatedResponse<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}

/**
 * Runner 任务关联（对齐 RunnerTaskAssignmentSerializer）
 */
export interface RunnerTaskAssignment {
  id: string
  session_id: string
  task_type: string
  session_status: string
  repo_url: string
  assigned_at: string
  status: 'assigned' | 'running' | 'completed' | 'failed'
  completed_at: string | null
}

/**
 * Runner 事件日志（对齐后端 RunnerEventSerializer）
 */
export interface RunnerEvent {
  id: string
  event_type: 'connected' | 'disconnected' | 'heartbeat' | 'task_assigned' | 'task_completed' | 'task_failed'
  detail: Record<string, unknown>
  created_at: string
}

/**
 * 注册令牌（来自 API）
 */
export interface RegistrationToken {
  id: string
  description: string
  scope: 'global' | 'project'
  space_id: string | null
  tags: string[]
  run_untagged: boolean
  is_paused: boolean
  is_protected: boolean
  max_timeout: number | null
  is_used: boolean
  used_at: string | null
  expires_at: string
  created_at: string
  is_valid: boolean
}

/**
 * 创建注册令牌请求
 */
export interface RegistrationTokenCreate {
  description?: string
  scope: 'global' | 'project'
  space_id?: string
  expires_in: number
  tags?: string[]
  run_untagged?: boolean
  is_paused?: boolean
  is_protected?: boolean
  max_timeout?: number | null
}

/**
 * 创建注册令牌响应（含一次性明文令牌）
 */
export interface RegistrationTokenCreateResponse extends RegistrationToken {
  token: string
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

// ============================================================================
// OIDC 相关类型
// ============================================================================

/**
 * OIDC Provider 类型（与后端 OIDCProviderKind 一致）
 */
export type OIDCProviderKind = 'feishu' | 'google' | 'github' | 'other'

/**
 * OIDC Provider（管理员视角）
 */
export interface OIDCProvider {
  id: string
  name: string
  kind: OIDCProviderKind
  issuer_url: string
  client_id: string
  authorization_endpoint: string
  token_endpoint: string
  userinfo_endpoint: string
  scopes: string
  is_active: boolean
  has_secret: boolean
  created_at: string
  updated_at: string
}

/**
 * OIDC Provider 创建/更新请求
 */
export interface OIDCProviderCreate {
  name: string
  kind: OIDCProviderKind
  issuer_url: string
  client_id: string
  client_secret?: string
  authorization_endpoint: string
  token_endpoint: string
  userinfo_endpoint?: string
  scopes?: string
  is_active?: boolean
}

/**
 * OIDC Provider 公开信息（登录页用）
 */
export interface OIDCProviderPublic {
  id: string
  name: string
}

/**
 * OIDC Discovery 结果
 */
export interface OIDCDiscoveryResult {
  authorization_endpoint: string
  token_endpoint: string
  userinfo_endpoint: string
}

/**
 * OIDC 授权响应
 */
export interface OIDCAuthorizeResponse {
  authorize_url: string
}
