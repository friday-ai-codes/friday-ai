/**
 * API 服务统一导出
 */

export { default as announcementsApi } from './announcements'
export * from './announcements'

export { default as authApi } from './auth'

export * from './auth'
// 技术蓝图（Phase 115）：五个只读供数端点 + 人审六端点 + 确认门八端点。
// ⚠️ 插在 auth 与 chat 之间而非文件末尾：`perfectionist/sort-exports` 会把末尾追加判成
// 乱序，而对本文件跑 `eslint --fix` 会**重排既有分组**（实测），违反 CREATE-ONLY 的纯追加
// 纪律 ⇒ 按字典序落位，既零删除行也不新增 lint 问题。
export { default as blueprintsApi } from './blueprints'
export * from './blueprints'
export { default as chatApi } from './chat'

export * from './chat'
export { ApiError } from './client'

export * from './dashboard'
export { default as feedbackApi } from './feedback'

export * from './feedback'
export { default as gitInstanceCredentialsApi } from './gitInstanceCredentials'

export * from './gitInstanceCredentials'
export * from './ingest'

export { default as knowledgeApi } from './knowledge'

export * from './knowledge'

export { default as logsApi } from './logs'
export * from './logs'

export { default as notificationsApi } from './notifications'
export * from './notifications'

export { default as artifactsApi } from './artifacts'
export * from './artifacts'

export { default as artifactTypesApi } from './artifactTypes'
export * from './artifactTypes'

export { default as mergeRequestsApi } from './mergeRequests'
export * from './mergeRequests'

export { default as projectMemoryApi } from './projectMemory'
export * from './projectMemory'

export { default as projectsApi } from './projects'
export * from './projects'

export { default as projectWorkspaceApi } from './projectWorkspace'
export * from './projectWorkspace'

export { default as providerCredentialsApi } from './providerCredentials'
export * from './providerCredentials'

export * from './repositories'

// 引用二级预览用的既有 REST（chunk-at 反查 / 仓库章程），前端此前无封装。
export { default as repositoryChunksApi } from './repositoryChunks'
export * from './repositoryChunks'

export { default as repoTreeApi } from './repoTree'
export * from './repoTree'

export { default as runnersApi } from './runners'
export * from './runners'

export { default as settingsApi } from './settings'

export * from './settings'
export { default as setupApi } from './setup'

export * from './setup'
export { default as spacesApi } from './spaces'

// 重新导出所有具体方法，便于按需引入
export * from './spaces'
export * from './specs'

export { default as workflowApi } from './workflow'
export * from './workflow'
