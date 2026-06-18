<script setup lang="ts">
/**
 * 通用「分面多选」筛选器（搜索 + 多选 + 计数徽标）。
 *
 * 触发按钮展示分面名 + 已选数量；点开为 Popover 内的可搜索列表（输入框模糊过滤选项
 * → Checkbox 精准多选，可多项组合）。受控组件，状态由调用方持有（便于 URL 持久化）。
 *
 * 不使用 reka Command 的内置过滤（其按 item value=key/uuid 匹配，与中文 label 模糊搜索
 * 冲突），改为自带输入框 + 本地 `filtered`，按 label 模糊匹配，行为确定。
 */
import { computed, ref } from 'vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Checkbox } from '~/components/ui/checkbox'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '~/components/ui/popover'

export interface FacetOption {
  value: string
  label: string
  /** 完整 iconify 类名（如 'icon-[lucide--file-text]'），可选 */
  icon?: string
  /** 选项命中数量，可选（显示在右侧弱化提示） */
  count?: number
}

const props = withDefaults(defineProps<{
  /** 分面标签，如「状态」「用户」 */
  label: string
  options: FacetOption[]
  /** 触发按钮图标（完整 iconify 类名） */
  icon?: string
  searchPlaceholder?: string
  emptyText?: string
  /** 选项较少时隐藏搜索框 */
  searchable?: boolean
}>(), {
  searchPlaceholder: '搜索…',
  emptyText: '无匹配项',
  searchable: true,
})

const selected = defineModel<string[]>({ default: () => [] })

const open = ref(false)
const search = ref('')

const selectedSet = computed(() => new Set(selected.value))

const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q)
    return props.options
  return props.options.filter(o =>
    o.label.toLowerCase().includes(q) || o.value.toLowerCase().includes(q),
  )
})

function toggle(value: string) {
  selected.value = selectedSet.value.has(value)
    ? selected.value.filter(v => v !== value)
    : [...selected.value, value]
}

function clear() {
  selected.value = []
  search.value = ''
}
</script>

<template>
  <Popover v-model:open="open">
    <PopoverTrigger as-child>
      <Button
        variant="outline"
        size="sm"
        class="h-9 gap-1.5 rounded-lg border-dashed bg-background/90"
        :class="selected.length > 0 ? 'border-primary/40 border-solid!' : ''"
      >
        <span v-if="icon" class="text-sm" :class="icon" />
        {{ label }}
        <template v-if="selected.length > 0">
          <span class="mx-0.5 h-3.5 w-px bg-border" />
          <Badge variant="secondary" class="rounded px-1.5 py-0 text-[0.7rem] font-semibold tabular-nums">
            {{ selected.length }}
          </Badge>
        </template>
        <span class="icon-[lucide--chevron-down] text-xs text-muted-foreground/70" />
      </Button>
    </PopoverTrigger>
    <PopoverContent align="start" class="w-60 p-0">
      <div v-if="searchable" class="flex items-center gap-2 border-b border-border/60 px-3">
        <span class="icon-[lucide--search] text-sm text-muted-foreground/60 shrink-0" />
        <input
          v-model="search"
          :placeholder="searchPlaceholder"
          class="h-9 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground/60"
        >
      </div>

      <div class="max-h-64 overflow-y-auto p-1">
        <p v-if="filtered.length === 0" class="px-2 py-6 text-center text-sm text-muted-foreground">
          {{ emptyText }}
        </p>
        <button
          v-for="opt in filtered"
          :key="opt.value"
          type="button"
          class="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-accent"
          @click="toggle(opt.value)"
        >
          <Checkbox :model-value="selectedSet.has(opt.value)" class="pointer-events-none" />
          <span v-if="opt.icon" class="text-sm shrink-0" :class="opt.icon" />
          <span class="flex-1 truncate text-sm">{{ opt.label }}</span>
          <span
            v-if="opt.count != null"
            class="shrink-0 text-xs text-muted-foreground/60 tabular-nums"
          >{{ opt.count }}</span>
        </button>
      </div>

      <div v-if="selected.length > 0" class="border-t border-border/50 p-1">
        <button
          type="button"
          class="w-full rounded-md px-2 py-1.5 text-center text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          @click="clear"
        >
          清除筛选（{{ selected.length }}）
        </button>
      </div>
    </PopoverContent>
  </Popover>
</template>
