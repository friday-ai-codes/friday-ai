<script setup lang="ts">
import type { ImportEdgeRow } from '~/api/codegraph'
import { computed, onMounted, ref } from 'vue'
import { getImports } from '~/api/codegraph'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '~/components/ui/select'

const props = defineProps<{
  repositoryId: string
}>()

const PAGE_SIZE_OPTIONS = [50, 100, 200] as const
const imports = ref<ImportEdgeRow[]>([])
const total = ref(0)
const offset = ref(0)
const limit = ref<number>(50)
const loading = ref(false)
const error = ref<string | null>(null)

interface ImportGroup {
  sourceFile: string
  items: ImportEdgeRow[]
}

const grouped = computed<ImportGroup[]>(() => {
  const map = new Map<string, ImportEdgeRow[]>()
  for (const item of imports.value) {
    const list = map.get(item.source_file) ?? []
    list.push(item)
    map.set(item.source_file, list)
  }
  return Array.from(map.entries()).map(([sourceFile, items]) => ({ sourceFile, items }))
})

async function fetchImports() {
  loading.value = true
  error.value = null
  try {
    const res = await getImports(props.repositoryId, {
      limit: limit.value,
      offset: offset.value,
    })
    imports.value = res.results
    total.value = res.count
  }
  catch (e: unknown) {
    error.value = e instanceof Error ? e.message : '加载失败'
  }
  finally {
    loading.value = false
  }
}

function prevPage() {
  if (offset.value >= limit.value) {
    offset.value -= limit.value
    fetchImports()
  }
}

function nextPage() {
  if (offset.value + limit.value < total.value) {
    offset.value += limit.value
    fetchImports()
  }
}

function handlePageSizeChange(value: unknown) {
  const next = Number(value)
  if (!Number.isFinite(next) || next <= 0)
    return
  limit.value = next
  offset.value = 0
  fetchImports()
}

const currentPage = computed(() => Math.floor(offset.value / limit.value) + 1)
const totalPages = computed(() => Math.ceil(total.value / limit.value))
const rangeStart = computed(() => total.value === 0 ? 0 : offset.value + 1)
const rangeEnd = computed(() => Math.min(offset.value + imports.value.length, total.value))

onMounted(fetchImports)
</script>

<template>
  <div class="space-y-3">
    <!-- 错误提示 -->
    <p v-if="error" class="text-xs text-destructive">
      加载导入关系失败：{{ error }}。请稍后重试。
    </p>

    <!-- 加载骨架 -->
    <template v-if="loading">
      <div v-for="i in 6" :key="i" class="flex items-center justify-between gap-2 px-3 py-2 rounded-lg">
        <div class="h-4 bg-muted/60 rounded w-40 animate-pulse" />
        <div class="h-4 bg-muted/60 rounded w-24 animate-pulse" />
      </div>
    </template>

    <!-- 空状态 -->
    <div
      v-else-if="imports.length === 0"
      class="flex flex-col items-center justify-center py-8 text-center"
    >
      <span class="icon-[lucide--package-open] text-3xl text-muted-foreground mb-3" />
      <p class="text-base font-semibold">
        当前仓库暂无导入关系数据
      </p>
      <p class="text-sm text-muted-foreground mt-1">
        请先完成代码索引。
      </p>
    </div>

    <!-- 分组列表 -->
    <div v-else class="space-y-4">
      <div v-for="group in grouped" :key="group.sourceFile">
        <!-- 分组标题 -->
        <div class="import-group-header flex items-center gap-1.5 mb-1.5 px-1">
          <span class="icon-[lucide--file-code] text-xs text-muted-foreground shrink-0" />
          <span class="font-mono text-xs text-muted-foreground truncate">{{ group.sourceFile }}</span>
        </div>

        <!-- 分组内条目 -->
        <div class="pl-4 space-y-0.5">
          <div
            v-for="item in group.items"
            :key="item.id"
            class="flex items-center justify-between gap-2 px-3 py-2 rounded-lg hover:bg-muted/30 transition-colors"
          >
            <div class="flex items-center gap-2 min-w-0">
              <span class="icon-[lucide--arrow-right] text-xs text-muted-foreground shrink-0" />
              <Badge variant="secondary" class="font-mono text-xs h-5 px-1.5 shrink-0">
                {{ item.target_module }}
              </Badge>
              <span
                v-if="item.imported_names.length > 0"
                class="text-xs text-muted-foreground truncate"
              >
                {{ item.imported_names.join(', ') }}
              </span>
            </div>
            <Badge v-if="item.is_relative" variant="outline" class="text-xs h-4 px-1 shrink-0">
              相对
            </Badge>
          </div>
        </div>
      </div>
    </div>

    <!-- 服务端分页 -->
    <div
      v-if="total > 0"
      class="flex items-center justify-between px-1 pt-2 gap-3 flex-wrap"
    >
      <div class="flex items-center gap-3 text-xs text-muted-foreground">
        <span>显示 {{ rangeStart }} 至 {{ rangeEnd }} 共 {{ total }} 条</span>
        <span>第 {{ currentPage }} / {{ totalPages }} 页</span>
        <div class="flex items-center gap-2">
          <span>每页:</span>
          <Select
            :model-value="String(limit)"
            @update:model-value="handlePageSizeChange"
          >
            <SelectTrigger class="h-7 w-[70px] text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem
                v-for="size in PAGE_SIZE_OPTIONS"
                :key="size"
                :value="String(size)"
              >
                {{ size }}
              </SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>
      <div class="flex gap-2">
        <Button
          variant="outline"
          size="sm"
          class="h-7 text-xs"
          :disabled="currentPage <= 1"
          @click="prevPage"
        >
          上一页
        </Button>
        <Button
          variant="outline"
          size="sm"
          class="h-7 text-xs"
          :disabled="currentPage >= totalPages"
          @click="nextPage"
        >
          下一页
        </Button>
      </div>
    </div>
  </div>
</template>
