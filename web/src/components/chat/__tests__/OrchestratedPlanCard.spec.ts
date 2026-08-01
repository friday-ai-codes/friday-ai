/**
 * 109-04：OrchestratedPlanCard.vue 单元测试（SPINE-01 前端半边）。
 *
 * 覆盖：点击一次投影、created=true / false 两种 toast 通道、投影后就地交棒给
 * TechPlanCard 的 props 来源、失败可重试、投影期间 disabled、零 v-html。
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import OrchestratedPlanCard from '~/components/chat/OrchestratedPlanCard.vue'
import { useChatStore } from '~/stores/chat'

const toastSuccess = vi.fn()
const toastError = vi.fn()
vi.mock('~/composables/useToast', () => ({
  useToast: () => ({ success: toastSuccess, error: toastError }),
}))

// 109-REVIEW HI-01：改用**真实** chat store（只替换投影 action）。
// 原先整模块 mock 掉 store 让真实 TechPlanCard 根本无法挂载，于是交棒后的选仓面
// 只能靠 StubTechPlanCard 断言 props 透传——「透传的 props 够不够真实卡片跑完四步」
// 这件事没有任何用例覆盖，HI-01 的缺口因此在 240 行全绿的 spec 里纹丝不动。
const projectPlanToCodingPlan = vi.hoisted(() => vi.fn())

// 真实 TechPlanCard 会异步初始化 markdown 渲染器；换成 echo 避免拉 shiki 重依赖。
vi.mock('~/composables/useMarkdownRenderer', () => ({
  getMarkdownRenderer: vi.fn(async () => ({
    render: (raw: string) => `<div data-test="md">${raw}</div>`,
  })),
}))

const StubBadge = defineComponent({
  name: 'Badge',
  props: ['variant'],
  setup(props, { slots }) {
    return () => h('span', { 'data-test': 'badge', 'data-variant': props.variant }, slots.default?.())
  },
})
const StubButton = defineComponent({
  name: 'Button',
  props: ['disabled'],
  emits: ['click'],
  setup(props, { slots, emit }) {
    return () => h('button', {
      'data-test': 'btn',
      'disabled': props.disabled || false,
      'onClick': () => emit('click'),
    }, slots.default?.())
  },
})
const StubTechPlanCard = defineComponent({
  name: 'TechPlanCard',
  props: [
    'planId',
    'codingPlanId',
    'title',
    'techPlan',
    'affectedFiles',
    'recommendedRepositoryIds',
    'status',
    'isConfirming',
  ],
  setup(props) {
    return () => h('div', {
      'data-test': 'tech-plan-card',
      'data-plan-id': props.planId,
      'data-coding-plan-id': props.codingPlanId,
      'data-title': props.title,
      'data-tech-plan': props.techPlan,
      'data-affected-count': String(props.affectedFiles?.length ?? 0),
      'data-recommended': (props.recommendedRepositoryIds ?? []).join(','),
      'data-status': props.status,
      'data-is-confirming': String(props.isConfirming),
    })
  },
})

const ARTIFACT_VERSION_ID = 'av-uuid-1'

function projectionResponse(overrides: Record<string, unknown> = {}) {
  return {
    coding_plan_id: 'plan-uuid-1',
    created: true,
    title: '跨仓改造方案',
    tech_plan: '# 方案正文',
    affected_files: [{ file_path: 'server/a.py', change_type: 'add' }],
    recommended_repository_ids: ['repo-1', 'repo-2'],
    recommended_repositories: [
      { id: 'repo-1', name: 'repo-alpha' },
      { id: 'repo-2', name: 'repo-beta' },
    ],
    provenance: 'orchestrated',
    ...overrides,
  }
}

function mountCard() {
  return mount(OrchestratedPlanCard, {
    props: { artifactVersionId: ARTIFACT_VERSION_ID },
    global: {
      stubs: {
        Badge: StubBadge,
        Button: StubButton,
        TechPlanCard: StubTechPlanCard,
      },
    },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  setActivePinia(createPinia())
  // 只替换投影 action，其余走真实 store（真实 TechPlanCard 依赖 storeToRefs）
  ;(useChatStore() as any).projectPlanToCodingPlan = projectPlanToCodingPlan
})

describe('orchestratedPlanCard', () => {
  it('renders 入口文案与徽标，且不渲染方案正文 / 进度 UI', () => {
    const wrapper = mountCard()
    expect(wrapper.text()).toContain('技术方案已产出')
    expect(wrapper.text()).toContain('已编排')
    expect(wrapper.text()).toContain('进入编码')
    expect(wrapper.find('[data-test="badge"]').attributes('data-variant')).toBe('success')
    // D-4：在途完全不呈现 ⇒ 没有任何阶段名 / 百分比 / 骨架屏
    expect(wrapper.find('.animate-pulse').exists()).toBe(false)
    expect(wrapper.find('[data-test="tech-plan-card"]').exists()).toBe(false)
  })

  it('点击「进入编码」以 artifactVersionId 调投影 action 恰好一次', async () => {
    projectPlanToCodingPlan.mockResolvedValue(projectionResponse())
    const wrapper = mountCard()
    await wrapper.find('[data-test="enter-coding"]').trigger('click')
    await flushPromises()

    expect(projectPlanToCodingPlan).toHaveBeenCalledTimes(1)
    expect(projectPlanToCodingPlan).toHaveBeenCalledWith(ARTIFACT_VERSION_ID)
  })

  it('created=true → 就绪 toast 走 success 通道', async () => {
    projectPlanToCodingPlan.mockResolvedValue(projectionResponse({ created: true }))
    const wrapper = mountCard()
    await wrapper.find('[data-test="enter-coding"]').trigger('click')
    await flushPromises()

    expect(toastSuccess).toHaveBeenCalledWith('编码方案已就绪，请选择目标仓库')
    expect(toastError).not.toHaveBeenCalled()
  })

  it('created=false → 「已复用既有编码方案」走中性 success 通道而非 error', async () => {
    projectPlanToCodingPlan.mockResolvedValue(projectionResponse({ created: false }))
    const wrapper = mountCard()
    await wrapper.find('[data-test="enter-coding"]').trigger('click')
    await flushPromises()

    expect(toastSuccess).toHaveBeenCalledWith('已复用既有编码方案')
    // 幂等是系统正确性，不是异常状态：断言的是通道而非仅文案
    expect(toastError).not.toHaveBeenCalled()
    // 卡片表现与首次一致：同样交棒
    expect(wrapper.find('[data-test="tech-plan-card"]').exists()).toBe(true)
  })

  it('投影成功后就地内嵌 TechPlanCard，props 来自投影响应', async () => {
    projectPlanToCodingPlan.mockResolvedValue(projectionResponse())
    const wrapper = mountCard()
    await wrapper.find('[data-test="enter-coding"]').trigger('click')
    await flushPromises()

    const handed = wrapper.find('[data-test="tech-plan-card"]')
    expect(handed.exists()).toBe(true)
    expect(handed.attributes('data-coding-plan-id')).toBe('plan-uuid-1')
    expect(handed.attributes('data-plan-id')).toBe('plan-uuid-1')
    expect(handed.attributes('data-title')).toBe('跨仓改造方案')
    expect(handed.attributes('data-tech-plan')).toBe('# 方案正文')
    expect(handed.attributes('data-affected-count')).toBe('1')
    expect(handed.attributes('data-recommended')).toBe('repo-1,repo-2')
    expect(handed.attributes('data-status')).toBe('draft')
    expect(handed.attributes('data-is-confirming')).toBe('false')
  })

  it('投影成功后按钮被替换为已投影说明行（不留一个点了没反应的按钮）', async () => {
    projectPlanToCodingPlan.mockResolvedValue(projectionResponse())
    const wrapper = mountCard()
    await wrapper.find('[data-test="enter-coding"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-test="enter-coding"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('已进入编码，请在下方选择目标仓库')
  })

  it('投影期间按钮 disabled 且不重复发请求', async () => {
    let resolveProjection: ((v: unknown) => void) | undefined
    projectPlanToCodingPlan.mockImplementation(
      () => new Promise((resolve) => { resolveProjection = resolve }),
    )
    const wrapper = mountCard()
    await wrapper.find('[data-test="enter-coding"]').trigger('click')
    await flushPromises()

    const btn = wrapper.find('[data-test="enter-coding"]')
    expect(btn.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('正在准备编码方案…')

    // 重复点击不再发请求
    await btn.trigger('click')
    await flushPromises()
    expect(projectPlanToCodingPlan).toHaveBeenCalledTimes(1)

    resolveProjection?.(projectionResponse())
    await flushPromises()
  })

  it('投影失败 → error toast 用前端常量，按钮回到可点击可重试', async () => {
    projectPlanToCodingPlan.mockRejectedValueOnce(new Error('boom: 后端 detail 不该上屏'))
    const wrapper = mountCard()
    await wrapper.find('[data-test="enter-coding"]').trigger('click')
    await flushPromises()

    expect(toastError).toHaveBeenCalledWith('未能进入编码，请稍后重试')
    // 不回显后端自由文本
    expect(toastError).not.toHaveBeenCalledWith(expect.stringContaining('boom'))
    expect(wrapper.find('[data-test="tech-plan-card"]').exists()).toBe(false)

    const btn = wrapper.find('[data-test="enter-coding"]')
    expect(btn.exists()).toBe(true)
    expect(btn.attributes('disabled')).toBeUndefined()

    // 重试可再次发请求
    projectPlanToCodingPlan.mockResolvedValueOnce(projectionResponse())
    await btn.trigger('click')
    await flushPromises()
    expect(projectPlanToCodingPlan).toHaveBeenCalledTimes(2)
    expect(wrapper.find('[data-test="tech-plan-card"]').exists()).toBe(true)
  })

  it('组件源码零 v-html（新增面不得引入未转义 HTML 渲染）', () => {
    const source = readFileSync(
      resolve(process.cwd(), 'src/components/chat/OrchestratedPlanCard.vue'),
      'utf-8',
    )
    const hits = source
      .split('\n')
      .filter(line => line.includes('v-html'))
      .filter((line) => {
        const trimmed = line.trim()
        // 过滤注释行，避免注释里提到 v-html 让断言自我失效
        return !trimmed.startsWith('//')
          && !trimmed.startsWith('*')
          && !trimmed.startsWith('<!--')
      })
    expect(hits).toEqual([])
  })
})

/**
 * 🔴 109-REVIEW HI-01：交棒**不 stub** TechPlanCard 的集成用例。
 *
 * 上面的用例用 StubTechPlanCard 顶掉真实组件，只断言 props 透传——于是「透传的 props
 * 够不够真实 TechPlanCard 跑完四步」这件事没有任何覆盖。实际缺口是：不传
 * `available-repositories` / `target-repositories` 时，交棒后的选仓面渲染成空列表
 * （「未找到匹配的仓库」），用户既看不到 AI 推荐了哪几个仓，也无法勾选或取消，
 * SC-1 的第一步「选目标仓」在界面上不成立。
 *
 * 本组用例挂载真实 TechPlanCard **与真实 RepoMultiSelector**，只 stub 到叶子 UI
 * 原语为止，断言选仓列表真的渲染出可勾选行。
 */
describe('orchestratedPlanCard — 交棒后的真实选仓面（不 stub TechPlanCard）', () => {
  function passthrough(name: string, dataTest?: string) {
    return defineComponent({
      name,
      setup: (_, { slots }) => () =>
        h('div', dataTest ? { 'data-test': dataTest } : {}, slots.default?.()),
    })
  }

  const leafStubs = {
    Badge: StubBadge,
    Button: StubButton,
    Input: passthrough('Input'),
    Checkbox: passthrough('Checkbox'),
    Command: passthrough('Command'),
    CommandInput: passthrough('CommandInput'),
    CommandList: passthrough('CommandList'),
    CommandGroup: passthrough('CommandGroup'),
    CommandEmpty: passthrough('CommandEmpty', 'command-empty'),
    CommandItem: passthrough('CommandItem', 'repo-option'),
    Tooltip: passthrough('Tooltip'),
    TooltipContent: passthrough('TooltipContent'),
    TooltipProvider: passthrough('TooltipProvider'),
    TooltipTrigger: passthrough('TooltipTrigger'),
    Dialog: passthrough('Dialog'),
    DialogContent: passthrough('DialogContent'),
    DialogHeader: passthrough('DialogHeader'),
    DialogTitle: passthrough('DialogTitle'),
    DialogDescription: passthrough('DialogDescription'),
    AlertDialog: passthrough('AlertDialog'),
    AlertDialogContent: passthrough('AlertDialogContent'),
    AlertDialogHeader: passthrough('AlertDialogHeader'),
    AlertDialogTitle: passthrough('AlertDialogTitle'),
    AlertDialogDescription: passthrough('AlertDialogDescription'),
    AlertDialogFooter: passthrough('AlertDialogFooter'),
    AlertDialogAction: passthrough('AlertDialogAction'),
    AlertDialogCancel: passthrough('AlertDialogCancel'),
    Select: passthrough('Select'),
    SelectTrigger: passthrough('SelectTrigger'),
    SelectContent: passthrough('SelectContent'),
    SelectItem: passthrough('SelectItem'),
    SelectValue: passthrough('SelectValue'),
    CodingSessionStatusRow: passthrough('CodingSessionStatusRow'),
    ExportConfirmDialog: passthrough('ExportConfirmDialog'),
  }

  async function projectAndSettle() {
    projectPlanToCodingPlan.mockResolvedValue(projectionResponse())
    const wrapper = mount(OrchestratedPlanCard, {
      props: { artifactVersionId: ARTIFACT_VERSION_ID },
      global: { stubs: leafStubs },
    })
    await wrapper.find('[data-test="enter-coding"]').trigger('click')
    await flushPromises()
    return wrapper
  }

  it('选仓列表渲染出每个推荐仓库的可勾选行（缺 available-repositories 时此处为 0）', async () => {
    const wrapper = await projectAndSettle()

    // 卡片里有两个 RepoMultiSelector（创建态内嵌 + 追加态 Dialog），取内嵌那个
    const inlineSelector = wrapper.findAllComponents({ name: 'RepoMultiSelector' })[0]
    expect(inlineSelector).toBeTruthy()
    const options = inlineSelector.findAll('[data-test="repo-option"]')
    expect(options.length).toBe(2)
    // 行文本还含「AI 推荐」tooltip 文案，故按包含关系断言仓库名
    expect(options[0].text()).toContain('repo-alpha')
    expect(options[1].text()).toContain('repo-beta')
    expect(wrapper.text()).toContain('选择目标仓库')
  })

  it('「目标仓库」徽标区列出 AI 推荐的仓库名（缺 target-repositories 时整块不渲染）', async () => {
    const wrapper = await projectAndSettle()

    expect(wrapper.text()).toContain('目标仓库')
    expect(wrapper.text()).toContain('repo-alpha')
    expect(wrapper.text()).toContain('repo-beta')
  })

  it('交棒后正文与来源标志一并生效：渲染方案正文且不挂草稿横幅', async () => {
    const wrapper = await projectAndSettle()

    expect(wrapper.html()).toContain('<div data-test="md"># 方案正文</div>')
    expect(wrapper.find('[data-test="unresearched-banner"]').exists()).toBe(false)
  })
})

describe('orchestratedPlanCard — 源码纪律', () => {
  it('组件源码零 v-html（新增面不得引入未转义 HTML 渲染）', () => {
    const source = readFileSync(
      resolve(process.cwd(), 'src/components/chat/OrchestratedPlanCard.vue'),
      'utf-8',
    )
    const hits = source
      .split('\n')
      .filter(line => line.includes('v-html'))
      .filter((line) => {
        const trimmed = line.trim()
        // 过滤注释行，避免注释里提到 v-html 让断言自我失效
        return !trimmed.startsWith('//')
          && !trimmed.startsWith('*')
          && !trimmed.startsWith('<!--')
      })
    expect(hits).toEqual([])
  })
})
