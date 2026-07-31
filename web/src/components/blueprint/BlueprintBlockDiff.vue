<script setup lang="ts">
/**
 * block 级版本对比（Phase 115-04，UI-SPEC §9.2）。
 *
 * **diff 在前端算，零新增后端端点** —— 两版正文都已在手（§3.1 端点带 `version_id` 取回），
 * 为它开一条 REST 属净新增面。
 *
 * ⭐ **块级增删一律走 `classifyBlockDiff`（115-02，canonical 指纹）** ——
 * ⛔ 组件内不自写序列化比较：键序不定会把「内容未变」误判成 `modified`，评审被噪声淹没。
 * `modified` 的块**才**进 `diffWords()` 求词级 `Change[]`。
 *
 * ⚠️ **不照抄 analog 的深度 watch**：`prompts/PromptVersionDiff.vue:30-36` 深度监听两个
 * prop 对象、却把结果整体替换进 `shallowRef`，是既有的一处自相矛盾。这里只监听
 * `version_id` 这类标量。
 *
 * ⭐ **`.diff-added` / `.diff-removed` / `.diff-unchanged` 三条 CSS 原样复制进本组件的
 * `<style scoped>`**（值逐字同 `prompts/PromptVersionDiff.vue:119-137`）。它们在那边是
 * `scoped` 的、跨组件不可复用，也不存在可 import 的共享令牌文件（P-11）——
 * 「逐字沿用」在实现上就是复制。⛔ 别去找、别新建全局令牌。
 * **本文件是本 plan 唯一允许出现颜色字面量的地方。**
 *
 * ⭐ **diff 模式下批注层与所有写动作关闭**（纯对照视图）：本组件不渲染划线标记、
 * 不接受线程 props、不 emit 任何写动作，只有一个 `update:mode`。
 *
 * ⚠️ `must_haves` 段没有 `block_id`（后端 `iter_blocks` 对它零 collect，P-14）⇒
 * **不参与块级对比**。这里保留一行占位并用 `data-diff-excluded` 承载该身份；
 * 「不参与块级对比」这句文案 `diff.*` 子树里没有，按 §13.2 回报而不自补
 * （缺口已登记在 115-04-SUMMARY）。
 *
 * 安全：全程 Vue mustache 经 `<pre>` 渲染，不使用任何原始 HTML 注入指令，XSS 面 = 0。
 * 性能：用 `shallowRef` 存 diff 输出（`Change[]` 只整体替换、不原地改），避免深响应式。
 */

import type { Change } from 'diff'
import type { BlueprintBlock, BlueprintDocumentResponse } from '~/types/blueprint'
import { diffWords } from 'diff'
import { computed, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '~/components/ui/collapsible'
import { blockText, classifyBlockDiff, iterBlocks } from '~/utils/blueprintBlocks'

const props = withDefaults(defineProps<{
  baseDoc: BlueprintDocumentResponse
  targetDoc: BlueprintDocumentResponse
  mode?: 'inline' | 'split'
}>(), {
  mode: 'inline',
})

const emit = defineEmits<{
  'update:mode': [mode: 'inline' | 'split']
}>()

const { t } = useI18n()

/** 段呈现顺序与 i18n 标签键（`meta.summary` 归到需求规格段，与 115-02 的走查同源）。 */
const SECTION_ORDER: ReadonlyArray<[string, string]> = [
  ['meta', 'requirementSpec'],
  ['requirement_spec', 'requirementSpec'],
  ['repo_associations', 'repoAssociations'],
  ['current_state_analysis', 'currentStateAnalysis'],
  ['implementation_overview', 'implementationOverview'],
  ['api_contracts', 'apiContracts'],
  ['impact_analysis', 'impactAnalysis'],
  ['interaction_flows', 'interactionFlows'],
]

interface DiffBlockView {
  blockId: string
  sectionKey: string
  kind: 'added' | 'removed' | 'modified'
  /** `added` / `removed` 的整块文本。 */
  text: string
  /** `modified` 的词级差分（⭐ 只整体替换，不原地改）。 */
  changes: Change[]
}

interface DiffCounts {
  added: number
  removed: number
  modified: number
}

/** ⭐ shallow：`Change[]` 是 diff 输出，做深响应式毫无收益且很贵。 */
const blockViews = shallowRef<DiffBlockView[]>([])
const counts = shallowRef<DiffCounts>({ added: 0, removed: 0, modified: 0 })

function indexBlocks(content: unknown): Map<string, { sectionKey: string, block: BlueprintBlock }> {
  const map = new Map<string, { sectionKey: string, block: BlueprintBlock }>()
  for (const entry of iterBlocks(content))
    map.set(String(entry.block.block_id), { sectionKey: entry.sectionKey, block: entry.block })
  return map
}

function recompute(): void {
  const baseIndex = indexBlocks(props.baseDoc?.content)
  const targetIndex = indexBlocks(props.targetDoc?.content)
  const classification = classifyBlockDiff(props.baseDoc?.content, props.targetDoc?.content)

  const views: DiffBlockView[] = []

  for (const blockId of classification.added) {
    const entry = targetIndex.get(blockId)
    views.push({
      blockId,
      sectionKey: entry?.sectionKey ?? '',
      kind: 'added',
      text: blockText(entry?.block),
      changes: [],
    })
  }
  for (const blockId of classification.removed) {
    const entry = baseIndex.get(blockId)
    views.push({
      blockId,
      sectionKey: entry?.sectionKey ?? '',
      kind: 'removed',
      text: blockText(entry?.block),
      changes: [],
    })
  }
  for (const blockId of classification.modified) {
    const before = baseIndex.get(blockId)
    const after = targetIndex.get(blockId)
    views.push({
      blockId,
      sectionKey: after?.sectionKey ?? before?.sectionKey ?? '',
      kind: 'modified',
      text: '',
      // ⭐ 真实调用 diff 包的词级差分（与 analog 的 diffLines 同包同族，返回同构 Change[]）。
      changes: diffWords(blockText(before?.block), blockText(after?.block)),
    })
  }

  blockViews.value = views
  counts.value = {
    added: classification.added.length,
    removed: classification.removed.length,
    modified: classification.modified.length,
  }
}

recompute()

// ⚠️ 只监听标量（版本标识），⛔ 不做深度监听。
watch(
  () => [props.baseDoc?.version_id, props.targetDoc?.version_id],
  () => recompute(),
)

interface DiffSectionView {
  key: string
  label: string
  blocks: DiffBlockView[]
  changed: boolean
}

/** 多个走查段可以映射到同一个导航段（`meta.summary` 并进需求规格），按导航段合并呈现。 */
const sections = computed<DiffSectionView[]>(() => {
  const merged = new Map<string, DiffSectionView>()
  for (const [sectionKey, labelKey] of SECTION_ORDER) {
    const blocks = blockViews.value.filter(view => view.sectionKey === sectionKey)
    const existing = merged.get(labelKey)
    if (existing) {
      existing.blocks.push(...blocks)
      existing.changed = existing.blocks.length > 0
      continue
    }
    merged.set(labelKey, {
      key: labelKey,
      label: t(`knowledge.blueprints.section.${labelKey}`),
      blocks: [...blocks],
      changed: blocks.length > 0,
    })
  }
  return [...merged.values()]
})

const summary = computed(() =>
  t('knowledge.blueprints.diff.summary', {
    a: props.baseDoc?.version_no ?? 0,
    b: props.targetDoc?.version_no ?? 0,
    added: counts.value.added,
    removed: counts.value.removed,
    modified: counts.value.modified,
  }),
)

const hasAnyChange = computed(() => blockViews.value.length > 0)

/** 基线视角：unchanged + removed（抄 analog 的视角切分）。 */
function leftSegments(changes: Change[]): Change[] {
  return changes.filter(change => !change.added)
}

/** 目标视角：unchanged + added。 */
function rightSegments(changes: Change[]): Change[] {
  return changes.filter(change => !change.removed)
}

function segmentClass(change: Change): string {
  if (change.added)
    return 'diff-added'
  if (change.removed)
    return 'diff-removed'
  return 'diff-unchanged'
}

function setMode(mode: 'inline' | 'split'): void {
  emit('update:mode', mode)
}
</script>

<template>
  <div data-testid="blueprint-diff" class="space-y-3">
    <div class="flex flex-wrap items-center gap-2">
      <p class="text-xs text-muted-foreground" aria-live="polite" data-testid="blueprint-diff-summary">
        {{ summary }}
      </p>
      <div class="ml-auto flex items-center gap-1">
        <Button
          size="sm"
          :variant="mode === 'inline' ? 'secondary' : 'ghost'"
          data-testid="blueprint-diff-mode-inline"
          @click="setMode('inline')"
        >
          {{ t('knowledge.blueprints.diff.modeInline') }}
        </Button>
        <Button
          size="sm"
          :variant="mode === 'split' ? 'secondary' : 'ghost'"
          data-testid="blueprint-diff-mode-split"
          @click="setMode('split')"
        >
          {{ t('knowledge.blueprints.diff.modeSplit') }}
        </Button>
      </div>
    </div>

    <p v-if="!hasAnyChange" class="text-sm text-muted-foreground">
      {{ t('knowledge.blueprints.diff.noChange') }}
    </p>

    <Collapsible
      v-for="section in sections"
      :key="section.key"
      :data-diff-section="section.key"
      :default-open="section.changed"
    >
      <CollapsibleTrigger class="flex w-full items-center gap-2 rounded-lg px-1 py-1.5 text-left text-sm font-medium hover:bg-muted/60">
        <span class="text-foreground">{{ section.label }}</span>
        <Badge v-if="!section.changed" variant="muted">
          {{ t('knowledge.blueprints.diff.sectionUnchanged') }}
        </Badge>
        <Badge v-else variant="info">
          {{ section.blocks.length }}
        </Badge>
      </CollapsibleTrigger>
      <CollapsibleContent class="space-y-2 pt-1.5">
        <div
          v-for="view in section.blocks"
          :key="view.blockId"
          data-diff-block
          :data-diff-kind="view.kind"
          :data-block-id="view.blockId"
        >
          <!-- 整块增 / 删 -->
          <div v-if="view.kind !== 'modified'" :class="view.kind === 'added' ? 'diff-added' : 'diff-removed'">
            <pre
              class="whitespace-pre-wrap break-words px-3 py-1 font-mono text-xs leading-6"
              :class="view.kind === 'removed' ? 'line-through opacity-80' : ''"
            >{{ view.text }}</pre>
          </div>

          <!-- 块内词级差分：单栏 inline -->
          <div v-else-if="mode === 'inline'" class="rounded-lg border border-border/50">
            <pre class="whitespace-pre-wrap break-words px-3 py-1 font-mono text-xs leading-6"><span
              v-for="(change, i) in view.changes"
              :key="`I-${i}`"
              :class="segmentClass(change)"
            >{{ change.value }}</span></pre>
          </div>

          <!-- 块内词级差分：左右并排 split -->
          <div v-else class="grid grid-cols-2 gap-0 overflow-hidden rounded-lg border border-border/50">
            <div data-diff-column="left" class="overflow-auto border-r border-border/50">
              <pre class="whitespace-pre-wrap break-words px-3 py-1 font-mono text-xs leading-6"><span
                v-for="(change, i) in leftSegments(view.changes)"
                :key="`L-${i}`"
                :class="segmentClass(change)"
              >{{ change.value }}</span></pre>
            </div>
            <div data-diff-column="right" class="overflow-auto">
              <pre class="whitespace-pre-wrap break-words px-3 py-1 font-mono text-xs leading-6"><span
                v-for="(change, i) in rightSegments(view.changes)"
                :key="`R-${i}`"
                :class="segmentClass(change)"
              >{{ change.value }}</span></pre>
            </div>
          </div>
        </div>
      </CollapsibleContent>
    </Collapsible>

    <!-- ⚠️ 验收锚点段无 block_id，不参与块级对比（身份由 data-diff-excluded 承载） -->
    <div
      data-diff-section="must_haves"
      data-diff-excluded="true"
      class="flex items-center gap-2 rounded-lg border border-dashed border-border/60 px-2.5 py-2"
    >
      <span class="icon-[lucide--info] text-muted-foreground" aria-hidden="true" />
      <span class="text-xs text-muted-foreground">{{ t('knowledge.blueprints.section.mustHaves') }}</span>
      <Badge variant="muted">
        {{ t('knowledge.blueprints.diff.mustHavesExcluded') }}
      </Badge>
    </div>
  </div>
</template>

<style scoped>
/* ⭐ 逐字复制自 prompts 目录下版本对比组件的 scoped 令牌（P-11：那三条是 scoped 的，
 * 跨组件不可复用，也没有可 import 的共享令牌文件 ⇒「逐字沿用」= 复制）。 */
.diff-added {
  background: hsl(142 71% 45% / 0.12);
  color: hsl(142 71% 20%);
  border-left: 3px solid hsl(142 71% 45%);
}
.diff-removed {
  background: hsl(0 72% 51% / 0.1);
  color: hsl(0 72% 30%);
  border-left: 3px solid hsl(0 72% 51%);
}
.diff-unchanged {
  background: transparent;
  color: hsl(215 28% 17%);
  border-left: 3px solid transparent;
}
</style>
