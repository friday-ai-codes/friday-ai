<script setup lang="ts">
/**
 * 版本树切换器（quick-260806 节点重跑 → 版本谱系）。
 *
 * 数据源是 stages API 的 `versions[]`（带 `version_label` 谱系标签），分组逻辑全部委托
 * `~/utils/blueprintVersionTree.buildVersionTree`（纯函数，⛔ 组件内不写第二份）。
 *
 * 展示形态：按谱系根分节（"2.1" 归在 "2" 之下），同一 label 组取最新一条为代表、
 * 组内其余版本可展开查看；当前版本带「当前」徽标。选择即 emit `change(version_id)`，
 * 加载机制沿用页面既有的 `?version=` 参数（本组件只 emit 不发请求）。
 *
 * ⭐ 版本原因徽标沿用 `producedByReason`（与 `BlueprintVersionSwitcher` 同一判据源）。
 */

import type { BlueprintStageVersionRow } from '~/types/blueprint'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '~/components/ui/popover'
import { producedByReason } from '~/config/blueprintStatus'
import { buildVersionTree, versionDisplayLabel } from '~/utils/blueprintVersionTree'

const props = withDefaults(defineProps<{
  versions?: BlueprintStageVersionRow[]
  currentVersionId?: string | null
}>(), {
  versions: () => [],
  currentVersionId: null,
})

const emit = defineEmits<{
  change: [versionId: string]
  /** 以该版本为基线打开 diff（与旧 `BlueprintVersionSwitcher` 的 `compare` 同语义）。 */
  compare: [baseVersionId: string]
}>()

const { t } = useI18n()

const tree = computed(() => buildVersionTree(props.versions))

/** 触发器文案：正在查看的版本（无匹配时回落 is_current 那条）。 */
const activeVersion = computed(() => {
  const rows = props.versions
  return rows.find(row => row.version_id === props.currentVersionId)
    ?? rows.find(row => row.is_current)
    ?? null
})

/** 展开「组内全部版本」的组 label 集合（代表之外的旧版本默认折叠）。 */
const expandedGroups = ref<Set<string>>(new Set())

function groupKey(rootLabel: string, label: string): string {
  return `${rootLabel}::${label}`
}

function toggleGroup(rootLabel: string, label: string): void {
  const key = groupKey(rootLabel, label)
  const next = new Set(expandedGroups.value)
  if (next.has(key))
    next.delete(key)
  else next.add(key)
  expandedGroups.value = next
}

function reasonOf(ref: string) {
  return producedByReason(ref)
}

/** 面板内时间：`M/d HH:mm`（完整时间放 title；整串日期会把徽标挤到换行/裁切）。 */
function formatTime(iso: string): string {
  if (!iso)
    return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime()))
    return iso
  const pad = (n: number): string => String(n).padStart(2, '0')
  return `${date.getMonth() + 1}/${date.getDate()} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function fullTime(iso: string): string {
  if (!iso)
    return ''
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString('zh-CN', { hour12: false })
}

/**
 * 组头只在**有层级信息**时渲染：旧数据根（legacy）与「根下只有一个组」的根都不出组头——
 * 「谱系 v10」+「v10」这种组头是纯重复（quick-260806 实测反馈：满屏噪音）。
 */
function showRootHeader(root: { legacy: boolean, groups: unknown[] }): boolean {
  return !root.legacy && root.groups.length > 1
}
</script>

<template>
  <Popover>
    <PopoverTrigger as-child>
      <Button variant="outline" size="sm" data-testid="blueprint-version-tree">
        <span class="icon-[lucide--git-branch] mr-1.5" aria-hidden="true" />
        <span v-if="activeVersion">{{ versionDisplayLabel(activeVersion) }}</span>
        <span v-else>{{ t('knowledge.blueprints.version.switch') }}</span>
      </Button>
    </PopoverTrigger>
    <PopoverContent class="max-h-96 w-96 overflow-y-auto p-1.5" align="end">
      <p v-if="tree.length === 0" class="px-2 py-3 text-xs text-muted-foreground">
        {{ t('knowledge.blueprints.version.empty') }}
      </p>
      <div v-else class="space-y-0.5">
        <section
          v-for="root in tree"
          :key="root.rootLabel"
          data-testid="blueprint-version-tree-root"
          :data-root="root.rootLabel"
        >
          <!-- ⭐ 组头只在有层级信息时出现（多个 label 组归于同一谱系根）；旧数据与
               单组谱系直接平铺 —— 「谱系 v10」+「v10」是纯重复噪音。 -->
          <p
            v-if="showRootHeader(root)"
            class="px-2 pb-0.5 pt-1.5 text-[11px] font-medium text-muted-foreground/80"
          >
            {{ t('knowledge.blueprints.version.treeRoot', { label: root.rootLabel }) }}
          </p>
          <ul class="space-y-0.5">
            <li
              v-for="group in root.groups"
              :key="group.label || group.representative.version_id"
              data-testid="blueprint-version-tree-group"
              :data-label="group.displayLabel"
            >
              <!-- 组代表：仅在组头存在时才对子 label 缩进（没有组头就没有层级可言） -->
              <div class="flex items-center gap-1" :class="showRootHeader(root) && group.label !== root.rootLabel ? 'pl-4' : ''">
                <button
                  type="button"
                  data-testid="blueprint-version-tree-item"
                  :data-version-id="group.representative.version_id"
                  :aria-pressed="group.representative.version_id === currentVersionId"
                  class="flex min-w-0 flex-1 items-center gap-1.5 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-muted"
                  :class="group.representative.version_id === currentVersionId ? 'bg-muted' : ''"
                  @click="emit('change', group.representative.version_id)"
                >
                  <span class="shrink-0 text-xs font-medium tabular-nums text-foreground">{{ group.displayLabel }}</span>
                  <!-- 当前版本：小圆点指示，⛔ 不用长文字徽标（会把行挤到换行） -->
                  <span
                    v-if="group.representative.is_current"
                    class="size-1.5 shrink-0 rounded-full bg-success"
                    :title="t('knowledge.blueprints.version.current')"
                    :aria-label="t('knowledge.blueprints.version.current')"
                    data-testid="blueprint-version-tree-current-dot"
                  />
                  <Badge
                    :variant="reasonOf(group.representative.produced_by_ref).variant as any"
                    class="min-w-0 shrink whitespace-nowrap"
                    data-testid="blueprint-version-tree-reason"
                  >
                    <span :class="`icon-[${reasonOf(group.representative.produced_by_ref).icon}]`" class="shrink-0" aria-hidden="true" />
                    <span class="truncate">{{ t(reasonOf(group.representative.produced_by_ref).labelKey) }}</span>
                  </Badge>
                  <span
                    class="ml-auto shrink-0 text-[11px] tabular-nums text-muted-foreground"
                    :title="fullTime(group.representative.created_at)"
                  >
                    {{ formatTime(group.representative.created_at) }}
                  </span>
                </button>
                <!-- diff 基线入口（并自旧 BlueprintVersionSwitcher —— 版本入口只留一个） -->
                <Button
                  variant="ghost"
                  size="icon-sm"
                  data-testid="blueprint-version-tree-compare"
                  :aria-label="t('knowledge.blueprints.diff.baseline')"
                  :title="t('knowledge.blueprints.diff.baseline')"
                  @click="emit('compare', group.representative.version_id)"
                >
                  <span class="icon-[lucide--git-compare]" aria-hidden="true" />
                </Button>
                <!-- 组内还有旧版本才出展开钮 -->
                <Button
                  v-if="group.entries.length > 1"
                  variant="ghost"
                  size="icon-sm"
                  :aria-label="t('knowledge.blueprints.version.groupToggle', { n: group.entries.length })"
                  :title="t('knowledge.blueprints.version.groupToggle', { n: group.entries.length })"
                  data-testid="blueprint-version-tree-group-toggle"
                  @click="toggleGroup(root.rootLabel, group.label)"
                >
                  <span
                    class="icon-[lucide--chevron-down] transition-transform"
                    :class="expandedGroups.has(groupKey(root.rootLabel, group.label)) ? 'rotate-180' : ''"
                    aria-hidden="true"
                  />
                </Button>
              </div>

              <!-- 组内全部版本（version_no 降序；代表之外的旧条目） -->
              <ul
                v-if="group.entries.length > 1 && expandedGroups.has(groupKey(root.rootLabel, group.label))"
                class="mt-0.5 space-y-0.5 border-l border-border/60"
                :class="showRootHeader(root) && group.label !== root.rootLabel ? 'ml-6 pl-2' : 'ml-3 pl-2'"
              >
                <li v-for="entry in group.entries" :key="entry.version_id" class="flex items-center gap-1">
                  <button
                    type="button"
                    data-testid="blueprint-version-tree-entry"
                    :data-version-id="entry.version_id"
                    :aria-pressed="entry.version_id === currentVersionId"
                    class="flex min-w-0 flex-1 items-center gap-1.5 rounded-lg px-2 py-1 text-left transition-colors hover:bg-muted"
                    :class="entry.version_id === currentVersionId ? 'bg-muted' : ''"
                    @click="emit('change', entry.version_id)"
                  >
                    <span class="shrink-0 text-[11px] tabular-nums text-muted-foreground">v{{ entry.version_no }}</span>
                    <span
                      v-if="entry.is_current"
                      class="size-1.5 shrink-0 rounded-full bg-success"
                      :title="t('knowledge.blueprints.version.current')"
                      :aria-label="t('knowledge.blueprints.version.current')"
                    />
                    <span
                      class="ml-auto shrink-0 text-[11px] tabular-nums text-muted-foreground/70"
                      :title="fullTime(entry.created_at)"
                    >
                      {{ formatTime(entry.created_at) }}
                    </span>
                  </button>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    data-testid="blueprint-version-tree-compare"
                    :aria-label="t('knowledge.blueprints.diff.baseline')"
                    :title="t('knowledge.blueprints.diff.baseline')"
                    @click="emit('compare', entry.version_id)"
                  >
                    <span class="icon-[lucide--git-compare]" aria-hidden="true" />
                  </Button>
                </li>
              </ul>
            </li>
          </ul>
        </section>
      </div>
    </PopoverContent>
  </Popover>
</template>
