<script setup lang="ts">
import type { BranchIndexRow } from '~/api/repositories'
import { computed, ref } from 'vue'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from '~/components/ui/command'
import { Input } from '~/components/ui/input'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '~/components/ui/popover'

const props = defineProps<{
  /** 分支列表（保持传入顺序展示；后端已按 HEAD > main/master > 活跃度 > 字典序排序） */
  branches: string[]
  /** 提供时列表行展示 stale / 相对索引时间 */
  indexRows?: BranchIndexRow[]
  /** 远端 HEAD 所在分支，展示 HEAD 徽标并置顶推荐 */
  headBranch?: string | null
  recommendedBranch?: string | null
  modelValue?: string | null
  disabled?: boolean
  placeholder?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string | null]
}>()

const rowByName = computed(() => {
  const map = new Map<string, BranchIndexRow>()
  for (const row of props.indexRows ?? []) {
    map.set(row.branch_name, row)
  }
  return map
})

const richMode = computed(() => (props.indexRows?.length ?? 0) > 0)

function formatIndexedAgo(iso: string | null): string {
  if (!iso)
    return '—'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then))
    return '—'
  const sec = Math.floor((Date.now() - then) / 1000)
  if (sec < 45)
    return '刚刚'
  const min = Math.floor(sec / 60)
  if (min < 60)
    return `${min} 分钟前`
  const h = Math.floor(min / 60)
  if (h < 24)
    return `${h} 小时前`
  const d = Math.floor(h / 24)
  if (d < 30)
    return `${d} 天前`
  return new Date(iso).toLocaleDateString('zh-CN')
}

const open = ref(false)

const selectedValue = computed({
  get: () => props.modelValue ?? null,
  set: (val: string | null) => emit('update:modelValue', val),
})

/** 推荐组：HEAD 分支优先，其次 recommendedBranch（去重） */
const recommendedBranches = computed(() => {
  const names: string[] = []
  if (props.headBranch && props.branches.includes(props.headBranch))
    names.push(props.headBranch)
  if (
    props.recommendedBranch
    && props.recommendedBranch !== props.headBranch
    && props.branches.includes(props.recommendedBranch)
  ) {
    names.push(props.recommendedBranch)
  }
  return names
})

/** 其余分支保持传入顺序（后端已排序），不再客户端字典序重排 */
const otherBranches = computed(() => {
  const picked = new Set(recommendedBranches.value)
  return props.branches.filter(b => !picked.has(b))
})

function selectBranch(branch: string) {
  selectedValue.value = branch
  open.value = false
}
</script>

<template>
  <!-- 无分支时降级为文本输入 -->
  <Input
    v-if="branches.length === 0"
    :model-value="modelValue ?? ''"
    :placeholder="placeholder ?? '输入默认分支名称，如 main'"
    class="h-10"
    :disabled="disabled"
    @update:model-value="emit('update:modelValue', ($event as string) || null)"
  />

  <!-- 有分支时使用 Combobox -->
  <Popover v-else v-model:open="open">
    <PopoverTrigger as-child>
      <Button
        variant="outline"
        role="combobox"
        :aria-expanded="open"
        :disabled="disabled"
        class="w-full h-10 justify-between font-normal"
      >
        <span class="flex items-center gap-2 min-w-0" :class="selectedValue ? 'text-foreground' : 'text-muted-foreground'">
          <span class="truncate font-mono text-sm">{{ selectedValue || (placeholder ?? '选择默认分支...') }}</span>
          <Badge
            v-if="selectedValue && selectedValue === headBranch"
            variant="outline"
            class="text-[10px] px-1.5 py-0 shrink-0 border-emerald-500/40 text-emerald-600 bg-emerald-500/5 font-semibold tracking-wide"
          >
            HEAD
          </Badge>
        </span>
        <span class="icon-[lucide--chevrons-up-down] ml-2 h-4 w-4 shrink-0 opacity-50" />
      </Button>
    </PopoverTrigger>
    <PopoverContent class="z-[10000] w-[--reka-popover-trigger-width] p-0" align="start">
      <Command>
        <CommandInput placeholder="搜索分支..." />
        <CommandList class="max-h-60">
          <CommandEmpty>未找到匹配的分支</CommandEmpty>

          <!-- 推荐分支组（HEAD 优先） -->
          <CommandGroup v-if="recommendedBranches.length > 0" heading="推荐">
            <CommandItem
              v-for="branch in recommendedBranches"
              :key="`rec-${branch}`"
              :value="branch"
              @select="selectBranch(branch)"
            >
              <span
                class="icon-[lucide--check] mr-2 h-4 w-4 shrink-0"
                :class="selectedValue === branch ? 'opacity-100' : 'opacity-0'"
              />
              <div class="flex flex-1 min-w-0 flex-col gap-0.5">
                <div class="flex items-center gap-2 min-w-0 flex-wrap">
                  <span class="font-mono text-sm truncate">{{ branch }}</span>
                  <Badge
                    v-if="branch === headBranch"
                    variant="outline"
                    class="text-[10px] px-1.5 py-0 shrink-0 border-emerald-500/40 text-emerald-600 bg-emerald-500/5 font-semibold tracking-wide"
                  >
                    HEAD
                  </Badge>
                  <Badge v-else variant="secondary" class="text-[10px] px-1.5 py-0 shrink-0">
                    推荐
                  </Badge>
                  <template v-if="richMode && rowByName.get(branch)">
                    <Badge
                      v-if="rowByName.get(branch)!.is_stale"
                      variant="destructive"
                      class="text-[10px] px-1.5 py-0 shrink-0"
                    >
                      stale
                    </Badge>
                    <span class="text-[10px] text-muted-foreground shrink-0 tabular-nums">
                      {{ formatIndexedAgo(rowByName.get(branch)!.last_indexed_at) }}
                    </span>
                  </template>
                </div>
              </div>
            </CommandItem>
          </CommandGroup>

          <CommandSeparator v-if="recommendedBranches.length > 0 && otherBranches.length > 0" />

          <!-- 所有分支组 -->
          <CommandGroup v-if="otherBranches.length > 0" heading="所有分支">
            <CommandItem
              v-for="branch in otherBranches"
              :key="branch"
              :value="branch"
              @select="selectBranch(branch)"
            >
              <span
                class="icon-[lucide--check] mr-2 h-4 w-4 shrink-0"
                :class="selectedValue === branch ? 'opacity-100' : 'opacity-0'"
              />
              <div class="flex flex-1 min-w-0 items-center gap-2">
                <span class="font-mono text-sm truncate">{{ branch }}</span>
                <template v-if="richMode && rowByName.get(branch)">
                  <Badge
                    v-if="rowByName.get(branch)!.is_stale"
                    variant="destructive"
                    class="text-[10px] px-1.5 py-0 shrink-0"
                  >
                    stale
                  </Badge>
                  <span class="text-[10px] text-muted-foreground ml-auto shrink-0 tabular-nums">
                    {{ formatIndexedAgo(rowByName.get(branch)!.last_indexed_at) }}
                  </span>
                </template>
              </div>
            </CommandItem>
          </CommandGroup>
        </CommandList>
      </Command>
    </PopoverContent>
  </Popover>
</template>
