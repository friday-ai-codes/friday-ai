import type {
 GitCredential,
 Repository,
 RepositoryCreate,
 RepositoryUpdate,
} from '~/types'
import client from './client'
export const repositoriesApi = {
 /**
 * List all repositories
 */
 list: async => {
 return client.get<Repository>('/repositories')
 },
 /**
 * Get repository by ID
 */
 get: async (id: string) => {
 return client.get<Repository>(`/repositories/${id}`)
 },
 /**
 * Create new repository
 */
 create: async (data: RepositoryCreate) => {
 return client.post<Repository>('/repositories', data)
 },
 /**
 * Update repository
 */
 update: async (id: string, data: RepositoryUpdate) => {
 return client.patch<Repository>(`/repositories/${id}`, data)
 },
 /**
 * Delete repository
 */
 delete: async (id: string) => {
 await client.del(`/repositories/${id}`)
 },
 /**
 * Get credential
 */
 getCredential: async (id: string) => {
 return client.get<GitCredential>(`/repositories/${id}/credentials`)
 },
 /**
 * Upload SSH key
 */
 uploadSshKey: async (id: string, data: FormData) => {
 return client.upload<GitCredential>(`/repositories/${id}/credentials/ssh-key`, data)
 },
 /**
 * Set access token
 */
 setAccessToken: async (id: string, data: FormData) => {
 return client.upload<GitCredential>(`/repositories/${id}/credentials/access-token`, data)
 },
 /**
 * Delete credential
 */
 deleteCredential: async (id: string) => {
 await client.del(`/repositories/${id}/credentials`)
 },
}
