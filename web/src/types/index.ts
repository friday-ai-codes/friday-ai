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
/**
 * 任务状态枚举
 * 对应后端 TaskStatus
 */
export type TaskStatus
 = | 'pending'
 | 'planning'
 | 'plan_review'
 | 'executing'
 | 'code_review'
 | 'merged'
 | 'failed'
/**
 * 任务执行模式
 */
export type TaskMode = 'plan' | 'execute'
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
 claude_md_path: string
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
}
/**
 * 创建仓库请求
 */
export interface RepositoryCreate extends RepositoryBase {}
/**
 * 更新仓库请求
 */
export interface RepositoryUpdate {
 name?: string
 git_url?: string
 git_platform?: GitPlatform
 default_branch?: string
 claude_md_path?: string
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
}
/**
 * 飞书配置读取响应（不含敏感信息，webhook_token 由 Project 接口返回）
 */
export interface FeishuConfig {
 project_key: string | null
 plugin_id: string | null
 has_plugin_secret: boolean
 is_configured: boolean
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
// 任务相关类型
// ============================================================================
/**
 * 任务基础字段
 */
export interface TaskBase {
 work_item_id: string
 feature_id: string
 title: string
 description: string | null
 git_repo_url: string | null
 git_branch: string | null
 branch_name: string | null
 commit_sha: string | null
 pr_url: string | null
 session_id: string | null
 plan_output: string | null
 status: TaskStatus
}
/**
 * 任务完整类型（来自 API）
 */
export interface Task extends TaskBase {
 id: string
 project_id: string
 repository_id: string | null
 created_at: string
 updated_at: string
 plan_started_at: string | null
 plan_completed_at: string | null
 execute_started_at: string | null
 execute_completed_at: string | null
 retry_count: number
 error_message: string | null
 human_feedback: string | null
}
/**
 * 创建任务请求
 */
export interface TaskCreate {
 project_id: string
 repository_id?: string
 work_item_id: string
 feature_id: string
 title: string
 description?: string
}
/**
 * 更新任务请求
 */
export interface TaskUpdate {
 status?: TaskStatus
 repository_id?: string
 git_repo_url?: string
 git_branch?: string
 branch_name?: string
 commit_sha?: string
 pr_url?: string
 session_id?: string
 plan_output?: string
 human_feedback?: string
 error_message?: string
}
/**
 * 任务列表过滤参数
 */
export interface TaskFilters {
 project_id?: string
 status?: TaskStatus
 limit?: number
 offset?: number
}
/**
 * 任务执行请求
 */
export interface TaskExecuteRequest {
 mode: TaskMode
}
/**
 * 任务执行响应
 */
export interface TaskExecuteResponse {
 task_id: string
 container_id: string
 mode: string
 message: string
}
/**
 * 任务日志响应
 */
export interface TaskLogsResponse {
 task_id: string
 logs: string
}
/**
 * 容器状态响应
 */
export interface ContainerStatusResponse {
 task_id: string
 container: {
 id: string
 status: string
 started_at: string
 } | null
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
// UI 辅助类型
// ============================================================================
/**
 * 状态颜色映射
 */
export const STATUS_COLORS: Record<TaskStatus, string> = {
 pending: 'bg-gray-100 text-gray-800',
 planning: 'bg-blue-100 text-blue-800',
 plan_review: 'bg-yellow-100 text-yellow-800',
 executing: 'bg-blue-100 text-blue-800',
 code_review: 'bg-yellow-100 text-yellow-800',
 merged: 'bg-green-100 text-green-800',
 failed: 'bg-red-100 text-red-800',
}
/**
 * 状态中文名称映射
 */
export const STATUS_LABELS: Record<TaskStatus, string> = {
 pending: '待处理',
 planning: '规划中',
 plan_review: '方案审核',
 executing: '执行中',
 code_review: '代码审核',
 merged: '已合并',
 failed: '失败',
}
/**
 * Git 平台中文名称映射
 */
export const PLATFORM_LABELS: Record<GitPlatform, string> = {
 github: 'GitHub',
 gitlab: 'GitLab',
 gitea: 'Gitea',
 bitbucket: 'Bitbucket',
}
/**
 * 有效的状态转换映射
 */
export const VALID_TRANSITIONS: Record<TaskStatus, TaskStatus> = {
 pending: ['planning', 'failed'],
 planning: ['plan_review', 'failed'],
 plan_review: ['planning', 'executing'],
 executing: ['code_review', 'failed'],
 code_review: ['executing', 'merged'],
 failed: ['pending'],
 merged:,
}
