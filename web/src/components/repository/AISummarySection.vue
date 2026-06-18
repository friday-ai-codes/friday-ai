<script setup lang="ts">
import type { AISummaryLogEntry, AISummaryStatus, AISummaryStatusResponse } from '~/api/repositories'
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ApiError } from '~/api/client'
import { repositoriesApi } from '~/api/repositories'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '~/components/ui/collapsible'
import { MarkdownPreview } from '~/components/ui/markdown-editor'
import { Skeleton } from '~/components/ui/skeleton'
import { useToast } from '~/composables/useToast'

const props = defineProps<{
  repositoryId: string
}>()

const { success: toastSuccess, warning: toastWarning } = useToast()

// 状态
const status = ref<AISummaryStatus>('not_started')
const summary = ref<string | null>(null)
const generatedAt = ref<string | null>(null)
const errorMsg = ref<string | null>(null)
const generating = ref(false)
// PageIndex 能力树状态
const hasTree = ref(false)
const isMonorepo = ref(false)
const treeNodeCount = ref(0)
// Claude Code 调用细节（生成中实时增长的活动流）
const recentLogs = ref<AISummaryLogEntry[]>([])

// 轮询控制
let pollTimer: ReturnType<typeof setTimeout> | null = null
let pollCount = 0

// Collapsible 分段展开状态
const sections = reactive({
  overview: true,
  tech_stack: true,
  modules: true,
  entry_points: true,
  build_commands: true,
  testing_commands: true,
  conventions: true,
})

// 活动流展示：最新在最上方
const displayLogs = computed(() => [...recentLogs.value].reverse())

function logIcon(type: string): string {
  switch (type) {
    case 'tool_call':
      return 'icon-[lucide--wrench]'
    case 'text':
      return 'icon-[lucide--message-square-text]'
    case 'result':
      return 'icon-[lucide--check-circle-2]'
    default:
      return 'icon-[lucide--activity]'
  }
}

/** tool_call 内容形如 `Read({"file_path": "..."})`，拆出工具名与参数串 */
function formatToolCall(content: string): { name: string, args: string } {
  const idx = content.indexOf('(')
  if (idx <= 0)
    return { name: content, args: '' }
  return {
    name: content.slice(0, idx),
    args: content.slice(idx + 1).replace(/\)\s*$/, ''),
  }
}

// 解析 JSON summary
const parsedSummary = computed(() => {
  if (!summary.value)
    return null
  try {
    const parsed = JSON.parse(summary.value)
    if (typeof parsed === 'object' && parsed !== null)
      return parsed
    return null
  }
  catch {
    return null
  }
})

// 获取状态
async function fetchStatus() {
  try {
    const res: AISummaryStatusResponse = await repositoriesApi.getSummaryStatus(props.repositoryId)
    status.value = res.status
    summary.value = res.summary
    generatedAt.value = res.generated_at
    errorMsg.value = res.error
    hasTree.value = res.has_tree ?? false
    isMonorepo.value = res.is_monorepo ?? false
    treeNodeCount.value = res.tree_node_count ?? 0
    recentLogs.value = res.recent_logs ?? []

    // 终态时停止轮询
    if (res.status === 'completed' || res.status === 'failed' || res.status === 'not_started') {
      stopPolling()
    }
  }
  catch {
    // 静默处理
  }
}

// 启动轮询（setTimeout 递归，per D-10）
function startPolling() {
  stopPolling()
  pollCount = 0
  poll()
}

function poll() {
  const delay = pollCount < 3 ? 2000 : 4000
  pollTimer = setTimeout(async () => {
    await fetchStatus()
    // 非终态时继续轮询
    if (status.value === 'pending' || status.value === 'running') {
      pollCount++
      poll()
    }
  }, delay)
}

function stopPolling() {
  if (pollTimer) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
  pollCount = 0
}

// 触发生成
async function generateSummary() {
  generating.value = true
  const isRegenerate = status.value === 'completed' || status.value === 'failed'
  try {
    await repositoriesApi.generateSummary(props.repositoryId)
    status.value = 'pending'
    toastSuccess(isRegenerate ? 'AI 描述与 PageIndex 索引重新生成任务已启动' : 'AI 描述与 PageIndex 索引生成任务已启动')
    startPolling()
  }
  catch (e: unknown) {
    if (e instanceof ApiError && e.status === 409) {
      toastWarning('生成任务正在进行中，请稍候')
      // 恢复 polling 以跟踪进度
      if (status.value !== 'pending' && status.value !== 'running') {
        status.value = 'running'
      }
      startPolling()
    }
  }
  finally {
    generating.value = false
  }
}

// 分段配置
const sectionConfig = [
  { key: 'overview', title: '项目概览', icon: 'icon-[lucide--info]', type: 'markdown' },
  { key: 'tech_stack', title: '技术栈', icon: 'icon-[lucide--layers]', type: 'badges' },
  { key: 'modules', title: '模块结构', icon: 'icon-[lucide--folder-tree]', type: 'modules' },
  { key: 'entry_points', title: '入口文件', icon: 'icon-[lucide--file-code]', type: 'mono-list' },
  { key: 'build_commands', title: '构建命令', icon: 'icon-[lucide--terminal]', type: 'mono-list' },
  { key: 'testing_commands', title: '测试命令', icon: 'icon-[lucide--flask-conical]', type: 'mono-list' },
  { key: 'conventions', title: '代码规范', icon: 'icon-[lucide--book-open]', type: 'markdown' },
] as const

onMounted(async () => {
  await fetchStatus()
  if (status.value === 'pending' || status.value === 'running') {
    startPolling()
  }
})

onUnmounted(() => {
  stopPolling()
})
</script>

<template>
  <div class="card overflow-hidden">
    <!-- 卡片头 -->
    <div class="flex items-center justify-between px-5 py-3.5 border-b border-border/50 gap-3">
      <div class="flex items-center gap-2 min-w-0">
        <div class="p-1.5 rounded-lg bg-primary/10 shrink-0">
          <span class="icon-[lucide--sparkles] text-primary" />
        </div>
        <div class="min-w-0">
          <h3 class="text-sm font-semibold text-foreground">
            AI 描述与 PageIndex 索引
          </h3>
          <p class="text-xs text-muted-foreground truncate">
            自动分析仓库结构，生成项目概览与可检索的能力树索引
          </p>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <!-- pending / running Badge -->
        <Badge v-if="status === 'pending'" variant="warning">
          <span class="icon-[lucide--clock] mr-1" />
          排队中
        </Badge>
        <Badge v-else-if="status === 'running'" variant="info">
          <span class="icon-[lucide--loader-2] mr-1 animate-spin" />
          生成中
        </Badge>
        <!-- completed: 时间戳 + 重新生成 -->
        <template v-else-if="status === 'completed'">
          <span v-if="generatedAt" class="text-xs text-muted-foreground">
            生成于 {{ new Date(generatedAt).toLocaleString('zh-CN') }}
          </span>
          <Button
            variant="ghost"
            size="sm"
            :disabled="generating"
            @click="generateSummary"
          >
            <span class="icon-[lucide--sparkles] mr-1.5" />
            重新生成
          </Button>
        </template>
        <!-- failed: 重新生成 -->
        <template v-else-if="status === 'failed'">
          <Button
            variant="ghost"
            size="sm"
            :disabled="generating"
            @click="generateSummary"
          >
            <span class="icon-[lucide--sparkles] mr-1.5" />
            重新生成
          </Button>
        </template>
      </div>
    </div>

    <!-- 卡片内容 -->
    <div class="p-5">
      <!-- 状态 A: not_started 空状态 -->
      <div v-if="status === 'not_started'" class="space-y-4">
        <div class="flex flex-col items-center justify-center py-6 space-y-3">
          <span class="icon-[lucide--sparkles] text-2xl text-muted-foreground/40" />
          <p class="text-sm font-semibold text-foreground">
            尚未生成 AI 描述与 PageIndex 索引
          </p>
          <p class="text-xs text-muted-foreground text-center max-w-sm">
            新建仓库会自动触发生成；也可点击下方按钮手动触发，AI 将分析仓库结构并生成描述与能力树索引
          </p>
          <Button
            variant="default"
            size="sm"
            :disabled="generating"
            @click="generateSummary"
          >
            <span class="icon-[lucide--sparkles] mr-1.5" />
            生成描述与索引
          </Button>
        </div>
      </div>

      <!-- 状态 B: pending / running — Claude Code 实时活动流（无日志时骨架屏兜底） -->
      <div v-else-if="status === 'pending' || status === 'running'" class="space-y-4">
        <div
          v-if="displayLogs.length > 0"
          data-testid="summary-activity-stream"
          class="rounded-lg border border-border/50 bg-muted/20 overflow-hidden"
        >
          <div class="flex items-center gap-2 px-3 py-2 border-b border-border/40 text-xs text-muted-foreground">
            <span class="icon-[lucide--terminal]" />
            Claude Code 实时活动
            <span class="ml-auto font-mono text-[10px] opacity-70">{{ displayLogs.length }} 条</span>
          </div>
          <div class="max-h-[240px] overflow-y-auto px-3 py-2 space-y-1.5">
            <div
              v-for="(log, idx) in displayLogs"
              :key="`${log.ts}-${idx}`"
              class="flex items-start gap-2 text-xs leading-relaxed"
              :class="idx === 0 ? 'text-foreground' : 'text-muted-foreground'"
            >
              <span :class="logIcon(log.type)" class="mt-0.5 shrink-0" />
              <span v-if="log.type === 'tool_call'" class="min-w-0 break-all">
                <span class="font-semibold">{{ formatToolCall(log.content).name }}</span>
                <span
                  v-if="formatToolCall(log.content).args"
                  class="font-mono text-[11px] opacity-80"
                >({{ formatToolCall(log.content).args }})</span>
              </span>
              <span v-else class="min-w-0 break-all line-clamp-2">{{ log.content }}</span>
            </div>
          </div>
        </div>
        <div v-else class="space-y-3">
          <Skeleton class="h-4 w-full" />
          <Skeleton class="h-4 w-4/5" />
          <Skeleton class="h-4 w-3/5" />
        </div>
        <div class="flex items-center gap-2 text-sm text-muted-foreground">
          <span class="icon-[lucide--loader-2] animate-spin" />
          <span>{{ status === 'pending' ? '任务排队中...' : 'AI 正在分析仓库结构，生成描述与能力树索引...' }}</span>
        </div>
      </div>

      <!-- 状态 C: completed -->
      <div v-else-if="status === 'completed' && summary">
        <!-- PageIndex 索引状态行 -->
        <div
          class="mb-4 flex flex-wrap items-center gap-2 rounded-lg border p-3"
          :class="hasTree ? 'border-emerald-500/30 bg-emerald-500/5' : 'border-border/50 bg-muted/20'"
        >
          <span
            class="shrink-0"
            :class="hasTree ? 'icon-[lucide--folder-tree] text-emerald-600 dark:text-emerald-400' : 'icon-[lucide--folder-tree] text-muted-foreground/60'"
          />
          <template v-if="hasTree">
            <span class="text-xs font-medium text-foreground">PageIndex 能力树已生成</span>
            <Badge variant="secondary" class="text-[10px]">{{ treeNodeCount }} 个节点</Badge>
            <Badge v-if="isMonorepo" variant="secondary" class="text-[10px]">monorepo</Badge>
            <RouterLink
              :to="{ path: '/knowledge', query: { tab: 'tree' } }"
              class="ml-auto text-xs text-primary hover:underline"
            >
              在知识树中查看 →
            </RouterLink>
          </template>
          <template v-else>
            <span class="text-xs text-muted-foreground">
              本次结果未包含能力树索引（可能为旧版描述），点击「重新生成」可补建 PageIndex 索引
            </span>
          </template>
        </div>

        <!-- 结构化 JSON 分段展示 -->
        <div v-if="parsedSummary" class="space-y-4">
          <template v-for="section in sectionConfig" :key="section.key">
            <Collapsible
              v-if="parsedSummary[section.key]"
              v-model:open="sections[section.key]"
              default-open
            >
              <CollapsibleTrigger class="flex items-center gap-2 w-full px-3 py-2 rounded-lg hover:bg-muted/40 transition-colors">
                <span
                  class="icon-[lucide--chevron-right] transition-transform"
                  :class="{ 'rotate-90': sections[section.key] }"
                />
                <span :class="section.icon" class="text-primary" />
                <span class="text-xs font-semibold text-foreground">{{ section.title }}</span>
              </CollapsibleTrigger>
              <CollapsibleContent>
                <div class="mt-1 ml-7 p-3 rounded-lg bg-muted/30 border border-border/40">
                  <!-- Markdown 渲染 -->
                  <template v-if="section.type === 'markdown'">
                    <MarkdownPreview :content="String(parsedSummary[section.key])" />
                  </template>

                  <!-- 技术栈 Badge 列表 -->
                  <template v-else-if="section.type === 'badges'">
                    <div class="flex flex-wrap gap-2">
                      <Badge
                        v-for="(tech, idx) in (Array.isArray(parsedSummary[section.key])
                          ? parsedSummary[section.key]
                          : String(parsedSummary[section.key]).split(','))"
                        :key="idx"
                        variant="secondary"
                        class="font-mono text-sm"
                      >
                        {{ typeof tech === 'string' ? tech.trim() : tech }}
                      </Badge>
                    </div>
                  </template>

                  <!-- 模块结构 -->
                  <template v-else-if="section.type === 'modules'">
                    <div class="space-y-2">
                      <div
                        v-for="(mod, idx) in (Array.isArray(parsedSummary[section.key]) ? parsedSummary[section.key] : [])"
                        :key="idx"
                        class="flex items-start gap-2"
                      >
                        <span class="text-sm font-semibold text-foreground shrink-0">
                          {{ typeof mod === 'object' && mod?.name ? mod.name : mod }}
                        </span>
                        <span
                          v-if="typeof mod === 'object' && mod?.description"
                          class="text-sm text-muted-foreground"
                        >
                          {{ mod.description }}
                        </span>
                      </div>
                    </div>
                  </template>

                  <!-- 等宽列表（入口文件/构建命令/测试命令） -->
                  <template v-else-if="section.type === 'mono-list'">
                    <div class="space-y-1">
                      <div
                        v-for="(item, idx) in (Array.isArray(parsedSummary[section.key]) ? parsedSummary[section.key] : [])"
                        :key="idx"
                        class="font-mono text-sm text-foreground"
                      >
                        {{ item }}
                      </div>
                    </div>
                  </template>
                </div>
              </CollapsibleContent>
            </Collapsible>
          </template>
        </div>

        <!-- Markdown 降级模式 -->
        <div v-else class="p-3 rounded-lg bg-muted/30 border border-border/40 max-h-[400px] overflow-y-auto">
          <MarkdownPreview :content="summary" />
        </div>
      </div>

      <!-- 状态 D: failed -->
      <div v-else-if="status === 'failed'" class="flex flex-col items-center justify-center py-8 space-y-3">
        <span class="icon-[lucide--alert-triangle] text-2xl text-destructive" />
        <p class="text-sm font-semibold text-foreground">
          描述与索引生成失败
        </p>
        <p v-if="errorMsg" class="text-sm text-destructive text-center max-w-md leading-relaxed">
          {{ errorMsg }}
        </p>
        <p v-else class="text-xs text-muted-foreground text-center max-w-md">
          任务未成功完成。请确认 Runner 在线、Docker 可用，且仓库 Git 凭据与 AI API 配置正确。
        </p>
        <Button
          variant="outline"
          size="sm"
          :disabled="generating"
          @click="generateSummary"
        >
          <span class="icon-[lucide--sparkles] mr-1.5" />
          重新生成描述
        </Button>
        <!-- 失败诊断：展开最近一次运行的 Claude Code 活动 -->
        <details v-if="displayLogs.length > 0" class="w-full max-w-md">
          <summary class="cursor-pointer text-xs text-muted-foreground hover:text-foreground text-center">
            查看最近一次运行的活动（{{ displayLogs.length }} 条）
          </summary>
          <div class="mt-2 max-h-[200px] overflow-y-auto rounded-lg border border-border/40 bg-muted/20 px-3 py-2 space-y-1.5">
            <div
              v-for="(log, idx) in displayLogs"
              :key="`${log.ts}-${idx}`"
              class="flex items-start gap-2 text-xs leading-relaxed text-muted-foreground"
            >
              <span :class="logIcon(log.type)" class="mt-0.5 shrink-0" />
              <span v-if="log.type === 'tool_call'" class="min-w-0 break-all">
                <span class="font-semibold">{{ formatToolCall(log.content).name }}</span>
                <span
                  v-if="formatToolCall(log.content).args"
                  class="font-mono text-[11px] opacity-80"
                >({{ formatToolCall(log.content).args }})</span>
              </span>
              <span v-else class="min-w-0 break-all line-clamp-2">{{ log.content }}</span>
            </div>
          </div>
        </details>
      </div>
    </div>
  </div>
</template>
