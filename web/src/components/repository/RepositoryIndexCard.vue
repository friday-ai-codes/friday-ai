<script setup lang="ts">
import type { IndexStatusResponse, SearchResultItem } from '~/api/repositories'
import type { IndexStreamRepositoryPayload } from '~/composables/useIndexProgressStream'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { IndexStatus, repositoriesApi } from '~/api/repositories'
import StatusBadge from '~/components/common/StatusBadge.vue'
import { Button } from '~/components/ui/button'
import { Input } from '~/components/ui/input'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { connectIndexProgressStream } from '~/composables/useIndexProgressStream'
import { useToast } from '~/composables/useToast'

const props = withDefaults(defineProps<{
  repositoryId: string
  /** 嵌入知识库 Hub 时隐藏外层 card 壳 */
  embedded?: boolean
}>(), {
  embedded: false,
})

const loading = ref(true)
const indexStatus = ref<IndexStatusResponse | null>(null)
const triggering = ref(false)
const deleting = ref(false)
const cancelling = ref(false)
const exporting = ref(false)
const importing = ref(false)
const fileInput = ref<HTMLInputElement>()

const { handleError } = useErrorHandler()
const { success, error: showError } = useToast()

// SSE 实时进度（INDEXING 期间替代 setInterval polling — 这样无论页面进入时
// status 是 NOT_INDEXED / PENDING 还是 INDEXING，stage 都能跟随后端实时刷新）
let streamController: AbortController | null = null
// SSE 失败兜底：dev 环境 vite proxy 偶发 ECONNREFUSED 把长连接中断，
// 此时降级为 polling /index/status/，确保 stage 仍然能刷新
let pollInterval: ReturnType<typeof setInterval> | null = null

// 加载索引状态
async function loadIndexStatus() {
  try {
    indexStatus.value = await repositoriesApi.getIndexStatus(props.repositoryId)
  }
  catch {
    // intentionally ignored
  }
  finally {
    loading.value = false
  }
}

// 把 SSE 推来的 repository 进度合并进 indexStatus（保持其它字段不变）
function applyStreamRepoProgress(repo: IndexStreamRepositoryPayload) {
  if (!indexStatus.value) {
    indexStatus.value = { ...repo } as unknown as IndexStatusResponse
    return
  }
  indexStatus.value = {
    ...indexStatus.value,
    ...repo,
  } as IndexStatusResponse
}

// 触发索引
async function triggerIndex() {
  triggering.value = true
  try {
    await repositoriesApi.triggerIndex(props.repositoryId)
    success('索引任务已启动')
    await loadIndexStatus()
    startStream()
  }
  catch (e: unknown) {
    handleError(e, '启动索引')
  }
  finally {
    triggering.value = false
  }
}

// 停止索引
async function cancelIndex() {
  cancelling.value = true
  try {
    await repositoriesApi.cancelIndex(props.repositoryId)
    stopAllProgressWatchers()
    success('索引已停止')
    await loadIndexStatus()
  }
  catch (e: unknown) {
    handleError(e, '停止索引')
  }
  finally {
    cancelling.value = false
  }
}

// 删除索引
async function deleteIndex() {
  deleting.value = true
  try {
    await repositoriesApi.deleteIndex(props.repositoryId)
    success('索引已删除')
    await loadIndexStatus()
  }
  catch (e: unknown) {
    handleError(e, '删除索引')
  }
  finally {
    deleting.value = false
  }
}

// 导出索引快照
async function exportSnapshot() {
  exporting.value = true
  try {
    await repositoriesApi.downloadSnapshot(props.repositoryId)
    success('索引快照已下载')
  }
  catch (e: unknown) {
    handleError(e, '导出索引快照')
  }
  finally {
    exporting.value = false
  }
}

// 触发导入文件选择
function triggerImport() {
  fileInput.value?.click()
}

// 导入索引快照
async function handleImportFile(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file)
    return

  importing.value = true
  try {
    const result = await repositoriesApi.uploadSnapshot(props.repositoryId, file)
    success('索引快照已恢复', `已恢复 ${result.points_count} 个索引块`)
    await loadIndexStatus()
  }
  catch (e: unknown) {
    handleError(e, '导入索引快照')
  }
  finally {
    importing.value = false
    target.value = ''
  }
}

// 搜索测试
const searchQuery = ref('')
const searching = ref(false)
const searchResults = ref<SearchResultItem[]>([])
const searchTotal = ref(0)
const hasSearched = ref(false)

async function testSearch() {
  if (!searchQuery.value.trim())
    return
  searching.value = true
  searchResults.value = []
  hasSearched.value = false
  try {
    const res = await repositoriesApi.searchCode(props.repositoryId, {
      query: searchQuery.value,
      top_k: 10,
    })
    searchResults.value = res.results
    searchTotal.value = res.total
    hasSearched.value = true
  }
  catch (e: unknown) {
    handleError(e, '搜索测试')
  }
  finally {
    searching.value = false
  }
}

// 启动 SSE 流（替代 setInterval — 用后端推 stage 解决"克隆中..."卡住问题）
function startStream() {
  if (streamController)
    return
  streamController = connectIndexProgressStream(props.repositoryId, {
    onEvent: (event) => {
      if (event.type === 'progress') {
        applyStreamRepoProgress(event.repository)
      }
      else if (event.type === 'done') {
        // 索引结束：停流 + 拉一次最终状态做权威同步（同时拿到 last_indexed_at 等非 SSE 字段）
        stopAllProgressWatchers()
        loadIndexStatus().then(() => {
          if (indexStatus.value?.index_status === IndexStatus.INDEXED) {
            success('索引构建完成')
          }
          else if (indexStatus.value?.index_status === IndexStatus.CANCELLED) {
            success('索引已停止')
          }
          else if (indexStatus.value?.index_status === IndexStatus.FAILED) {
            showError('索引构建失败')
          }
        })
      }
    },
    onError: () => {
      // SSE 断开（dev 环境 vite proxy ECONNREFUSED、网络抖动等）→ 降级为 polling
      // /index/status/，让 stage 仍然能刷新；status 切到非 INDEXING 时再全部停止
      stopStream()
      startPollingFallback()
    },
  })
}

function stopStream() {
  streamController?.abort()
  streamController = null
}

// SSE 兜底 polling：3 秒一次拉 /index/status/，等价于 SSE 推 progress 帧
function startPollingFallback() {
  if (pollInterval)
    return
  pollInterval = setInterval(async () => {
    await loadIndexStatus()
    if (indexStatus.value?.index_status !== IndexStatus.INDEXING) {
      stopAllProgressWatchers()
      if (indexStatus.value?.index_status === IndexStatus.INDEXED) {
        success('索引构建完成')
      }
      else if (indexStatus.value?.index_status === IndexStatus.CANCELLED) {
        success('索引已停止')
      }
      else if (indexStatus.value?.index_status === IndexStatus.FAILED) {
        showError('索引构建失败')
      }
    }
  }, 3000)
}

function stopPollingFallback() {
  if (pollInterval) {
    clearInterval(pollInterval)
    pollInterval = null
  }
}

function stopAllProgressWatchers() {
  stopStream()
  stopPollingFallback()
}

// 格式化日期
function formatDate(dateStr: string | null) {
  if (!dateStr)
    return '-'
  return new Date(dateStr).toLocaleString('zh-CN')
}

// 统一进度（INDX-03）
const overallProgress = computed(() => {
  return indexStatus.value?.overall_progress ?? 0
})

const overallStage = computed(() => {
  return indexStatus.value?.overall_stage ?? '准备中...'
})

// PROG-02：AI 描述生成状态（排队中 / 生成中 / 完成 / 失败）前端可见
const AI_SUMMARY_STATUS_LABELS: Record<string, string> = {
  pending: '排队中',
  running: '生成中',
  completed: '已完成',
  failed: '生成失败',
}
const aiSummaryStatus = computed(() => indexStatus.value?.ai_summary_status ?? '')
const aiSummaryStatusLabel = computed(() => AI_SUMMARY_STATUS_LABELS[aiSummaryStatus.value] ?? '')
// 仅在有进行中/失败/完成的明确状态时展示（not_started / 空 不展示）
const showAiSummaryStatus = computed(() => aiSummaryStatusLabel.value.length > 0)
const aiSummaryError = computed(() => indexStatus.value?.ai_summary_error ?? '')

// OBS-05：文件级实时进度（来自 SSE / polling）
const currentFile = computed(() => indexStatus.value?.current_indexing_file ?? '')
const filesProcessed = computed(() => indexStatus.value?.indexed_files_processed ?? 0)
const filesTotal = computed(() => indexStatus.value?.indexed_files_total ?? 0)
const hasCurrentFile = computed(() => currentFile.value.length > 0)
const hasFilesCounter = computed(() => filesTotal.value > 0)
const filesPercent = computed(() => {
  if (filesTotal.value <= 0)
    return null
  return Math.min(100, Math.round((filesProcessed.value / filesTotal.value) * 100))
})

// 当 status 切到 INDEXING（页面挂载或他处触发）→ 自动开 SSE 拿实时 stage
watch(
  () => indexStatus.value?.index_status,
  (next) => {
    if (next === IndexStatus.INDEXING) {
      startStream()
    }
    else {
      stopAllProgressWatchers()
    }
  },
)

onMounted(async () => {
  await loadIndexStatus()
  if (indexStatus.value?.index_status === IndexStatus.INDEXING) {
    startStream()
  }
})

onUnmounted(() => {
  stopAllProgressWatchers()
})
</script>

<template>
  <div :class="embedded ? '' : 'card'">
    <div
      v-if="!embedded"
      class="px-5 py-3.5 border-b border-border/50 flex items-center justify-between"
    >
      <div class="flex items-center gap-2">
        <span class="icon-[lucide--database] text-primary" />
        <h3 class="text-sm font-semibold">
          代码索引
        </h3>
        <span class="text-xs text-muted-foreground">向量化代码库</span>
      </div>
      <StatusBadge v-if="indexStatus" type="index" :status="indexStatus.index_status" />
    </div>
    <div :class="embedded ? '' : 'p-5'">
      <!-- 加载状态 -->
      <div v-if="loading" class="flex items-center justify-center gap-3 py-8">
        <span class="icon-[lucide--loader-circle] text-2xl text-primary animate-spin" />
        <span class="text-muted-foreground">加载索引状态...</span>
      </div>

      <!-- 索引状态 -->
      <div v-else-if="indexStatus" class="space-y-6">
        <!-- 已索引状态 -->
        <div v-if="indexStatus.index_status === IndexStatus.INDEXED" class="space-y-4">
          <div class="flex items-center gap-3">
            <div class="p-2 rounded-full bg-emerald-500/10">
              <span class="icon-[lucide--check-circle] text-2xl text-emerald-500" />
            </div>
            <div>
              <p class="font-medium">
                索引已就绪
              </p>
              <p class="text-sm text-muted-foreground">
                最后更新: {{ formatDate(indexStatus.last_indexed_at) }}
              </p>
            </div>
          </div>
          <div class="flex flex-wrap gap-2">
            <Button
              variant="outline"
              :disabled="triggering"
              @click="triggerIndex"
            >
              <span v-if="triggering" class="icon-[lucide--loader-circle] animate-spin mr-2" />
              <span v-else class="icon-[lucide--refresh-cw] mr-2" />
              更新索引
            </Button>
            <Button
              variant="outline"
              :disabled="exporting"
              @click="exportSnapshot"
            >
              <span v-if="exporting" class="icon-[lucide--loader-circle] animate-spin mr-2" />
              <span v-else class="icon-[lucide--download] mr-2" />
              备份索引
            </Button>
            <Button
              variant="outline"
              :disabled="importing"
              @click="triggerImport"
            >
              <span v-if="importing" class="icon-[lucide--loader-circle] animate-spin mr-2" />
              <span v-else class="icon-[lucide--upload] mr-2" />
              导入索引
            </Button>
            <Button
              variant="outline"
              class="hover:bg-destructive/10 hover:text-destructive hover:border-destructive/50"
              :disabled="deleting"
              @click="deleteIndex"
            >
              <span v-if="deleting" class="icon-[lucide--loader-circle] animate-spin mr-2" />
              <span v-else class="icon-[lucide--trash-2] mr-2" />
              删除索引
            </Button>
          </div>

          <!-- 搜索测试 -->
          <div class="border-t border-border/50 pt-4 mt-2 space-y-3">
            <div class="flex items-center gap-1.5 text-sm text-muted-foreground">
              <span class="icon-[lucide--search]" />
              搜索测试
            </div>

            <div class="space-y-3">
              <form class="flex gap-2" @submit.prevent="testSearch">
                <Input
                  v-model="searchQuery"
                  placeholder="输入关键词测试召回效果..."
                  class="flex-1"
                />
                <Button
                  type="submit"
                  size="sm"
                  :disabled="searching || !searchQuery.trim()"
                >
                  <span v-if="searching" class="icon-[lucide--loader-circle] animate-spin mr-1.5" />
                  <span v-else class="icon-[lucide--search] mr-1.5" />
                  搜索
                </Button>
              </form>

              <!-- 搜索结果 -->
              <div v-if="searchResults.length > 0" class="space-y-2">
                <p class="text-xs text-muted-foreground">
                  共召回 {{ searchTotal }} 条结果
                </p>
                <div class="max-h-[400px] overflow-y-auto space-y-2">
                  <div
                    v-for="(item, idx) in searchResults"
                    :key="idx"
                    class="rounded-lg border border-border/60 bg-muted/30 overflow-hidden"
                  >
                    <div class="flex items-center justify-between px-3 py-1.5 bg-muted/50 border-b border-border/40">
                      <div class="flex items-center gap-2 text-xs min-w-0">
                        <span class="icon-[lucide--file-code] text-primary shrink-0" />
                        <span class="font-mono truncate" :title="item.file_path">{{ item.file_path }}</span>
                        <span class="text-muted-foreground shrink-0">L{{ item.start_line }}-{{ item.end_line }}</span>
                      </div>
                      <div class="flex items-center gap-2 text-xs shrink-0 ml-2">
                        <span class="px-1.5 py-0.5 rounded bg-primary/10 text-primary font-medium">{{ item.language }}</span>
                        <span class="text-muted-foreground">{{ (item.score * 100).toFixed(1) }}%</span>
                      </div>
                    </div>
                    <pre class="px-3 py-2 text-xs leading-relaxed overflow-x-auto max-h-[200px]"><code>{{ item.content }}</code></pre>
                  </div>
                </div>
              </div>

              <!-- 无结果 -->
              <div v-else-if="hasSearched && searchTotal === 0 && !searching" class="text-center py-4">
                <span class="icon-[lucide--search-x] text-2xl text-muted-foreground" />
                <p class="text-sm text-muted-foreground mt-1">
                  没有匹配的结果
                </p>
              </div>
            </div>
          </div>
        </div>

        <!-- 索引中状态 -->
        <!-- 视觉减负：去掉大圆 spinner + "正在构建索引"标题（与右上角 badge 重复），
             只保留 1 个 stage 前的小 spinner，避免页面上多个 loading icon 同时旋转 -->
        <div v-else-if="indexStatus.index_status === IndexStatus.INDEXING" class="space-y-4">
          <!-- OBS-05：当前正在索引的文件 + 文件级 N/M 计数（最显眼位置） -->
          <div
            v-if="hasCurrentFile || hasFilesCounter"
            class="rounded-xl border border-primary/30 bg-primary/5 px-4 py-3 space-y-1.5"
          >
            <div class="flex items-center justify-between gap-3">
              <span class="text-[11px] uppercase tracking-wider text-muted-foreground">
                当前文件
              </span>
              <span
                v-if="hasFilesCounter"
                class="font-mono tabular-nums text-xs text-primary"
              >
                {{ filesProcessed }} / {{ filesTotal }}
                <span v-if="filesPercent !== null" class="text-muted-foreground ml-1">
                  ({{ filesPercent }}%)
                </span>
              </span>
            </div>
            <p
              v-if="hasCurrentFile"
              class="font-mono text-sm text-foreground truncate"
              :title="currentFile"
            >
              {{ currentFile }}
            </p>
            <p v-else class="text-sm text-muted-foreground">
              准备中…
            </p>
          </div>

          <!-- 统一索引进度（INDX-03）：stage 文案 + 整体百分比 + 进度条 -->
          <div class="space-y-1.5">
            <div class="flex items-center justify-between text-sm">
              <span class="text-muted-foreground inline-flex items-center gap-1.5">
                <span class="icon-[lucide--loader-circle] animate-spin text-primary" />
                {{ overallStage }}
              </span>
              <span class="font-medium text-primary tabular-nums">{{ overallProgress }}%</span>
            </div>
            <div class="h-2 bg-muted rounded-full overflow-hidden">
              <div
                class="h-full bg-primary transition-all duration-500"
                :style="{ width: `${overallProgress}%` }"
              />
            </div>
            <!-- PROG-02：AI 描述生成状态 -->
            <div
              v-if="showAiSummaryStatus"
              class="flex items-center gap-1.5 text-xs text-muted-foreground"
              data-testid="ai-summary-status"
            >
              <span
                v-if="aiSummaryStatus === 'running' || aiSummaryStatus === 'pending'"
                class="icon-[lucide--sparkles] text-primary"
              />
              <span v-else-if="aiSummaryStatus === 'completed'" class="icon-[lucide--check] text-emerald-500" />
              <span v-else-if="aiSummaryStatus === 'failed'" class="icon-[lucide--triangle-alert] text-destructive" />
              <span>建立知识：{{ aiSummaryStatusLabel }}</span>
              <span v-if="aiSummaryStatus === 'failed' && aiSummaryError" class="text-destructive/80 truncate">— {{ aiSummaryError }}</span>
            </div>
          </div>

          <div class="flex flex-wrap gap-2">
            <Button
              variant="outline"
              class="hover:bg-destructive/10 hover:text-destructive hover:border-destructive/50"
              :disabled="cancelling"
              @click="cancelIndex"
            >
              <span v-if="cancelling" class="icon-[lucide--loader-circle] animate-spin mr-2" />
              <span v-else class="icon-[lucide--circle-stop] mr-2" />
              停止索引
            </Button>
          </div>
        </div>

        <!-- 已停止状态 -->
        <div v-else-if="indexStatus.index_status === IndexStatus.CANCELLED" class="space-y-4">
          <div class="flex items-center gap-3">
            <div class="p-2 rounded-full bg-muted">
              <span class="icon-[lucide--circle-stop] text-2xl text-muted-foreground" />
            </div>
            <div>
              <p class="font-medium">
                索引已停止
              </p>
              <p class="text-sm text-muted-foreground">
                {{ indexStatus.index_error || '用户已停止索引' }}
              </p>
            </div>
          </div>
          <div class="flex flex-wrap gap-2">
            <Button
              :disabled="triggering"
              @click="triggerIndex"
            >
              <span v-if="triggering" class="icon-[lucide--loader-circle] animate-spin mr-2" />
              <span v-else class="icon-[lucide--refresh-cw] mr-2" />
              重新索引
            </Button>
            <Button
              variant="outline"
              :disabled="importing"
              @click="triggerImport"
            >
              <span v-if="importing" class="icon-[lucide--loader-circle] animate-spin mr-2" />
              <span v-else class="icon-[lucide--upload] mr-2" />
              导入索引
            </Button>
          </div>
        </div>

        <!-- 失败状态 -->
        <div v-else-if="indexStatus.index_status === IndexStatus.FAILED" class="space-y-4">
          <div class="flex items-center gap-3">
            <div class="p-2 rounded-full bg-destructive/10">
              <span class="icon-[lucide--x-circle] text-2xl text-destructive" />
            </div>
            <div>
              <p class="font-medium">
                索引构建失败
              </p>
              <p class="text-sm text-muted-foreground">
                {{ indexStatus.index_error || '未知错误' }}
              </p>
            </div>
          </div>
          <div class="flex flex-wrap gap-2">
            <Button
              :disabled="triggering"
              @click="triggerIndex"
            >
              <span v-if="triggering" class="icon-[lucide--loader-circle] animate-spin mr-2" />
              <span v-else class="icon-[lucide--refresh-cw] mr-2" />
              重试
            </Button>
            <Button
              variant="outline"
              :disabled="importing"
              @click="triggerImport"
            >
              <span v-if="importing" class="icon-[lucide--loader-circle] animate-spin mr-2" />
              <span v-else class="icon-[lucide--upload] mr-2" />
              导入索引
            </Button>
            <Button
              variant="outline"
              class="hover:bg-destructive/10 hover:text-destructive hover:border-destructive/50"
              :disabled="deleting"
              @click="deleteIndex"
            >
              <span v-if="deleting" class="icon-[lucide--loader-circle] animate-spin mr-2" />
              <span v-else class="icon-[lucide--trash-2] mr-2" />
              删除索引
            </Button>
          </div>
        </div>

        <!-- 未索引状态 -->
        <div v-else class="text-center py-6">
          <div class="inline-flex p-3 rounded-full bg-muted/50 mb-3">
            <span class="icon-[lucide--database] text-3xl text-muted-foreground" />
          </div>
          <p class="text-muted-foreground mb-4">
            尚未建立代码索引
          </p>
          <div class="flex justify-center gap-2">
            <Button
              :disabled="triggering"
              @click="triggerIndex"
            >
              <span v-if="triggering" class="icon-[lucide--loader-circle] animate-spin mr-2" />
              <span v-else class="icon-[lucide--play] mr-2" />
              新建索引
            </Button>
            <Button
              variant="outline"
              :disabled="importing"
              @click="triggerImport"
            >
              <span v-if="importing" class="icon-[lucide--loader-circle] animate-spin mr-2" />
              <span v-else class="icon-[lucide--upload] mr-2" />
              导入索引
            </Button>
          </div>
        </div>
      </div>
    </div>

    <!-- 隐藏的文件选择器 -->
    <input
      ref="fileInput"
      type="file"
      accept=".snapshot"
      class="hidden"
      @change="handleImportFile"
    >
  </div>
</template>
