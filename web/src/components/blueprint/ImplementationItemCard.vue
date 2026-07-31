<script setup lang="ts">
/**
 * 实现项卡（Phase 115-05，UI-SPEC §6.5）。
 *
 * **职责**：把 `implementation_overview.items[]` 的一条排版成一张卡（锚定信息条 + 四分区）；
 * 三处 Block[]（`how` / `existing_integration` / `test_strategy`）一律交给
 * `BlueprintBlockList`，⛔ 卡内不自行处理批注与引用（UI-SPEC §13.3）。
 *
 * ⛔ **不引入语法高亮引擎**：`how` 里常见的 `pseudocode` 块由 115-03 的 `BlueprintBlock`
 * 渲染（等宽 + 行号 + 复制），本卡不碰。
 *
 * `change_type` 四档的图标是**运行期按值拼接的裸名** ⇒ 已在 115-02 追加进 `main.css`
 * 的 safelist（`file-plus` / `file-pen-line` / `file-x` / `file-cog`）。
 *
 * ⚠️ **i18n 缺口（按 §13.2 回报而不自补，见 115-05-SUMMARY §i18n）**：`change_type` 四档中文名、
 * 「与既有功能如何配合」「测试策略」「涉及文件」三个小标题无键 ⇒ 徽标渲染 schema 原样 token
 * （颜色与图标承载语义），三块不渲染文字小标题、身份由 `data-field` 承载。
 */

import type { SelectionPayload } from './BlueprintBlockList.vue'
import type { BlueprintImplementationItem, BlueprintThreadDetail, Citation } from '~/types/blueprint'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Badge } from '~/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '~/components/ui/table'
import BlueprintBlockList from './BlueprintBlockList.vue'

const props = withDefaults(defineProps<{
  item: BlueprintImplementationItem
  moduleName?: string
  repoName?: string
  /** —— 以下五项是 blockCtx，原样透传给 `BlueprintBlockList` —— */
  threads?: BlueprintThreadDetail[]
  citations?: Record<string, Citation>
  readonly?: boolean
  activeThreadId?: string | null
  showClosed?: boolean
}>(), {
  moduleName: '',
  repoName: '',
  threads: () => [],
  citations: () => ({}),
  readonly: false,
  activeThreadId: null,
  showClosed: false,
})

const emit = defineEmits<{
  'thread-click': [threadId: string, allThreadIds: string[]]
  'citation-click': [citationId: string]
  'selection-comment': [payload: SelectionPayload]
  'cross-block-selection': []
}>()

const { t } = useI18n()

/** `change_type` 四档 → 徽标 variant + 裸图标名（图标已在 115-02 的 safelist）。 */
const CHANGE_TYPE_META: Record<string, { variant: 'success' | 'info' | 'destructive' | 'secondary', icon: string }> = {
  create: { variant: 'success', icon: 'lucide--file-plus' },
  modify: { variant: 'info', icon: 'lucide--file-pen-line' },
  remove: { variant: 'destructive', icon: 'lucide--file-x' },
  indirect_refine: { variant: 'secondary', icon: 'lucide--file-cog' },
}

/** `files_touched[].action` 三档 → variant（与 `change_type` 同色系，⛔ 不发明第四档）。 */
const FILE_ACTION_VARIANT: Record<string, 'success' | 'info' | 'destructive'> = {
  create: 'success',
  modify: 'info',
  remove: 'destructive',
}

const changeTypeMeta = computed(() => CHANGE_TYPE_META[props.item.change_type] ?? null)

const howBlocks = computed(() => props.item.how ?? [])
const testStrategyBlocks = computed(() => props.item.test_strategy ?? [])
const filesTouched = computed(() => props.item.files_touched ?? [])
const dependsOn = computed(() => props.item.depends_on ?? [])

/** `existing_integration` 只对 `modify` / `indirect_refine` 有意义（UI-SPEC §6.5）。 */
const existingIntegrationBlocks = computed(() => {
  const kind = props.item.change_type
  if (kind !== 'modify' && kind !== 'indirect_refine')
    return []
  return props.item.existing_integration ?? []
})

function fileActionVariant(action: string): 'success' | 'info' | 'destructive' | 'outline' {
  return FILE_ACTION_VARIANT[action] ?? 'outline'
}

function forwardThread(threadId: string, allThreadIds: string[]): void {
  emit('thread-click', threadId, allThreadIds)
}
</script>

<template>
  <div
    :id="`impl-${item.id}`"
    class="card space-y-3 p-4"
    data-testid="blueprint-impl-item"
    :data-change-type="item.change_type"
    :data-wave="item.wave ?? ''"
  >
    <div class="flex items-start gap-2">
      <Badge v-if="changeTypeMeta" :variant="changeTypeMeta.variant">
        <span :class="`icon-[${changeTypeMeta.icon}]`" aria-hidden="true" />
        {{ item.change_type }}
      </Badge>
      <Badge v-else variant="outline">
        {{ item.change_type }}
      </Badge>
      <h4 class="min-w-0 flex-1 text-sm font-semibold">
        {{ item.title }}
      </h4>
    </div>

    <!-- 锚定信息条：模块 · 仓 · 波次 · 依赖 -->
    <div class="flex flex-wrap items-center gap-2 font-mono text-[11px] text-muted-foreground">
      <span>{{ item.id }}</span>
      <span v-if="moduleName || item.module_id">· {{ moduleName || item.module_id }}</span>
      <span v-if="repoName || item.repository_id">· {{ repoName || item.repository_id }}</span>
      <span v-if="item.wave !== undefined">· wave {{ item.wave }}</span>
      <span
        v-for="dep in dependsOn"
        :key="dep"
        class="rounded-md border border-border bg-muted/60 px-1.5 py-0.5"
        data-testid="blueprint-impl-depends-on"
      >{{ dep }}</span>
    </div>

    <div v-if="howBlocks.length" data-field="how">
      <BlueprintBlockList
        :blocks="howBlocks"
        :section-path="`implementation_overview.items[${item.id}].how`"
        :threads="threads"
        :citations="citations"
        :readonly="readonly"
        :active-thread-id="activeThreadId"
        :show-closed="showClosed"
        @thread-click="forwardThread"
        @citation-click="emit('citation-click', $event)"
        @selection-comment="emit('selection-comment', $event)"
        @cross-block-selection="emit('cross-block-selection')"
      />
    </div>

    <div v-if="existingIntegrationBlocks.length" data-field="existing-integration">
      <BlueprintBlockList
        :blocks="existingIntegrationBlocks"
        :section-path="`implementation_overview.items[${item.id}].existing_integration`"
        :threads="threads"
        :citations="citations"
        :readonly="readonly"
        :active-thread-id="activeThreadId"
        :show-closed="showClosed"
        @thread-click="forwardThread"
        @citation-click="emit('citation-click', $event)"
        @selection-comment="emit('selection-comment', $event)"
        @cross-block-selection="emit('cross-block-selection')"
      />
    </div>

    <div v-if="filesTouched.length" data-field="files-touched">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead scope="col">
              {{ t('knowledge.blueprints.mustHaves.colPath') }}
            </TableHead>
            <TableHead scope="col">
              {{ t('knowledge.blueprints.flow.action') }}
            </TableHead>
            <TableHead scope="col">
              {{ t('knowledge.blueprints.flow.note') }}
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow v-for="(file, index) in filesTouched" :key="`${file.path}-${index}`" data-testid="blueprint-impl-file">
            <TableCell class="font-mono text-xs">
              {{ file.path }}
            </TableCell>
            <TableCell>
              <Badge :variant="fileActionVariant(file.action)">
                {{ file.action }}
              </Badge>
            </TableCell>
            <TableCell class="text-xs text-muted-foreground">
              {{ file.note || '—' }}
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </div>

    <div v-if="testStrategyBlocks.length" data-field="test-strategy">
      <BlueprintBlockList
        :blocks="testStrategyBlocks"
        :section-path="`implementation_overview.items[${item.id}].test_strategy`"
        :threads="threads"
        :citations="citations"
        :readonly="readonly"
        :active-thread-id="activeThreadId"
        :show-closed="showClosed"
        @thread-click="forwardThread"
        @citation-click="emit('citation-click', $event)"
        @selection-comment="emit('selection-comment', $event)"
        @cross-block-selection="emit('cross-block-selection')"
      />
    </div>
  </div>
</template>
