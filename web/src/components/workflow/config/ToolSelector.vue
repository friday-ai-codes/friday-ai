<script setup lang="ts">
import { computed, ref } from 'vue'

import { Checkbox } from '~/components/ui/checkbox'
import { Input } from '~/components/ui/input'
import { Label } from '~/components/ui/label'

/**
 * ToolSelector - AI Agent 节点的轻量工具多选组件。
 * 复选框统一使用 shadcn Checkbox（容器负责点击，Checkbox 设 pointer-events-none 避免双触发）。
 */

interface Tool {
  name: string
  description: string
  category?: string
}

interface Props {
  tools: Tool[]
  modelValue: string[]
}

const props = defineProps<Props>()
const emit = defineEmits<{
  (e: 'update:modelValue', value: string[]): void
}>()

const searchQuery = ref('')

// Filter tools by search query (name or description)
const filteredTools = computed(() => {
  const query = searchQuery.value.toLowerCase().trim()
  if (!query)
    return props.tools
  return props.tools.filter(
    t =>
      t.name.toLowerCase().includes(query)
      || t.description.toLowerCase().includes(query),
  )
})

// Check if all tools are selected (empty array = all selected)
const allSelected = computed(
  () => props.modelValue.length === 0,
)

// Check if a specific tool is enabled
function isToolEnabled(toolName: string): boolean {
  if (props.modelValue.length === 0)
    return true
  return props.modelValue.includes(toolName)
}

// Toggle tool selection
function toggleTool(toolName: string) {
  const current = [...props.modelValue]

  if (allSelected.value) {
    // Currently all selected, user wants to disable one tool
    const newValue = props.tools
      .map(t => t.name)
      .filter(name => name !== toolName)
    emit('update:modelValue', newValue)
  }
  else {
    const idx = current.indexOf(toolName)
    if (idx >= 0) {
      current.splice(idx, 1)
      emit('update:modelValue', current)
    }
    else {
      current.push(toolName)
      if (current.length === props.tools.length) {
        emit('update:modelValue', [])
      }
      else {
        emit('update:modelValue', current)
      }
    }
  }
}

// Select all tools (emit empty array)
function selectAll() {
  emit('update:modelValue', [])
}
</script>

<template>
  <div class="space-y-2">
    <!-- Header with label and select all button -->
    <div class="flex items-center justify-between">
      <Label class="text-xs">启用的工具</Label>
      <button
        type="button"
        class="text-[10px] text-primary hover:underline"
        :class="{ 'text-muted-foreground': allSelected }"
        @click="selectAll"
      >
        {{ allSelected ? '已全选' : '全选' }}
      </button>
    </div>

    <!-- Search input -->
    <Input
      v-model="searchQuery"
      placeholder="搜索工具..."
      class="bg-background/50 h-7 text-xs"
    >
      <template #prefix>
        <span class="icon-[lucide--search] text-xs text-muted-foreground" />
      </template>
    </Input>

    <!-- Tools list with native scroll -->
    <div class="h-36 overflow-y-auto rounded-lg border border-border/50 bg-muted/30">
      <div class="p-1.5 space-y-0.5">
        <div
          v-for="tool in filteredTools"
          :key="tool.name"
          class="flex items-center gap-2 px-2 py-1.5 rounded cursor-pointer hover:bg-muted/50"
          @click="toggleTool(tool.name)"
        >
          <Checkbox
            :model-value="isToolEnabled(tool.name)"
            class="size-3.5 shrink-0 pointer-events-none"
          />
          <div class="flex-1 min-w-0">
            <div class="font-mono text-[11px] leading-tight">{{ tool.name }}</div>
            <div class="text-[10px] text-muted-foreground truncate leading-tight">
              {{ tool.description }}
            </div>
          </div>
        </div>

        <!-- Empty state -->
        <div
          v-if="filteredTools.length === 0"
          class="py-3 text-center text-[11px] text-muted-foreground"
        >
          未找到匹配的工具
        </div>
      </div>
    </div>

    <!-- Help text -->
    <p class="text-[10px] text-muted-foreground">
      留空表示启用所有工具
    </p>
  </div>
</template>
