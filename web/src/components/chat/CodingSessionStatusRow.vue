<script setup lang="ts">
/**
 * Phase：单条 CodingSession 状态行
 *
 * 单行展示一个 CodingSession：
 * 仓库名 → 状态徽章 → 分支链 → commit sha + 复制 → PR 链 → 重试按钮
 *
 * 单一职责：受控渲染 + retry emit；本组件不发请求，重试动作交给调用方
 * （TechPlanCard 调 chat store retrySingleRepository action）。
 */
import type { CodingPlanSessionRuntime } from '~/types/chat'
import { computed } from 'vue'
import StatusBadge from '~/components/common/StatusBadge.vue'
import { Button } from '~/components/ui/button'
import { useToast } from '~/composables/useToast'
import { buildBranchUrl, buildCommitUrl, extractGitWebBase } from '~/lib/gitUrl'
import RelevanceBadge from './RelevanceBadge.vue'
const props = defineProps<{
 session: CodingPlanSessionRuntime
 repoGitUrl: string
 /**
 * Phase：可选 conversationId 用于在仓库名旁渲染 RelevanceBadge。
 * 不传则不渲染（向后兼容既有调用方）。
 */
 conversationId?: string
 onRetry?: (sessionId: string) => void | Promise<void>
}>
const effectiveConversationId = computed( => props.conversationId || '')
const emit = defineEmits<{
 (e: 'retry', sessionId: string): void
}>
const { success } = useToast
const repoWebUrl = computed( => extractGitWebBase(props.repoGitUrl))
const branchUrl = computed( =>
 props.session.branch_name
 ? buildBranchUrl(props.repoGitUrl, props.session.branch_name): '',
)
const commitUrl = computed( =>
 props.session.commit_sha
 ? buildCommitUrl(props.repoGitUrl, props.session.commit_sha): '',
)
const commitShaShort = computed( => props.session.commit_sha.slice(0, 8))
const isFailed = computed( => props.session.status === 'failed')
const isCompleted = computed( => props.session.status === 'completed')
async function copyCommitSha {
 if (!props.session.commit_sha)
 return
 await navigator.clipboard.writeText(props.session.commit_sha)
 success('已复制 commit sha')
}
function handleRetry {
 props.onRetry?.(props.session.session_id)
 emit('retry', props.session.session_id)
}
</script>
<template>
 <div class="flex flex-wrap items-center gap-2 text-xs py-1.5 border-b border-border/30 last:border-b-0">
 <!-- 仓库名（可点击跳 web base） -->
 <a
 v-if="repoWebUrl":href="repoWebUrl"
 target="_blank"
 rel="noopener noreferrer"
 class="flex items-center gap-1 text-foreground hover:text-primary":aria-label="`打开仓库 ${session.repository_name}`"
 >
 <span class="icon-[lucide--folder-git-2] text-sm" />
 <span class="font-medium">{{ session.repository_name }}</span>
 </a>
 <span v-else class="flex items-center gap-1 text-foreground">
 <span class="icon-[lucide--folder-git-2] text-sm" />
 <span class="font-medium">{{ session.repository_name }}</span>
 </span>
 <!-- Phase：相关性徽章（store 无 trace 时优雅降级不渲染） -->
 <RelevanceBadge
 v-if="effectiveConversationId":repository-id="session.repository_id":conversation-id="effectiveConversationId"
 />
 <!-- 状态徽章 -->
 <StatusBadge type="codingSession":status="session.status" />
 <!-- 分支链 -->
 <a
 v-if="branchUrl":href="branchUrl"
 target="_blank"
 rel="noopener noreferrer"
 class="flex items-center gap-1 text-muted-foreground hover:text-primary":aria-label="`打开分支 ${session.branch_name}`"
 >
 <span class="icon-[lucide--git-branch] text-sm" />
 <code class="text-xs">{{ session.branch_name }}</code>
 </a>
 <!-- commit sha + 复制按钮 -->
 <span v-if="session.commit_sha" class="flex items-center gap-1 text-muted-foreground">
 <span class="icon-[lucide--git-commit] text-sm" />
 <a
 v-if="commitUrl":href="commitUrl"
 target="_blank"
 rel="noopener noreferrer"
 class="font-mono text-xs hover:text-primary":title="session.commit_sha"
 >{{ commitShaShort }}</a>
 <span
 v-else
 class="font-mono text-xs":title="session.commit_sha"
 >{{ commitShaShort }}</span>
 <button
 type="button"
 class="text-muted-foreground hover:text-primary":aria-label="`复制 commit sha ${session.commit_sha}`"
 @click="copyCommitSha"
 >
 <span class="icon-[lucide--copy] text-sm" />
 </button>
 </span>
 <!-- PR 链（completed） -->
 <a
 v-if="isCompleted && session.pr_url":href="session.pr_url"
 target="_blank"
 rel="noopener noreferrer"
 class="flex items-center gap-1 text-emerald-500 hover:underline"
 aria-label="打开合并请求"
 >
 <span class="icon-[lucide--git-pull-request] text-sm" />
 <span>查看 PR</span>
 </a>
 <!-- 错误信息（failed） -->
 <span
 v-if="isFailed && session.error_message"
 class="flex items-center gap-1 text-destructive truncate max-w-xs":title="session.error_message"
 >
 <span class="icon-[lucide--alert-circle] text-sm" />
 <span>{{ session.error_message }}</span>
 </span>
 <!-- 重试按钮（failed） -->
 <Button
 v-if="isFailed"
 variant="outline"
 size="sm"
 class="ml-auto":aria-label="`重试 ${session.repository_name} 的编码会话`"
 @click="handleRetry"
 >
 <span class="icon-[lucide--rotate-cw] mr-1" />
 重试
 </Button>
 </div>
</template>
