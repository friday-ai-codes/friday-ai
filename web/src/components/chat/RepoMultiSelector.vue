<script setup lang="ts">
/**
 * ：仓库多选器
 *
 * 用于 TechPlanCard 创建态内嵌 + FAN-04 追加态 Dialog。受控的多选交互：
 * 外部传 repositories / modelValue / disabledIds，组件本身不感知 conversation /
 * space / plan 概念，数据交互（拉仓库 / 提交）全部由调用方承担，单一职责。
 */
import type { RepoSelectableItem } from '~/types/chat'
import { computed, onMounted, ref } from 'vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Checkbox } from '~/components/ui/checkbox'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '~/components/ui/command'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '~/components/ui/tooltip'

const props = withDefaults(defineProps<{
  repositories: RepoSelectableItem[]
  modelValue: string[]
  disabledIds?: string[]
  recommendedIds?: string[]
  placeholder?: string
  maxSelectable?: number
  submitting?: boolean
}>(), {
  disabledIds: () => [],
  recommendedIds: () => [],
  placeholder: '搜索仓库...',
  maxSelectable: 20,
  submitting: false,
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: string[]): void
  (e: 'confirm', value: string[]): void
}>()

const search = ref('')

// 推荐预填：组件 mount 时合并 recommendedIds 到 modelValue（不覆盖外部已传值）
onMounted(() => {
  if (!props.recommendedIds || props.recommendedIds.length === 0)
    return
  const next = Array.from(new Set([...props.modelValue, ...props.recommendedIds]))
  if (next.length !== props.modelValue.length)
    emit('update:modelValue', next)
})

const filtered = computed(() => {
  const q = search.value.trim().toLowerCase()
  if (!q)
    return props.repositories
  return props.repositories.filter(r => r.name.toLowerCase().includes(q))
})

const selectedSet = computed(() => new Set(props.modelValue))
const disabledSet = computed(() => new Set(props.disabledIds))
const recommendedSet = computed(() => new Set(props.recommendedIds))

const atLimit = computed(() => props.modelValue.length >= props.maxSelectable)

function isDisabled(id: string): boolean {
  if (disabledSet.value.has(id))
    return true
  if (atLimit.value && !selectedSet.value.has(id))
    return true
  return false
}

function toggle(id: string) {
  if (isDisabled(id))
    return
  const next = selectedSet.value.has(id)
    ? props.modelValue.filter(x => x !== id)
    : [...props.modelValue, id]
  emit('update:modelValue', next)
}

function handleConfirm() {
  if (props.modelValue.length === 0 || props.submitting)
    return
  emit('confirm', [...props.modelValue])
}
</script>

<template>
  <div class="flex flex-col gap-3">
    <Command class="rounded-lg border border-border bg-background">
      <CommandInput v-model="search" :placeholder="placeholder" />
      <CommandList class="max-h-72">
        <CommandEmpty>未找到匹配的仓库</CommandEmpty>
        <CommandGroup>
          <CommandItem
            v-for="repo in filtered"
            :key="repo.id"
            :value="repo.id"
            :disabled="isDisabled(repo.id)"
            class="flex items-center gap-2 cursor-pointer"
            @select="toggle(repo.id)"
          >
            <Checkbox
              :model-value="selectedSet.has(repo.id)"
              :disabled="isDisabled(repo.id)"
              class="pointer-events-none"
            />
            <div class="flex-1 flex items-center gap-2 min-w-0">
              <span class="text-sm truncate">{{ repo.name }}</span>
              <span
                v-if="repo.description"
                class="text-xs text-muted-foreground truncate"
              >{{ repo.description }}</span>
            </div>
            <TooltipProvider v-if="recommendedSet.has(repo.id)">
              <Tooltip>
                <TooltipTrigger as-child>
                  <span class="icon-[lucide--sparkles] text-primary text-sm" />
                </TooltipTrigger>
                <TooltipContent>AI 推荐</TooltipContent>
              </Tooltip>
            </TooltipProvider>
            <TooltipProvider v-if="disabledSet.has(repo.id)">
              <Tooltip>
                <TooltipTrigger as-child>
                  <Badge variant="outline" class="text-xs">
                    已加入
                  </Badge>
                </TooltipTrigger>
                <TooltipContent>该仓库已有进行中的编码会话</TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </CommandItem>
        </CommandGroup>
      </CommandList>
    </Command>

    <div class="flex items-center justify-between text-sm">
      <span class="text-muted-foreground">
        已选
        <span class="text-foreground font-medium">{{ modelValue.length }}</span>
        / {{ maxSelectable }}
      </span>
      <Button
        :disabled="modelValue.length === 0 || submitting"
        @click="handleConfirm"
      >
        <span v-if="submitting" class="icon-[lucide--loader-2] animate-spin mr-2" />
        确认编码
      </Button>
    </div>

    <p v-if="atLimit" class="text-xs text-amber-500">
      已达上限 {{ maxSelectable }} 个仓库
    </p>
  </div>
</template>
