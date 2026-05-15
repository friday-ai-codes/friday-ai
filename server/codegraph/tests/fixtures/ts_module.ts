import { Component, type Ref, ref } from 'vue'
import type { User } from './types'
import * as utils from './utils'
export interface ServiceConfig {
 apiBase: string
 timeout: number
}
export type StatusCode = 200 | 401 | 500
export class UserService {
 private base: string
 constructor(config: ServiceConfig) {
 this.base = config.apiBase
 }
 async fetchUser(id: string): Promise<User> {
 const resp = await utils.request(`${this.base}/users/${id}`)
 return resp.data
 }
}
export function createService(cfg: ServiceConfig): UserService {
 return new UserService(cfg)
}
export const buildUrl = (path: string): string => {
 return utils.join('/api', path)
}
export { User } from './types'
