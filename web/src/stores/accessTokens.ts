/**
 * Friday Access Token 管理 Pinia Store（Phase）
 *
 * 安全姿态：
 * - 仅缓存元数据 DTO（AccessTokenDto），明文 token 绝不写入任何 store state。
 * - createToken 把后端一次性返回的明文剥离后再入列表，明文仅作 action 返回值
 * 交给调用方的瞬态内存 ref；本模块绝不写浏览器持久存储，绝不打印明文到调试台。
 * - 刻意不复用 providerCredential store 的浏览器存储 persist/hydrate：
 * 元数据无需跨刷新缓存，且杜绝任何明文残留可能。
 */
import type {
 AccessTokenCreatePayload,
 AccessTokenDto,
} from '~/types/accessToken'
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { accessTokensApi } from '~/api/accessTokens'
export const useAccessTokenStore = defineStore('accessToken', => {
 // ============================================================================
 // State（仅元数据，无明文）
 // ============================================================================
 const tokens = ref<AccessTokenDto>
 const loading = ref(false)
 const lastError = ref<string | null>(null)
 // ============================================================================
 // Getters
 // ============================================================================
 const getTokenById = computed( => {
 return (id: string): AccessTokenDto | null =>
 tokens.value.find(t => t.id === id) ?? null
 })
 // ============================================================================
 // Actions（错误统一 re-throw，供 UI 层 useErrorHandler 承接）
 // ============================================================================
 /** 拉取当前用户的 Access Token 元数据列表。 */
 async function fetchTokens: Promise<AccessTokenDto> {
 loading.value = true
 lastError.value = null
 try {
 const list = await accessTokensApi.list
 tokens.value = list
 return list
 }
 catch (e) {
 lastError.value = e instanceof Error ? e.message: '加载 Access Token 失败'
 throw e
 }
 finally {
 loading.value = false
 }
 }
 /**
 * 创建 Access Token。
 *
 * 后端一次性返回的明文经此处「剥离」后仅元数据入列表头部；
 * 明文作为返回值交给调用方内存 ref，绝不写入 store state / 持久存储 / 调试台。
 */
 async function createToken(payload: AccessTokenCreatePayload): Promise<string> {
 loading.value = true
 lastError.value = null
 try {
 const result = await accessTokensApi.create(payload)
 // 剥离明文：meta 不含 token 字段，仅元数据入 store
 const { token, ...meta } = result
 tokens.value = [meta, ...tokens.value]
 return token
 }
 catch (e) {
 lastError.value = e instanceof Error ? e.message: '创建 Access Token 失败'
 throw e
 }
 finally {
 loading.value = false
 }
 }
 /** 软吊销指定 Token，用返回的元数据替换列表对应行。 */
 async function revokeToken(id: string): Promise<AccessTokenDto> {
 loading.value = true
 lastError.value = null
 try {
 const updated = await accessTokensApi.revoke(id)
 tokens.value = tokens.value.map(t => (t.id === id ? updated: t))
 return updated
 }
 catch (e) {
 lastError.value = e instanceof Error ? e.message: '吊销 Access Token 失败'
 throw e
 }
 finally {
 loading.value = false
 }
 }
 return {
 // state
 tokens,
 loading,
 lastError,
 // getters
 getTokenById,
 // actions
 fetchTokens,
 createToken,
 revokeToken,
 }
})
