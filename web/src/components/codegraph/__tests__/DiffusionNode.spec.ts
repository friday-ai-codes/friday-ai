/**
 * — DiffusionNode 单测（ 扩展 tooltip 内容覆盖）
 * 验证：file_basename 显示 / hop Badge 文案 / 外壳 class / aria-label /
 *      TooltipContent 三行（file_path:line / chunk_id:first8 / content preview 或 fallback）/
 *      line_start && line_end 全 null 时的 file_path 单行 + "行号信息缺失" 注释降级。
 */
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import DiffusionNode from '../DiffusionNode.vue'

vi.mock('@vue-flow/core', () => ({
  Handle: { template: '<div class="handle-stub" />', props: ['type', 'position'] },
  Position: { Top: 'top', Bottom: 'bottom', Left: 'left', Right: 'right' },
}))

vi.mock('~/components/ui/badge', () => ({
  Badge: { template: '<span class="badge-stub" :data-variant="variant"><slot /></span>', props: ['variant'] },
}))

vi.mock('~/components/ui/tooltip', () => ({
  Tooltip: { template: '<div><slot /></div>' },
  TooltipTrigger: { template: '<div><slot /></div>' },
  TooltipContent: { template: '<div><slot /></div>' },
  TooltipProvider: { template: '<div><slot /></div>' },
}))

describe('diffusionNode', () => {
  const baseData = {
    chunk_id: 'abcdef0123456789',
    file_path: 'src/services/auth/handler.ts',
    fileBasename: 'handler.ts',
    line_start: 10,
    line_end: 42,
    hop: 1 as const,
  }

  it('a: hop=1 节点渲染 Badge 文案 "1-hop"', () => {
    const wrapper = mount(DiffusionNode, { props: { data: baseData } })
    expect(wrapper.text()).toContain('1-hop')
  })

  it('b: hop=2 节点 Badge 文案 "2-hop" + 外壳 border-dashed', () => {
    const wrapper = mount(DiffusionNode, {
      props: { data: { ...baseData, hop: 2 as const } },
    })
    expect(wrapper.text()).toContain('2-hop')
    expect(wrapper.html()).toContain('border-dashed')
  })

  it('c: hop=source 节点 Badge 文案 "起点" + 外壳 border-primary/50', () => {
    const wrapper = mount(DiffusionNode, {
      props: { data: { ...baseData, hop: 'source' as const } },
    })
    expect(wrapper.text()).toContain('起点')
    expect(wrapper.html()).toContain('border-primary/50')
  })

  it('d: 外壳 aria-label 含 "代码块 {basename}, {hop}"', () => {
    const wrapper = mount(DiffusionNode, { props: { data: baseData } })
    const aria = wrapper.find('[role="button"]').attributes('aria-label')
    expect(aria).toContain('代码块 handler.ts')
    expect(aria).toContain('1-hop')
  })

  it('e: 首行显示 fileBasename 而非完整 file_path', () => {
    const wrapper = mount(DiffusionNode, { props: { data: baseData } })
    // 首行节点头部仅 basename；file_path 完整出现在尾部
    expect(wrapper.text()).toContain('handler.ts')
    expect(wrapper.text()).toContain('src/services/auth/handler.ts')
  })

  it('f: TooltipContent 含 chunk_id 前 8 字符（mono muted）', () => {
    const wrapper = mount(DiffusionNode, { props: { data: baseData } })
    expect(wrapper.text()).toContain('chunk_id: abcdef01')
  })

  it('g: TooltipContent 第 3 行渲染 content preview 前 200 字符', () => {
    const longContent = 'x'.repeat(300)
    const wrapper = mount(DiffusionNode, {
      props: { data: { ...baseData, content: longContent } },
    })
    const text = wrapper.text()
    expect(text).toContain('x'.repeat(200))
    expect(text).not.toContain('x'.repeat(201))
  })

  it('h: 缺 content 时 TooltipContent 第 3 行渲染 fallback 文案（LO-05：移除"悬停"误导词）', () => {
    const wrapper = mount(DiffusionNode, { props: { data: baseData } })
    expect(wrapper.text()).toContain('点击查看完整代码片段')
    // LO-05：旧文案"悬停查看代码"在 hover 状态下展示具有误导性，已删除
    expect(wrapper.text()).not.toContain('悬停查看代码')
  })

  it('i: line_start && line_end 全 null 时仅渲染 file_path + "行号信息缺失" 注释', () => {
    const wrapper = mount(DiffusionNode, {
      props: {
        data: { ...baseData, line_start: null, line_end: null },
      },
    })
    const html = wrapper.html()
    expect(html).toContain('src/services/auth/handler.ts')
    expect(html).toContain('行号信息缺失')
    expect(wrapper.text()).not.toContain('src/services/auth/handler.ts:?-?')
  })

  it('j: chunk_id 前 8 字符严格 slice(0, 8) 即使更长', () => {
    const longChunkId = '0123456789abcdef0123456789abcdef'
    const wrapper = mount(DiffusionNode, {
      props: { data: { ...baseData, chunk_id: longChunkId } },
    })
    expect(wrapper.text()).toContain('chunk_id: 01234567')
    expect(wrapper.text()).not.toContain('chunk_id: 012345678')
  })

  it('k: HI-01 keydown.enter → emit activate(chunk_id)（键盘激活路径，WCAG button widget）', async () => {
    const wrapper = mount(DiffusionNode, { props: { data: baseData } })
    const root = wrapper.find('[role="button"]')
    await root.trigger('keydown.enter')
    const emitted = wrapper.emitted('activate')
    expect(emitted).toBeDefined()
    expect(emitted?.[0]).toEqual([baseData.chunk_id])
  })

  it('l: HI-01 keydown.space → emit activate(chunk_id)', async () => {
    const wrapper = mount(DiffusionNode, { props: { data: baseData } })
    const root = wrapper.find('[role="button"]')
    await root.trigger('keydown.space')
    const emitted = wrapper.emitted('activate')
    expect(emitted).toBeDefined()
    expect(emitted?.[0]).toEqual([baseData.chunk_id])
  })

  it('m: ME-05 chunk_id null 守卫 → 不抛 TypeError，slice 退化为空', () => {
    const wrapper = mount(DiffusionNode, {
      // @ts-expect-error: 模拟后端 partial mock chunk_id=null
      props: { data: { ...baseData, chunk_id: null } },
    })
    expect(wrapper.text()).toContain('chunk_id:')
    // null 守卫退化为空字符串 → 不会出现 "null"
    expect(wrapper.text()).not.toContain('chunk_id: null')
  })
})
