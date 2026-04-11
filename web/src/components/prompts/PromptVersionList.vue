<script setup lang="ts">
/**
 * PromptVersionList.vue — Sheet 抽屉内 Versions Tab 的主面板
 *
 * 职责：
 * - DESC 排序展示所有版本，标记 active_version 为 `当前版本` Badge
 * - 提供两个 Select 选择 v1/v2 对比 → 嵌入 PromptVersionDiff 子组件
 * - "恢复到此版本" 按钮 → useConfirmDialog 二次确认 → store.activateVersion
 * - 成功后 `已回滚到 v{N}` toast
 *
 * 上游依赖：
 * - ~/stores/prompts:activateVersion（Plan Task 3 交付）
 * - ~/composables/useConfirmDialog（既有，程序式 AlertDialog）
 * - ~/composables/useToast + useErrorHandler（既有）
 * - ./PromptVersionDiff.vue（本 Plan Task 2 Part A）
 */
import type { PromptDetail, PromptVersion } from '~/types/prompts'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import {
 Select,
 SelectContent,
 SelectItem,
 SelectTrigger,
 SelectValue,
} from '~/components/ui/select'
import { useConfirmDialog } from '~/composables/useConfirmDialog'
import { useErrorHandler } from '~/composables/useErrorHandler'
import { useToast } from '~/composables/useToast'
import { usePromptsStore } from '~/stores/prompts'
import PromptVersionDiff from './PromptVersionDiff.vue'
const props = defineProps<{
 prompt: PromptDetail
 versions: PromptVersion
}>
const store = usePromptsStore
const { confirm } = useConfirmDialog
const { success } = useToast
const { handleError } = useErrorHandler
// DESC 排序：版本号大的在前
const sortedVersions = computed<PromptVersion>( =>
 [...props.versions].sort((a, b) => b.version - a.version),
)
// 默认：v1 = 最早，v2 = 最新（便于用户一眼看到最新变更）
const selectedV1 = ref<string>('')
const selectedV2 = ref<string>('')
watch(
 sortedVersions,
 (list) => {
 if (list.length >= 2) {
 selectedV1.value = list[list.length - 1].id // 最早
 selectedV2.value = list[0].id // 最新
 }
 else if (list.length === 1) {
 selectedV1.value = list[0].id
 selectedV2.value = list[0].id
 }
 },
 { immediate: true },
)
const v1Version = computed( =>
 sortedVersions.value.find(v => v.id === selectedV1.value) ?? null,
)
const v2Version = computed( =>
 sortedVersions.value.find(v => v.id === selectedV2.value) ?? null,
)
const activeVersionId = computed( => props.prompt.active_version?.id ?? null)
function isActive(v: PromptVersion): boolean {
 return v.id === activeVersionId.value
}
/** 选中的任一版本若非 active 版本，允许回滚到它（优先 v2 侧） */
const rollbackCandidate = computed<PromptVersion | null>( => {
 if (v2Version.value && !isActive(v2Version.value))
 return v2Version.value
 if (v1Version.value && !isActive(v1Version.value))
 return v1Version.value
 return null
})
async function handleRollback: Promise<void> {
 const target = rollbackCandidate.value
 if (!target)
 return
 const userLabel = target.created_by === null ? '未知用户': `user#${target.created_by}`
 const timeLabel = new Date(target.created_at).toLocaleString('zh-CN')
 const ok = await confirm({
 title: '确认回滚',
 description: `将回滚到 v${target.version}，由 ${userLabel} 于 ${timeLabel} 创建。回滚会生成新的版本快照。`,
 confirmText: '确认回滚',
 })
 if (!ok)
 return
 try {
 await store.activateVersion(props.prompt.id, target.id)
 success(`已回滚到 v${target.version}`)
 }
 catch (e) {
 handleError(e, '版本回滚')
 }
}
</script>
<template>
 <div class="space-y-4">
 <h4 class="text-sm font-semibold text-foreground">
 版本历史
 </h4>
 <!-- 版本列表：DESC 排序 -->
 <ul v-if="sortedVersions.length > 0" class="space-y-2">
 <li
 v-for="v in sortedVersions":key="v.id"
 class="flex items-center justify-between gap-2 rounded-lg border border-border/50 "
 >
 <div class="flex-1 min-w-0">
 <div class="flex items-center gap-2">
 <span class="text-xs font-semibold">v{{ v.version }}</span>
 <Badge v-if="isActive(v)" variant="default">
 当前版本
 </Badge>
 </div>
 <p class="text-xs text-muted-foreground mt-1 truncate">
 {{ v.change_note || '（无说明）' }}
 </p>
 <p class="text-[10px] text-muted-foreground">
 {{ new Date(v.created_at).toLocaleString('zh-CN') }}
 </p>
 </div>
 </li>
 </ul>
 <!-- 单版本场景：inline 提示 -->
 <p v-if="sortedVersions.length === 1" class="text-xs text-muted-foreground">
 仅有一个版本，保存后会自动追加新版本供对比
 </p>
 <!-- 多版本：Select 选择器 + diff -->
 <div v-if="sortedVersions.length >= 2" class="space-y-3">
 <div class="grid grid-cols-2 gap-3">
 <div class="space-y-1.5">
 <label class="text-xs text-muted-foreground">对比版本 A</label>
 <Select v-model="selectedV1">
 <SelectTrigger>
 <SelectValue />
 </SelectTrigger>
 <SelectContent>
 <SelectItem v-for="v in sortedVersions":key="v.id":value="v.id">
 v{{ v.version }}
 </SelectItem>
 </SelectContent>
 </Select>
 </div>
 <div class="space-y-1.5">
 <label class="text-xs text-muted-foreground">对比版本 B</label>
 <Select v-model="selectedV2">
 <SelectTrigger>
 <SelectValue />
 </SelectTrigger>
 <SelectContent>
 <SelectItem v-for="v in sortedVersions":key="v.id":value="v.id">
 v{{ v.version }}
 </SelectItem>
 </SelectContent>
 </Select>
 </div>
 </div>
 <PromptVersionDiff
 v-if="v1Version && v2Version":v1="v1Version":v2="v2Version"
 />
 <div class="flex justify-end">
 <Button
 variant="outline":disabled="!rollbackCandidate":title="rollbackCandidate ? '': '当前正是此版本'"
 @click="handleRollback"
 >
 恢复到此版本
 </Button>
 </div>
 </div>
 </div>
</template>
