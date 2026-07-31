<script setup lang="ts">
/**
 * 选区浮层（Phase 115-04，UI-SPEC §7.4 / §7.9 / §18.1）。
 *
 * 输入是 `BlueprintBlockList` 侦测到的选区矩形（`range.getBoundingClientRect()`），
 * 输出是两个动作：「发起评论」（父层据此建线程走 `blueprint-review/threads/`）与「复制原文」。
 *
 * ⭐ **定位方案在 115-02 已定夺，锁在方案层面**：`PopoverAnchor` **直接从 `reka-ui` 导入**
 * （实测 `reka-ui@2.9.10` 的 `dist/index.js` 与 `dist/index.d.ts` 都导出它），套一个
 * `position: fixed` 的**零尺寸虚拟锚点** div；容器与内容仍用 `~/components/ui/popover` 的
 * `Popover` / `PopoverContent`。
 * ⛔ **不要从 `~/components/ui/popover` 拿 `PopoverAnchor`** —— 那个 barrel 只导出
 * `Popover` / `PopoverContent` / `PopoverTrigger` 三个，给它补一行导出就是本 plan 的第七处
 * 既有文件修改，违反 CREATE-ONLY。本地 wrapper 自己也是直接从 `reka-ui` 取原语的
 * （`ui/popover/Popover.vue` 就是 `import { PopoverRoot, useForwardPropsEmits } from 'reka-ui'`）。
 * ⛔ 不引入浮层定位库、不手搓定位算法（全仓零调用点，API 形状未实测）。
 *
 * ⭐ **`canComment === false`（即可编辑闸关闭）时「发起评论」按钮不存在于 DOM**（§7.9），
 * 只留「复制原文」。⛔ 不是 `disabled` —— 渲染一个会撞 400 的入口等于把用户送进死路。
 *
 * a11y（§18.1）：浮层出现后**焦点不自动抢占**（抢焦点会打断选区），`Tab` 可进入，
 * `Esc` 关闭且**保留选区**（本组件只 emit `dismiss`，⛔ 不去动 `window.getSelection()`）。
 * 按钮触控目标 ≥44px；焦点环用不透明 `--color-primary-600`（3.74:1），
 * ⛔ 不复制既有 `.btn:focus-visible` 的 50% 透明 teal-500（实算 1.59:1，未过 WCAG 2.4.11）。
 *
 * ⚠️ happy-dom 无布局引擎、`getBoundingClientRect` 恒返 0 矩形 ⇒ **落点坐标归 UAT**；
 * 自动化只测「按钮渲染与否 / 事件派发」。
 */

import { PopoverAnchor } from 'reka-ui'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Button } from '~/components/ui/button'
import { Popover, PopoverContent } from '~/components/ui/popover'

const props = withDefaults(defineProps<{
  /** 选区矩形；`null` = 无选区 ⇒ 浮层关闭。 */
  rect: DOMRect | null
  /** `isBlueprintEditable(current_status)`；为 `false` 时「发起评论」不渲染。 */
  canComment?: boolean
}>(), {
  canComment: true,
})

const emit = defineEmits<{
  comment: []
  copy: []
  dismiss: []
}>()

const { t } = useI18n()

const FOCUS_CLASS = 'outline-none focus-visible:[outline:2px_solid_var(--color-primary-600)] focus-visible:[outline-offset:2px]'

const isOpen = computed(() => props.rect !== null)

/** 零尺寸虚拟锚点：贴住选区矩形，`pointer-events: none` 以免挡住正文选择。 */
const anchorStyle = computed(() => ({
  position: 'fixed' as const,
  top: `${props.rect?.top ?? 0}px`,
  left: `${props.rect?.left ?? 0}px`,
  width: `${props.rect?.width ?? 0}px`,
  height: `${props.rect?.height ?? 0}px`,
  pointerEvents: 'none' as const,
}))

function onOpenChange(value: boolean): void {
  if (!value)
    emit('dismiss')
}

/** ⭐ 不抢焦点：抢了会清掉用户刚拖出来的选区。 */
function keepSelection(event: Event): void {
  event.preventDefault()
}
</script>

<template>
  <Popover :open="isOpen" @update:open="onOpenChange">
    <PopoverAnchor as="div" :style="anchorStyle" aria-hidden="true" />
    <PopoverContent
      data-testid="blueprint-selection-popover"
      side="top"
      :side-offset="8"
      class="w-auto p-1.5"
      @open-auto-focus="keepSelection"
      @close-auto-focus="keepSelection"
    >
      <div class="flex items-center gap-1">
        <Button
          v-if="canComment"
          size="sm"
          variant="ghost"
          data-testid="blueprint-selection-comment"
          :class="`min-h-11 ${FOCUS_CLASS}`"
          @click="emit('comment')"
        >
          <span class="icon-[lucide--message-square-plus] mr-1.5" aria-hidden="true" />
          {{ t('knowledge.blueprints.annotation.selection.comment') }}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          data-testid="blueprint-selection-copy"
          :class="`min-h-11 ${FOCUS_CLASS}`"
          @click="emit('copy')"
        >
          <span class="icon-[lucide--copy] mr-1.5" aria-hidden="true" />
          {{ t('knowledge.blueprints.annotation.selection.copy') }}
        </Button>
      </div>
    </PopoverContent>
  </Popover>
</template>
