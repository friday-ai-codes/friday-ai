<script setup lang="ts">
/**
 * GraphSearchModal — 仓库级 GraphRAG 关联搜索弹窗
 *
 * 消费 296-02 端点 `POST /repositories/{id}/graph-search/`：输入查询 → 展示 L3
 * 命中片段列表 + 复用 v24.0 GraphRAGDiffusionTab（Vue Flow + dagre）渲染 hop1/hop2
 * 二跳扩散图。**0 新依赖**（@vue-flow/* + dagre 复用 catalog 已存在）。
 *
 * branch 由页面 selectedBranch 经 RepositoryKnowledgeHub → 本组件 prop 透传，调
 * graphSearch 时带 branch；切分支后搜索作用于对应分支（后端分支作用域过滤）。
 */
import type { GraphSearchResponse } from '~/api/repositories'
import type { SourceChunk } from '~/composables/useDiffusionGraph'
import { ref } from 'vue'
import { graphSearch } from '~/api/repositories'
import GraphRAGDiffusionTab from '~/components/codegraph/GraphRAGDiffusionTab.vue'
import { Button } from '~/components/ui/button'
import {
  Dialog,
  DialogDescription,
  DialogHeader,
  DialogScrollContent,
  DialogTitle,
} from '~/components/ui/dialog'
import { Input } from '~/components/ui/input'

const props = defineProps<{
  repositoryId: string
  branch?: string | null
}>()

const open = defineModel<boolean>('open', { default: false })

const query = ref('')
const isLoading = ref(false)
const result = ref<GraphSearchResponse | null>(null)
const errorMsg = ref('')
const selectedChunkId = ref<string | null>(null)

/**
 * 从 result.results 构建扩散图「起点」节点 SourceChunk[]（平移 playground.vue:40
 * 逻辑，数据源改为已序列化好的 results —— chunk_id/file_path/line_start/line_end/content）。
 */
function extractSourceChunks(res: GraphSearchResponse | null): SourceChunk[] {
  if (!res?.results)
    return []
  return res.results.map(r => ({
    chunk_id: r.chunk_id,
    file_path: r.file_path,
    line_start: r.line_start,
    line_end: r.line_end,
    content: r.content,
  }))
}

async function onSearch() {
  const q = query.value.trim()
  if (!q || isLoading.value)
    return
  isLoading.value = true
  errorMsg.value = ''
  selectedChunkId.value = null
  try {
    result.value = await graphSearch(props.repositoryId, {
      query: q,
      branch: props.branch ?? null,
    })
  }
  catch (err: unknown) {
    result.value = null
    errorMsg.value = err instanceof Error ? err.message : '关联搜索失败，请稍后重试'
  }
  finally {
    isLoading.value = false
  }
}

function onNodeClick(chunkId: string) {
  // 点击扩散图节点 → 高亮命中片段列表中对应起点（hop1/hop2 节点无对应 result 时无副作用）
  selectedChunkId.value = chunkId
}
</script>

<template>
  <Dialog v-model:open="open">
    <DialogScrollContent class="max-w-5xl bg-card/85 backdrop-blur-xl border-border/50">
      <DialogHeader>
        <DialogTitle class="flex items-center gap-2">
          <span class="icon-[lucide--share-2] text-primary" />
          关联搜索
        </DialogTitle>
        <DialogDescription>
          基于 GraphRAG 检索命中片段及其 hop1/hop2 关联代码块扩散图
          <span v-if="props.branch" class="ml-1 font-mono text-foreground">· {{ props.branch }}</span>
        </DialogDescription>
      </DialogHeader>

      <!-- 查询输入 -->
      <div class="flex items-center gap-2">
        <Input
          v-model="query"
          placeholder="输入查询，例如：用户登录鉴权流程"
          class="h-10 flex-1"
          :disabled="isLoading"
          @keydown.enter="onSearch"
        />
        <Button :disabled="isLoading || !query.trim()" @click="onSearch">
          <span
            :class="isLoading
              ? 'icon-[lucide--loader-circle] animate-spin mr-1.5'
              : 'icon-[lucide--search] mr-1.5'"
          />
          {{ isLoading ? '搜索中...' : '搜索' }}
        </Button>
      </div>

      <!-- 错误提示 -->
      <p v-if="errorMsg" class="text-sm text-destructive flex items-center gap-1.5">
        <span class="icon-[lucide--alert-circle]" />
        {{ errorMsg }}
      </p>

      <!-- 结果区：命中片段列表 + 扩散图 -->
      <div class="grid gap-4 lg:grid-cols-2">
        <!-- L3 命中片段 -->
        <div class="min-w-0 space-y-2">
          <h4 class="text-xs font-semibold text-muted-foreground flex items-center gap-1.5">
            <span class="icon-[lucide--file-code] text-sm" />
            命中片段
            <span v-if="result" class="font-normal">（{{ result.results.length }}）</span>
          </h4>

          <div
            v-if="!result && !isLoading"
            class="rounded-xl border border-border/50 bg-muted/20 p-6 text-center text-sm text-muted-foreground"
          >
            输入查询并搜索，查看命中片段与关联扩散图
          </div>

          <ul v-else class="space-y-2 max-h-[460px] overflow-y-auto pr-1">
            <li
              v-for="(item, idx) in result?.results ?? []"
              :key="`${item.chunk_id}-${idx}`"
              class="rounded-xl border bg-card p-3 transition-colors"
              :class="selectedChunkId === item.chunk_id
                ? 'border-primary/50 ring-1 ring-primary/30'
                : 'border-border/50'"
            >
              <div class="flex items-center justify-between gap-2">
                <p class="text-xs font-mono text-foreground truncate">
                  {{ item.file_path }}
                </p>
                <span class="text-[11px] text-muted-foreground shrink-0 tabular-nums">
                  {{ item.score.toFixed(2) }}
                </span>
              </div>
              <p
                v-if="item.line_start != null"
                class="text-[11px] text-muted-foreground mt-0.5"
              >
                L{{ item.line_start }}<template v-if="item.line_end != null">
                  –{{ item.line_end }}
                </template>
              </p>
              <pre class="mt-2 text-[11px] leading-relaxed text-muted-foreground/90 whitespace-pre-wrap wrap-break-word line-clamp-4">{{ item.content }}</pre>
            </li>

            <li
              v-if="result && result.results.length === 0"
              class="rounded-xl border border-border/50 bg-muted/20 p-6 text-center text-sm text-muted-foreground"
            >
              未召回任何命中片段
            </li>
          </ul>
        </div>

        <!-- hop1/hop2 扩散图（复用 GraphRAGDiffusionTab） -->
        <div class="min-w-0 rounded-xl border border-border/50 bg-card overflow-hidden">
          <GraphRAGDiffusionTab
            :hop1-neighbors="result?.hop1_neighbors ?? []"
            :hop2-neighbors="result?.hop2_neighbors ?? []"
            :source-chunks="extractSourceChunks(result)"
            :loading="isLoading"
            @node-click="onNodeClick"
          />
        </div>
      </div>
    </DialogScrollContent>
  </Dialog>
</template>
