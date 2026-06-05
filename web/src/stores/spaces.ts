/**
 * Spaces Store
 * 管理空间列表和空间相关操作
 */

import type { FeishuConfig, Space, SpaceCreate, SpaceUpdate } from '~/types'
import { spacesApi } from '~/api'

export const useSpacesStore = defineStore('spaces', () => {
  // ============================================================================
  // State
  // ============================================================================

  const spaces = ref<Space[]>([])
  const currentSpace = ref<Space | null>(null)
  const currentFeishuConfig = ref<FeishuConfig | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  // ============================================================================
  // Getters
  // ============================================================================

  const spaceById = computed(() => {
    return (id: string) => spaces.value.find(p => p.id === id)
  })

  const spaceCount = computed(() => spaces.value.length)

  // ============================================================================
  // Actions
  // ============================================================================

  /**
   * 获取空间列表
   */
  async function fetchSpaces() {
    loading.value = true
    error.value = null
    try {
      spaces.value = await spacesApi.list()
    }
    catch (e) {
      error.value = e instanceof Error ? e.message : '获取空间列表失败'
      throw e
    }
    finally {
      loading.value = false
    }
  }

  /**
   * 获取单个空间详情
   */
  async function fetchSpace(spaceId: string) {
    loading.value = true
    error.value = null
    try {
      currentSpace.value = await spacesApi.get(spaceId)
      return currentSpace.value
    }
    catch (e) {
      error.value = e instanceof Error ? e.message : '获取空间详情失败'
      throw e
    }
    finally {
      loading.value = false
    }
  }

  /**
   * 创建空间
   */
  async function createSpace(data: SpaceCreate) {
    loading.value = true
    error.value = null
    try {
      const newSpace = await spacesApi.create(data)
      spaces.value.unshift(newSpace)
      return newSpace
    }
    catch (e) {
      error.value = e instanceof Error ? e.message : '创建空间失败'
      throw e
    }
    finally {
      loading.value = false
    }
  }

  /**
   * 更新空间
   */
  async function updateSpace(spaceId: string, data: SpaceUpdate) {
    loading.value = true
    error.value = null
    try {
      const updatedSpace = await spacesApi.update(spaceId, data)
      // 更新列表中的空间
      const index = spaces.value.findIndex(p => p.id === spaceId)
      if (index !== -1) {
        spaces.value[index] = updatedSpace
      }
      // 更新当前空间
      if (currentSpace.value?.id === spaceId) {
        currentSpace.value = updatedSpace
      }
      return updatedSpace
    }
    catch (e) {
      error.value = e instanceof Error ? e.message : '更新空间失败'
      throw e
    }
    finally {
      loading.value = false
    }
  }

  /**
   * 删除空间
   */
  async function deleteSpace(spaceId: string) {
    loading.value = true
    error.value = null
    try {
      await spacesApi.delete(spaceId)
      // 从列表中移除
      spaces.value = spaces.value.filter(p => p.id !== spaceId)
      // 清空当前空间
      if (currentSpace.value?.id === spaceId) {
        currentSpace.value = null
      }
    }
    catch (e) {
      error.value = e instanceof Error ? e.message : '删除空间失败'
      throw e
    }
    finally {
      loading.value = false
    }
  }

  // ============================================================================
  // 仓库关联管理
  // ============================================================================

  /**
   * 关联仓库
   */
  async function addRepository(spaceId: string, repositoryId: string) {
    loading.value = true
    error.value = null
    try {
      await spacesApi.addRepository(spaceId, repositoryId)
      // 刷新空间详情以获取最新关联的仓库列表
      if (currentSpace.value?.id === spaceId) {
        await fetchSpace(spaceId)
      }
    }
    catch (e) {
      error.value = e instanceof Error ? e.message : '关联仓库失败'
      throw e
    }
    finally {
      loading.value = false
    }
  }

  /**
   * 解除关联仓库
   */
  async function removeRepository(spaceId: string, repositoryId: string) {
    loading.value = true
    error.value = null
    try {
      await spacesApi.removeRepository(spaceId, repositoryId)
      // 刷新空间详情以获取最新关联的仓库列表
      if (currentSpace.value?.id === spaceId) {
        await fetchSpace(spaceId)
      }
    }
    catch (e) {
      error.value = e instanceof Error ? e.message : '解除关联仓库失败'
      throw e
    }
    finally {
      loading.value = false
    }
  }

  /**
   * 清空当前空间
   */
  function clearCurrent() {
    currentSpace.value = null
    currentFeishuConfig.value = null
  }

  // ============================================================================
  // 飞书配置管理
  // ============================================================================

  /**
   * 获取飞书配置
   */
  async function fetchFeishuConfig(spaceId: string) {
    try {
      currentFeishuConfig.value = await spacesApi.getFeishuConfig(spaceId)
      return currentFeishuConfig.value
    }
    catch {
      // 404 表示没有配置，不是错误
      currentFeishuConfig.value = null
      return null
    }
  }

  return {
    // State
    spaces,
    currentSpace,
    currentFeishuConfig,
    loading,
    error,
    // Getters
    spaceById,
    spaceCount,
    // Actions
    fetchSpaces,
    fetchSpace,
    createSpace,
    updateSpace,
    deleteSpace,
    addRepository,
    removeRepository,
    fetchFeishuConfig,
    clearCurrent,
  }
})
