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
 * - ~/stores/prompts::activateVersion（-01 Task 3 交付）
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
  versions: PromptVersion[]
}>()

const store = usePromptsStore()
const { confirm } = useConfirmDialog()
const { success } = useToast()
const { handleError } = useErrorHandler()

// DESC 排序：版本号大的在前
const sortedVersions = computed<PromptVersion[]>(() =>
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

const v1Version = computed(() =>
  sortedVersions.value.find(v => v.id === selectedV1.value) ?? null,
)
const v2Version = computed(() =>
  sortedVersions.value.find(v => v.id === selectedV2.value) ?? null,
)

const activeVersionId = computed(() => props.prompt.active_version?.id ?? null)

function isActive(v: PromptVersion): boolean {
  return v.id === activeVersionId.value
}

/** 选中的任一版本若非 active 版本，允许回滚到它（优先 v2 侧） */
const rollbackCandidate = computed<PromptVersion | null>(() => {
  if (v2Version.value && !isActive(v2Version.value))
    return v2Version.value
  if (v1Version.value && !isActive(v1Version.value))
    return v1Version.value
  return null
})

async function handleRollback(): Promise<void> {
  const target = rollbackCandidate.value
  if (!target)
    return
  const userLabel = target.created_by === null ? '未知用户' : `user#${target.created_by}`
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
  <div class="space-y-5">
    <!-- 标题 + 总计 -->
    <div class="flex items-end justify-between gap-2">
      <div>
        <h4 class="text-sm font-semibold text-foreground flex items-center gap-2">
          <span class="icon-[lucide--history] text-primary text-base" />
          版本历史
        </h4>
        <p class="text-xs text-muted-foreground mt-0.5">
          共 {{ sortedVersions.length }} 个版本，按时间倒序展示
        </p>
      </div>
    </div>

    <!-- 版本列表：DESC 排序 -->
    <ul v-if="sortedVersions.length > 0" class="space-y-2">
      <li
        v-for="v in sortedVersions"
        :key="v.id"
        class="rounded-xl border p-3 transition-colors"
        :class="isActive(v)
          ? 'border-primary/40 bg-primary/4 shadow-sm'
          : 'border-border/60 bg-card hover:border-border'"
      >
        <div class="flex items-start justify-between gap-3">
          <div class="flex-1 min-w-0 space-y-1">
            <div class="flex items-center gap-2 flex-wrap">
              <span
                class="font-mono text-xs font-semibold px-1.5 py-0.5 rounded"
                :class="isActive(v)
                  ? 'bg-primary/15 text-primary'
                  : 'bg-muted text-foreground'"
              >
                v{{ v.version }}
              </span>
              <Badge v-if="isActive(v)" variant="default">
                当前版本
              </Badge>
              <span class="text-[11px] text-muted-foreground">
                {{ new Date(v.created_at).toLocaleString('zh-CN') }}
              </span>
            </div>
            <p
              class="text-xs leading-relaxed text-foreground/80"
              :class="!v.change_note && 'italic text-muted-foreground'"
            >
              {{ v.change_note || '（保存时未填写变更说明）' }}
            </p>
          </div>
        </div>
      </li>
    </ul>

    <!-- 单版本场景：inline 提示 -->
    <div
      v-if="sortedVersions.length === 1"
      class="rounded-lg border border-dashed border-border/60 bg-muted/30 px-3 py-2 text-xs text-muted-foreground"
    >
      仅有一个版本，保存后会自动追加新版本供对比
    </div>

    <!-- 多版本：Select 选择器 + diff -->
    <div v-if="sortedVersions.length >= 2" class="space-y-3 pt-2 border-t border-border/50">
      <div>
        <h5 class="text-sm font-semibold text-foreground flex items-center gap-2 mb-3">
          <span class="icon-[lucide--git-compare] text-primary text-base" />
          版本对比
        </h5>
        <div class="grid grid-cols-2 gap-3">
          <div class="space-y-1.5">
            <label class="text-xs font-medium text-foreground">对比版本 A</label>
            <Select v-model="selectedV1">
              <SelectTrigger class="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem v-for="v in sortedVersions" :key="v.id" :value="v.id">
                  v{{ v.version }}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div class="space-y-1.5">
            <label class="text-xs font-medium text-foreground">对比版本 B</label>
            <Select v-model="selectedV2">
              <SelectTrigger class="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem v-for="v in sortedVersions" :key="v.id" :value="v.id">
                  v{{ v.version }}
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>

      <PromptVersionDiff
        v-if="v1Version && v2Version"
        :v1="v1Version"
        :v2="v2Version"
      />

      <div class="flex justify-end">
        <Button
          variant="outline"
          :disabled="!rollbackCandidate"
          :title="rollbackCandidate ? '' : '当前正是此版本'"
          @click="handleRollback"
        >
          <span class="icon-[lucide--undo-2] mr-1.5 text-sm" />
          恢复到此版本
        </Button>
      </div>
    </div>
  </div>
</template>
