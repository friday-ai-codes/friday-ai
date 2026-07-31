/**
 * `BlueprintBlock.vue` / `BlueprintBlockList.vue` 组件测试（Phase 115-03）。
 *
 * 覆盖路径（编号与 115-03-PLAN Task 3 ①逐条对应）：
 *  1. 五类块各渲染一条：paragraph / list / table / pseudocode / mermaid（⭐ 必 stub MermaidDiagram，
 *     否则要连带 vue-final-modal 插件）
 *  2. `<mark>` 计数与属性：两条不重叠 ⇒ 2 个；两条重叠 ⇒ 切成 3 个不相交子段，中间那段列出 2 条
 *  3. ⭐ 越界整块色条（§20 断言 8）+ **负向对照**（offset 改合法 ⇒ 有 mark、无 degraded）
 *  4. ⭐ table / mermaid 强制整块：挂**合法** offset 的线程仍走整块、mark 计数 0
 *  5. ⭐ orphaned 正文完全不渲染：mark 0 **且** degraded 也不出现（连整块色条都不给）
 *  6. resolved/dismissed 默认不着色；`showClosed` 打开后着色，类名用 `annotationClass` 的真实返回断言
 *  7. ⭐ 无编辑入口：emitted 键集 ⊆ {thread-click, citation-click}，⛔ 不含 selection-comment
 *  8. citation chip：池中取不到的 id 不渲染；外链 chip 是 `<a target="_blank">` 且点击不 emit；
 *     站内 chip 点击 emit 一次
 *  9. ⭐ `blockText` 同源（P-13）：`type: pseudocode` 且 `text` 非空 ⇒ 可划线文本取 `text`
 * 10. 选区 emit（在 `BlueprintBlockList` 上测）：同块 ⇒ `selection-comment` 四键载荷；
 *     跨块 ⇒ `cross-block-selection`
 *
 * A2 能力锁结论（115-02）：happy-dom 20.10.2 的 `createRange` / `createTreeWalker` /
 * `getSelection` **全部支持** ⇒ 第 10 条走**真实 DOM 选区**，⛔ 不降级成手工造 payload。
 * 仍归 UAT 的只有 `getBoundingClientRect` 的**落点坐标**（无布局引擎，恒 0 矩形）。
 */

import type { BlueprintBlock as BlueprintBlockModel, BlueprintThreadDetail, Citation } from '~/types/blueprint'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createI18n } from 'vue-i18n'
import { annotationClass } from '~/components/blueprint/annotationTokens'
import BlueprintBlock from '~/components/blueprint/BlueprintBlock.vue'
import BlueprintBlockList from '~/components/blueprint/BlueprintBlockList.vue'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  missingWarn: false,
  fallbackWarn: false,
  messages: {
    'zh-CN': {
      knowledge: {
        blueprints: {
          block: {
            copy: '复制本段原文',
            copied: '已复制',
            language: '语言：{name}',
            diagramUnavailable: '流程图暂时无法渲染，以下为原始定义',
          },
          annotation: {
            markLabel: '共 {count} 条批注（{kind}）',
            degraded: '无法精确定位到原文片段，已标注整块',
            quotedSnapshot: '引用时的原文快照',
            crossBlock: '评论只能针对同一段落内的文字，请缩小选区',
          },
          citation: {
            open: '查看引用来源',
            openExternal: '在新页面打开',
            fallback: '原始来源不可达，以下为引用时的快照',
            sourceKnowledgeEntity: '知识条目',
            sourceRepoFile: '仓库文件',
            sourceUrl: '外部链接',
          },
          thread: {
            kindAiClarification: 'AI 提问',
            kindAiReviewFinding: 'AI 审查',
            kindHumanComment: '人工评论',
            kindRepoConfirmation: '确认门',
          },
        },
      },
    },
  },
})

/** 长度 10 的默认正文，方便手算 offset。 */
const DEFAULT_TEXT = '0123456789'

function makeBlock(overrides: Partial<BlueprintBlockModel> = {}): BlueprintBlockModel {
  return { block_id: 'b1', type: 'paragraph', text: DEFAULT_TEXT, ...overrides }
}

function makeThread(overrides: Partial<BlueprintThreadDetail> = {}): BlueprintThreadDetail {
  return {
    thread_id: 't1',
    kind: 'ai_review_finding',
    severity: 'blocker',
    status: 'open',
    blocking: true,
    anchor_status: 'anchored',
    anchor: { block_id: 'b1', start_offset: 0, end_offset: 3 },
    return_stage: '',
    created_at: '2026-08-01T00:00:00Z',
    options: [],
    last_reminded_at: null,
    messages: [],
    ...overrides,
  }
}

function makeCitation(overrides: Partial<Citation> = {}): Citation {
  return {
    citation_id: 'c1',
    source_type: 'knowledge_entity',
    source_id: 'entity-1',
    title: '知识条目一',
    ...overrides,
  }
}

interface BlockProps {
  block: BlueprintBlockModel
  sectionPath?: string
  threads?: BlueprintThreadDetail[]
  citations?: Record<string, Citation>
  readonly?: boolean
  activeThreadId?: string | null
  showClosed?: boolean
  plainMermaid?: boolean
}

function mountBlock(props: BlockProps) {
  return mount(BlueprintBlock, {
    props,
    global: { plugins: [i18n], stubs: { MermaidDiagram: true } },
  })
}

const MARK = '[data-testid="blueprint-annotation-mark"]'
const CHIP = '[data-testid="blueprint-citation-chip"]'

describe('blueprintBlock.vue —— 五类块渲染', () => {
  it('1a. paragraph 渲染 <p> 且正文可见', () => {
    const wrapper = mountBlock({ block: makeBlock() })
    expect(wrapper.find('p').exists()).toBe(true)
    expect(wrapper.text()).toContain(DEFAULT_TEXT)
  })

  it('1b. list 渲染 <ul>，<li> 数 == 条目数（offset 坐标系是 \\n 连接的扁平串）', () => {
    const wrapper = mountBlock({
      block: makeBlock({ type: 'list', text: ['第一条', '第二条', '第三条'] }),
    })
    expect(wrapper.find('ul').exists()).toBe(true)
    expect(wrapper.findAll('li')).toHaveLength(3)
    expect(wrapper.text()).toContain('第二条')
  })

  it('1c. table 渲染语义 <table>，<th> 数 == rows[0].length', () => {
    const wrapper = mountBlock({
      block: makeBlock({ type: 'table', text: null, rows: [['列一', '列二'], ['值一', '值二']] }),
    })
    expect(wrapper.find('table').exists()).toBe(true)
    expect(wrapper.findAll('th')).toHaveLength(2)
    expect(wrapper.text()).toContain('值二')
  })

  it('1d. pseudocode 渲染 <pre> 且含 code.source 与语言徽标', () => {
    const wrapper = mountBlock({
      block: makeBlock({
        type: 'pseudocode',
        text: null,
        code: { language: 'python', source: 'def main():\n    pass' },
      }),
    })
    expect(wrapper.find('pre').exists()).toBe(true)
    expect(wrapper.text()).toContain('def main():')
    expect(wrapper.text()).toContain('语言：python')
  })

  it('1e. mermaid 在 stub 下渲染 MermaidDiagram；空源码时不渲染它', () => {
    const withCode = mountBlock({ block: makeBlock({ type: 'mermaid', text: 'graph TD;A-->B;' }) })
    expect(withCode.html()).toContain('mermaid-diagram-stub')

    const empty = mountBlock({ block: makeBlock({ type: 'mermaid', text: '' }) })
    expect(empty.html()).not.toContain('mermaid-diagram-stub')
  })

  it('1f. plainMermaid 为 true 时 mermaid 退化为源码 <pre>（预览弹层内不渲染图）', () => {
    const wrapper = mountBlock({
      block: makeBlock({ type: 'mermaid', text: 'graph TD;A-->B;' }),
      plainMermaid: true,
    })
    expect(wrapper.html()).not.toContain('mermaid-diagram-stub')
    expect(wrapper.find('pre').text()).toContain('graph TD;A-->B;')
  })
})

describe('blueprintBlock.vue —— <mark> 切分与属性', () => {
  it('2a. 两条不重叠的 anchored 线程 ⇒ 2 个 <mark>，data-thread-id 各自正确', () => {
    const wrapper = mountBlock({
      block: makeBlock(),
      threads: [
        makeThread({ thread_id: 't1', anchor: { block_id: 'b1', start_offset: 0, end_offset: 3 } }),
        makeThread({ thread_id: 't2', anchor: { block_id: 'b1', start_offset: 5, end_offset: 8 } }),
      ],
    })
    const marks = wrapper.findAll(MARK)
    expect(marks).toHaveLength(2)
    expect(marks.map(m => m.attributes('data-thread-id'))).toEqual(['t1', 't2'])
    expect(marks[0].attributes('role')).toBe('button')
    expect(marks[0].attributes('tabindex')).toBe('0')
    expect(marks[0].attributes('data-severity')).toBe('blocker')
    expect(marks[0].attributes('data-thread-status')).toBe('open')
  })

  it('2b. 两条重叠 ⇒ 切成 3 个不相交子段，中间那段的 aria-label 列出 2 条', () => {
    const wrapper = mountBlock({
      block: makeBlock(),
      threads: [
        makeThread({ thread_id: 't1', anchor: { block_id: 'b1', start_offset: 0, end_offset: 5 } }),
        makeThread({ thread_id: 't2', anchor: { block_id: 'b1', start_offset: 3, end_offset: 8 } }),
      ],
    })
    const marks = wrapper.findAll(MARK)
    expect(marks).toHaveLength(3)
    expect(marks[1].attributes('aria-label')).toContain('共 2 条批注')
    // 拼接还原：三段 mark 文本 + 尾部纯文本 == 原文
    expect(wrapper.text()).toContain(DEFAULT_TEXT)
  })

  it('2c. 点击 <mark> 派发 thread-click，第二参数是该段覆盖的全部线程 id', async () => {
    const wrapper = mountBlock({
      block: makeBlock(),
      threads: [
        makeThread({ thread_id: 't1', anchor: { block_id: 'b1', start_offset: 0, end_offset: 5 } }),
        makeThread({ thread_id: 't2', anchor: { block_id: 'b1', start_offset: 3, end_offset: 8 } }),
      ],
    })
    await wrapper.findAll(MARK)[1].trigger('click')
    const emitted = wrapper.emitted('thread-click')
    expect(emitted).toHaveLength(1)
    expect(emitted?.[0][1]).toEqual(['t1', 't2'])
  })

  it('2d. 键盘 Enter / Space 与点击等价（a11y）', async () => {
    const wrapper = mountBlock({ block: makeBlock(), threads: [makeThread()] })
    await wrapper.find(MARK).trigger('keydown.enter')
    await wrapper.find(MARK).trigger('keydown.space')
    expect(wrapper.emitted('thread-click')).toHaveLength(2)
  })
})

describe('blueprintBlock.vue —— 越界降级 / 强制整块 / 失锚三态', () => {
  it('3a. ⭐ 越界（end_offset > 文本长度）⇒ 出整块色条、mark 计数 0', () => {
    const wrapper = mountBlock({
      block: makeBlock(),
      threads: [makeThread({ anchor: { block_id: 'b1', start_offset: 0, end_offset: 999 } })],
    })
    expect(wrapper.find('[data-testid="blueprint-block-degraded"]').exists()).toBe(true)
    expect(wrapper.findAll(MARK)).toHaveLength(0)
  })

  it('3b. ⭐ 负向对照：同一条线程改成合法 offset ⇒ 出 mark、不出整块色条', () => {
    const wrapper = mountBlock({
      block: makeBlock(),
      threads: [makeThread({ anchor: { block_id: 'b1', start_offset: 0, end_offset: 4 } })],
    })
    expect(wrapper.findAll(MARK)).toHaveLength(1)
    expect(wrapper.find('[data-testid="blueprint-block-degraded"]').exists()).toBe(false)
  })

  it('3c. 整块色条角标点击派发优先级最高那条线程', async () => {
    const wrapper = mountBlock({
      block: makeBlock(),
      threads: [makeThread({ anchor: { block_id: 'b1', start_offset: 3, end_offset: 1 } })],
    })
    await wrapper.find('[data-testid="blueprint-block-degraded"]').trigger('click')
    expect(wrapper.emitted('thread-click')?.[0][0]).toBe('t1')
  })

  it('4a. ⭐ table 挂合法 offset 的线程仍走整块（坐标系无法映射到单元格）', () => {
    const wrapper = mountBlock({
      block: makeBlock({ type: 'table', text: null, rows: [['a', 'b'], ['c', 'd']] }),
      threads: [makeThread({ anchor: { block_id: 'b1', start_offset: 0, end_offset: 3 } })],
    })
    expect(wrapper.find('[data-testid="blueprint-block-degraded"]').exists()).toBe(true)
    expect(wrapper.findAll(MARK)).toHaveLength(0)
  })

  it('4b. ⭐ mermaid 挂合法 offset 的线程仍走整块（渲染的是 SVG）', () => {
    const wrapper = mountBlock({
      block: makeBlock({ type: 'mermaid', text: 'graph TD;A-->B;' }),
      threads: [makeThread({ anchor: { block_id: 'b1', start_offset: 0, end_offset: 3 } })],
    })
    expect(wrapper.find('[data-testid="blueprint-block-degraded"]').exists()).toBe(true)
    expect(wrapper.findAll(MARK)).toHaveLength(0)
  })

  it('5. ⭐ orphaned 线程正文完全不渲染：mark 0 **且** 整块色条也不出现', () => {
    const wrapper = mountBlock({
      block: makeBlock(),
      threads: [makeThread({ anchor_status: 'orphaned' })],
    })
    expect(wrapper.findAll(MARK)).toHaveLength(0)
    expect(wrapper.find('[data-testid="blueprint-block-degraded"]').exists()).toBe(false)
  })

  it('6. resolved 默认不着色；showClosed 打开后着色且类名 == annotationClass 的真实返回', () => {
    const thread = makeThread({
      kind: 'human_comment',
      severity: '',
      status: 'resolved',
      anchor: { block_id: 'b1', start_offset: 0, end_offset: 4 },
    })

    const hidden = mountBlock({ block: makeBlock(), threads: [thread] })
    expect(hidden.findAll(MARK)).toHaveLength(0)

    const shown = mountBlock({ block: makeBlock(), threads: [thread], showClosed: true })
    const marks = shown.findAll(MARK)
    expect(marks).toHaveLength(1)
    expect(marks[0].attributes('class')).toBe(annotationClass('human_comment', '', 'resolved', false))
  })
})

describe('blueprintBlock.vue —— 无编辑面 / citation chip / blockText 同源', () => {
  it('7. ⭐ 无编辑入口：emitted 键集 ⊆ {thread-click, citation-click}，⛔ 不含 selection-comment', async () => {
    const wrapper = mountBlock({
      block: makeBlock({ citations: ['c1'] }),
      threads: [makeThread()],
      citations: { c1: makeCitation() },
    })
    await wrapper.find(MARK).trigger('click')
    await wrapper.find(CHIP).trigger('click')

    // ⚠️ `emitted()` 里还会混入冒泡到组件根元素的**原生** DOM 事件（VTU 的既有行为），
    // 它们不是 `defineEmits` 声明面 ⇒ 断言前先剔除，否则断言的是 VTU 而不是组件契约。
    const NATIVE_EVENTS = new Set(['click', 'keydown', 'keyup', 'focus', 'blur', 'mousedown', 'mouseup'])
    const keys = Object.keys(wrapper.emitted()).filter(key => !NATIVE_EVENTS.has(key))
    expect(keys.sort()).toEqual(['citation-click', 'thread-click'])
    expect(keys).not.toContain('selection-comment')
    expect(wrapper.html()).not.toContain('edit-block')
    expect(wrapper.html()).not.toMatch(/data-testid="[^"]*edit/)
  })

  it('8a. 池中取不到的 citation id 不渲染（⛔ 不渲染 undefined）', () => {
    const wrapper = mountBlock({
      block: makeBlock({ citations: ['c1', 'missing'] }),
      citations: { c1: makeCitation() },
    })
    expect(wrapper.findAll(CHIP)).toHaveLength(1)
    expect(wrapper.text()).not.toContain('undefined')
  })

  it('8b. 外链 chip 是 <a target="_blank" rel="noopener noreferrer">，点击**不** emit', async () => {
    const wrapper = mountBlock({
      block: makeBlock({ citations: ['c1'] }),
      citations: {
        c1: makeCitation({
          citation_id: 'c1',
          source_type: 'url',
          source_id: 'https://example.com/doc',
          title: '外部链接一',
        }),
      },
    })
    const chip = wrapper.find(CHIP)
    expect(chip.element.tagName).toBe('A')
    expect(chip.attributes('target')).toBe('_blank')
    expect(chip.attributes('rel')).toBe('noopener noreferrer')
    // happy-dom 会对 <a href> 的点击真的发起导航（离线环境下噪声/不确定） ⇒ 拦掉默认行为，
    // 本用例只关心「点击不 emit citation-click」。
    chip.element.addEventListener('click', event => event.preventDefault())
    await chip.trigger('click')
    expect(wrapper.emitted('citation-click')).toBeUndefined()
  })

  it('8c. 站内 chip 是 <button>，点击 emit 一次 citation-click', async () => {
    const wrapper = mountBlock({
      block: makeBlock({ citations: ['c1'] }),
      citations: { c1: makeCitation() },
    })
    const chip = wrapper.find(CHIP)
    expect(chip.element.tagName).toBe('BUTTON')
    await chip.trigger('click')
    expect(wrapper.emitted('citation-click')).toEqual([['c1']])
  })

  it('9. ⭐ P-13：type=pseudocode 且 text 非空 ⇒ 可划线文本取 text 而不是 code.source', () => {
    const wrapper = mountBlock({
      block: makeBlock({
        type: 'pseudocode',
        text: 'TEXT-WINS',
        code: { language: 'python', source: 'SOURCE-LOSES' },
      }),
      threads: [makeThread({ anchor: { block_id: 'b1', start_offset: 0, end_offset: 4 } })],
    })
    expect(wrapper.text()).toContain('TEXT-WINS')
    expect(wrapper.text()).not.toContain('SOURCE-LOSES')
    // 坐标系一致 ⇒ 前 4 个字符被圈中；⛔ 若按 type 取了 code.source 会圈错字
    expect(wrapper.find(MARK).text()).toBe('TEXT')
  })
})

describe('blueprintBlockList.vue —— 选区侦测（唯一落点）', () => {
  function mountList(blocks: BlueprintBlockModel[]) {
    return mount(BlueprintBlockList, {
      props: { blocks },
      attachTo: document.body,
      global: { plugins: [i18n], stubs: { MermaidDiagram: true } },
    })
  }

  /**
   * 取包含 `needle` 的文本节点。
   *
   * ⚠️ **不能直接取 `walker.nextNode()`**：happy-dom 20.10.2 的 `createTreeWalker` 在
   * `SHOW_TEXT` 下**把注释节点也一并返回**（Vue 的 `<!--v-if-->` 与模板注释），它们的
   * `length` 为 0。对 `offsetInFlatText` 无影响（累加 0），但会让「取第一个文本节点」
   * 拿到一个长度为 0 的节点、`setEnd` 直接 `IndexSizeError`。
   */
  function textNodeWith(root: Element, needle: string): Text {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
    let node = walker.nextNode()
    while (node) {
      if ((node.textContent ?? '').includes(needle))
        return node as Text
      node = walker.nextNode()
    }
    throw new Error(`未找到包含 "${needle}" 的文本节点`)
  }

  async function selectAndFlush(range: Range): Promise<void> {
    const selection = window.getSelection()!
    selection.removeAllRanges()
    selection.addRange(range)
    document.dispatchEvent(new Event('selectionchange'))
    // 去抖窗口 120ms，留足余量
    await new Promise(resolve => setTimeout(resolve, 220))
  }

  it('10a. 同块选区 ⇒ emit selection-comment，载荷五键齐全且 offset 由 rangeOffsets 算出', async () => {
    const wrapper = mountList([makeBlock({ block_id: 'b1', text: 'HELLO WORLD' })])
    const blockEl = wrapper.element.querySelector('[data-block-id="b1"]')!
    const node = textNodeWith(blockEl, 'HELLO')

    const range = document.createRange()
    range.setStart(node, 0)
    range.setEnd(node, 5)
    await selectAndFlush(range)

    const emitted = wrapper.emitted('selection-comment')
    expect(emitted).toHaveLength(1)
    const payload = emitted![0][0] as Record<string, unknown>
    expect(payload.blockId).toBe('b1')
    expect(payload.startOffset).toBe(0)
    expect(payload.endOffset).toBe(5)
    expect(payload.quotedText).toBe('HELLO')
    expect(payload.rect).toBeDefined()
    expect(wrapper.emitted('cross-block-selection')).toBeUndefined()

    wrapper.unmount()
  })

  it('10b. ⭐ 跨块选区 ⇒ emit cross-block-selection 而**不是** selection-comment', async () => {
    const wrapper = mountList([
      makeBlock({ block_id: 'b1', text: 'FIRST BLOCK' }),
      makeBlock({ block_id: 'b2', text: 'SECOND BLOCK' }),
    ])
    const first = textNodeWith(wrapper.element.querySelector('[data-block-id="b1"]')!, 'FIRST')
    const second = textNodeWith(wrapper.element.querySelector('[data-block-id="b2"]')!, 'SECOND')

    const range = document.createRange()
    range.setStart(first, 0)
    range.setEnd(second, 6)
    await selectAndFlush(range)

    expect(wrapper.emitted('cross-block-selection')).toHaveLength(1)
    expect(wrapper.emitted('selection-comment')).toBeUndefined()

    wrapper.unmount()
  })

  it('10c. 折叠选区（光标）⇒ 两个事件都不 emit', async () => {
    const wrapper = mountList([makeBlock({ block_id: 'b1', text: 'HELLO WORLD' })])
    const node = textNodeWith(wrapper.element.querySelector('[data-block-id="b1"]')!, 'HELLO')

    const range = document.createRange()
    range.setStart(node, 2)
    range.setEnd(node, 2)
    await selectAndFlush(range)

    expect(wrapper.emitted('selection-comment')).toBeUndefined()
    expect(wrapper.emitted('cross-block-selection')).toBeUndefined()

    wrapper.unmount()
  })

  it('10d. onUnmounted 解绑：卸载后再触发 selectionchange 不再 emit（T-115-25）', async () => {
    const wrapper = mountList([makeBlock({ block_id: 'b1', text: 'HELLO WORLD' })])
    const node = textNodeWith(wrapper.element.querySelector('[data-block-id="b1"]')!, 'HELLO')
    const range = document.createRange()
    range.setStart(node, 0)
    range.setEnd(node, 5)

    wrapper.unmount()
    await selectAndFlush(range)

    expect(wrapper.emitted('selection-comment')).toBeUndefined()
  })

  it('10e. 段级三分支：loading 出骨架、空 blocks 走默认 slot、有 blocks 逐块渲染', () => {
    const loading = mount(BlueprintBlockList, {
      props: { blocks: [], loading: true },
      global: { plugins: [i18n] },
    })
    expect(loading.html()).toContain('animate-pulse')

    const empty = mount(BlueprintBlockList, {
      props: { blocks: [] },
      slots: { default: '<p class="empty-slot">本方案未涉及</p>' },
      global: { plugins: [i18n] },
    })
    expect(empty.find('.empty-slot').exists()).toBe(true)

    const filled = mount(BlueprintBlockList, {
      props: { blocks: [makeBlock({ block_id: 'b1' }), makeBlock({ block_id: 'b2' })] },
      global: { plugins: [i18n], stubs: { MermaidDiagram: true } },
    })
    expect(filled.findAll('[data-testid="blueprint-block"]')).toHaveLength(2)
  })
})
