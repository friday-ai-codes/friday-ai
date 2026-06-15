/**
 * 实例级 Git 凭证 API 客户端（Plan 26-04，REPO-01）。
 *
 * 对应后端 server/repositories/views.py::GitInstanceCredentialsView /
 * GitInstanceCredentialDetailView（IsSuperUser，CRUD 5 动作）。
 *
 * 安全契约（D-04 / 威胁 T-26-13/15）：读类型 **无任何明文 token 字段**，仅以
 * `has_token` 布尔表示是否已配置；`access_token` 仅出现在写入 payload，
 * 提交后绝不回显。`client.ts` 自动拼 `/api` 前缀且在末尾补 `/`，本模块统一写
 * 相对路径 `/repositories/git-instance-credentials/...`。
 */

import { del, get, patch, post } from './client'

/** 后端支持的 Git 平台（与 repositories.models.GitPlatform 对齐）。 */
export type GitInstanceProvider = 'github' | 'gitlab' | 'gitea' | 'bitbucket'

/** 实例凭证只读形状（与后端 GitInstanceCredentialSerializer 对齐，**无 token 字段**）。 */
export interface GitInstanceCredential {
  id: string
  host: string
  provider: GitInstanceProvider
  label: string
  /** 是否已配置 token（绝不回显明文）。 */
  has_token: boolean
  created_at: string
  updated_at: string
}

/** 创建 payload：host + access_token 必填。 */
export interface CreateGitInstanceCredentialPayload {
  host: string
  access_token: string
  provider?: GitInstanceProvider
  label?: string
}

/** 更新 payload：均可选；access_token 留空（省略）表示不修改既有 token。 */
export interface UpdateGitInstanceCredentialPayload {
  host?: string
  provider?: GitInstanceProvider
  label?: string
  access_token?: string
}

export const gitInstanceCredentialsApi = {
  /** GET 列表（按 host 排序）。 */
  list: async (): Promise<GitInstanceCredential[]> => {
    return get<GitInstanceCredential[]>('/repositories/git-instance-credentials/')
  },

  /** POST 新建实例凭证。 */
  create: async (
    payload: CreateGitInstanceCredentialPayload,
  ): Promise<GitInstanceCredential> => {
    return post<GitInstanceCredential>('/repositories/git-instance-credentials/', payload)
  },

  /** PATCH 更新实例凭证（access_token 省略/留空 = 不改 token）。 */
  update: async (
    id: string,
    payload: UpdateGitInstanceCredentialPayload,
  ): Promise<GitInstanceCredential> => {
    return patch<GitInstanceCredential>(
      `/repositories/git-instance-credentials/${id}/`,
      payload,
    )
  },

  /** DELETE 删除实例凭证。 */
  remove: async (id: string): Promise<void> => {
    await del(`/repositories/git-instance-credentials/${id}/`)
  },
}

export default gitInstanceCredentialsApi
