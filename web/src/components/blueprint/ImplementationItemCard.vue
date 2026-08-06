<script setup lang="ts">
/**
 * 实现项卡（Phase 115-05，UI-SPEC §6.5；quick-260806-fpx 连通性整改）。
 *
 * **职责**：把 `implementation_overview.items[]` 的一条排版成一张卡（卡头 + 锚定信息条 +
 * 四分区）；三处 Block[]（`how` / `existing_integration` / `test_strategy`）一律交给
 * `BlueprintBlockList`，⛔ 卡内不自行处理批注与引用（UI-SPEC §13.3）。
 *
 * ⭐ **`feature_point_id` 必须渲染**（quick-260806-fpx 补的洞）：它是 schema 的 **required**
 * 键（`blueprint_schema.py` `implementation_overview.items.required`）且有后置检查保证能解析
 * 到 `requirement_spec.feature_points`，但 115-05 起卡上从未渲染它 —— 于是「这条改动到底
 * 兑现了哪个功能点」在界面上无从回答，评审人只能靠标题猜。⛔ 不要再把它省掉。
 *
 * ⭐ **锚定信息条的每个 id 都是活的**：功能点 → `fp-<id>`、模块 → `mod-<id>`、
 * `depends_on` → `impl-<id>`，一律 emit `goto-anchor` 给上层（波次筛选冲突由段组件
 * `onItemAnchor` 统一解，⛔ 卡内不自行滚动、也不自己判筛选）。
 *
 * ⛔ **不引入语法高亮引擎**：`how` 里常见的 `pseudocode` 块由 115-03 的 `BlueprintBlock`
 * 渲染（等宽 + 行号 + 复制），本卡不碰。
 *
 * `change_type` 四档的图标是**运行期按值拼接的裸名**，查表在 `utils/blueprintImplItems.ts`，
 * 四档全部已进 `styles/main.css` 的 safelist（`file-x` 一档整改前缺席 ⇒ 删除类实现项
 * 徽标是无图标的，已补）。
 */

import type { SelectionPayload } from './BlueprintBlockList.vue'
import type {
  BlueprintFeaturePoint,
  BlueprintImplementationItem,
  BlueprintThreadDetail,
  Citation,
} from '~/types/blueprint'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Badge } from '~/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '~/components/ui/table'
import { changeTypeMetaOf, fileActionLabelKeyOf, fileActionVariantOf } from '~/utils/blueprintImplItems'
import BlueprintBlockList from './BlueprintBlockList.vue'
import BlueprintFeaturePointChip from './BlueprintFeaturePointChip.vue'

const props = withDefaults(defineProps<{
  item: BlueprintImplementationItem
  moduleName?: string
  repoName?: string
  /** 本项对应的完整功能点；缺失时 chip 只出 id（预览降级，⛔ 不隐藏 chip）。 */
  featurePoint?: BlueprintFeaturePoint | null
  /** —— 以下五项是 blockCtx，原样透传给 `BlueprintBlockList` —— */
  threads?: BlueprintThreadDetail[]
  citations?: Record<string, Citation>
  readonly?: boolean
  activeThreadId?: string | null
  showClosed?: boolean
}>(), {
  moduleName: '',
  repoName: '',
  featurePoint: null,
  threads: () => [],
  citations: () => ({}),
  readonly: false,
  activeThreadId: null,
  showClosed: false,
})

const emit = defineEmits<{
  'goto-anchor': [domId: string]
  'thread-click': [threadId: string, allThreadIds: string[]]
  'citation-click': [citationId: string]
  'selection-comment': [payload: SelectionPayload]
  'cross-block-selection': []
}>()

const { t } = useI18n()

const changeTypeMeta = computed(() => changeTypeMetaOf(props.item.change_type))

/** 未知 `change_type` 回落 schema 原样 token（⛔ 不发明第五档文案）。 */
const changeTypeLabel = computed(() => {
  const meta = changeTypeMeta.value
  return meta
    ? t(`knowledge.blueprints.impl.${meta.labelKey}`)
    : String(props.item.change_type ?? '')
})

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

function forwardThread(threadId: string, allThreadIds: string[]): void {
  emit('thread-click', threadId, allThreadIds)
}
</script>

<template>
  <div
    :id="`impl-${item.id}`"
    class="card scroll-mt-24"
    data-testid="blueprint-impl-item"
    :data-change-type="item.change_type"
    :data-wave="item.wave ?? ''"
  >
    <div class="flex items-start gap-2.5 border-b border-border/50 px-4 py-3">
      <Badge v-if="changeTypeMeta" :variant="changeTypeMeta.variant" class="mt-0.5 shrink-0">
        <span :class="`icon-[${changeTypeMeta.icon}]`" aria-hidden="true" />
        {{ changeTypeLabel }}
      </Badge>
      <Badge v-else variant="outline" class="mt-0.5 shrink-0">
        {{ changeTypeLabel }}
      </Badge>
      <h4 class="min-w-0 flex-1 text-base leading-snug font-semibold">
        {{ item.title }}
      </h4>
    </div>

    <!-- ⭐ 锚定信息条：功能点（本项兑现的需求）+ 模块 / 仓 / 波次 / 依赖 -->
    <div class="space-y-2 border-b border-border/50 bg-muted/25 px-4 py-2.5">
      <div v-if="item.feature_point_id" class="flex min-w-0 items-center gap-2">
        <span class="shrink-0 text-xs text-muted-foreground">{{ t('knowledge.blueprints.impl.deliversFeaturePoint') }}</span>
        <BlueprintFeaturePointChip
          :point-id="item.feature_point_id"
          :point="featurePoint"
          show-title
          @goto-anchor="emit('goto-anchor', $event)"
        />
      </div>

      <div class="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[11px] text-muted-foreground">
        <span class="font-mono">{{ item.id }}</span>

        <button
          v-if="item.module_id"
          type="button"
          class="inline-flex items-center gap-1 rounded-md px-1 py-0.5 transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          data-testid="blueprint-impl-module-link"
          :data-module-id="item.module_id"
          @click="emit('goto-anchor', `mod-${item.module_id}`)"
        >
          <span class="icon-[lucide--boxes]" aria-hidden="true" />
          {{ moduleName || item.module_id }}
        </button>
        <span v-else-if="moduleName" class="inline-flex items-center gap-1">
          <span class="icon-[lucide--boxes]" aria-hidden="true" />
          {{ moduleName }}
        </span>

        <!-- 仓库归属带显式「仓库」字样：裸仓名 chip 读者认不出这是仓库（实测反馈），
             而涉及文件的路径都是仓内相对路径，缺归属就成了悬空的 /apps/… -->
        <span v-if="repoName || item.repository_id" class="inline-flex items-center gap-1" data-testid="blueprint-impl-repo">
          <span class="icon-[lucide--git-branch]" aria-hidden="true" />
          <span>{{ t('knowledge.blueprints.impl.repoLabel') }}</span>
          <span class="text-foreground">{{ repoName || item.repository_id }}</span>
        </span>

        <span v-if="item.wave !== undefined" class="inline-flex items-center gap-1 tabular-nums">
          <span class="icon-[lucide--layers]" aria-hidden="true" />
          {{ t('knowledge.blueprints.impl.waveShort', { n: item.wave }) }}
        </span>

        <span v-if="dependsOn.length" class="inline-flex min-w-0 flex-wrap items-center gap-1">
          <span class="icon-[lucide--link] shrink-0" aria-hidden="true" />
          <span class="shrink-0">{{ t('knowledge.blueprints.impl.dependsOn') }}</span>
          <button
            v-for="dep in dependsOn"
            :key="dep"
            type="button"
            class="rounded-md border border-border bg-card px-1.5 py-0.5 font-mono transition-colors hover:border-primary/50 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
            data-testid="blueprint-impl-depends-on"
            @click="emit('goto-anchor', `impl-${dep}`)"
          >{{ dep }}</button>
        </span>
      </div>
    </div>

    <div class="space-y-3.5 p-4">
      <div v-if="howBlocks.length" data-field="how">
        <p class="mb-1.5 text-xs font-medium text-muted-foreground">
          {{ t('knowledge.blueprints.impl.how') }}
        </p>
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
        <p class="mb-1.5 text-xs font-medium text-muted-foreground">
          {{ t('knowledge.blueprints.impl.existingIntegration') }}
        </p>
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
        <p class="mb-1.5 text-xs font-medium text-muted-foreground">
          {{ t('knowledge.blueprints.impl.filesTouched', { n: filesTouched.length }) }}
          <!-- 路径的仓库归属（表内是仓内相对路径，不带归属就是悬空的 /apps/…） -->
          <span
            v-if="repoName || item.repository_id"
            class="font-normal text-muted-foreground/80"
            data-testid="blueprint-impl-files-repo"
          >
            · {{ t('knowledge.blueprints.impl.filesTouchedRepo', { repo: repoName || item.repository_id }) }}
          </span>
        </p>
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
              <TableCell class="font-mono text-xs break-all">
                {{ file.path }}
              </TableCell>
              <TableCell>
                <!-- 动作中文化：三档（含 edit/delete 等同义 token 归一）；认不出的原样透出 -->
                <Badge :variant="fileActionVariantOf(file.action)">
                  {{ fileActionLabelKeyOf(file.action)
                    ? t(`knowledge.blueprints.impl.${fileActionLabelKeyOf(file.action)}`)
                    : file.action }}
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
        <p class="mb-1.5 text-xs font-medium text-muted-foreground">
          {{ t('knowledge.blueprints.impl.testStrategy') }}
        </p>
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
  </div>
</template>
