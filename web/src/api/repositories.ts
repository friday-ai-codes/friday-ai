import type {
 GitCredential,
 Repository,
 RepositoryCreate,
 RepositoryUpdate,
} from '~/types'
import { del, get, patch, post, upload } from './client'
export const repositoriesApi = {
 /**
 * List all repositories
 */
 list: async => {
 return get<Repository>('/repositories/')
 },
 /**
 * Get repository by ID
 */
 get: async (id: string) => {
 return get<Repository>(`/repositories/${id}`)
 },
 /**
 * Create new repository
 */
 create: async (data: RepositoryCreate) => {
 return post<Repository>('/repositories/', data)
 },
 /**
 * Update repository
 */
 update: async (id: string, data: RepositoryUpdate) => {
 return patch<Repository>(`/repositories/${id}`, data)
 },
 /**
 * Delete repository
 */
 delete: async (id: string) => {
 await del(`/repositories/${id}`)
 },
 /**
 * Get credential
 */
 getCredential: async (id: string) => {
 return get<GitCredential>(`/repositories/${id}/credential`)
 },
 /**
 * Upload SSH key
 */
 uploadSshKey: async (id: string, data: FormData) => {
 return upload<GitCredential>(`/repositories/${id}/credential/ssh-key`, data)
 },
 /**
 * Set access token
 */
 setAccessToken: async (id: string, data: FormData) => {
 return upload<GitCredential>(`/repositories/${id}/credential/access-token`, data)
 },
 /**
 * Delete credential
 */
 deleteCredential: async (id: string) => {
 await del(`/repositories/${id}/credential`)
 },
}
