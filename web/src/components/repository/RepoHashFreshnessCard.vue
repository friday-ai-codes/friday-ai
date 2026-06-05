<script setup lang="ts">
import type { CollectionHealthResponse, IndexHistoryItem } from '~/api/repositories'
import type { Repository } from '~/types'
import { computed, onMounted, ref } from 'vue'
import { repositoriesApi } from '~/api/repositories'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '~/components/ui/tooltip'
import { formatRelativeTime } from '~/lib/relativeTime'

const props = defineProps<{
  repositoryId: string
}>()

const repo = ref<Repository | null>(null)
const loading = ref(true)
const checking = ref(false)
const errorMessage = ref<string | null>(null)

// 四态：fresh / stale / not_indexed / unknown
// - not_indexed：本地从未建立索引（last_indexed_commit_sha 为空），新鲜度概念不适用
// - unknown：已索引但未拉取过远端 HEAD（缺 remote_head_sha 或 remote_head_checked_at）
type FreshnessState = 'fresh' | 'stale' | 'not_indexed' | 'unknown'
const freshnessState = ref<FreshnessState>('unknown')
// refresh 后更新的远端 SHA（覆盖 repo.remote_head_sha）
const latestRemoteHeadSha = ref<string>('')

// 集合健康（Qdrant collection points 数）：从原 WebhookConfigPanel 合并过来，
// 与新鲜度共置一处避免两张卡片重复展示同一类"索引状态"信息
const health = ref<CollectionHealthResponse | null>(null)

// ：GraphRAG 状态（消费 后端 IndexHistory 三字段）
// 仅取最新一条 IndexHistory（limit=1）；graph_build_status 缺失时整段不渲染
const latestGraphHistory = ref<IndexHistoryItem | null>(null)

const { copy } = useClipboard()
const { success } = useToast()

function computeFreshness(r: Repository): FreshnessState {
  if (!r.last_indexed_commit_sha)
    return 'not_indexed'
  if (!r.remote_head_sha || !r.remote_head_checked_at)
    return 'unknown'
  return r.remote_head_sha === r.last_indexed_commit_sha ? 'fresh' : 'stale'
}

const localSha = computed(() => repo.value?.last_indexed_commit_sha?.slice(0, 7) || '—')
const remoteSha = computed(() => (latestRemoteHeadSha.value || repo.value?.remote_head_sha || '').slice(0, 7) || '—')
const lastCheckedAt = computed(() => repo.value?.remote_head_checked_at || null)
const behindCommits = computed(() => repo.value?.behind_commits ?? null)
const lastIndexedAt = computed(() => repo.value?.last_indexed_at || null)
const hasHealthInfo = computed(() => health.value !== null)
const isHealthy = computed(() => health.value?.status === 'healthy')

// ：GraphRAG 状态 Badge 派生
// Deviation D-B（per planner）：UI-SPEC §5.7 状态映射表中 completed 用 success Badge variant，
// shadcn-vue 项目虽然已配置 success variant，但 plan 显式选择 default + 绿色 check-circle 图标
// 双重信号补足语义（保持文字 + icon 不仅靠颜色，符合 a11y），与既有"集合健康"区段视觉一致。
const graphBuildStatusVariant = computed<'secondary' | 'destructive' | 'outline' | 'default'>(() => {
  const status = latestGraphHistory.value?.graph_build_status
  if (status === 'completed')
    return 'default'
  if (status === 'failed')
    return 'destructive'
  if (status === 'skipped')
    return 'outline'
  return 'secondary' // pending / running / unknown
})

const graphBuildStatusLabel = computed<string>(() => {
  const status = latestGraphHistory.value?.graph_build_status
  switch (status) {
    case 'pending': return '等待构建'
    case 'running': return '构建中...'
    case 'completed': return '已构建'
    case 'failed': return '构建失败'
    case 'skipped': return '已跳过'
    default: return '未知'
  }
})

const graphBuildStatusIcon = computed<string>(() => {
  const status = latestGraphHistory.value?.graph_build_status
  switch (status) {
    case 'pending': return 'icon-[lucide--clock]'
    case 'running': return 'icon-[lucide--loader-circle] animate-spin'
    case 'completed': return 'icon-[lucide--check-circle] text-emerald-500'
    case 'failed': return 'icon-[lucide--alert-circle]'
    case 'skipped': return 'icon-[lucide--minus-circle]'
    default: return 'icon-[lucide--help-circle]'
  }
})

async function loadRepo() {
  loading.value = true
  try {
    repo.value = await repositoriesApi.get(props.repositoryId)
    freshnessState.value = computeFreshness(repo.value)
    latestRemoteHeadSha.value = repo.value.remote_head_sha || ''
  }
  catch {
    freshnessState.value = 'unknown'
  }
  finally {
    loading.value = false
  }
}

async function loadHealth() {
  try {
    health.value = await repositoriesApi.getCollectionHealth(props.repositoryId)
  }
  catch {
    // intentionally ignored：集合健康获取失败不阻塞主新鲜度展示
  }
}

async function loadGraphHistory() {
  try {
    const res = await repositoriesApi.getIndexHistory(props.repositoryId, { limit: 1 })
    const first = res.items[0]
    // 仅当最新行回填了 graph_build_status 才挂上 ref；老行 / 字段缺失 → 整段不渲染
    if (first && first.graph_build_status)
      latestGraphHistory.value = first
    else
      latestGraphHistory.value = null
  }
  catch {
    // intentionally ignored：GraphRAG 状态获取失败不阻塞主新鲜度展示
  }
}

async function refresh() {
  checking.value = true
  errorMessage.value = null
  try {
    const res = await repositoriesApi.refreshRemoteHead(props.repositoryId)
    latestRemoteHeadSha.value = res.remote_head_sha
    // 重新加载仓库数据以更新 behind_commits，并基于最新数据本地重算 freshness
    // （后端只返回三态，会把 not_indexed 折叠成 unknown，因此不能直接用 res.freshness）
    repo.value = await repositoriesApi.get(props.repositoryId)
    freshnessState.value = computeFreshness(repo.value)
    // 顺便刷新一下集合健康（点击立即检查时通常也想看最新的向量点数）
    loadHealth()
    // ：用户点"立即检查"时同步刷新 GraphRAG 索引历史
    loadGraphHistory()
  }
  catch (e: unknown) {
    const msg = e instanceof Error ? e.message : '未知错误'
    errorMessage.value = `检查失败：${msg}。请稍后重试。`
  }
  finally {
    checking.value = false
  }
}

function copySha(sha: string) {
  copy(sha)
  success('已复制 SHA')
}

onMounted(() => {
  loadRepo()
  loadHealth()
  loadGraphHistory()
})
</script>

<template>
  <!-- D-14: .card 类（禁 glass-card）；STALE 态 border-l-4 border-amber-500（UI-SPEC §11 硬约束） -->
  <div class="card" :class="freshnessState === 'stale' ? 'border-l-4 border-amber-500' : ''">
    <!-- Header：px-5 py-3.5（UI-SPEC §2 卡片骨架） -->
    <div class="px-5 py-3.5 border-b border-border/50 flex items-center justify-between">
      <div class="flex items-center gap-2">
        <span class="icon-[lucide--git-compare-arrows] text-primary" />
        <h3 class="text-sm font-semibold">
          索引状态
        </h3>
        <span class="text-xs text-muted-foreground">新鲜度 · 集合健康</span>
      </div>
      <Button
        variant="outline"
        size="sm"
        class="h-8 text-xs"
        :disabled="checking"
        @click="refresh"
      >
        <span :class="checking ? 'icon-[lucide--loader-circle] animate-spin mr-1.5' : 'icon-[lucide--refresh-cw] mr-1.5'" />
        {{ checking ? '检查中...' : '立即检查' }}
      </Button>
    </div>

    <!-- Body：p-5（UI-SPEC §2 卡片骨架） -->
    <div class="p-5">
      <!-- 首次加载状态（UI-SPEC §5.4） -->
      <div v-if="loading" class="flex items-center gap-2 py-8 justify-center">
        <span class="icon-[lucide--loader-circle] text-2xl text-primary animate-spin" />
        <span class="text-sm text-muted-foreground">加载新鲜度状态...</span>
      </div>

      <template v-else>
        <!-- 三态主内容区（UI-SPEC §5） -->
        <div class="flex items-start gap-3">
          <!-- 状态图标（语义色，不使用 teal） -->
          <span
            v-if="freshnessState === 'fresh'"
            class="icon-[lucide--check-circle-2] text-2xl text-emerald-500 shrink-0 mt-0.5"
          />
          <span
            v-else-if="freshnessState === 'stale'"
            class="icon-[lucide--alert-triangle] text-2xl text-amber-500 shrink-0 mt-0.5"
          />
          <span
            v-else-if="freshnessState === 'not_indexed'"
            class="icon-[lucide--circle-dashed] text-2xl text-muted-foreground shrink-0 mt-0.5"
          />
          <span
            v-else
            class="icon-[lucide--help-circle] text-2xl text-muted-foreground shrink-0 mt-0.5"
          />

          <!-- 文案区（UI-SPEC §7 逐字锁定） -->
          <div class="flex-1 space-y-1" role="status" aria-live="polite">
            <p class="text-base font-semibold text-foreground">
              <template v-if="freshnessState === 'fresh'">
                索引最新
              </template>
              <template v-else-if="freshnessState === 'stale'">
                索引已过期
              </template>
              <template v-else-if="freshnessState === 'not_indexed'">
                尚未索引
              </template>
              <template v-else>
                远端状态未知
              </template>
            </p>
            <p class="text-sm text-muted-foreground">
              <template v-if="freshnessState === 'fresh'">
                本地与远程 HEAD 一致
              </template>
              <template v-else-if="freshnessState === 'stale'">
                <template v-if="behindCommits !== null">
                  距离最新 <span class="font-mono text-amber-600">{{ behindCommits }}</span> 个 commit
                </template>
                <template v-else>
                  本地与远端 HEAD 不一致
                </template>
              </template>
              <template v-else-if="freshnessState === 'not_indexed'">
                仓库还未建立本地索引，完成首次索引后即可比较新鲜度
              </template>
              <template v-else>
                请点击「立即检查」获取最新提交
              </template>
            </p>
          </div>
        </div>

        <!-- SHA 对比区 -->
        <div class="mt-4 space-y-1.5">
          <!-- not_indexed：不展示"本地 → 远端"对比，只展示远端 HEAD 信息（若已知） -->
          <div v-if="freshnessState === 'not_indexed'" class="flex items-center gap-2 text-xs text-muted-foreground">
            <template v-if="remoteSha !== '—'">
              <span>远端 HEAD</span>
              <Badge variant="secondary" class="font-mono">
                {{ remoteSha }}
              </Badge>
            </template>
            <template v-else>
              <span>暂无远端 HEAD 信息</span>
            </template>
          </div>

          <div v-else class="flex items-center gap-2 text-xs text-muted-foreground">
            <span>本地</span>
            <TooltipProvider :delay-duration="300">
              <Tooltip>
                <TooltipTrigger as-child>
                  <button
                    class="p-0 rounded hover:bg-muted/40 transition-colors"
                    @click="repo?.last_indexed_commit_sha && copySha(repo.last_indexed_commit_sha)"
                  >
                    <Badge variant="secondary" class="font-mono cursor-pointer">
                      {{ localSha }}
                    </Badge>
                  </button>
                </TooltipTrigger>
                <TooltipContent>点击复制完整 SHA</TooltipContent>
              </Tooltip>
            </TooltipProvider>

            <!-- STALE / UNKNOWN 态显示远端 SHA 对比 -->
            <template v-if="freshnessState !== 'fresh'">
              <span class="icon-[lucide--arrow-right] text-muted-foreground" />
              <span>远端</span>
              <Badge
                :variant="freshnessState === 'stale' ? 'outline' : 'secondary'"
                :class="freshnessState === 'stale' ? 'font-mono text-amber-600' : 'font-mono'"
              >
                {{ remoteSha }}
              </Badge>
            </template>
          </div>

          <!-- 相对时间 + Tooltip 绝对时间（UI-SPEC §5/§7） -->
          <TooltipProvider :delay-duration="300">
            <Tooltip>
              <TooltipTrigger as-child>
                <span class="text-xs text-muted-foreground cursor-default">
                  {{ lastCheckedAt ? `距离上次检查 ${formatRelativeTime(lastCheckedAt)}` : '尚未检查过' }}
                </span>
              </TooltipTrigger>
              <TooltipContent v-if="lastCheckedAt">
                <p>{{ new Date(lastCheckedAt).toLocaleString('zh-CN') }}</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>

        <!-- 集合健康 + 最后索引时间（从 WebhookConfigPanel 合并而来，避免两处重复展示） -->
        <div
          v-if="hasHealthInfo || lastIndexedAt"
          class="mt-4 pt-3 border-t border-border/50 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-muted-foreground"
        >
          <div v-if="hasHealthInfo" class="flex items-center gap-1.5">
            <span
              class="text-sm"
              :class="isHealthy ? 'icon-[lucide--check-circle] text-emerald-500' : 'icon-[lucide--alert-circle] text-destructive'"
            />
            <span>
              {{ isHealthy ? '集合健康' : '集合异常' }} ·
              <span class="font-mono tabular-nums">{{ health!.points_count.toLocaleString() }}</span> 个向量点
              <template v-if="health!.indexed_files_count !== undefined && health!.indexed_files_count !== null">
                · <span class="font-mono tabular-nums">{{ health!.indexed_files_count.toLocaleString() }}</span> 个已索引文件
              </template>
            </span>
          </div>
          <TooltipProvider v-if="lastIndexedAt" :delay-duration="300">
            <Tooltip>
              <TooltipTrigger as-child>
                <span class="flex items-center gap-1.5 cursor-default">
                  <span class="icon-[lucide--clock] text-sm" />
                  最后索引 {{ formatRelativeTime(lastIndexedAt) }}
                </span>
              </TooltipTrigger>
              <TooltipContent>
                <p>{{ new Date(lastIndexedAt).toLocaleString('zh-CN') }}</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>

        <!-- ：GraphRAG 状态（消费 字段；UI-SPEC ） -->
        <!-- v-if 守卫：无最新 IndexHistory / graph_build_status 缺失 → 整段不渲染（零回归 4 态 freshness） -->
        <div
          v-if="latestGraphHistory"
          class="mt-4 pt-3 border-t border-border/50 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-muted-foreground"
        >
          <div class="flex items-center gap-1.5">
            <span class="icon-[lucide--share-2] text-sm text-muted-foreground" aria-hidden="true" />
            <span>GraphRAG 状态</span>
          </div>
          <Badge
            :variant="graphBuildStatusVariant"
            class="text-xs h-5 px-1.5 flex items-center gap-1"
            role="status"
            :aria-label="`GraphRAG 构建状态：${graphBuildStatusLabel}`"
          >
            <span :class="graphBuildStatusIcon" class="text-xs" aria-hidden="true" />
            <span>{{ graphBuildStatusLabel }}</span>
            <!-- a11y：running 态屏幕阅读器额外语义 -->
            <span v-if="latestGraphHistory.graph_build_status === 'running'" class="sr-only">
              GraphRAG 索引正在构建中
            </span>
          </Badge>
          <span
            v-if="typeof latestGraphHistory.edge_count === 'number'"
            class="font-mono tabular-nums"
            :aria-label="`图谱边数 ${latestGraphHistory.edge_count}`"
          >
            {{ latestGraphHistory.edge_count.toLocaleString() }} 条边
          </span>
          <TooltipProvider v-if="latestGraphHistory.payload_synced_at" :delay-duration="300">
            <Tooltip>
              <TooltipTrigger as-child>
                <span class="flex items-center gap-1.5 cursor-default">
                  <span class="icon-[lucide--refresh-cw] text-sm" aria-hidden="true" />
                  <span>{{ formatRelativeTime(latestGraphHistory.payload_synced_at) }} 同步</span>
                </span>
              </TooltipTrigger>
              <TooltipContent>
                <p>{{ new Date(latestGraphHistory.payload_synced_at).toLocaleString('zh-CN') }}</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>

        <!-- ：跨仓 API 匹配状态（ cross_repo_match_count + cross_repo_built_at） -->
        <!-- v-if 守卫：cross_repo_built_at 非 null 才渲染（未运行 offline join 时不展示） -->
        <div
          v-if="latestGraphHistory && latestGraphHistory.cross_repo_built_at"
          class="mt-4 pt-3 border-t border-border/50 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-muted-foreground"
        >
          <div class="flex items-center gap-1.5">
            <span class="icon-[lucide--git-compare] text-sm text-muted-foreground" aria-hidden="true" />
            <span>跨仓 API 匹配</span>
          </div>
          <span
            class="font-mono tabular-nums"
            :aria-label="`跨仓 API 匹配数 ${latestGraphHistory.cross_repo_match_count ?? 0}`"
          >
            {{ (latestGraphHistory.cross_repo_match_count ?? 0).toLocaleString() }} 个匹配
          </span>
          <TooltipProvider :delay-duration="300">
            <Tooltip>
              <TooltipTrigger as-child>
                <span class="flex items-center gap-1.5 cursor-default">
                  <span class="icon-[lucide--clock] text-sm" aria-hidden="true" />
                  <span>{{ formatRelativeTime(latestGraphHistory.cross_repo_built_at) }} 构建</span>
                </span>
              </TooltipTrigger>
              <TooltipContent>
                <p>{{ new Date(latestGraphHistory.cross_repo_built_at).toLocaleString('zh-CN') }}</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>

        <!-- 错误提示（UI-SPEC §5.4 / §7） -->
        <p v-if="errorMessage" class="mt-2 text-xs text-destructive">
          {{ errorMessage }}
        </p>
      </template>
    </div>
  </div>
</template>
