<script setup lang="ts">
/**
 * 验收锚点段（Phase 115-05，UI-SPEC §6.1 段 7 / §6.9）。
 *
 * ⭐ **全文唯一不走 `BlueprintBlockList` 的正文段，且不收 blockCtx。**
 *
 * **为什么本段不接批注层（§6.9 关键约束第二条要求组件内写明）**：
 * `iter_blocks`（`server/services/process_runtime/blueprint_schema.py`）**不走查 `must_haves`**
 * —— 它的三个数组是纯字符串与普通对象，**零 `block_id`** ⇒ 后端不会往这里挂线程。因此本段：
 * 不渲染任何划线标记、选区浮层在本段**不弹**、不参与 §9.2 的块级 diff（diff 视图中本段整段折叠）。
 * **不复用 `BlueprintBlockList`**（它的契约前提就是块有 `block_id`），这是全文唯一的例外。
 * 给它接上批注层会得到一段**死码**：既没有线程会落进来，又让用户以为可以在这里划线提问。
 *
 * **为什么必须渲染**：`must_haves` 是 schema 的 **required** 键，承载 goal-backward 的验收断言。
 * 人审要回答的核心问题是「这方案做完了怎么算数」——不渲染它，评审人只能凭实现细节猜验收口径。
 *
 * ⭐ **空态规则**：三个数组**同为空或整键缺失**（v0 旧数据无此键）⇒ 不渲染任何内容卡
 * （⛔ 不出空态**卡**，对齐 `deferred_ideas` 的处理），改出**一行**说明文案；仅**部分**
 * 子块为空时该子块不渲染、其余照渲。
 *
 * ⚠️ 那一行是 UI-SPEC §6.9「整段与其导航项都不渲染，不出空态卡」被 P-4 订正后的必然结果：
 * 段容器与导航项已改为**无条件渲染**（否则 `AnchorNavLayout` 的 observer 挂不上），段内再
 * 什么都不出，页面上就留下一个光秃秃的 `<h2>验收锚点</h2>`，左栏导航项照样可点、点过去
 * 还是空的。文案键 `mustHaves.empty` 早已写好，此前从未被引用（UI-REVIEW M-5）。
 *
 * **分工边界（P-4，⛔ 不得越界）**：`<section id="must_haves">` 容器与左栏导航项由页面（115-06）
 * **无条件渲染** —— `AnchorNavLayout` 的 IntersectionObserver 只在 mount 时注册，条件渲染段容器
 * 会让它永远观察不到（左栏高亮静默失效）。本组件只决定**段内出不出内容**。
 */

import type { BlueprintMustHaves } from '~/types/blueprint'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '~/components/ui/table'

const props = withDefaults(defineProps<{
  /** ⚠️ 运行期可能整键缺失（v0 旧数据）⇒ 允许 `null`，三个子块逐个可选。 */
  mustHaves?: Partial<BlueprintMustHaves> | null
}>(), {
  mustHaves: null,
})

const { t } = useI18n()

/** 缺键占位符（⛔ 不渲染 `undefined`）。 */
const PLACEHOLDER = '—'

function readText(bag: Record<string, unknown>, key: string): string {
  const value = bag[key]
  return typeof value === 'string' && value ? value : PLACEHOLDER
}

const truths = computed(() => {
  const list = props.mustHaves?.truths
  if (!Array.isArray(list))
    return []
  return list
    .map(item => (typeof item === 'string' ? item : ''))
    .filter(item => item.length > 0)
})

const artifacts = computed(() => {
  const list = props.mustHaves?.artifacts
  if (!Array.isArray(list))
    return []
  return list.map((raw, index) => {
    const item = (raw ?? {}) as Record<string, unknown>
    return {
      key: `${index}`,
      path: readText(item, 'path'),
      provides: readText(item, 'provides'),
    }
  })
})

const keyLinks = computed(() => {
  const list = props.mustHaves?.key_links
  if (!Array.isArray(list))
    return []
  return list.map((raw, index) => {
    const item = (raw ?? {}) as Record<string, unknown>
    return {
      key: `${index}`,
      from: readText(item, 'from'),
      to: readText(item, 'to'),
      via: readText(item, 'via'),
    }
  })
})

/** ⭐ 三块同空 ⇒ 整段不出内容（⛔ 不出空态卡）。 */
const hasContent = computed(() => Boolean(truths.value.length || artifacts.value.length || keyLinks.value.length))
</script>

<template>
  <div v-if="hasContent" data-testid="blueprint-must-haves" class="space-y-4">
    <div v-if="truths.length" data-testid="blueprint-must-haves-truths" class="space-y-1.5">
      <p class="text-xs font-medium text-muted-foreground">
        {{ t('knowledge.blueprints.mustHaves.truths') }}
      </p>
      <ul class="space-y-1.5">
        <li v-for="(truth, index) in truths" :key="index" class="flex items-start gap-2">
          <span class="icon-[lucide--check] mt-0.5 shrink-0 text-primary" aria-hidden="true" />
          <span class="text-sm leading-relaxed">{{ truth }}</span>
        </li>
      </ul>
    </div>

    <div v-if="artifacts.length" data-testid="blueprint-must-haves-artifacts" class="space-y-1.5">
      <p class="text-xs font-medium text-muted-foreground">
        {{ t('knowledge.blueprints.mustHaves.artifacts') }}
      </p>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead scope="col">
              {{ t('knowledge.blueprints.mustHaves.colPath') }}
            </TableHead>
            <TableHead scope="col">
              {{ t('knowledge.blueprints.mustHaves.colProvides') }}
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow v-for="artifact in artifacts" :key="artifact.key" data-testid="blueprint-must-haves-artifact-row">
            <TableCell class="font-mono text-xs">
              {{ artifact.path }}
            </TableCell>
            <TableCell class="text-sm">
              {{ artifact.provides }}
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </div>

    <div v-if="keyLinks.length" data-testid="blueprint-must-haves-key-links" class="space-y-1.5">
      <p class="text-xs font-medium text-muted-foreground">
        {{ t('knowledge.blueprints.mustHaves.keyLinks') }}
      </p>
      <div
        v-for="link in keyLinks"
        :key="link.key"
        class="space-y-0.5"
        data-testid="blueprint-must-haves-key-link-row"
      >
        <!-- md 以上：起点 → 终点 一行；窄屏：竖排三行标签值 -->
        <div class="hidden items-center gap-2 md:flex">
          <span class="rounded-md border border-border bg-muted/60 px-1.5 py-0.5 font-mono text-[11px]">{{ link.from }}</span>
          <span class="icon-[lucide--chevron-right] text-muted-foreground" aria-hidden="true" />
          <span class="rounded-md border border-border bg-muted/60 px-1.5 py-0.5 font-mono text-[11px]">{{ link.to }}</span>
        </div>
        <p class="hidden text-[11px] text-muted-foreground md:block">
          {{ link.via }}
        </p>

        <dl class="space-y-0.5 md:hidden">
          <div class="flex gap-1 text-[11px]">
            <dt class="text-muted-foreground">
              {{ t('knowledge.blueprints.mustHaves.colFrom') }}
            </dt>
            <dd class="font-mono">
              {{ link.from }}
            </dd>
          </div>
          <div class="flex gap-1 text-[11px]">
            <dt class="text-muted-foreground">
              {{ t('knowledge.blueprints.mustHaves.colVia') }}
            </dt>
            <dd>{{ link.via }}</dd>
          </div>
          <div class="flex gap-1 text-[11px]">
            <dt class="text-muted-foreground">
              {{ t('knowledge.blueprints.mustHaves.colTo') }}
            </dt>
            <dd class="font-mono">
              {{ link.to }}
            </dd>
          </div>
        </dl>
      </div>
    </div>
  </div>

  <!-- ⭐ 三块全空的空态：⛔ 不是「什么都不渲染」—— 段容器与导航项由页面无条件渲染（P-4），
       段内不出一句话就只剩一个光秃秃的 <h2>，导航项照样可点、点过去还是空的。 -->
  <p v-else data-testid="blueprint-must-haves-empty" class="text-sm text-muted-foreground">
    {{ t('knowledge.blueprints.mustHaves.empty') }}
  </p>
</template>
