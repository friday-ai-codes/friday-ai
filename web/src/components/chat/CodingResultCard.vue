<script setup lang="ts">
/**
 * 编码结果卡片 -- 编码完成后展示 Pull Request 链接和分支信息。
 *
 * 复用 ExportSuccessCard 的外链模式：text-primary hover:underline + external-link 图标。
 *: 支持无 prUrl 但有 branchUrl 时展示分支链接（跳过 PR 场景）。
 */
import { computed } from 'vue'
import { Badge } from '~/components/ui/badge'
const props = defineProps<{
 prUrl: string
 branchName: string
 modifiedFilesCount: number
 branchUrl?: string
}>
const hasPR = computed( => !!props.prUrl)
const title = computed( => hasPR.value ? 'PR 已创建': '编码完成')
</script>
<template>
 <div class="card mt-2 animate-fade-in">
 <div class="px-4 py-3 border-b border-border/50 flex items-center gap-2">
 <span class="icon-[lucide--git-pull-request] text-primary" />
 <span class="text-sm font-semibold">{{ title }}</span>
 <Badge
 variant="outline"
 class="ml-auto text-emerald-500 border-emerald-500/30 bg-emerald-500/5"
 >
 编码完成
 </Badge>
 </div>
 <div class=" space-y-1.5">
 <!-- PR 链接 (有 PR 时) -->
 <a
 v-if="hasPR":href="prUrl"
 target="_blank"
 rel="noopener noreferrer"
 class="text-sm text-primary hover:underline flex items-center gap-1"
 >
 查看 Pull Request
 <span class="icon-[lucide--external-link] text-[10px]" />
 </a>
 <!-- 分支链接 (跳过 PR 时, ) -->
 <a
 v-else-if="branchUrl":href="branchUrl"
 target="_blank"
 rel="noopener noreferrer"
 class="text-sm text-primary hover:underline flex items-center gap-1"
 >
 查看分支
 <span class="icon-[lucide--external-link] text-[10px]" />
 </a>
 <p class="text-xs text-muted-foreground">
 分支: {{ branchName }} · {{ modifiedFilesCount }} 个文件变更
 </p>
 </div>
 </div>
</template>
