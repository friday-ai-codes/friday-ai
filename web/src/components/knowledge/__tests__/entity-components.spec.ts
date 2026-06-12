import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createI18n } from 'vue-i18n'
import EntityKindBadge from '~/components/knowledge/EntityKindBadge.vue'
import EntityVersionTimeline from '~/components/knowledge/EntityVersionTimeline.vue'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  messages: {
    'zh-CN': {
      knowledge: {
        entity: {
          kind: {
            workItem: '需求/缺陷',
            techPlan: '技术方案',
            codeChange: '代码变更',
          },
        },
      },
    },
  },
})

describe('entityKindBadge', () => {
  it('renders work_item label', () => {
    const wrapper = mount(EntityKindBadge, {
      props: { kind: 'work_item' },
      global: { plugins: [i18n] },
    })
    expect(wrapper.text()).toContain('需求/缺陷')
  })
})

describe('entityVersionTimeline', () => {
  it('renders timeline nodes', () => {
    const wrapper = mount(EntityVersionTimeline, {
      props: {
        nodes: [
          { entity_id: 'e1', version: 1, kind: 'work_item', title: 'A', summary: 's' },
          { entity_id: 'e1', version: 2, kind: 'work_item', title: 'B', summary: 's2' },
        ],
      },
      global: { plugins: [i18n] },
    })
    expect(wrapper.findAll('[data-testid="timeline-node"]').length).toBe(2)
  })
})
