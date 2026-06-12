import { mount } from '@vue/test-utils'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { createI18n } from 'vue-i18n'
import { describe, expect, it, vi } from 'vitest'
import EntityDetailPage from '~/pages/knowledge/entities/[id].vue'

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { id: '11111111-1111-1111-1111-111111111111' } }),
}))

vi.mock('~/api', () => ({
  knowledgeApi: {
    getEntity: vi.fn().mockResolvedValue({
      entity_id: '11111111-1111-1111-1111-111111111111',
      kind: 'work_item',
      version: 1,
      title: '测试实体',
      provenance: {},
      source_kind: 'feishu_work_item',
      source_id: '1',
      origin: 'feishu',
    }),
    getTimeline: vi.fn().mockResolvedValue([]),
    getRelated: vi.fn().mockResolvedValue([]),
  },
}))

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      knowledge: {
        entity: {
          pageTitle: '交付知识',
          sections: { metadata: '基本信息', timeline: '版本历史', related: '关联实体' },
          fields: { version: '版本', entityId: '实体 ID', validAt: '生效时间', eventTime: '事件时间' },
          badges: { currentVersion: '当前版本' },
          asOf: { label: '历史视点', placeholder: '', reset: '恢复当前' },
          includeSuperseded: '显示已取代版本',
          empty: {
            timelineTitle: '暂无版本历史',
            timelineBody: '',
            relatedTitle: '暂无关联实体',
            relatedBody: '',
          },
        },
      },
    },
  },
})

describe('entity detail page', () => {
  it('mounts with metadata title', async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = mount(EntityDetailPage, {
      global: {
        plugins: [i18n, [VueQueryPlugin, { queryClient }]],
        stubs: {
          AnchorNavLayout: { template: '<div><slot /></div>' },
          PageContainer: { template: '<div><slot /></div>' },
          CompactEmptyState: true,
          EntityDetailToolbar: true,
        },
      },
    })
    await new Promise(r => setTimeout(r, 50))
    expect(wrapper.html()).toContain('测试实体')
  })
})
