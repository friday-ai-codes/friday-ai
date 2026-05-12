<script setup lang="ts">
import { computed } from 'vue'
import StatusBadge from '~/components/common/StatusBadge.vue'
interface ChangedFiles {
 added?: string
 modified?: string
 deleted?: string
}
// 注：文件级实时进度（当前正在索引的文件 + N/M 计数）已迁移到
// RepositoryIndexCard 内部展示，避免与本卡片在视觉上重复。
// 此组件专注于本次索引涉及的变更文件分组（增量索引时有意义）。
const props = defineProps<{
 repositoryId: string
 indexHistoryId: string | null
 changedFiles: ChangedFiles
 isIndexing: boolean
}>
const addedFiles = computed( => props.changedFiles.added || )
const modifiedFiles = computed( => props.changedFiles.modified || )
const deletedFiles = computed( => props.changedFiles.deleted || )
const isEmpty = computed(
 => addedFiles.value.length === 0 && modifiedFiles.value.length === 0 && deletedFiles.value.length === 0,
)
</script>
<template>
 <!-- 仅在 INDEXING 状态时渲染（work item §6.2 挂载条件） -->
 <div v-if="isIndexing" class="card">
 <!-- Header：px-5 py-3.5（work item §2 卡片骨架） -->
 <div class="px-5 py-3.5 border-b border-border/50 flex items-center gap-2">
 <span class="icon-[lucide--clock] text-primary" />
 <h3 class="text-sm font-semibold">
 本次索引变更
 </h3>
 </div>
 <!-- Body： -->
 <div class="">
 <!-- 空状态：全量首次索引无变更文件清单（work item §7） -->
 <div v-if="isEmpty" class="flex items-center gap-2 text-sm text-muted-foreground">
 <span class="icon-[lucide--info]" />
 <span>全量首次索引（无变更文件清单）</span>
 </div>
 <div v-else class="space-y-4">
 <!-- 新增文件组 -->
 <div v-if="addedFiles.length > 0">
 <p class="text-xs text-muted-foreground mb-2">
 新增 ({{ addedFiles.length }})
 </p>
 <div class="space-y-1">
 <div
 v-for="file in addedFiles":key="file"
 class="flex items-center justify-between gap-2 px-3 py-2 rounded-lg hover:bg-muted/30 transition-colors"
 >
 <div class="flex items-center gap-2 min-w-0">
 <span class="icon-[lucide--plus] text-emerald-600 text-xs shrink-0" />
 <span class="font-mono text-xs truncate text-foreground":title="file">{{ file }}</span>
 </div>
 <StatusBadge type="index" status="running" size="sm" />
 </div>
 </div>
 </div>
 <!-- 修改文件组 -->
 <div v-if="modifiedFiles.length > 0">
 <p class="text-xs text-muted-foreground mb-2">
 修改 ({{ modifiedFiles.length }})
 </p>
 <div class="space-y-1">
 <div
 v-for="file in modifiedFiles":key="file"
 class="flex items-center justify-between gap-2 px-3 py-2 rounded-lg hover:bg-muted/30 transition-colors"
 >
 <div class="flex items-center gap-2 min-w-0">
 <span class="icon-[lucide--pencil] text-amber-600 text-xs shrink-0" />
 <span class="font-mono text-xs truncate text-foreground":title="file">{{ file }}</span>
 </div>
 <StatusBadge type="index" status="running" size="sm" />
 </div>
 </div>
 </div>
 <!-- 删除文件组（icon text-destructive，work item §6.2） -->
 <div v-if="deletedFiles.length > 0">
 <p class="text-xs text-muted-foreground mb-2">
 删除 ({{ deletedFiles.length }})
 </p>
 <div class="space-y-1">
 <div
 v-for="file in deletedFiles":key="file"
 class="flex items-center justify-between gap-2 px-3 py-2 rounded-lg hover:bg-muted/30 transition-colors"
 >
 <div class="flex items-center gap-2 min-w-0">
 <span class="icon-[lucide--minus] text-destructive text-xs shrink-0" />
 <span class="font-mono text-xs truncate text-foreground":title="file">{{ file }}</span>
 </div>
 <StatusBadge type="index" status="completed" size="sm" />
 </div>
 </div>
 </div>
 </div>
 </div>
 </div>
</template>
