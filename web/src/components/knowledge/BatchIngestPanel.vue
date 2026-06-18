<script setup lang="ts">
import type {
  IngestBatchRun,
  JsonIngestBatchRun,
  ResolvedJsonItem,
  StepStatus,
  WorkItemArtifacts,
} from '~/api/ingest'
import { useMutation, useQuery } from '@tanstack/vue-query'
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ingestApi } from '~/api/ingest'
import JsonEditor from '~/components/execution/JsonEditor.vue'
import { Button } from '~/components/ui/button'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'

const { handleError } = useErrorHandler()
const { success, warning } = useToast()
const router = useRouter()

// ==================== URL 爬取（飞书文档 / 多维表格 / wiki / 通用链接） ====================
const crawlInput = ref('')
const crawlMessage = ref('')
const crawlMessageKind = ref<'empty' | 'error' | ''>('')
const feishuNotConfigured = ref(false)
const feishuDeeplink = ref('/admin#integration')

const crawlMutation = useMutation({
  mutationFn: (url: string) => ingestApi.crawlUrl(url),
})
const crawling = computed(() => crawlMutation.isPending.value)

async function doCrawl() {
  const url = crawlInput.value.trim()
  if (!url)
    return
  crawlMessage.value = ''
  crawlMessageKind.value = ''
  feishuNotConfigured.value = false
  try {
    const res = await crawlMutation.mutateAsync(url)
    if (res.status === 'feishu_not_configured') {
      feishuNotConfigured.value = true
      feishuDeeplink.value = res.settings_deeplink || '/admin#integration'
      crawlMessage.value = res.message
      return
    }
    if (res.status === 'ok' && res.items.length) {
      // 爬出来的内容转成 JSON 回填编辑器，再走既有 resolve/校验链。
      jsonText.value = JSON.stringify(res.items, null, 2)
      await parseAndResolve()
      success(res.message || `已爬取 ${res.items.length} 条`)
      return
    }
    // empty / error：展示可读提示
    crawlMessageKind.value = res.status === 'empty' ? 'empty' : 'error'
    crawlMessage.value = res.message || '信息源无法获取到对应的内容'
  }
  catch (e) {
    handleError(e, 'URL 爬取')
  }
}

function goConfigureFeishu() {
  router.push(feishuDeeplink.value)
}

// ==================== JSON 编辑器 ====================
const EXAMPLE_ITEMS = [
  {
    space: '学习工具',
    work_item_id: 6935339052,
    work_item_type: 'story',
    mr_url: 'https://gitlab.example.com/group/repo/-/merge_requests/123',
  },
  { space: 'study_platform', work_item_id: 6994646102 },
  { space: '00000000-0000-0000-0000-000000000000', work_item_id: 7010225564, work_item_type: 'issue' },
]
const EXAMPLE_JSON = JSON.stringify(EXAMPLE_ITEMS, null, 2)

const jsonText = ref(EXAMPLE_JSON)
const parseError = ref('')

function downloadExample() {
  const blob = new Blob([EXAMPLE_JSON], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'batch-ingest-example.json'
  a.click()
  URL.revokeObjectURL(url)
}

// ==================== 解析 / 校验 ====================
const items = ref<ResolvedJsonItem[]>([])

function itemsToInput(list: ResolvedJsonItem[]) {
  return list.map(i => ({
    space: i.space,
    work_item_id: i.work_item_id,
    work_item_type: i.work_item_type,
    mr_url: i.mr_url,
  }))
}

const resolveMutation = useMutation({
  mutationFn: (payload: ReturnType<typeof itemsToInput>) => ingestApi.resolveItems(payload),
})
const resolving = computed(() => resolveMutation.isPending.value)

async function parseAndResolve() {
  parseError.value = ''
  let arr: unknown
  try {
    arr = JSON.parse(jsonText.value)
  }
  catch (e: any) {
    parseError.value = `JSON 解析失败：${e?.message || e}`
    return
  }
  if (!Array.isArray(arr)) {
    parseError.value = '顶层必须是数组（一组 { space, work_item_id, work_item_type?, mr_url? }）'
    return
  }
  try {
    const res = await resolveMutation.mutateAsync(arr as any)
    items.value = res.items
  }
  catch (e) {
    handleError(e, '解析校验')
  }
}

async function revalidate() {
  if (!items.value.length)
    return
  try {
    const res = await resolveMutation.mutateAsync(itemsToInput(items.value))
    items.value = res.items
  }
  catch (e) {
    handleError(e, '重新校验')
  }
}

function removeItem(idx: number) {
  items.value.splice(idx, 1)
}

const resolvedCount = computed(() => items.value.filter(i => i.resolved).length)

// ==================== 并发 + 派发 ====================
const concurrency = ref(3)
const batchId = ref<string | null>(null)
const runTriple = ref<Record<string, JsonIngestBatchRun>>({})
const skipped = ref<Array<{ space: string, work_item_id: number, error: string }>>([])

const dispatchMutation = useMutation({
  mutationFn: (payload: { list: ReturnType<typeof itemsToInput>, c: number }) =>
    ingestApi.dispatchJsonBatch(payload.list, payload.c),
})
const dispatching = computed(() => dispatchMutation.isPending.value)

async function startSync() {
  if (!resolvedCount.value)
    return
  try {
    const res = await dispatchMutation.mutateAsync({
      list: itemsToInput(items.value),
      c: concurrency.value,
    })
    runTriple.value = Object.fromEntries(res.runs.map(r => [r.run_id, r]))
    skipped.value = res.skipped
    artifactsByRun.value = {}
    if (!res.runs.length) {
      batchId.value = null
      warning('没有可关联的有效项（请先解决解析错误）')
      return
    }
    batchId.value = res.batch_id
    pollStartedAt.value = Date.now()
    success(`已派发 ${res.runs.length} 条关联，将在后台执行并实时更新`)
  }
  catch (e) {
    handleError(e, '同步派发')
  }
}

// ==================== 进度轮询 ====================
const POLL_TIMEOUT_MS = 10 * 60 * 1000
const pollStartedAt = ref<number | null>(null)

const batchQuery = useQuery({
  queryKey: computed(() => ['json-ingest-batch', batchId.value]),
  queryFn: () => ingestApi.getBatch(batchId.value as string),
  enabled: computed(() => !!batchId.value),
  refetchInterval: (query) => {
    if (query.state.data?.status !== 'running')
      return false
    if (pollStartedAt.value !== null && Date.now() - pollStartedAt.value > POLL_TIMEOUT_MS)
      return false
    return 2500
  },
})

const progressRuns = computed<IngestBatchRun[]>(() => batchQuery.data.value?.runs ?? [])
const okCount = computed(() => progressRuns.value.filter(r => r.status === 'completed').length)
const isRunning = computed(() => batchQuery.data.value?.status === 'running')

// ==================== 关联文档（实时） ====================
const artifactsByRun = ref<Record<string, WorkItemArtifacts>>({})
const artifactFetching = new Set<string>()

watch(progressRuns, async (runs) => {
  for (const run of runs) {
    const rid = run.run_id
    const triple = runTriple.value[rid]
    if (!triple || !triple.feishu_project_key)
      continue
    const stepOk = run.steps?.work_item?.status === 'ok' || run.steps?.document?.status === 'ok'
    if (!stepOk || artifactsByRun.value[rid] || artifactFetching.has(rid))
      continue
    artifactFetching.add(rid)
    try {
      const art = await ingestApi.getWorkItemArtifacts(
        triple.feishu_project_key,
        triple.work_item_type,
        triple.work_item_id,
      )
      artifactsByRun.value = { ...artifactsByRun.value, [rid]: art }
    }
    catch {
      // 工作项尚未落库 / 404：保持未取，下一轮轮询再试
      artifactFetching.delete(rid)
      continue
    }
    artifactFetching.delete(rid)
  }
}, { deep: true })

// ==================== 展示辅助 ====================
const DOC_TYPE_LABEL: Record<string, string> = {
  prd: '需求文档',
  tech_plan: '技术方案',
}

function docTypeLabel(type: string): string {
  return DOC_TYPE_LABEL[type] ?? type
}

function stepStatus(run: IngestBatchRun, key: 'work_item' | 'document' | 'mr_diff'): StepStatus {
  return (run.steps?.[key]?.status ?? 'pending') as StepStatus
}

function statusIcon(status: StepStatus): string {
  switch (status) {
    case 'ok': return 'icon-[lucide--check-circle-2] text-emerald-600 dark:text-emerald-400'
    case 'failed': return 'icon-[lucide--alert-circle] text-destructive'
    case 'skipped': return 'icon-[lucide--minus-circle] text-amber-700 dark:text-amber-400'
    default: return 'icon-[lucide--circle-dashed] text-muted-foreground'
  }
}

function runTitle(run: IngestBatchRun): string {
  const triple = runTriple.value[run.run_id]
  if (triple)
    return `${triple.space_name} · ${triple.work_item_type} #${triple.work_item_id}`
  return run.board_url || run.run_id
}
</script>

<template>
  <div class="space-y-5">
    <!-- ==================== URL 爬取（飞书文档 / 多维表格 / wiki / 通用链接） ==================== -->
    <div class="card">
      <div class="px-5 py-3.5 border-b border-border/50">
        <div class="flex items-center gap-2">
          <span class="icon-[lucide--link-2] text-primary" />
          <h3 class="text-sm font-semibold">
            链接爬取
          </h3>
        </div>
        <p class="text-xs text-muted-foreground mt-0.5">
          粘贴一个飞书文档 / 多维表格 / wiki 链接（或通用 http(s) 链接），自动抓取内容并用 AI 解析出看板工作项与 MR 关联，回填到下方「待爬取」列表。
        </p>
      </div>

      <div class="p-5 space-y-3">
        <div class="flex items-center gap-2">
          <input
            v-model="crawlInput"
            type="url"
            placeholder="https://xxx.feishu.cn/base/... 或 /docx/... 或 /wiki/..."
            class="flex-1 h-9 rounded border border-border bg-background px-3 text-sm outline-none focus:ring-1 focus:ring-primary/40"
            :disabled="crawling"
            @keydown.enter="doCrawl"
          >
          <Button :disabled="crawling || !crawlInput.trim()" @click="doCrawl">
            <span v-if="crawling" class="icon-[lucide--loader-circle] animate-spin mr-1.5" />
            <span v-else class="icon-[lucide--sparkles] mr-1.5" />
            {{ crawling ? '爬取中…' : '爬取' }}
          </Button>
        </div>

        <!-- 未配置飞书：引导去系统设置 -->
        <div
          v-if="feishuNotConfigured"
          class="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 flex items-start gap-2"
        >
          <span class="icon-[lucide--alert-triangle] text-amber-600 dark:text-amber-400 mt-0.5" />
          <div class="flex-1 min-w-0">
            <p class="text-xs text-amber-700 dark:text-amber-400">
              {{ crawlMessage }}
            </p>
            <Button variant="outline" size="sm" class="h-7 mt-2" @click="goConfigureFeishu">
              <span class="icon-[lucide--settings] mr-1.5" />
              去配置飞书应用
            </Button>
          </div>
        </div>

        <!-- 解析为空 / 出错提示 -->
        <p
          v-else-if="crawlMessage"
          class="text-xs"
          :class="crawlMessageKind === 'error' ? 'text-destructive' : 'text-muted-foreground'"
        >
          {{ crawlMessage }}
        </p>
      </div>
    </div>

    <!-- ==================== JSON 输入 ==================== -->
    <div class="card">
      <div class="px-5 py-3.5 border-b border-border/50 flex items-start justify-between gap-3 flex-wrap">
        <div>
          <div class="flex items-center gap-2">
            <span class="icon-[lucide--braces] text-primary" />
            <h3 class="text-sm font-semibold">
              JSON 批量录入
            </h3>
          </div>
          <p class="text-xs text-muted-foreground mt-0.5">
            粘贴一组 <code class="text-[11px]">{ space, work_item_id, work_item_type?, mr_url? }</code>；空间可填名称（模糊匹配）/ 系统 id / 飞书 key。MR 选填。
          </p>
        </div>
        <Button variant="outline" size="sm" class="h-8 shrink-0" @click="downloadExample">
          <span class="icon-[lucide--download] mr-1.5" />
          下载示例
        </Button>
      </div>

      <div class="p-5 space-y-3">
        <JsonEditor v-model="jsonText" height="220px" />
        <p v-if="parseError" class="text-xs text-destructive">
          {{ parseError }}
        </p>
        <div class="flex items-center gap-2">
          <Button :disabled="resolving" @click="parseAndResolve">
            <span v-if="resolving" class="icon-[lucide--loader-circle] animate-spin mr-1.5" />
            <span v-else class="icon-[lucide--list-checks] mr-1.5" />
            解析 / 校验
          </Button>
        </div>
      </div>
    </div>

    <!-- ==================== 解析后可编辑列表 ==================== -->
    <div v-if="items.length" class="card">
      <div class="px-5 py-3.5 border-b border-border/50 flex items-center justify-between gap-3 flex-wrap">
        <span class="text-sm font-medium">
          待爬取（{{ items.length }}，可关联 {{ resolvedCount }}）
        </span>
        <Button variant="outline" size="sm" class="h-8" :disabled="resolving" @click="revalidate">
          <span class="icon-[lucide--refresh-cw] mr-1.5" :class="{ 'animate-spin': resolving }" />
          重新校验
        </Button>
      </div>

      <div class="p-3 overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-left text-xs text-muted-foreground border-b border-border/50">
              <th class="px-2 py-2 font-medium">
                空间
              </th>
              <th class="px-2 py-2 font-medium">
                匹配
              </th>
              <th class="px-2 py-2 font-medium">
                类型
              </th>
              <th class="px-2 py-2 font-medium">
                工作项 ID
              </th>
              <th class="px-2 py-2 font-medium">
                MR（选填）
              </th>
              <th class="px-2 py-2 font-medium">
                状态
              </th>
              <th class="px-2 py-2" />
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(item, idx) in items"
              :key="idx"
              class="border-b border-border/30 align-top"
            >
              <td class="px-2 py-1.5">
                <input
                  v-model="item.space"
                  class="w-32 h-8 rounded border border-border bg-background px-2 text-xs outline-none focus:ring-1 focus:ring-primary/40"
                >
              </td>
              <td class="px-2 py-1.5">
                <div v-if="item.space_name" class="text-xs">
                  <div class="font-medium truncate max-w-[140px]">
                    {{ item.space_name }}
                  </div>
                  <div class="font-mono text-[10px] text-muted-foreground truncate max-w-[140px]">
                    {{ item.feishu_project_key }}
                  </div>
                </div>
                <span v-else class="text-xs text-muted-foreground">—</span>
              </td>
              <td class="px-2 py-1.5">
                <input
                  v-model="item.work_item_type"
                  class="w-20 h-8 rounded border border-border bg-background px-2 text-xs font-mono outline-none focus:ring-1 focus:ring-primary/40"
                >
              </td>
              <td class="px-2 py-1.5">
                <input
                  v-model.number="item.work_item_id"
                  type="number"
                  class="w-32 h-8 rounded border border-border bg-background px-2 text-xs font-mono outline-none focus:ring-1 focus:ring-primary/40"
                >
              </td>
              <td class="px-2 py-1.5">
                <input
                  v-model="item.mr_url"
                  placeholder="可选"
                  class="w-48 h-8 rounded border border-border bg-background px-2 text-xs outline-none focus:ring-1 focus:ring-primary/40"
                >
              </td>
              <td class="px-2 py-1.5">
                <span
                  v-if="item.resolved"
                  class="inline-flex items-center gap-1 text-[11px] text-emerald-600 dark:text-emerald-400"
                >
                  <span class="icon-[lucide--check-circle-2]" /> 就绪
                </span>
                <span
                  v-else
                  class="inline-flex items-center gap-1 text-[11px] text-destructive"
                  :title="item.error"
                >
                  <span class="icon-[lucide--alert-triangle]" /> {{ item.error || '不可摄取' }}
                </span>
              </td>
              <td class="px-2 py-1.5 text-right">
                <button
                  class="text-muted-foreground hover:text-destructive transition-colors"
                  @click="removeItem(idx)"
                >
                  <span class="icon-[lucide--trash-2] h-4 w-4" />
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="px-5 py-3.5 border-t border-border/50 flex items-center justify-between gap-3 flex-wrap">
        <label class="flex items-center gap-2 text-xs text-muted-foreground">
          并发数
          <input
            v-model.number="concurrency"
            type="number"
            min="1"
            max="10"
            class="w-16 h-8 rounded border border-border bg-background px-2 text-xs outline-none focus:ring-1 focus:ring-primary/40"
          >
          <span class="text-[11px]">（1–10，默认 3；命中限流会自动等待重试）</span>
        </label>
        <Button :disabled="dispatching || !resolvedCount" @click="startSync">
          <span v-if="dispatching" class="icon-[lucide--loader-circle] animate-spin mr-1.5" />
          <span v-else class="icon-[lucide--play] mr-1.5" />
          {{ dispatching ? '派发中…' : `开始关联（${resolvedCount}）` }}
        </Button>
      </div>
    </div>

    <!-- ==================== 跳过项（不可摄取） ==================== -->
    <div v-if="skipped.length" class="card border-amber-500/30 p-4">
      <div class="text-sm font-medium text-amber-700 dark:text-amber-400 mb-2">
        已跳过 {{ skipped.length }} 项（无法解析）
      </div>
      <ul class="space-y-1 text-xs text-muted-foreground">
        <li v-for="(s, i) in skipped" :key="i">
          <span class="font-mono">{{ s.space || '(空)' }} #{{ s.work_item_id }}</span> — {{ s.error }}
        </li>
      </ul>
    </div>

    <!-- ==================== 摄取进度 + 关联文档 ==================== -->
    <div v-if="batchId && progressRuns.length" class="card" data-testid="json-ingest-progress">
      <div class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2 text-sm font-medium">
        <span v-if="isRunning" class="icon-[lucide--loader-circle] animate-spin text-primary" />
        <span v-else class="icon-[lucide--check-circle-2] text-emerald-600 dark:text-emerald-400" />
        <span>
          <template v-if="isRunning">爬取关联进行中…（完成 {{ okCount }}/{{ progressRuns.length }}）</template>
          <template v-else>爬取关联完成（成功 {{ okCount }}/{{ progressRuns.length }}）</template>
        </span>
      </div>
      <ul class="divide-y divide-border/40">
        <li v-for="run in progressRuns" :key="run.run_id" class="px-5 py-3 space-y-2">
          <div class="flex items-center justify-between gap-3 flex-wrap">
            <span class="text-sm font-medium truncate max-w-[55%]">{{ runTitle(run) }}</span>
            <div class="flex items-center gap-3 text-xs">
              <span class="inline-flex items-center gap-1">
                <span :class="statusIcon(stepStatus(run, 'work_item'))" /> 工作项
              </span>
              <span class="inline-flex items-center gap-1">
                <span :class="statusIcon(stepStatus(run, 'document'))" /> 文档
              </span>
              <span class="inline-flex items-center gap-1">
                <span :class="statusIcon(stepStatus(run, 'mr_diff'))" /> MR
              </span>
            </div>
          </div>

          <!-- 关联内容（PRD / 技术方案 等，实时展开） -->
          <div
            v-if="artifactsByRun[run.run_id]"
            class="rounded-lg border border-border/50 bg-muted/20 p-3 space-y-2"
          >
            <div class="flex items-center gap-2 text-xs">
              <span class="icon-[lucide--link] text-muted-foreground" />
              <span class="font-medium">{{ artifactsByRun[run.run_id].work_item.title || '工作项' }}</span>
              <span v-if="artifactsByRun[run.run_id].work_item.status_display_name" class="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground">
                {{ artifactsByRun[run.run_id].work_item.status_display_name }}
              </span>
            </div>
            <div class="flex flex-wrap items-center gap-2">
              <a
                v-if="artifactsByRun[run.run_id].work_item.prd_url"
                :href="artifactsByRun[run.run_id].work_item.prd_url"
                target="_blank"
                rel="noopener"
                class="inline-flex items-center gap-1 text-xs text-primary hover:underline"
              >
                <span class="icon-[lucide--file-text]" /> 需求文档
              </a>
              <a
                v-if="artifactsByRun[run.run_id].work_item.tech_doc_url"
                :href="artifactsByRun[run.run_id].work_item.tech_doc_url"
                target="_blank"
                rel="noopener"
                class="inline-flex items-center gap-1 text-xs text-primary hover:underline"
              >
                <span class="icon-[lucide--file-code-2]" /> 技术方案
              </a>
              <a
                v-for="(doc, di) in artifactsByRun[run.run_id].documents"
                :key="di"
                :href="doc.canonical_url || undefined"
                :target="doc.canonical_url ? '_blank' : undefined"
                rel="noopener"
                class="inline-flex items-center gap-1 rounded bg-background border border-border/60 px-2 py-0.5 text-[11px]"
                :class="doc.canonical_url ? 'text-primary hover:underline' : 'text-muted-foreground'"
              >
                <span class="icon-[lucide--file]" />
                {{ docTypeLabel(doc.document_type) }}
                <span v-if="doc.has_content" class="icon-[lucide--check] text-emerald-500" />
              </a>
              <span
                v-if="!artifactsByRun[run.run_id].work_item.prd_url && !artifactsByRun[run.run_id].work_item.tech_doc_url && !artifactsByRun[run.run_id].documents.length"
                class="text-xs text-muted-foreground"
              >
                暂无关联文档
              </span>
            </div>
          </div>
        </li>
      </ul>
    </div>
  </div>
</template>
