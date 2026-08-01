/**
 * block 级人工编辑面的组件测试（CLAR-03 闭环相位）。
 *
 * 这条需求是被里程碑审计从「Complete」打回成缺口的：**后端端点齐备、前端零消费方**，
 * 而六份相位 VERIFICATION 结构性地看不见它（114 只验后端、115 的需求清单不含 CLAR-03）。
 * 因此本文件的三条主用例逐条对着「用户在产品里点哪里能做到这件事」写，⛔ 不测「函数存在」。
 *
 * 覆盖路径：
 *  1. ⭐ **可达性闸**：`confirmed`（不在可编辑白名单）⇒ 闸判假 ⇒ 选区浮层里
 *     `blueprint-selection-edit` **不存在于 DOM**；`pending_review` ⇒ 存在且点击 emit `edit`。
 *     另加历史版本 / diff 视图 / table 块三条负向。
 *     （变异证据见文件尾注 ①）
 *  2. ⭐ **成功编辑的 `ops` 载荷良构**：改文本 → 提交 ⇒ 恰一条 `replace` op，`block_id`
 *     逐字保留、`block` 带新正文；再经 api 层断言**打的是 edit-blocks 端点、body 是 `{ops}`**。
 *  3. ⭐ **冲突态渲染成独立状态**：`conflict` 为真 ⇒ 冲突面板 + 刷新出口存在，输入框与保存
 *     按钮**都不在**（⛔ 不能让用户对着一份已经过时的基线继续点保存）。
 *  4. 写回坐标系与读侧 `blockText` 互逆（string / 数组 / `code.source` 三档 + table 判空）。
 *  5. 删块必须过 destructive 二次确认：确认前零 emit，确认后 emit 一条 `delete` op。
 */

import type { BlueprintBlock } from '~/types/blueprint'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import {
  blockEditTarget,
  canEditBlueprintBlock,
  withBlockText,
} from '~/components/blueprint/blockEditOps'
import BlueprintBlockEditDialog from '~/components/blueprint/BlueprintBlockEditDialog.vue'
import BlueprintSelectionPopover from '~/components/blueprint/BlueprintSelectionPopover.vue'
import { useConfirmDialog } from '~/composables/useConfirmDialog'

vi.mock('~/api/client', () => ({
  get: vi.fn(),
  post: vi.fn(async () => ({ status: 'applied', version_id: 'v2', version_no: 2, rejected: [], reanchor: {} })),
  ApiError: class ApiError extends Error {},
}))

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  missingWarn: false,
  fallbackWarn: false,
  messages: {
    'zh-CN': {
      knowledge: {
        blueprints: {
          annotation: {
            selection: { comment: '发起评论', edit: '编辑此块', copy: '复制原文' },
          },
          edit: {
            title: '编辑本块正文',
            body: '保存后生成一个新版本',
            placeholder: '写入本块的正文…',
            save: '保存并生成新版本',
            delete: '删除本块',
            deleteTitle: '删除本块',
            deleteBody: '删除后挂在本块上的批注会失去锚点',
            deleteConfirm: '确认删除',
            unsupported: '本块是表格，暂不支持在此直接编辑正文',
            conflictNotice: '方案正文在你编辑期间已被更新',
            conflictRefresh: '刷新后重试',
          },
        },
      },
    },
  },
})

/** reka-ui 的 Dialog / Popover 走 Portal，VTU 里看不到 ⇒ 拍平成裸 div（范式同 115 各 spec）。 */
const OVERLAY_STUBS = {
  Dialog: { template: '<div><slot /></div>' },
  DialogContent: { template: '<div><slot /></div>' },
  DialogHeader: { template: '<div><slot /></div>' },
  DialogTitle: { template: '<div><slot /></div>' },
  DialogDescription: { template: '<div><slot /></div>' },
  DialogFooter: { template: '<div><slot /></div>' },
  Popover: { template: '<div><slot /></div>' },
  PopoverAnchor: { template: '<div><slot /></div>' },
  PopoverContent: { template: '<div><slot /></div>' },
}

const EDIT_BUTTON = '[data-testid="blueprint-selection-edit"]'
const TEXTAREA = '[data-testid="blueprint-block-edit-textarea"]'
const SUBMIT = '[data-testid="blueprint-block-edit-submit"]'
const DELETE = '[data-testid="blueprint-block-edit-delete"]'
const CONFLICT = '[data-testid="blueprint-block-edit-conflict"]'
const REFRESH = '[data-testid="blueprint-block-edit-refresh"]'

function makeBlock(overrides: Partial<BlueprintBlock> = {}): BlueprintBlock {
  return { block_id: 'blk_01', type: 'paragraph', text: '原始正文', ...overrides }
}

function mountPopover(props: Record<string, unknown> = {}) {
  return mount(BlueprintSelectionPopover, {
    props: { rect: { top: 0, left: 0, width: 10, height: 10 } as DOMRect, ...props },
    global: { plugins: [i18n], stubs: OVERLAY_STUBS },
  })
}

function mountDialog(props: Record<string, unknown> = {}) {
  return mount(BlueprintBlockEditDialog, {
    props: { open: true, block: makeBlock(), ...props },
    global: { plugins: [i18n], stubs: OVERLAY_STUBS },
  })
}

// ── 1. 可达性闸 ────────────────────────────────────────────────────────────────

describe('cLAR-03 ①：编辑入口的可达性闸', () => {
  it('1a. ⭐ `confirmed` 蓝图判假、`pending_review` 判真（白名单成员对齐后端）', () => {
    const block = makeBlock()
    expect(canEditBlueprintBlock('confirmed', block)).toBe(false)
    expect(canEditBlueprintBlock('implementing', block)).toBe(false)
    expect(canEditBlueprintBlock('archived', block)).toBe(false)
    // 白名单六值各取三条正向，证明判据非恒假
    expect(canEditBlueprintBlock('pending_review', block)).toBe(true)
    expect(canEditBlueprintBlock('drafting', block)).toBe(true)
    expect(canEditBlueprintBlock('needs_clarification', block)).toBe(true)
  })

  it('1b. 历史版本 / diff 视图 / table 块 / 查不到块，四条各自判假', () => {
    const block = makeBlock()
    expect(canEditBlueprintBlock('pending_review', block, { historicalVersion: true })).toBe(false)
    expect(canEditBlueprintBlock('pending_review', block, { diffMode: true })).toBe(false)
    expect(
      canEditBlueprintBlock('pending_review', { block_id: 't1', type: 'table', rows: [['a']] }),
    ).toBe(false)
    expect(canEditBlueprintBlock('pending_review', null)).toBe(false)
  })

  it('1c. ⭐ 闸判假 ⇒「编辑此块」**不存在于 DOM**（⛔ 不是 disabled）', () => {
    const wrapper = mountPopover({ canEdit: false })
    expect(wrapper.find(EDIT_BUTTON).exists()).toBe(false)
    // 负向对照：同一次渲染里「复制原文」照常在 ⇒ 证明不是整个浮层没渲染出来
    expect(wrapper.find('[data-testid="blueprint-selection-copy"]').exists()).toBe(true)
  })

  it('1d. 闸判真 ⇒ 按钮存在且点击 emit `edit`', async () => {
    const wrapper = mountPopover({ canEdit: true })
    const button = wrapper.find(EDIT_BUTTON)
    expect(button.exists()).toBe(true)
    await button.trigger('click')
    expect(wrapper.emitted('edit')).toHaveLength(1)
  })

  it('1e. `canEdit` 默认关闭（新能力对既有调用点默认不生效）', () => {
    expect(mountPopover().find(EDIT_BUTTON).exists()).toBe(false)
  })
})

// ── 2. ops 载荷良构 ────────────────────────────────────────────────────────────

describe('cLAR-03 ②：成功编辑的 ops 载荷', () => {
  it('2a. ⭐ 改文本后提交 ⇒ 恰一条 replace op，`block_id` 逐字保留、正文是新值', async () => {
    const wrapper = mountDialog({ block: makeBlock({ citations: ['c1'] }) })
    await wrapper.find(TEXTAREA).setValue('改过的正文')
    await wrapper.find(SUBMIT).trigger('click')

    const ops = wrapper.emitted('submit')?.[0]?.[0] as Record<string, unknown>[]
    expect(ops).toHaveLength(1)
    expect(ops[0].op).toBe('replace')
    expect(ops[0].block_id).toBe('blk_01')
    expect(ops[0].block).toMatchObject({
      block_id: 'blk_01',
      type: 'paragraph',
      text: '改过的正文',
      // 编辑面不碰引用绑定
      citations: ['c1'],
    })
  })

  it('2b. 未改动 ⇒ 保存按钮 disabled 且零 emit（⛔ 不白跑一趟必然 unchanged 的请求）', async () => {
    const wrapper = mountDialog()
    expect(wrapper.find(SUBMIT).attributes('disabled')).toBeDefined()
    await wrapper.find(SUBMIT).trigger('click')
    expect(wrapper.emitted('submit')).toBeUndefined()
  })

  it('2c. ⭐ api 层打的是 edit-blocks 端点，body 恰为 `{ops}`', async () => {
    const client = await import('~/api/client')
    const { editBlueprintBlocks } = await import('~/api/blueprints')
    const ops = [{ op: 'replace' as const, block_id: 'blk_01', block: makeBlock() }]

    await editBlueprintBlocks('art-1', { ops })

    expect(client.post).toHaveBeenCalledWith(
      '/delivery/artifacts/art-1/blueprint-review/edit-blocks/',
      { ops },
    )
  })
})

// ── 3. 冲突态 ─────────────────────────────────────────────────────────────────

describe('cLAR-03 ③：冲突态渲染成独立的可操作状态', () => {
  it('3a. ⭐ `conflict` ⇒ 冲突面板 + 刷新出口在，输入框与保存按钮**都不在**', () => {
    const wrapper = mountDialog({ conflict: true })
    expect(wrapper.find(CONFLICT).exists()).toBe(true)
    expect(wrapper.find(REFRESH).exists()).toBe(true)
    expect(wrapper.find(TEXTAREA).exists()).toBe(false)
    expect(wrapper.find(SUBMIT).exists()).toBe(false)
    expect(wrapper.find(CONFLICT).text()).toContain('已被更新')
  })

  it('3b. 非冲突态下冲突面板不存在（证明 3a 不是恒真）', () => {
    const wrapper = mountDialog({ conflict: false })
    expect(wrapper.find(CONFLICT).exists()).toBe(false)
    expect(wrapper.find(TEXTAREA).exists()).toBe(true)
  })

  it('3c. 点刷新 ⇒ emit `refresh`（这一档的唯一解药，⛔ 不是静默 no-op）', async () => {
    const wrapper = mountDialog({ conflict: true })
    await wrapper.find(REFRESH).trigger('click')
    expect(wrapper.emitted('refresh')).toHaveLength(1)
  })

  it('3d. 硬失败（非冲突）就近回显 detail 与逐条 reason，⛔ 不关窗', () => {
    const wrapper = mountDialog({
      errorDetail: 'patch 存在无法应用的操作',
      rejected: [{ op: 'replace', block_id: 'blk_01', reason: 'missing_block' }],
    })
    expect(wrapper.find('[data-testid="blueprint-block-edit-error"]').text())
      .toBe('patch 存在无法应用的操作')
    expect(wrapper.find('[data-testid="blueprint-block-edit-rejected"]').text())
      .toContain('missing_block')
    expect(wrapper.find(TEXTAREA).exists()).toBe(true)
  })
})

// ── 4. 写回坐标系 ─────────────────────────────────────────────────────────────

describe('cLAR-03 ④：写回落点与读侧 blockText 互逆', () => {
  it('4a. 三档落点判定 + table 判空', () => {
    expect(blockEditTarget(makeBlock())).toBe('text')
    expect(blockEditTarget({ block_id: 'b', type: 'list', text: ['a', 'b'] })).toBe('text_lines')
    expect(blockEditTarget({ block_id: 'b', type: 'pseudocode', code: { source: 'x' } })).toBe('code_source')
    expect(blockEditTarget({ block_id: 'b', type: 'table', rows: [['a']] })).toBeNull()
    // 空块兜底成字符串 text（否则新写的正文无处落地）
    expect(blockEditTarget({ block_id: 'b', type: 'paragraph' })).toBe('text')
  })

  it('4b. ⭐ 数组 text 按 `\\n` 还原成数组，pseudocode 写回 `code.source`', () => {
    const list = withBlockText({ block_id: 'b', type: 'list', text: ['a'] }, '甲\n乙')
    expect(list.text).toEqual(['甲', '乙'])

    const code = withBlockText(
      { block_id: 'b', type: 'pseudocode', code: { language: 'py', source: 'old' } },
      'new',
    )
    expect(code.code).toEqual({ language: 'py', source: 'new' })
  })

  it('4c. ⛔ 入参不被原地修改（它来自 query 缓存）', () => {
    const original = makeBlock()
    const next = withBlockText(original, '新的')
    expect(original.text).toBe('原始正文')
    expect(next.text).toBe('新的')
    expect(next).not.toBe(original)
  })
})

// ── 5. 删块二次确认 ───────────────────────────────────────────────────────────

describe('cLAR-03 ⑤：删块走 destructive 二次确认', () => {
  beforeEach(() => {
    const { isOpen } = useConfirmDialog()
    isOpen.value = false
  })

  it('5a. 点删除只打开确认框，确认前零 emit', async () => {
    const wrapper = mountDialog()
    const { isOpen, options } = useConfirmDialog()
    await wrapper.find(DELETE).trigger('click')

    expect(isOpen.value).toBe(true)
    expect(options.value.variant).toBe('destructive')
    expect(wrapper.emitted('submit')).toBeUndefined()
  })

  it('5b. ⭐ 确认后 emit 恰一条 delete op', async () => {
    const wrapper = mountDialog()
    const { handleConfirm } = useConfirmDialog()
    await wrapper.find(DELETE).trigger('click')
    handleConfirm()
    await new Promise(resolve => setTimeout(resolve, 0))

    const ops = wrapper.emitted('submit')?.[0]?.[0] as Record<string, unknown>[]
    expect(ops).toEqual([{ op: 'delete', block_id: 'blk_01' }])
  })

  it('5c. 取消后零 emit', async () => {
    const wrapper = mountDialog()
    const { handleCancel } = useConfirmDialog()
    await wrapper.find(DELETE).trigger('click')
    handleCancel()
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(wrapper.emitted('submit')).toBeUndefined()
  })
})

/*
 * ① 可达性闸的变异证据（本地实跑，见 CLAR-03 闭环记录）：
 *    - 把 `canEditBlueprintBlock` 的 `isBlueprintEditable` 判断删掉 ⇒ 1a 转红
 *      （`confirmed` 从 false 变 true）。
 *    - 把 `BlueprintSelectionPopover` 那颗按钮的 `v-if="canEdit"` 删掉 ⇒ 1c / 1e 转红。
 *    ⇒ 两条断言都不是恒真。
 */
