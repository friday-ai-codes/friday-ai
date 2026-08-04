<script setup lang="ts">
/**
 * 蓝图段内块序列渲染 + ⭐ **选区侦测的唯一落点**（Phase 115-03，UI-SPEC §6.2 / §7.4）。
 *
 * **职责**：段级三分支（骨架 / 实渲 / 空态）+ 逐块渲染 `BlueprintBlock` + 透传它的两项 emit，
 * 外加本组件独有的两项选区 emit。
 *
 * **为什么选区监听挂在 List 而不是 Block 上**：`selectionchange` 是 `document` 级事件，
 * N 个块各挂一个监听器就是 N 次重复回调；而且「跨块选区」这一档在单块视角里根本判不出来
 * （每个块只看得见自己）。⇒ 监听器只在这里挂一个，`onUnmounted` 必解绑（T-115-25：
 * 漏解绑会在路由切换后继续触发并泄漏）。
 *
 * **分工边界**：本组件只负责**算出选区落点**并把 `rect` 交出去；⛔ `readonly` 不在此处拦截 ——
 * 是否渲染「发起评论」按钮由 115-04 的选区 popover 依 `readonly` 决定（§7.9：`readonly` 时
 * 只留「复制原文」）。虚拟锚点 div 与 popover 本体同样归 115-04：方案已锁死为
 * `import { PopoverAnchor } from 'reka-ui'` + 零尺寸锚点，⛔ 不引入那个浮层定位库
 * （基线虽有该依赖，但 `web/src/` 至今零引用，保持这个状态）、⛔ 不手写定位计算。
 *
 * **安全**：本组件不渲染任何来自后端的富文本，正文一律下沉给 `BlueprintBlock`（全程 mustache）。
 */

import type { BlueprintBlock as BlueprintBlockModel, BlueprintThreadDetail, Citation } from '~/types/blueprint'
import { useDebounceFn } from '@vueuse/core'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Skeleton } from '~/components/ui/skeleton'
import { groupThreadsByBlock, rangeOffsets } from '~/utils/blueprintAnnotations'
import { blockText } from '~/utils/blueprintBlocks'
import BlueprintBlock from './BlueprintBlock.vue'

/**
 * 选区评论的载荷（⭐ **具名导出**，115-04/05/06 一律 `import type` 复用，⛔ 不各自重写）。
 *
 * ⚠️ `rect` 在 happy-dom 下**恒为 0 矩形**（无布局引擎，能力锁已实测）：逻辑层可自动化测，
 * popover 的实际落点属 UAT。
 */
export interface SelectionPayload {
  blockId: string
  startOffset: number
  endOffset: number
  quotedText: string
  rect: DOMRect
  /** ⭐ 键盘路径（block 内「对此块评论」按钮）：页面据此跳过 popover、直接开草稿卡。 */
  viaKeyboard?: boolean
}

const props = withDefaults(defineProps<{
  blocks?: BlueprintBlockModel[]
  sectionPath?: string
  /** 本段全部线程（组件内经 `groupThreadsByBlock` 按 `block_id` 分组，⛔ 调用方不必预分组）。 */
  threads?: BlueprintThreadDetail[]
  citations?: Record<string, Citation>
  readonly?: boolean
  activeThreadId?: string | null
  showClosed?: boolean
  loading?: boolean
  plainMermaid?: boolean
  /** 骨架条数（默认 3 条 `h-16`）。 */
  skeletonRows?: number
}>(), {
  blocks: () => [],
  sectionPath: '',
  threads: () => [],
  citations: () => ({}),
  readonly: false,
  activeThreadId: null,
  showClosed: false,
  loading: false,
  plainMermaid: false,
  skeletonRows: 3,
})

const emit = defineEmits<{
  'thread-click': [threadId: string, allThreadIds: string[]]
  'citation-click': [citationId: string]
  'selection-comment': [payload: SelectionPayload]
  'cross-block-selection': []
}>()

const { t } = useI18n()

/** `quoted_text` 上限：超出截断（⛔ 不整段回传，后端 anchor 只存快照）。 */
const QUOTED_TEXT_LIMIT = 500

/** 选区回调去抖窗口（毫秒）：拖选过程中 `selectionchange` 会连发。 */
const SELECTION_DEBOUNCE_MS = 120

const rootEl = ref<HTMLElement | null>(null)

const threadsByBlock = computed(() => groupThreadsByBlock(props.threads ?? []))

function threadsFor(blockId: string): BlueprintThreadDetail[] {
  return threadsByBlock.value[blockId] ?? []
}

/** 由任意节点向上找最近的 `[data-block-id]` 祖先（找不到返回 `null`）。 */
function closestBlockRoot(node: Node | null): HTMLElement | null {
  let current: Node | null = node
  while (current) {
    if (current.nodeType === 1) {
      const element = current as HTMLElement
      if (typeof element.getAttribute === 'function' && element.getAttribute('data-block-id'))
        return element
    }
    current = current.parentNode
  }
  return null
}

/**
 * 选区 → 评论的前四步（§7.4）。
 *
 * 1. 折叠选区 / 无 range ⇒ 直接 return（⛔ 不清状态，避免把已弹出的 popover 抖没）；
 * 2. 选区不在本 list 根内 ⇒ return（别的段 / 别的组件的选区，⛔ 不抢）；
 * 3. 两端各自的 `[data-block-id]` 不是同一个 ⇒ `cross-block-selection`（页面渲染 toast）；
 * 4. 同块 ⇒ 经 `rangeOffsets` 算扁平坐标系 offset，emit `selection-comment`。
 */
function detectSelection(): void {
  const root = rootEl.value
  if (!root)
    return

  const selection = window.getSelection?.()
  if (!selection || selection.isCollapsed || selection.rangeCount === 0)
    return

  const range = selection.getRangeAt(0)
  if (!root.contains(range.commonAncestorContainer))
    return

  const startBlock = closestBlockRoot(range.startContainer)
  const endBlock = closestBlockRoot(range.endContainer)
  if (!startBlock && !endBlock)
    return

  if (!startBlock || !endBlock || startBlock !== endBlock) {
    emit('cross-block-selection')
    return
  }

  const blockId = startBlock.getAttribute('data-block-id') ?? ''
  const offsets = rangeOffsets(range, startBlock)
  if (!blockId || !offsets)
    return

  emit('selection-comment', {
    blockId,
    startOffset: offsets.start,
    endOffset: offsets.end,
    quotedText: selection.toString().slice(0, QUOTED_TEXT_LIMIT),
    rect: range.getBoundingClientRect(),
  })
}

const onSelectionChange = useDebounceFn(detectSelection, SELECTION_DEBOUNCE_MS)

/**
 * ⭐ 键盘评论入口的载荷装配：整块作为选区（offset 覆盖全文），坐标系与拖选路径同源
 * （`blockText` 扁平串）⇒ 后端锚点校验与重锚逻辑零差别。
 */
function onCommentBlock(block: BlueprintBlockModel): void {
  const flat = blockText(block)
  if (!block.block_id || !flat)
    return
  const el = rootEl.value?.querySelector(`[data-block-id="${block.block_id}"]`)
  emit('selection-comment', {
    blockId: block.block_id,
    startOffset: 0,
    endOffset: flat.length,
    quotedText: flat.slice(0, QUOTED_TEXT_LIMIT),
    rect: el ? el.getBoundingClientRect() : new DOMRect(),
    viaKeyboard: true,
  })
}

onMounted(() => {
  document.addEventListener('selectionchange', onSelectionChange)
})

onUnmounted(() => {
  // ⛔ 漏这一行会让监听器在路由切换后继续触发（T-115-25）。
  document.removeEventListener('selectionchange', onSelectionChange)
})
</script>

<template>
  <div ref="rootEl" data-testid="blueprint-block-list" class="space-y-2">
    <template v-if="loading">
      <Skeleton v-for="i in skeletonRows" :key="i" class="h-16 w-full" />
    </template>

    <slot v-else-if="!blocks.length" />

    <!-- ⭐ 包装层承载键盘评论入口：按钮必须在 `[data-block-id]` **之外** ——
         块内多出的文本节点会污染 `rangeOffsets` 的扁平坐标系，让拖选 offset 整体偏移。 -->
    <div
      v-for="block in blocks"
      v-else
      :key="block.block_id"
      class="relative"
    >
      <!-- 键盘评论入口（skip-link 模式）：视觉隐藏，Tab 聚焦时浮现；
           鼠标用户仍走拖选 popover，两条路径殊途同归到同一个草稿卡。readonly 时不存在于 DOM。 -->
      <button
        v-if="!readonly"
        type="button"
        class="sr-only focus:not-sr-only focus:absolute focus:-top-1 focus:right-0 focus:z-10 focus:inline-flex focus:items-center focus:gap-1 focus:rounded-md focus:border focus:border-border focus:bg-background focus:px-2 focus:py-1 focus:text-xs focus:text-foreground focus:shadow-card"
        data-testid="blueprint-block-comment-kb"
        @click="onCommentBlock(block)"
      >
        <span class="icon-[lucide--message-square-plus]" aria-hidden="true" />
        {{ t('knowledge.blueprints.annotation.commentBlock') }}
      </button>

      <BlueprintBlock
        :block="block"
        :section-path="sectionPath"
        :threads="threadsFor(block.block_id)"
        :citations="citations"
        :readonly="readonly"
        :active-thread-id="activeThreadId"
        :show-closed="showClosed"
        :plain-mermaid="plainMermaid"
        @thread-click="(threadId, allThreadIds) => emit('thread-click', threadId, allThreadIds)"
        @citation-click="emit('citation-click', $event)"
      />
    </div>
  </div>
</template>
