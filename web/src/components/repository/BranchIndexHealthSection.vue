<script setup lang="ts">
import type { BranchIndexRow } from '~/api/repositories'
import { Badge } from '~/components/ui/badge'
const props = defineProps<{
 row: BranchIndexRow | null
}>
function formatWhen(iso: string | null): string {
 if (!iso)
 return '—'
 return new Date(iso).toLocaleString('zh-CN')
}
</script>
<template>
 <div v-if="!props.row" class="rounded-lg border border-dashed border-border/60 bg-muted/20 px-4 py-6 text-center text-sm text-muted-foreground">
 暂无分支索引数据
 </div>
 <div v-else class="rounded-lg border border-border/50 bg-muted/20 space-y-3">
 <div class="flex items-center justify-between gap-2 flex-wrap">
 <span class="text-xs font-medium text-muted-foreground">当前分支健康</span>
 <Badge:variant="props.row.is_stale ? 'destructive': 'secondary'"
 class="text-[10px]"
 >
 {{ props.row.is_stale ? 'stale': 'fresh' }}
 </Badge>
 </div>
 <dl class="grid gap-3 sm:grid-cols-2 text-sm">
 <div>
 <dt class="text-xs text-muted-foreground">
 上次索引时间
 </dt>
 <dd class="mt-0.5 font-medium text-foreground tabular-nums">
 {{ formatWhen(props.row.last_indexed_at) }}
 </dd>
 </div>
 <div>
 <dt class="text-xs text-muted-foreground">
 索引提交 SHA
 </dt>
 <dd class="mt-0.5 font-mono text-xs break-all text-foreground">
 {{ props.row.last_indexed_commit_sha || '—' }}
 </dd>
 </div>
 <div>
 <dt class="text-xs text-muted-foreground">
 有效块数
 </dt>
 <dd class="mt-0.5 font-medium tabular-nums">
 {{ props.row.effective_chunks_count }}
 </dd>
 </div>
 <div>
 <dt class="text-xs text-muted-foreground">
 基准分支
 </dt>
 <dd class="mt-0.5">
 {{ props.row.is_base_branch ? '是': '否' }}
 </dd>
 </div>
 </dl>
 </div>
</template>
