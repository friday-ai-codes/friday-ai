import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import RepoCharterSection from '~/components/repository/RepoCharterSection.vue'
import zhCN from '~/locales/zh-CN.json'

const fetchMock = vi.fn()
const confirmMock = vi.fn()
const draftMock = vi.fn()
const dialogConfirmMock = vi.fn()

vi.mock('~/api/repositoryChunks', () => ({
  fetchRepositoryCharter: (...args: unknown[]) => fetchMock(...args),
  confirmRepositoryCharter: (...args: unknown[]) => confirmMock(...args),
  draftRepositoryCharter: (...args: unknown[]) => draftMock(...args),
}))

vi.mock('~/composables/useConfirmDialog', () => ({
  useConfirmDialog: () => ({ confirm: (...args: unknown[]) => dialogConfirmMock(...args) }),
}))

vi.mock('~/composables/useToast', () => ({
  useToast: () => ({
    success: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
  }),
}))

vi.mock('~/composables/useErrorHandler', () => ({
  useErrorHandler: () => ({ handleError: vi.fn() }),
}))

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: { 'zh-CN': zhCN },
})

function mountSection() {
  return mount(RepoCharterSection, {
    props: { repositoryId: 'repo-1' },
    global: {
      plugins: [i18n],
      stubs: {
        Select: true,
        SelectTrigger: true,
        SelectValue: true,
        SelectContent: true,
        SelectItem: true,
        Textarea: { template: '<textarea />', props: ['modelValue'] },
        Input: { template: '<input />', props: ['modelValue'] },
        Button: { template: '<button><slot /></button>' },
        Badge: { template: '<span><slot /></span>' },
        Skeleton: { template: '<div />' },
      },
    },
  })
}

describe('repo charter section', () => {
  beforeEach(() => {
    fetchMock.mockReset()
    confirmMock.mockReset()
    draftMock.mockReset()
    dialogConfirmMock.mockReset()
    dialogConfirmMock.mockResolvedValue(true)
  })

  it('shows empty state with charter title when no charter', async () => {
    fetchMock.mockResolvedValue(null)
    const wrapper = mountSection()
    await flushPromises()
    expect(wrapper.text()).toContain(zhCN.repositories.charter.title)
    expect(wrapper.find('[data-testid="repo-charter-empty"]').exists()).toBe(true)
    expect(wrapper.text()).toContain(zhCN.repositories.charter.emptyTitle)
  })

  it('calls confirm with edits after save confirm', async () => {
    fetchMock.mockResolvedValue(null)
    confirmMock.mockResolvedValue({
      id: 'c1',
      repository: 'repo-1',
      version: 1,
      source: 'human_confirmed',
      confirmed_by: 'u1',
      positioning: '人手章程',
      owned_domains: [],
      boundaries: [],
      placement_preferences: [],
      audience: '',
      form: '',
      evolution: 'active',
      draft_content: {},
      created_at: '',
      updated_at: '',
    })
    const wrapper = mountSection()
    await flushPromises()

    await wrapper.find('[data-testid="repo-charter-manual-fill"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('[data-testid="repo-charter-editor"]').exists()).toBe(true)

    await wrapper.find('[data-testid="repo-charter-save-confirm"]').trigger('click')
    await flushPromises()

    expect(dialogConfirmMock).toHaveBeenCalled()
    expect(confirmMock).toHaveBeenCalledWith(
      'repo-1',
      expect.objectContaining({
        positioning: expect.any(String),
        owned_domains: expect.any(Array),
        evolution: 'active',
      }),
    )
  })

  it('shows pending draft banner when draft_content is present', async () => {
    fetchMock.mockResolvedValue({
      id: 'c1',
      repository: 'repo-1',
      version: 2,
      source: 'human_confirmed',
      confirmed_by: 'u1',
      positioning: '正式定位',
      owned_domains: [],
      boundaries: [],
      placement_preferences: [],
      audience: '',
      form: '',
      evolution: 'active',
      draft_content: { positioning: '修订草案定位' },
      created_at: '',
      updated_at: '',
    })
    const wrapper = mountSection()
    await flushPromises()
    expect(wrapper.find('[data-testid="repo-charter-pending-draft"]').exists()).toBe(true)
    expect(wrapper.text()).toContain(zhCN.repositories.charter.pendingDraft)
  })
})
