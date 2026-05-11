<script setup lang="ts">
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
}>
const repo = ref<Repository | null>(null)
const loading = ref(true)
const checking = ref(false)
const errorMessage = ref<string | null>(null)
// 三态：fresh / stale / unknown
const freshnessState = ref<'fresh' | 'stale' | 'unknown'>('unknown')
// refresh 后更新的远端 SHA（覆盖 repo.remote_head_sha）
const latestRemoteHeadSha = ref<string>('')
const { copy } = useClipboard
const { success } = useToast
function computeFreshness(r: Repository): 'fresh' | 'stale' | 'unknown' {
 if (!r.remote_head_sha || !r.remote_head_checked_at || !r.last_indexed_commit_sha)
 return 'unknown'
 return r.remote_head_sha === r.last_indexed_commit_sha ? 'fresh': 'stale'
}
const localSha = computed( => repo.value?.last_indexed_commit_sha?.slice(0, 7) || '—')
const remoteSha = computed( => (latestRemoteHeadSha.value || repo.value?.remote_head_sha || '').slice(0, 7) || '—')
const lastCheckedAt = computed( => repo.value?.remote_head_checked_at || null)
const behindCommits = computed( => repo.value?.behind_commits ?? null)
async function loadRepo {
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
async function refresh {
 checking.value = true
 errorMessage.value = null
 try {
 const res = await repositoriesApi.refreshRemoteHead(props.repositoryId)
 freshnessState.value = res.freshness
 latestRemoteHeadSha.value = res.remote_head_sha
 // 重新加载仓库数据以更新 behind_commits
 repo.value = await repositoriesApi.get(props.repositoryId)
 }
 catch (e: unknown) {
 const msg = e instanceof Error ? e.message: '未知错误'
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
onMounted(loadRepo)
</script>
<template>
 <!--: .card 类（禁 glass-card）；STALE 态 border- border-amber-500（work item §11 硬约束） -->
 <div class="card":class="freshnessState === 'stale' ? 'border- border-amber-500': ''">
 <!-- Header：px-5 py-3.5（work item §2 卡片骨架） -->
 <div class="px-5 py-3.5 border-b border-border/50 flex items-center justify-between">
 <div class="flex items-center gap-2">
 <span class="icon-[lucide--git-compare-arrows] text-primary" />
 <h3 class="text-sm font-semibold">
 Hash 新鲜度
 </h3>
 <span class="text-xs text-muted-foreground">本地索引 vs 远端 HEAD</span>
 </div>
 <Button
 variant="outline"
 size="sm"
 class=" text-xs":disabled="checking"
 @click="refresh"
 >
 <span:class="checking ? 'icon-[lucide--loader-circle] animate-spin mr-1.5': 'icon-[lucide--refresh-cw] mr-1.5'" />
 {{ checking ? '检查中...': '立即检查' }}
 </Button>
 </div>
 <!-- Body：（work item §2 卡片骨架） -->
 <div class="">
 <!-- 首次加载状态（work item §5.4） -->
 <div v-if="loading" class="flex items-center gap-2 py-8 justify-center">
 <span class="icon-[lucide--loader-circle] text-2xl text-primary animate-spin" />
 <span class="text-sm text-muted-foreground">加载新鲜度状态...</span>
 </div>
 <template v-else>
 <!-- 三态主内容区（work item §5） -->
 <div class="flex items-start gap-3">
 <!-- 状态图标（语义色，不使用 teal）-->
 <span
 v-if="freshnessState === 'fresh'"
 class="icon-[lucide--check-circle-2] text-2xl text-emerald-500 shrink-0 mt-0.5"
 />
 <span
 v-else-if="freshnessState === 'stale'"
 class="icon-[lucide--alert-triangle] text-2xl text-amber-500 shrink-0 mt-0.5"
 />
 <span
 v-else
 class="icon-[lucide--help-circle] text-2xl text-muted-foreground shrink-0 mt-0.5"
 />
 <!-- 文案区（work item §7 逐字锁定） -->
 <div class="flex-1 space-y-1" role="status" aria-live="polite">
 <p class="text-base font-semibold text-foreground">
 <template v-if="freshnessState === 'fresh'">
 索引最新
 </template>
 <template v-else-if="freshnessState === 'stale'">
 索引已过期
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
 <template v-else>
 请点击「立即检查」获取最新提交
 </template>
 </p>
 </div>
 </div>
 <!-- SHA 对比区 -->
 <div class="mt-4 space-y-1.5">
 <div class="flex items-center gap-2 text-xs text-muted-foreground">
 <span>本地</span>
 <TooltipProvider:delay-duration="300">
 <Tooltip>
 <TooltipTrigger as-child>
 <button
 class=" rounded hover:bg-muted/40 transition-colors"
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
 <Badge:variant="freshnessState === 'stale' ? 'outline': 'secondary'":class="freshnessState === 'stale' ? 'font-mono text-amber-600': 'font-mono'"
 >
 {{ remoteSha }}
 </Badge>
 </template>
 </div>
 <!-- 相对时间 + Tooltip 绝对时间（work item §5/§7） -->
 <TooltipProvider:delay-duration="300">
 <Tooltip>
 <TooltipTrigger as-child>
 <span class="text-xs text-muted-foreground cursor-default">
 {{ lastCheckedAt ? `距离上次检查 ${formatRelativeTime(lastCheckedAt)}`: '尚未检查过' }}
 </span>
 </TooltipTrigger>
 <TooltipContent v-if="lastCheckedAt">
 <p>{{ new Date(lastCheckedAt).toLocaleString('zh-CN') }}</p>
 </TooltipContent>
 </Tooltip>
 </TooltipProvider>
 </div>
 <!-- 错误提示（work item §5.4 / §7） -->
 <p v-if="errorMessage" class="mt-2 text-xs text-destructive">
 {{ errorMessage }}
 </p>
 </template>
 </div>
 </div>
</template>
