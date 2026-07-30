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

const toastSuccess = vi.fn()
const toastError = vi.fn()
vi.mock('~/composables/useToast', () => ({
  useToast: () => ({ success: toastSuccess, error: toastError }),
}))

const projectPlanToCodingPlan = vi.fn()
vi.mock('~/stores/chat', () => ({
  useChatStore: () => ({ projectPlanToCodingPlan }),
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
