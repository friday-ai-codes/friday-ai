<script setup lang="ts">
/**
 * PR 结果卡片 -- 编码完成后展示 Pull Request 链接和分支信息。
 *
 * 复用 ExportSuccessCard 的外链模式：text-primary hover:underline + external-link 图标。
 */
import { Badge } from '~/components/ui/badge'
defineProps<{
 prUrl: string
 branchName: string
 modifiedFilesCount: number
}>
</script>
<template>
 <div class="card mt-2 animate-fade-in">
 <div class="px-4 py-3 border-b border-border/50 flex items-center gap-2">
 <span class="icon-[lucide--git-pull-request] text-primary" />
 <span class="text-sm font-semibold">PR 已创建</span>
 <Badge
 variant="outline"
 class="ml-auto text-emerald-500 border-emerald-500/30 bg-emerald-500/5"
 >
 编码完成
 </Badge>
 </div>
 <div class=" space-y-1.5">
 <a:href="prUrl"
 target="_blank"
 rel="noopener noreferrer"
 class="text-sm text-primary hover:underline flex items-center gap-1"
 >
 查看 Pull Request
 <span class="icon-[lucide--external-link] text-[10px]" />
 </a>
 <p class="text-xs text-muted-foreground">
 分支: {{ branchName }} · {{ modifiedFilesCount }} 个文件变更
 </p>
 </div>
 </div>
</template>
