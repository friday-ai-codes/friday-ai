/**
 * Repositories Store
 * 管理仓库列表和仓库相关操作
 */

import type { GitCredential, Repository, RepositoryCreate, RepositoryUpdate } from '~/types'
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { repositoriesApi } from '~/api'

export const useRepositoriesStore = defineStore('repositories', () => {
  // ============================================================================
  // State
  // ============================================================================

  const repositories = ref<Repository[]>([])
  const currentRepository = ref<Repository | null>(null)
  const currentCredential = ref<GitCredential | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  // ============================================================================
  // Getters
  // ============================================================================

  const repositoryById = computed(() => {
    return (id: string) => repositories.value.find(r => r.id === id)
  })

  const repositoryCount = computed(() => repositories.value.length)

  // ============================================================================
  // Actions
  // ============================================================================

  /**
   * 获取仓库列表
   */
  async function fetchRepositories() {
    loading.value = true
    error.value = null
    try {
      repositories.value = await repositoriesApi.list()
    }
    catch (e) {
      error.value = e instanceof Error ? e.message : '获取仓库列表失败'
      throw e
    }
    finally {
      loading.value = false
    }
  }

  /**
   * 获取单个仓库详情
   */
  async function fetchRepository(id: string) {
    loading.value = true
    error.value = null
    try {
      currentRepository.value = await repositoriesApi.get(id)
      return currentRepository.value
    }
    catch (e) {
      error.value = e instanceof Error ? e.message : '获取仓库详情失败'
      throw e
    }
    finally {
      loading.value = false
    }
  }

  /**
   * 创建仓库
   */
  async function createRepository(data: RepositoryCreate) {
    loading.value = true
    error.value = null
    try {
      const newRepository = await repositoriesApi.create(data)
      repositories.value.unshift(newRepository)
      return newRepository
    }
    catch (e) {
      error.value = e instanceof Error ? e.message : '创建仓库失败'
      throw e
    }
    finally {
      loading.value = false
    }
  }

  /**
   * 更新仓库
   */
  async function updateRepository(id: string, data: RepositoryUpdate) {
    loading.value = true
    error.value = null
    try {
      const updatedRepository = await repositoriesApi.update(id, data)
      // 更新列表中的仓库
      const index = repositories.value.findIndex(r => r.id === id)
      if (index !== -1) {
        repositories.value[index] = updatedRepository
      }
      // 更新当前仓库
      if (currentRepository.value?.id === id) {
        currentRepository.value = updatedRepository
      }
      return updatedRepository
    }
    catch (e) {
      error.value = e instanceof Error ? e.message : '更新仓库失败'
      throw e
    }
    finally {
      loading.value = false
    }
  }

  /**
   * 删除仓库
   */
  async function deleteRepository(id: string) {
    loading.value = true
    error.value = null
    try {
      await repositoriesApi.delete(id)
      // 从列表中移除
      repositories.value = repositories.value.filter(r => r.id !== id)
      // 清空当前仓库
      if (currentRepository.value?.id === id) {
        currentRepository.value = null
      }
    }
    catch (e) {
      error.value = e instanceof Error ? e.message : '删除仓库失败'
      throw e
    }
    finally {
      loading.value = false
    }
  }

  // ============================================================================
  // 凭证管理
  // ============================================================================

  /**
   * 获取仓库凭证
   */
  async function fetchCredential(id: string) {
    try {
      currentCredential.value = await repositoriesApi.getCredential(id)
      return currentCredential.value
    }
    catch {
      // 404 表示没有凭证，不是错误
      currentCredential.value = null
      return null
    }
  }

  /**
   * 设置/更新 Access Token
   */
  async function setAccessToken(id: string, data: { token: string, git_user_name?: string, git_user_email?: string }) {
    loading.value = true
    error.value = null
    try {
      currentCredential.value = await repositoriesApi.setAccessToken(id, data)
      // 更新仓库的 has_credential 状态
      const repository = repositories.value.find(r => r.id === id)
      if (repository) {
        repository.has_credential = true
      }
      if (currentRepository.value?.id === id) {
        currentRepository.value.has_credential = true
      }
      return currentCredential.value
    }
    catch (e) {
      error.value = e instanceof Error ? e.message : '设置 Access Token 失败'
      throw e
    }
    finally {
      loading.value = false
    }
  }

  /**
   * 删除凭证
   */
  async function deleteCredential(id: string) {
    loading.value = true
    error.value = null
    try {
      await repositoriesApi.deleteCredential(id)
      currentCredential.value = null
      // 更新仓库的 has_credential 状态
      const repository = repositories.value.find(r => r.id === id)
      if (repository) {
        repository.has_credential = false
      }
      if (currentRepository.value?.id === id) {
        currentRepository.value.has_credential = false
      }
    }
    catch (e) {
      error.value = e instanceof Error ? e.message : '删除凭证失败'
      throw e
    }
    finally {
      loading.value = false
    }
  }

  /**
   * 清空当前仓库
   */
  function clearCurrent() {
    currentRepository.value = null
    currentCredential.value = null
  }

  return {
    // State
    repositories,
    currentRepository,
    currentCredential,
    loading,
    error,
    // Getters
    repositoryById,
    repositoryCount,
    // Actions
    fetchRepositories,
    fetchRepository,
    createRepository,
    updateRepository,
    deleteRepository,
    fetchCredential,
    setAccessToken,
    deleteCredential,
    clearCurrent,
  }
})
