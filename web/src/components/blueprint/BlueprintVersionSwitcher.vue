<script setup lang="ts">
/**
 * 版本切换器（Phase 115-04，UI-SPEC §9.1）。
 *
 * **数据源是既有的 `deliveryArtifacts.getArtifactTimeline(artifactId)`（零新端点）** ——
 * 由父层查询后把 `versions[]` 传进来，本组件只做呈现与派发。
 *
 * ⭐ **版本原因的唯一判据是 115-02 的 `producedByReason(produced_by_ref)`**（五档查表：
 * 四个前缀 + AI 产出兜底）。⛔ 组件内**不自写前缀匹配** —— 判据分叉后两处会各自漂移，
 * 而症状只是徽标写错、不报错。
 *
 * ⭐ **非 current 版本 = 历史模式**：切换后由页面（115-06）渲染常驻提示条
 * 「正在查看历史版本 v{n}，操作已禁用」+「回到当前版本」，并让**所有写动作组件不渲染**。
 * 本组件只负责 emit `change` / `compare`，⛔ 自身不持有写动作。
 */

import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '~/components/ui/popover'
import { producedByReason } from '~/config/blueprintStatus'

/** `ArtifactTimeline.versions[]` 的必要子集（⛔ 不重新封装那个既有端点）。 */
export interface BlueprintVersionEntry {
  id: string
  version_no: number
  produced_by_ref: string
  is_current: boolean
  supersedes_id: string | null
  created_at: string
}

const props = withDefaults(defineProps<{
  versions?: BlueprintVersionEntry[]
  currentVersionId?: string | null
}>(), {
  versions: () => [],
  currentVersionId: null,
})

const emit = defineEmits<{
  change: [versionId: string]
  compare: [baseVersionId: string]
}>()

const { t } = useI18n()

interface VersionRow extends BlueprintVersionEntry {
  reasonLabel: string
  reasonIcon: string
  reasonVariant: 'secondary' | 'info' | 'warning' | 'destructive' | 'muted'
  selected: boolean
}

const rows = computed<VersionRow[]>(() =>
  props.versions.map((version) => {
    const reason = producedByReason(version.produced_by_ref)
    return {
      ...version,
      reasonLabel: t(reason.labelKey),
      reasonIcon: reason.icon,
      reasonVariant: reason.variant as VersionRow['reasonVariant'],
      selected: version.id === props.currentVersionId,
    }
  }),
)

const activeRow = computed(() =>
  rows.value.find(row => row.selected) ?? rows.value.find(row => row.is_current) ?? null,
)

function formatTime(iso: string): string {
  if (!iso)
    return ''
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString('zh-CN', { hour12: false })
}
</script>

<template>
  <Popover>
    <PopoverTrigger as-child>
      <Button variant="outline" size="sm" data-testid="blueprint-version-switcher">
        <span class="icon-[lucide--history] mr-1.5" aria-hidden="true" />
        <span v-if="activeRow">v{{ activeRow.version_no }}</span>
        <span v-else>{{ t('knowledge.blueprints.version.switch') }}</span>
      </Button>
    </PopoverTrigger>
    <PopoverContent class="w-80 p-1.5" align="end">
      <p v-if="rows.length === 0" class="px-2 py-3 text-xs text-muted-foreground">
        {{ t('knowledge.blueprints.version.empty') }}
      </p>
      <ul v-else class="space-y-1">
        <li v-for="row in rows" :key="row.id" class="flex items-center gap-1.5">
          <button
            type="button"
            data-testid="blueprint-version-item"
            :data-version-id="row.id"
            :aria-pressed="row.selected"
            class="flex min-w-0 flex-1 items-center gap-1.5 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-muted"
            :class="row.selected ? 'bg-muted' : ''"
            @click="emit('change', row.id)"
          >
            <span class="text-xs font-medium text-foreground">v{{ row.version_no }}</span>
            <Badge v-if="row.is_current" variant="success">
              {{ t('knowledge.blueprints.version.current') }}
            </Badge>
            <Badge :variant="row.reasonVariant" data-testid="blueprint-version-reason">
              <span :class="`icon-[${row.reasonIcon}]`" aria-hidden="true" />
              {{ row.reasonLabel }}
            </Badge>
            <span class="ml-auto shrink-0 text-[11px] text-muted-foreground">{{ formatTime(row.created_at) }}</span>
          </button>
          <Button
            variant="ghost"
            size="icon-sm"
            data-testid="blueprint-version-compare"
            :aria-label="t('knowledge.blueprints.diff.baseline')"
            :title="t('knowledge.blueprints.diff.baseline')"
            @click="emit('compare', row.id)"
          >
            <span class="icon-[lucide--git-compare]" aria-hidden="true" />
          </Button>
        </li>
      </ul>
    </PopoverContent>
  </Popover>
</template>
