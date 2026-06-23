/**
 * ：ClarificationCard.vue 单元测试。
 *
 * 覆盖：
 * - 渲染 question + options
 * - 提交按钮 disabled 当无 selection 且无 freeform
 * - 提交调用 postClarificationAnswer + markClarificationAnswered
 * - 提交错误展示错误文案
 * - answered 态：button / textarea / 按钮 disable + 「已回复」摘要
 * - allow_freeform=false 隐藏 textarea
 *
 * 组件用 `<button role="radio">` 而非原生 input radio 实现单选（与 shadcn-vue
 * 设计风格统一；项目内无 RadioGroup 组件）。
 */
import type { ClarificationPayload } from '~/types/clarification'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick } from 'vue'
import ClarificationCard from '~/components/chat/ClarificationCard.vue'
import { useChatStore } from '~/stores/chat'

const postClarificationAnswerMock = vi.fn()
vi.mock('~/api/chat', () => ({
  postClarificationAnswer: (...args: unknown[]) => postClarificationAnswerMock(...args),
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
  props: ['disabled', 'variant'],
  emits: ['click'],
  setup(props, { slots, emit }) {
    // 组件底部有「跳过」(variant=ghost) 与「提交答复」(默认 variant) 两个 Button，
    // 按 variant 区分 data-test，避免 .find('[data-test="submit-btn"]') 误命中跳过按钮。
    const isSkip = props.variant === 'ghost'
    return () => h('button', {
      'data-test': isSkip ? 'skip-btn' : 'submit-btn',
      'disabled': props.disabled || false,
      'onClick': () => !props.disabled && emit('click'),
    }, slots.default?.())
  },
})
const StubTextarea = defineComponent({
  name: 'Textarea',
  props: ['modelValue', 'disabled'],
  emits: ['update:modelValue'],
  setup(props, { emit }) {
    return () => h('textarea', {
      'value': props.modelValue,
      'disabled': props.disabled,
      'data-test': 'textarea',
      'onInput': (e: Event) => emit('update:modelValue', (e.target as HTMLTextAreaElement).value),
    })
  },
})

const globalStubs = {
  Badge: StubBadge,
  Button: StubButton,
  Textarea: StubTextarea,
}

function makePayload(overrides: Partial<ClarificationPayload> = {}): ClarificationPayload {
  return {
    clarification_id: 'cid-abc',
    question: '你想改哪个仓库？',
    options: [
      { id: 'opt-A', label: '改 friday-server', hint: '修改后端 API' },
      { id: 'opt-B', label: '改 friday-web' },
    ],
    allow_freeform: true,
    status: 'pending',
    ...overrides,
  }
}

function mountCard(payload: ClarificationPayload) {
  return mount(ClarificationCard, {
    props: { payload },
    global: { stubs: globalStubs },
  })
}

/** 返回所有 role=radio 按钮（不含提交按钮）。 */
function getOptionButtons(wrapper: ReturnType<typeof mountCard>) {
  return wrapper.findAll('button[role="radio"]')
}

beforeEach(() => {
  vi.clearAllMocks()
  setActivePinia(createPinia())
})

describe('clarificationCard', () => {
  it('renders question + options 列表', async () => {
    const wrapper = mountCard(makePayload())
    await flushPromises()
    expect(wrapper.text()).toContain('你想改哪个仓库？')
    expect(wrapper.text()).toContain('改 friday-server')
    expect(wrapper.text()).toContain('改 friday-web')
    expect(wrapper.text()).toContain('修改后端 API')
    expect(getOptionButtons(wrapper).length).toBe(2)
  })

  it('提交按钮在 selection / freeform 均空时 disabled', async () => {
    const wrapper = mountCard(makePayload())
    await flushPromises()
    const submitBtn = wrapper.find('[data-test="submit-btn"]')
    expect((submitBtn.element as HTMLButtonElement).disabled).toBe(true)
  })

  it('选中 option 后提交 → 调 api + markAnswered + status 切换', async () => {
    postClarificationAnswerMock.mockResolvedValue({
      clarification_id: 'cid-abc',
      selected_option_id: 'opt-A',
      freeform_text: '',
      answered_at: '2026-05-21T03:00:00Z',
      inferred_state: { selected_repository_ids: ['r1'] },
    })

    const payload = makePayload()
    const store = useChatStore()
    store.upsertClarification(payload)

    const wrapper = mountCard(payload)
    await flushPromises()

    const optionBtns = getOptionButtons(wrapper)
    await optionBtns[0].trigger('click')
    await nextTick()

    const submitBtn = wrapper.find('[data-test="submit-btn"]')
    expect((submitBtn.element as HTMLButtonElement).disabled).toBe(false)
    await submitBtn.trigger('click')
    await flushPromises()

    expect(postClarificationAnswerMock).toHaveBeenCalledWith('cid-abc', {
      selected_option_id: 'opt-A',
      freeform_text: undefined,
    })

    const updated = store.pendingClarifications.get('cid-abc')
    expect(updated?.status).toBe('answered')
    expect(updated?.answer?.selected_option_id).toBe('opt-A')
  })

  it('仅 freeform 文本时也能提交', async () => {
    postClarificationAnswerMock.mockResolvedValue({
      clarification_id: 'cid-abc',
      selected_option_id: '',
      freeform_text: '我想改 cli 仓库',
      answered_at: '2026-05-21T03:00:00Z',
      inferred_state: {},
    })

    const wrapper = mountCard(makePayload())
    await flushPromises()
    const textarea = wrapper.find('textarea')
    expect(textarea.exists()).toBe(true)
    await textarea.setValue('我想改 cli 仓库')
    await nextTick()

    const submitBtn = wrapper.find('[data-test="submit-btn"]')
    expect((submitBtn.element as HTMLButtonElement).disabled).toBe(false)
    await submitBtn.trigger('click')
    await flushPromises()

    expect(postClarificationAnswerMock).toHaveBeenCalledWith('cid-abc', {
      selected_option_id: undefined,
      freeform_text: '我想改 cli 仓库',
    })
  })

  it('submit 异常时展示错误文案，不切到 answered', async () => {
    postClarificationAnswerMock.mockRejectedValue(new Error('网络故障'))

    const payload = makePayload()
    const store = useChatStore()
    store.upsertClarification(payload)

    const wrapper = mountCard(payload)
    await flushPromises()
    await getOptionButtons(wrapper)[0].trigger('click')
    await nextTick()
    await wrapper.find('[data-test="submit-btn"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('网络故障')
    // 仍是 pending（未 markAnswered）
    const entry = store.pendingClarifications.get('cid-abc')
    expect(entry?.status).toBe('pending')
  })

  it('answered 态：option 按钮 disabled + 按钮区不渲染 + 显示已回复摘要', async () => {
    const payload = makePayload({
      status: 'answered',
      answer: {
        selected_option_id: 'opt-A',
        freeform_text: '',
        answered_at: '2026-05-21T03:00:00Z',
      },
    })
    const wrapper = mountCard(payload)
    await flushPromises()

    // 已回复态下方提交按钮区整体不渲染
    expect(wrapper.find('[data-test="submit-btn"]').exists()).toBe(false)
    // 但 option 按钮仍然渲染，只是 disabled
    const optionBtns = getOptionButtons(wrapper)
    expect(optionBtns.length).toBe(2)
    for (const b of optionBtns)
      expect((b.element as HTMLButtonElement).disabled).toBe(true)

    // 摘要文案
    expect(wrapper.text()).toContain('已回复')
    expect(wrapper.text()).toContain('改 friday-server')

    const badge = wrapper.find('[data-test="badge"]')
    expect(badge.text()).toBe('已回复')
  })

  it('allow_freeform=false 不渲染 textarea', async () => {
    const wrapper = mountCard(makePayload({ allow_freeform: false }))
    await flushPromises()
    expect(wrapper.find('textarea').exists()).toBe(false)
  })
})
