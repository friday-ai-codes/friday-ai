<script setup lang="ts">
/**
 * block 正文人工编辑弹窗（CLAR-03 闭环相位，闭 115-UI-SPEC §0.2 判定 7 顺延的那一条）。
 *
 * ## 这个面为什么最终还是建了
 *
 * 115 把它顺延时给的**设计论证**是「在只读评审面开编辑入口 = 绕过『要改先驳回』的纪律」。
 * 该论证的前提在 114-MJ-04 之后已不成立：`edit-blocks` 端点如今有 `is_blueprint_editable`
 * 状态闸，**已 `confirmed` / `implementing` / `archived` 的蓝图一律 400**，「要改先驳回」由
 * 后端结构性兜住，不再依赖「前端不给入口」这条软纪律。CLAR-03 首句承诺的是一个**用户能力**
 * （「人类可直接编辑蓝图内容（block 级）」），端点齐备而产品面不可达，记账上就是把不可达的
 * 能力记成了已交付。⇒ 本组件把那半条兑现。
 *
 * ## 职责边界
 *
 * 一个 block 进、一批 `ops` 出。**本组件不发请求、不读 query**：只 emit `submit(ops)`，
 * 由查看器页面调 `blueprintsApi.editBlueprintBlocks` 并把结果分档回喂（`errorDetail` /
 * `conflict`）。范式与 `BlueprintRejectDialog` 一致（受控 `open` + `update:open` + `submit`）。
 *
 * ## 三档产出与两档回喂
 *
 * - **保存** ⇒ 一条 `replace` op（整块替换，`block_id` 逐字保留 —— 改 id 会把该块上的全部
 *   线程 anchor 打散）。
 * - **删除** ⇒ 一条 `delete` op，且**必须**先过 `useConfirmDialog` 的 destructive 二次确认：
 *   删块会让挂在它上面的批注线程当场失锚（后端 `areanchor_threads` 置 `orphaned`），是本面
 *   唯一不可由「再编辑一次」原地撤销的动作。
 * - **冲突回喂**（`conflict: true`）⇒ 渲染独立的冲突面板 + 「刷新后重试」，⛔ 不是一句
 *   toast 就算数：这一档的语义是「你的编辑是基于一份已经不是最新的正文算出来的」，
 *   唯一解药是拿最新正文重来，必须给出这个出口。
 *
 * ## 坐标系（⛔ 不按 `block.type` 分派）
 *
 * 写回字段由 `blockEditOps.blockEditTarget` 按**字段优先级**判定，与读侧 `blockText`
 * （`~/utils/blueprintBlocks`，后端 `_block_text` 的逐字同源件）互为逆运算。按 `type` 分派
 * 会造出「读取自 `text`、写回进 `code.source`」这种把原文复制成两份的块 —— 症状是编辑看着
 * 生效了，下次打开又变回旧文。
 *
 * ⛔ **`rows`（table）不可编辑**：它的文本坐标系是「单元格扁平后 `\n` 连接」，单框文本编辑
 * 压平行列后无法还原成 `rows`。与 115 对 table 强制整块批注的处置同源，登记为顺延。
 *
 * 安全：正文全程 `Textarea` + mustache，⛔ 无任何原始 HTML 注入指令。
 */

import type { BlueprintBlock, BlueprintBlockEditRejection, BlueprintBlockOp } from '~/types/blueprint'
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Button } from '~/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '~/components/ui/dialog'
import { Textarea } from '~/components/ui/textarea'
import { useConfirmDialog } from '~/composables/useConfirmDialog'
import { blockText } from '~/utils/blueprintBlocks'
import { blockEditTarget, withBlockText } from './blockEditOps'

const props = withDefaults(defineProps<{
  open: boolean
  /** 待编辑的块；`null` ⇒ 弹窗内容为空（父层一般同时把 `open` 置 false）。 */
  block?: BlueprintBlock | null
  submitting?: boolean
  /** 后端 400 的可回显中文错因（`rejected` / `invalid` 两档共用）。 */
  errorDetail?: string
  /** 被拒条目逐条回显（`reason` 是稳定枚举，⛔ 不翻译成自造文案）。 */
  rejected?: BlueprintBlockEditRejection[]
  /** ⭐ 冲突态：基线已被推进（`block_not_found`）⇒ 渲染独立面板 + 刷新出口。 */
  conflict?: boolean
}>(), {
  block: null,
  submitting: false,
  errorDetail: '',
  rejected: () => [],
  conflict: false,
})

const emit = defineEmits<{
  'update:open': [value: boolean]
  'submit': [ops: BlueprintBlockOp[]]
  'refresh': []
}>()

const { t } = useI18n()
const { confirm } = useConfirmDialog()

const draft = ref('')
const textarea = ref<InstanceType<typeof Textarea> | null>(null)

const originalText = computed(() => blockText(props.block))
const target = computed(() => blockEditTarget(props.block))
const canEditText = computed(() => target.value !== null)

/** 与原文逐字相同就不必提交（后端会回 `unchanged`，但白跑一趟请求没有意义）。 */
const isDirty = computed(() => draft.value !== originalText.value)
const canSubmit = computed(
  () => canEditText.value && isDirty.value && !props.submitting && !props.conflict,
)

// `immediate` 不可省：弹窗若在**挂载那一刻**就已 `open`，非 immediate 的 watch 不会触发 ⇒
// 草稿停在空串、`isDirty` 假阳性 ⇒ 一进来保存按钮就是可点的，点下去把整块清空。
watch(() => props.open, (value) => {
  if (value)
    draft.value = originalText.value
}, { immediate: true })

/** 换块（父层在弹窗开着时切了目标）也要重置草稿，⛔ 否则会把 A 块的文本写进 B 块。 */
watch(() => props.block?.block_id, () => {
  if (props.open)
    draft.value = originalText.value
})

function setOpen(value: boolean): void {
  emit('update:open', value)
}

/** reka-ui 的 `open-auto-focus`：初始焦点落在正文输入框（§18.2）。 */
function focusDraft(event: Event): void {
  event.preventDefault()
  void nextTick(() => {
    const el = (textarea.value as unknown as { $el?: HTMLElement } | null)?.$el
    if (el && typeof el.focus === 'function')
      el.focus()
  })
}

function submitReplace(): void {
  const block = props.block
  if (!canSubmit.value || !block)
    return
  emit('submit', [{
    op: 'replace',
    block_id: block.block_id,
    block: withBlockText(block, draft.value),
  }])
}

/** ⭐ 删块不可原地撤销（挂在它上面的批注会当场失锚）⇒ 走全局 destructive 二次确认。 */
async function submitDelete(): Promise<void> {
  const block = props.block
  if (!block || props.submitting || props.conflict)
    return
  const ok = await confirm({
    title: t('knowledge.blueprints.edit.deleteTitle'),
    description: t('knowledge.blueprints.edit.deleteBody'),
    confirmText: t('knowledge.blueprints.edit.deleteConfirm'),
    variant: 'destructive',
  })
  if (ok)
    emit('submit', [{ op: 'delete', block_id: block.block_id }])
}
</script>

<template>
  <Dialog :open="open" @update:open="setOpen">
    <DialogContent
      data-testid="blueprint-block-edit-dialog"
      class="max-w-2xl"
      @open-auto-focus="focusDraft"
    >
      <DialogHeader>
        <DialogTitle>{{ t('knowledge.blueprints.edit.title') }}</DialogTitle>
        <DialogDescription>{{ t('knowledge.blueprints.edit.body') }}</DialogDescription>
      </DialogHeader>

      <!-- ⭐ 冲突态：独立面板 + 刷新出口，⛔ 不是静默 no-op 也不是一句 toast -->
      <div
        v-if="conflict"
        data-testid="blueprint-block-edit-conflict"
        class="space-y-2 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-sm"
        role="alert"
      >
        <p class="flex items-center gap-2">
          <span class="icon-[lucide--git-pull-request-arrow]" aria-hidden="true" />
          <span>{{ t('knowledge.blueprints.edit.conflictNotice') }}</span>
        </p>
        <Button
          variant="outline"
          size="sm"
          data-testid="blueprint-block-edit-refresh"
          @click="emit('refresh')"
        >
          {{ t('knowledge.blueprints.edit.conflictRefresh') }}
        </Button>
      </div>

      <template v-else>
        <p
          v-if="!canEditText"
          data-testid="blueprint-block-edit-unsupported"
          class="rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground"
        >
          {{ t('knowledge.blueprints.edit.unsupported') }}
        </p>

        <Textarea
          v-else
          ref="textarea"
          v-model="draft"
          data-testid="blueprint-block-edit-textarea"
          class="min-h-48 font-mono text-sm"
          :placeholder="t('knowledge.blueprints.edit.placeholder')"
        />

        <p
          v-if="errorDetail"
          data-testid="blueprint-block-edit-error"
          class="text-xs text-destructive"
        >
          {{ errorDetail }}
        </p>

        <ul v-if="rejected.length" data-testid="blueprint-block-edit-rejected" class="space-y-0.5">
          <li v-for="(item, index) in rejected" :key="index" class="font-mono text-[11px] text-muted-foreground">
            {{ item.op }} · {{ item.block_id }} · {{ item.reason }}
          </li>
        </ul>
      </template>

      <DialogFooter>
        <Button
          v-if="!conflict"
          variant="destructive"
          size="sm"
          class="mr-auto"
          data-testid="blueprint-block-edit-delete"
          :disabled="submitting"
          @click="submitDelete"
        >
          <span class="icon-[lucide--trash-2] mr-1.5" aria-hidden="true" />
          {{ t('knowledge.blueprints.edit.delete') }}
        </Button>
        <Button
          v-if="!conflict"
          variant="default"
          size="sm"
          data-testid="blueprint-block-edit-submit"
          :disabled="!canSubmit"
          @click="submitReplace"
        >
          {{ t('knowledge.blueprints.edit.save') }}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>
