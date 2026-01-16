import type {
 GitCredential,
 Repository,
 RepositoryCreate,
 RepositoryUpdate,
} from '~/types'
import { del, get, patch, post, upload } from './client'
export const repositoriesApi = {
 /**
 * 获取仓库列表
 */
 list: async => {
 return get<Repository>('/repositories/')
 },
 /**
 * 获取仓库详情
 */
 get: async (id: string) => {
 return get<Repository>(`/repositories/${id}`)
 },
 /**
 * 创建仓库（包含 Access Token 凭证）
 */
 create: async (data: RepositoryCreate) => {
 return post<Repository>('/repositories/', data)
 },
 /**
 * 更新仓库
 */
 update: async (id: string, data: RepositoryUpdate) => {
 return patch<Repository>(`/repositories/${id}`, data)
 },
 /**
 * 删除仓库
 */
 delete: async (id: string) => {
 await del(`/repositories/${id}`)
 },
 /**
 * 获取凭证信息（不含敏感数据）
 */
 getCredential: async (id: string) => {
 return get<GitCredential>(`/repositories/${id}/credential`)
 },
 /**
 * 设置/更新 Access Token
 */
 setAccessToken: async (id: string, data: FormData) => {
 return upload<GitCredential>(`/repositories/${id}/credential/access-token`, data)
 },
 /**
 * 删除凭证
 */
 deleteCredential: async (id: string) => {
 await del(`/repositories/${id}/credential`)
 },
}
