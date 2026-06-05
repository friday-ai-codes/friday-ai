import type { ComputedRef, Ref } from 'vue'
/**
 * useDebugDataEditor — 调试数据编辑状态管理
 *
 * 管理 JSON 编辑器的编辑状态：开始编辑、保存修改、重置、脏检测。
 * 配合 JsonEditor.vue 组件使用。
 */
import { computed, ref } from 'vue'

interface DebugDataEditorReturn {
  /** 编辑中的 JSON 字符串 */
  editedJson: Ref<string>
  /** 是否在编辑模式 */
  isEditing: Ref<boolean>
  /** 是否有未保存修改 */
  isDirty: ComputedRef<boolean>
  /** JSON 解析错误信息，无错误时为 null */
  jsonError: ComputedRef<string | null>
  /** 进入编辑模式，用 originalData 初始化 */
  startEdit: () => void
  /** 重置编辑内容为 originalData */
  resetEdit: () => void
  /** 退出编辑模式并重置 */
  cancelEdit: () => void
  /** 解析编辑后的数据，JSON 无效时返回 null */
  getEditedData: () => Record<string, any> | null
}

export function useDebugDataEditor(
  originalData: Ref<Record<string, any> | null>,
): DebugDataEditorReturn {
  const editedJson = ref('')
  const isEditing = ref(false)

  function serialize(data: Record<string, any> | null): string {
    return data ? JSON.stringify(data, null, 2) : '{}'
  }

  const isDirty = computed(() => {
    if (!isEditing.value)
      return false
    return editedJson.value !== serialize(originalData.value)
  })

  const jsonError = computed<string | null>(() => {
    if (!isEditing.value)
      return null
    try {
      JSON.parse(editedJson.value)
      return null
    }
    catch (e) {
      return (e as Error).message
    }
  })

  function startEdit(): void {
    editedJson.value = serialize(originalData.value)
    isEditing.value = true
  }

  function resetEdit(): void {
    editedJson.value = serialize(originalData.value)
  }

  function cancelEdit(): void {
    isEditing.value = false
    resetEdit()
  }

  function getEditedData(): Record<string, any> | null {
    try {
      return JSON.parse(editedJson.value) as Record<string, any>
    }
    catch {
      return null
    }
  }

  return {
    editedJson,
    isEditing,
    isDirty,
    jsonError,
    startEdit,
    resetEdit,
    cancelEdit,
    getEditedData,
  }
}
