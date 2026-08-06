/**
 * markdown-lite 解析单测（quick-260806-gfk）。
 *
 * 重点盯不变式：lines 无缝覆盖全文（批注 offset 坐标系依赖它）、styles 落在行内且互不重叠。
 */
import { describe, expect, it } from 'vitest'
import { buildMarkdownRender, isMarkdownishText, parseMarkdownLite } from '../blueprintMarkdownLite'

const SAMPLE = [
  '## 模块 1: 入口与权益展示',
  '- 入口位置与排序',
  '- 验收: - [ ] **当** 用户进入 **时**, 系统应展示入口',
  '',
  '#### 功能点 A: 页面结构',
  '1. 第一步',
  '  - 嵌套条目',
  '普通说明文字',
].join('\n')

describe('isMarkdownishText', () => {
  it('含标题行 ⇒ true', () => {
    expect(isMarkdownishText(SAMPLE)).toBe(true)
  })

  it('无记号的纯文本（单行 / 多行）⇒ false', () => {
    expect(isMarkdownishText('一句普通描述')).toBe(false)
    expect(isMarkdownishText('第一行\n第二行\n第三行')).toBe(false)
  })

  it('≥2 行列表 ⇒ true', () => {
    expect(isMarkdownishText('- 条目一\n- 条目二')).toBe(true)
  })

  /**
   * ⭐ 后端 prompt 的正文约定是「凡代码标识符、文件路径、函数名一律用反引号包裹」，
   * 而 `impl_items[].how` / `findings[].detail` 这类字段常常只有一行。单行若退回裸 `<p>`
   * 路径，反引号就会原样显示在页面上 —— 约定越守，页面越脏。
   */
  it('⭐ 单行含行内代码 / 加粗 ⇒ true（记号必须被渲染掉而不是裸露）', () => {
    expect(isMarkdownishText('在 `SpecialCard.vue` 中调用 `browserJump`')).toBe(true)
    expect(isMarkdownishText('**样式必须与同模块其他入口一致**')).toBe(true)
  })

  it('单行的孤立反引号 / 星号不算记号（未成对 ⇒ 不该走富渲染）', () => {
    expect(isMarkdownishText('预计耗时 3`5 天')).toBe(false)
    expect(isMarkdownishText('权重 * 系数')).toBe(false)
  })

  /**
   * ⭐ `BOLD_RE` / `CODE_RE` 带 `g` 标志，`test()` 会推进 `lastIndex`。用前不归零的话，
   * 对**第二个**字符串判定时会从陈旧下标起找 ⇒ 开头处的命中被跳过、结果随调用顺序
   * 变化（隔一个错一个）。判定必须是纯函数。
   */
  it('⭐ 连续判定同类文本结果稳定（/g 正则的 lastIndex 不得泄漏）', () => {
    for (let i = 0; i < 5; i++) {
      expect(isMarkdownishText('**加粗甲**'), `第 ${i + 1} 次判定翻车`).toBe(true)
      expect(isMarkdownishText('**加粗乙**'), `第 ${i + 1} 次判定翻车`).toBe(true)
      expect(isMarkdownishText('`代码甲`'), `第 ${i + 1} 次判定翻车`).toBe(true)
      expect(isMarkdownishText('`代码乙`'), `第 ${i + 1} 次判定翻车`).toBe(true)
    }
  })
})

describe('单行行内代码的渲染映射（配合 isMarkdownishText 的单行分支）', () => {
  it('反引号被删除、内容标为 code，且坐标可双向还原', () => {
    const source = '调用 `browserJump` 跳转'
    const model = buildMarkdownRender(source)

    expect(model.rendered).toBe('调用 browserJump 跳转')
    const code = model.styles.filter(style => style.style === 'code')
    expect(code).toHaveLength(1)
    expect(model.rendered.slice(code[0].start, code[0].end)).toBe('browserJump')
    // 渲染坐标 → 源坐标：切出来的必须还是同一个词（批注锚点靠这条换算）。
    expect(source.slice(model.toSource(code[0].start), model.toSource(code[0].end - 1) + 1)).toBe(
      'browserJump',
    )
  })
})

describe('parseMarkdownLite', () => {
  it('lines 无缝覆盖全文（不变式）', () => {
    const { lines } = parseMarkdownLite(SAMPLE)
    expect(lines[0].start).toBe(0)
    expect(lines[lines.length - 1].end).toBe(SAMPLE.length)
    for (let i = 1; i < lines.length; i++)
      expect(lines[i].start).toBe(lines[i - 1].end)
  })

  it('行分类正确', () => {
    const { lines } = parseMarkdownLite(SAMPLE)
    const kinds = lines.map(line => line.kind)
    expect(kinds).toEqual(['h2', 'bullet', 'bullet', 'blank', 'h4', 'ordered', 'bullet', 'plain'])
    expect(lines[6].depth).toBe(1)
  })

  it('styles 互不重叠且落在行内', () => {
    const { lines, styles } = parseMarkdownLite(SAMPLE)
    for (let i = 1; i < styles.length; i++)
      expect(styles[i].start).toBeGreaterThanOrEqual(styles[i - 1].end)
    for (const style of styles) {
      const line = lines.find(l => style.start >= l.start && style.end <= l.end)
      expect(line).toBeDefined()
    }
  })

  it('行首记号 + 行内加粗都产出 marker/bold 区间', () => {
    const text = '- 验收: **当** 用户进入'
    const { styles } = parseMarkdownLite(`${text}\n- второй`)
    const markerRanges = styles.filter(s => s.style === 'marker')
    const boldRanges = styles.filter(s => s.style === 'bold')
    // 行首 `- ` + `**` 两侧 ×1 对 + 第二行 `- `
    expect(markerRanges.length).toBe(4)
    expect(boldRanges.length).toBe(1)
    expect(text.slice(boldRanges[0].start, boldRanges[0].end)).toBe('当')
  })

  it('行内 `code` 记号', () => {
    const { styles } = parseMarkdownLite('说明 `SettingKeys` 常量\n- 另一行')
    const code = styles.find(s => s.style === 'code')
    expect(code).toBeDefined()
  })

  it('列表里嵌标题（- #### 功能点）按标题渲染，记号整段淡化', () => {
    const text = '- #### 功能点 A: 页面结构\n  - 子项'
    const { lines, styles } = parseMarkdownLite(text)
    expect(lines[0].kind).toBe('h4')
    const marker = styles.find(s => s.start === 0 && s.style === 'marker')
    expect(marker).toBeDefined()
    expect(text.slice(marker!.start, marker!.end)).toBe('- #### ')
  })

  it('句中任务框 - [ ] 产出 taskbox 区间，且不与行首记号重叠', () => {
    const text = '  - 验收：- [ ] **当** 用户进入'
    const { styles } = parseMarkdownLite(`${text}\n- 次行`)
    const taskbox = styles.find(
      s => s.style === 'taskbox' && text.slice(s.start, s.end) === '- [ ]' && s.start > 0,
    )
    expect(taskbox).toBeDefined()
    for (let i = 1; i < styles.length; i++)
      expect(styles[i].start).toBeGreaterThanOrEqual(styles[i - 1].end)
  })

  it('行首任务框走 taskbox 档、有序编号走 dim 档（可见不隐藏）', () => {
    const { styles: taskStyles } = parseMarkdownLite('- [ ] 待办一\n- [x] 待办二')
    expect(taskStyles.filter(s => s.style === 'taskbox')).toHaveLength(2)
    const { styles: orderedStyles } = parseMarkdownLite('1. 第一步\n2. 第二步')
    expect(orderedStyles.filter(s => s.style === 'dim')).toHaveLength(2)
    expect(orderedStyles.filter(s => s.style === 'marker')).toHaveLength(0)
  })

  it('有序编号的四种形态都认（quick-260806-fpx）：`1. ` / `1)` / `（1）` / `①`', () => {
    const { lines } = parseMarkdownLite('1. 标准\n2) 半角括号\n（3）全角括号\n④带圈无空格')

    expect(lines.map(line => line.kind)).toEqual(['ordered', 'ordered', 'ordered', 'ordered'])
  })

  it('⭐ `1.5 倍` 不是编号：`\\d[.]` 分支必须跟空白，否则行首数字被吞掉', () => {
    const { lines, styles } = parseMarkdownLite('1.5 倍速播放\n另一行')

    expect(lines[0].kind).toBe('plain')
    // 整行零记号 ⇒ 渲染文本必须逐字保留「1.5」
    expect(styles.filter(s => s.start < lines[0].end)).toHaveLength(0)
    expect(buildMarkdownRender('1.5 倍速播放\n另一行').rendered).toContain('1.5 倍速播放')
  })

  it('带括号/带圈编号走 dim 档（编号携带信息 ⇒ 可见不删）', () => {
    const model = buildMarkdownRender('（1）第一步\n（2）第二步')

    expect(model.rendered).toContain('（1）')
    expect(model.styles.filter(s => s.style === 'dim')).toHaveLength(2)
  })

  it('空文本 ⇒ 空模型；尾 \\n 归入末行', () => {
    expect(parseMarkdownLite('')).toEqual({ lines: [], styles: [] })
    const { lines } = parseMarkdownLite('## 标题\n- 条目\n')
    expect(lines).toHaveLength(2)
    expect(lines[1].end).toBe('## 标题\n- 条目\n'.length)
  })
})

describe('buildMarkdownRender（源↔渲染映射）', () => {
  const SOURCE = '## 标题\n- 验收：- [ ] **当** 进入\n1. 第一步'
  //              渲染： '标题\n验收：ⓘ 当 进入\n1. 第一步'（ⓘ=任务框图标，零字符）

  it('渲染文本删除记号、保留内容与 \\n；有序编号保留', () => {
    const model = buildMarkdownRender(SOURCE)
    expect(model.rendered).toBe('标题\n验收： 当 进入\n1. 第一步')
    expect(model.rendered).not.toContain('#')
    expect(model.rendered).not.toContain('**')
    expect(model.rendered).toContain('1. ')
  })

  it('toSource / toRendered 对内容字符逐字往返', () => {
    const model = buildMarkdownRender(SOURCE)
    for (let rend = 0; rend < model.rendered.length; rend++) {
      const src = model.toSource(rend)
      expect(SOURCE[src]).toBe(model.rendered[rend])
      expect(model.toRendered(src)).toBe(rend)
    }
  })

  it('源偏移落在被删记号内 ⇒ 向后夹到下一个保留字符', () => {
    const model = buildMarkdownRender(SOURCE)
    // 源 offset 0/1 落在 `##` 内 ⇒ 渲染 offset 0（'标'）
    expect(model.toRendered(0)).toBe(0)
    expect(model.toRendered(1)).toBe(0)
    // 源末尾之外 ⇒ 渲染末尾
    expect(model.toRendered(SOURCE.length)).toBe(model.rendered.length)
  })

  it('任务框产出 glyph 插入点，checked 变体识别 [x]', () => {
    const model = buildMarkdownRender('- [ ] 待办\n- [x] 已完成')
    expect(model.glyphs).toHaveLength(2)
    expect(model.glyphs[0].glyph).toBe('taskbox')
    expect(model.glyphs[1].glyph).toBe('taskbox-checked')
  })

  it('lines/styles 换算到渲染坐标且行首尾相接', () => {
    const model = buildMarkdownRender(SOURCE)
    expect(model.lines[0].start).toBe(0)
    expect(model.lines[model.lines.length - 1].end).toBe(model.rendered.length)
    for (let i = 1; i < model.lines.length; i++)
      expect(model.lines[i].start).toBe(model.lines[i - 1].end)
    const bold = model.styles.find(s => s.style === 'bold')
    expect(bold).toBeDefined()
    expect(model.rendered.slice(bold!.start, bold!.end)).toBe('当')
  })
})
