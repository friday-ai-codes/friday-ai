/**
 * 110-02：SubStepTimeline.vue 单元测试。
 *
 * A 组是 `ExecutionNode` 既有用法的**零回归锁**——泛化前先写、先绿，泛化后必须仍绿。
 * B 组覆盖本 plan 新增的六态 / 可选摘要 / 可选角标 / 只读模式 / list 语义。
 *
 * 🔴 挂载**真实组件**，只 stub 到 `Badge` 这一层 UI 原语（109-REVIEW HI-01 的教训：
 * stub 掉被测对象会让全绿的 spec 对真实缺口完全无感）。
 */
import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import SubStepTimeline from '~/components/execution/dag/SubStepTimeline.vue'

const StubBadge = defineComponent({
  name: 'Badge',
  props: ['variant'],
  setup(props, { slots }) {
    return () => h('span', { 'data-test': 'badge', 'data-variant': props.variant }, slots.default?.())
  },
})

/** 步骤行选择器：泛化前后都成立（`relative flex items-start gap-2` 三个类均未改动）。 */
const ROW = '.relative.flex.items-start.gap-2'
/** 名称列容器：其内的 span 依次为 [步骤名, 摘要行]。 */
const NAME_COL = '.flex-1.min-w-0'

function mountTimeline(props: Record<string, any>) {
  return mount(SubStepTimeline as any, {
    props,
    global: { stubs: { Badge: StubBadge } },
  })
}

/** 复刻 `ExecutionNode` 传下来的真实 `SubStep` 形状（TS 上多余、运行时存在的字段全带上）。 */
function subStep(overrides: Record<string, any> = {}) {
  return {
    id: 'ss-1',
    name: '解析需求',
    step_type: 'llm_call',
    step_order: 1,
    status: 'pending',
    input_data: { prompt: 'x' },
    output_data: {},
    started_at: null,
    completed_at: null,
    ...overrides,
  }
}

let errorSpy: ReturnType<typeof vi.spyOn>
let warnSpy: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
  warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
})

afterEach(() => {
  expect(errorSpy).not.toHaveBeenCalled()
  expect(warnSpy).not.toHaveBeenCalled()
  vi.restoreAllMocks()
})

// ============================================================================
// A 组：ExecutionNode 既有用法零回归锁
// ============================================================================

describe('subStepTimeline · A 组：ExecutionNode 既有用法零回归', () => {
  it('接受 SubStep 形状的 item（含 step_type / step_order / input_data / started_at），渲染不抛且行数正确', () => {
    const wrapper = mountTimeline({
      steps: [
        subStep({ id: 'a', name: '第一步' }),
        subStep({ id: 'b', name: '第二步', step_order: 2, status: 'running' }),
        subStep({ id: 'c', name: '第三步', step_order: 3, status: 'completed' }),
      ],
    })

    expect(wrapper.findAll(ROW)).toHaveLength(3)
    expect(wrapper.text()).toContain('第一步')
    expect(wrapper.text()).toContain('第三步')
  })

  it('4 个既有状态各渲染既有状态点类', () => {
    const wrapper = mountTimeline({
      steps: [
        subStep({ id: 'p', status: 'pending' }),
        subStep({ id: 'r', status: 'running' }),
        subStep({ id: 'c', status: 'completed' }),
        subStep({ id: 'f', status: 'failed' }),
      ],
    })

    const dots = wrapper.findAll(ROW).map(row => row.find('.rounded-full').classes())

    expect(dots[0]).toContain('bg-muted-foreground/50')
    expect(dots[1]).toContain('bg-primary')
    expect(dots[1]).toContain('animate-pulse')
    expect(dots[2]).toContain('bg-emerald-400')
    expect(dots[3]).toContain('bg-red-400')
  })

  it('failed + 超长 output_data.error ⇒ 摘要行恰为前 50 字（断言长度与前缀，不是「包含」）', () => {
    const longError = '0123456789'.repeat(8) // 80 字
    const wrapper = mountTimeline({
      steps: [subStep({ id: 'f', status: 'failed', output_data: { error: longError } })],
    })

    const spans = wrapper.find(ROW).find(NAME_COL).findAll('span')
    expect(spans).toHaveLength(2)

    const summary = spans[1].text()
    expect(summary).toHaveLength(50)
    expect(summary).toBe(longError.slice(0, 50))
    expect(longError.startsWith(summary)).toBe(true)
    // 「没截断」的实现下 text 会是 80 字——上面的长度断言是它唯一会红的地方。
    expect(summary).not.toBe(longError)
  })

  it('failed 摘要行沿用既有红色配色', () => {
    const wrapper = mountTimeline({
      steps: [subStep({ id: 'f', status: 'failed', output_data: { error: '炸了' } })],
    })

    const spans = wrapper.find(ROW).find(NAME_COL).findAll('span')
    expect(spans[0].classes()).toContain('text-red-400')
    expect(spans[1].classes()).toContain('text-red-400/70')
    expect(spans[1].text()).toBe('炸了')
  })

  it('非 failed 步骤不渲染摘要行（无 summary 时）', () => {
    const wrapper = mountTimeline({
      steps: [subStep({ id: 'c', status: 'completed', output_data: { error: '不该显示' } })],
    })

    expect(wrapper.find(ROW).find(NAME_COL).findAll('span')).toHaveLength(1)
    expect(wrapper.text()).not.toContain('不该显示')
  })

  it('默认（不传 interactive）点击一行 ⇒ emit stepClick 且实参为该行 id，行含 cursor-pointer', async () => {
    const wrapper = mountTimeline({
      steps: [subStep({ id: 'ss-a' }), subStep({ id: 'ss-b', name: '第二步' })],
    })

    const rows = wrapper.findAll(ROW)
    expect(rows[0].classes()).toContain('cursor-pointer')
    expect(rows[0].classes()).toContain('hover:bg-muted/30')

    await rows[1].trigger('click')

    expect(wrapper.emitted('stepClick')).toHaveLength(1)
    expect(wrapper.emitted('stepClick')![0]).toEqual(['ss-b'])
  })
})

// ============================================================================
// B 组：本 plan 新增能力
// ============================================================================

describe('subStepTimeline · B 组：interactive 只读模式', () => {
  it('interactive: false ⇒ 点击不 emit stepClick，且行不含 cursor-pointer', async () => {
    const wrapper = mountTimeline({
      interactive: false,
      steps: [subStep({ id: 'ss-a' }), subStep({ id: 'ss-b' })],
    })

    const rows = wrapper.findAll(ROW)
    expect(rows[0].classes()).not.toContain('cursor-pointer')
    expect(rows[0].classes()).not.toContain('hover:bg-muted/30')

    await rows[0].trigger('click')
    await rows[1].trigger('click')

    expect(wrapper.emitted('stepClick')).toBeUndefined()
  })

  it('interactive: false ⇒ 行不进 tab 序（无 tabindex、非 button）', () => {
    const wrapper = mountTimeline({ interactive: false, steps: [subStep({ id: 'a' })] })
    const row = wrapper.find(ROW)

    expect(row.attributes('tabindex')).toBeUndefined()
    expect(row.element.tagName).toBe('DIV')
    expect(wrapper.findAll('button')).toHaveLength(0)
  })
})

describe('subStepTimeline · B 组：skipped / unknown 空心点', () => {
  it.each([['skipped'], ['unknown']])('%s ⇒ 空心点（bg-transparent + border），且不是失败色', (status) => {
    const wrapper = mountTimeline({ steps: [subStep({ id: 's', status })] })
    const dot = wrapper.find(ROW).find('.rounded-full').classes()

    expect(dot).toContain('bg-transparent')
    expect(dot).toContain('border')
    expect(dot).toContain('border-muted-foreground/50')
    // 把「不知道」画成「失败」是撒谎——这条是本用例要防的。
    expect(dot).not.toContain('bg-red-400')
  })

  it('skipped / unknown 共用同一视觉，靠状态文案区分', () => {
    const wrapper = mountTimeline({
      steps: [subStep({ id: 's', status: 'skipped' }), subStep({ id: 'u', status: 'unknown' })],
    })
    const rows = wrapper.findAll(ROW)

    expect(rows[0].find('.rounded-full').classes()).toEqual(rows[1].find('.rounded-full').classes())
    expect(rows[0].find('.sr-only').text()).toBe('已跳过')
    expect(rows[1].find('.sr-only').text()).toBe('进度未知')
  })
})

describe('subStepTimeline · B 组：摘要行', () => {
  it('summary 存在 ⇒ 摘要行文本为 summary，配色走 muted', () => {
    const wrapper = mountTimeline({
      steps: [subStep({ id: 'c', status: 'completed', summary: '已产出 3 个方案' })],
    })

    const spans = wrapper.find(ROW).find(NAME_COL).findAll('span')
    expect(spans).toHaveLength(2)
    expect(spans[1].text()).toBe('已产出 3 个方案')
    expect(spans[1].classes()).toContain('text-muted-foreground')
  })

  it('🔴 failed + summary + output_data.error 三者齐全 ⇒ 渲染 summary，DOM 文本不含 error 内容', () => {
    const wrapper = mountTimeline({
      steps: [subStep({
        id: 'f',
        status: 'failed',
        summary: '路由降级后仍无可用仓库',
        output_data: { error: 'RAW_BACKEND_STACKTRACE_XYZ' },
      })],
    })

    const spans = wrapper.find(ROW).find(NAME_COL).findAll('span')
    // 回退实现可能把两行都渲染出来 ⇒ 断言只有一条摘要行，且 DOM 全文不含 error 内容。
    expect(spans).toHaveLength(2)
    expect(spans[1].text()).toBe('路由降级后仍无可用仓库')
    expect(wrapper.text()).not.toContain('RAW_BACKEND_STACKTRACE_XYZ')
  })

  it('summary 与 output_data.error 均缺省 ⇒ 整行不渲染摘要', () => {
    const wrapper = mountTimeline({ steps: [subStep({ id: 'p', status: 'pending' })] })
    expect(wrapper.find(ROW).find(NAME_COL).findAll('span')).toHaveLength(1)
  })
})

describe('subStepTimeline · B 组：行尾角标', () => {
  it('badge 存在 ⇒ 渲染角标且文案 / variant 正确', () => {
    const wrapper = mountTimeline({
      steps: [subStep({ id: 'r', badge: { text: '已降级', variant: 'warning' } })],
    })

    const badge = wrapper.find('[data-test="badge"]')
    expect(badge.exists()).toBe(true)
    expect(badge.text()).toBe('已降级')
    expect(badge.attributes('data-variant')).toBe('warning')
  })

  it('badge 缺省 ⇒ DOM 里无角标节点', () => {
    const wrapper = mountTimeline({ steps: [subStep({ id: 'r' })] })
    expect(wrapper.find('[data-test="badge"]').exists()).toBe(false)
  })
})

describe('subStepTimeline · B 组：running 的 pulse 开关', () => {
  it('running + pulse: false ⇒ 含 bg-primary 但不含 animate-pulse（色值不变，只去动画）', () => {
    const wrapper = mountTimeline({
      steps: [subStep({ id: 'r', status: 'running', pulse: false })],
    })
    const dot = wrapper.find(ROW).find('.rounded-full').classes()

    expect(dot).toContain('bg-primary')
    expect(dot).not.toContain('animate-pulse')
  })

  it('running 不传 pulse ⇒ 两者都含（默认值回归锁）', () => {
    const wrapper = mountTimeline({ steps: [subStep({ id: 'r', status: 'running' })] })
    const dot = wrapper.find(ROW).find('.rounded-full').classes()

    expect(dot).toContain('bg-primary')
    expect(dot).toContain('animate-pulse')
  })

  it('running + pulse: true ⇒ 与缺省一致', () => {
    const wrapper = mountTimeline({
      steps: [subStep({ id: 'r', status: 'running', pulse: true })],
    })
    expect(wrapper.find(ROW).find('.rounded-full').classes()).toContain('animate-pulse')
  })
})

describe('subStepTimeline · B 组：状态文本', () => {
  it('不传 statusText ⇒ 用内置中文默认（title 与 sr-only 同源）', () => {
    const wrapper = mountTimeline({
      steps: [
        subStep({ id: 'p', status: 'pending' }),
        subStep({ id: 'r', status: 'running' }),
        subStep({ id: 'c', status: 'completed' }),
        subStep({ id: 'f', status: 'failed' }),
        subStep({ id: 's', status: 'skipped' }),
        subStep({ id: 'u', status: 'unknown' }),
      ],
    })

    const rows = wrapper.findAll(ROW)
    const expected = ['未开始', '进行中', '已完成', '失败', '已跳过', '进度未知']

    expected.forEach((label, i) => {
      expect(rows[i].attributes('title')).toBe(label)
      expect(rows[i].find('.sr-only').text()).toBe(label)
    })
  })

  it('statusText 逐键覆盖 ⇒ 覆盖到的用覆盖值，未覆盖的仍用内置默认', () => {
    const wrapper = mountTimeline({
      statusText: { failed: '编排失败' },
      steps: [subStep({ id: 'f', status: 'failed' }), subStep({ id: 's', status: 'skipped' })],
    })

    const rows = wrapper.findAll(ROW)
    expect(rows[0].attributes('title')).toBe('编排失败')
    expect(rows[0].find('.sr-only').text()).toBe('编排失败')
    expect(rows[1].attributes('title')).toBe('已跳过')
  })
})

describe('subStepTimeline · B 组：可访问性语义', () => {
  it('容器 role=list、每行 role=listitem', () => {
    const wrapper = mountTimeline({
      steps: [subStep({ id: 'a' }), subStep({ id: 'b' })],
    })

    expect(wrapper.find('[role="list"]').exists()).toBe(true)
    expect(wrapper.findAll('[role="listitem"]')).toHaveLength(2)
  })

  it('🔴 组件渲染结果整体不含 aria-live', () => {
    const wrapper = mountTimeline({
      steps: [
        subStep({ id: 'f', status: 'failed', summary: '失败了' }),
        subStep({ id: 'r', status: 'running' }),
      ],
    })

    expect(wrapper.html()).not.toContain('aria-live')
  })

  it('🔴 failed + summary ⇒ 摘要行 role=alert 且 aria-live 属性不存在；非 failed 摘要行无 role', () => {
    const wrapper = mountTimeline({
      steps: [
        subStep({ id: 'f', status: 'failed', summary: '路由失败' }),
        subStep({ id: 'c', status: 'completed', summary: '已完成 3 项' }),
      ],
    })

    const rows = wrapper.findAll(ROW)
    const failedSummary = rows[0].find(NAME_COL).findAll('span')[1]
    const okSummary = rows[1].find(NAME_COL).findAll('span')[1]

    expect(failedSummary.attributes('role')).toBe('alert')
    // 断言属性**不存在**，不是断言它等于某值。
    expect(failedSummary.attributes('aria-live')).toBeUndefined()
    expect(okSummary.attributes('role')).toBeUndefined()
  })

  it('failed 走 output_data.error 回退路径时摘要行同样是 role=alert', () => {
    const wrapper = mountTimeline({
      steps: [subStep({ id: 'f', status: 'failed', output_data: { error: '炸了' } })],
    })

    const summary = wrapper.find(ROW).find(NAME_COL).findAll('span')[1]
    expect(summary.attributes('role')).toBe('alert')
    expect(summary.attributes('aria-live')).toBeUndefined()
  })
})

describe('subStepTimeline · B 组：兜底', () => {
  it('status 不在 6 值内 ⇒ 不抛，状态点回退灰实心，状态文本回退「进度未知」', () => {
    const wrapper = mountTimeline({ steps: [subStep({ id: 'w', status: 'weird' })] })

    const dot = wrapper.find(ROW).find('.rounded-full').classes()
    expect(dot).toContain('bg-muted-foreground/50')
    expect(dot).not.toContain('bg-transparent')
    expect(wrapper.find(ROW).find('.sr-only').text()).toBe('进度未知')
  })

  it('steps 为空数组 ⇒ 不抛，无任何行', () => {
    const wrapper = mountTimeline({ steps: [] })
    expect(wrapper.findAll(ROW)).toHaveLength(0)
    expect(wrapper.find('[role="list"]').exists()).toBe(true)
  })
})
