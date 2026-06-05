import type { ComputedRef, Ref } from 'vue'
import type { DesignTimeVariable } from '~/composables/useDesignTimeVariables'

import { ref } from 'vue'
import { areTypesCompatible } from '~/composables/useSchemaValidation'

interface OverrideField {
  key: string
  label: string
  currentValue: string
  newValue: string
}

export function useAutoFill(
  nodeTypeInfo: ComputedRef<{ inputs?: Array<{ name: string, label?: string, type: string }>, [key: string]: any } | null | undefined>,
  designTimeVariables: Ref<DesignTimeVariable[]>,
  nodeConfig: Ref<Record<string, any>>,
) {
  const overrideDialogOpen = ref(false)
  const fieldsToOverride = ref<OverrideField[]>([])
  const pendingFills = ref<Record<string, string>>({})

  // 计算自动填充：按名称优先、类型回退
  function computeAutoFills(): { fills: Record<string, string>, overrides: OverrideField[] } {
    const fills: Record<string, string> = {}
    const overrides: OverrideField[] = []

    const inputs = nodeTypeInfo.value?.inputs || []
    const vars = designTimeVariables.value

    for (const input of inputs) {
      // 名称优先匹配（不区分大小写）
      let match = vars.find(v =>
        v.key.toLowerCase() === input.name.toLowerCase(),
      )

      // 类型回退匹配
      if (!match) {
        match = vars.find(v => areTypesCompatible(v.type, input.type))
      }

      if (match) {
        const varPath = `{{${match.path}}}`
        const currentVal = nodeConfig.value[input.name]

        if (currentVal && currentVal !== varPath) {
          overrides.push({
            key: input.name,
            label: input.label || input.name,
            currentValue: String(currentVal),
            newValue: varPath,
          })
        }
        else if (!currentVal) {
          fills[input.name] = varPath
        }
      }
    }

    return { fills, overrides }
  }

  function handleAutoFill() {
    const { fills, overrides } = computeAutoFills()

    if (Object.keys(fills).length === 0 && overrides.length === 0) {
      return
    }

    // 直接填充空字段
    for (const [key, value] of Object.entries(fills)) {
      nodeConfig.value[key] = value
    }

    // 有冲突字段时弹出确认对话框
    if (overrides.length > 0) {
      fieldsToOverride.value = overrides
      pendingFills.value = Object.fromEntries(
        overrides.map(o => [o.key, o.newValue]),
      )
      overrideDialogOpen.value = true
    }
  }

  function handleOverrideConfirm(selectedKeys: string[]) {
    for (const key of selectedKeys) {
      if (pendingFills.value[key]) {
        nodeConfig.value[key] = pendingFills.value[key]
      }
    }
    pendingFills.value = {}
  }

  return {
    overrideDialogOpen,
    fieldsToOverride,
    handleAutoFill,
    handleOverrideConfirm,
  }
}
