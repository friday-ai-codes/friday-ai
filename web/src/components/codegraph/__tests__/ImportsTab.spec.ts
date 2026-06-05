/**
 * — ImportsTab 单测
 * 验证：按 source_file 分组显示（同一 source_file 只渲染一次分组标题）
 */
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import ImportsTab from '../ImportsTab.vue'

vi.mock('~/api/codegraph', () => ({
  getImports: vi.fn().mockResolvedValue({
    count: 2,
    offset: 0,
    limit: 50,
    results: [
      {
        id: 'imp-1',
        source_file: 'src/main.py',
        target_module: 'os',
        imported_names: ['path'],
        is_relative: false,
      },
      {
        id: 'imp-2',
        source_file: 'src/main.py',
        target_module: 'sys',
        imported_names: ['argv'],
        is_relative: false,
      },
    ],
  }),
}))

vi.mock('@vueuse/core', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@vueuse/core')>()
  return { ...actual }
})

const stubComponents = {
  Badge: defineComponent({ template: '<span><slot /></span>' }),
  Button: defineComponent({ template: '<button v-bind="$attrs"><slot /></button>' }),
}

function mountImportsTab() {
  return mount(ImportsTab, {
    props: { repositoryId: 'repo-1' },
    global: { stubs: stubComponents },
  })
}

describe('importsTab', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('a: 挂载后调用 getImports API', async () => {
    const { getImports } = await import('~/api/codegraph')
    vi.mocked(getImports).mockResolvedValue({
      count: 1,
      offset: 0,
      limit: 50,
      results: [{
        id: 'imp-1',
        source_file: 'src/main.py',
        target_module: 'os',
        imported_names: ['path'],
        is_relative: false,
      }],
    })
    mountImportsTab()
    await flushPromises()
    expect(getImports).toHaveBeenCalledWith('repo-1', expect.any(Object))
  })

  it('b: 2 条同一 source_file 的 import 仅渲染 1 个分组标题', async () => {
    const { getImports } = await import('~/api/codegraph')
    vi.mocked(getImports).mockResolvedValue({
      count: 2,
      offset: 0,
      limit: 50,
      results: [
        {
          id: 'imp-1',
          source_file: 'src/main.py',
          target_module: 'os',
          imported_names: ['path'],
          is_relative: false,
        },
        {
          id: 'imp-2',
          source_file: 'src/main.py',
          target_module: 'sys',
          imported_names: ['argv'],
          is_relative: false,
        },
      ],
    })
    const wrapper = mountImportsTab()
    await flushPromises()

    // source_file 作为分组标题只渲染一次
    const text = wrapper.text()
    const groupHeaders = wrapper.findAll('.import-group-header')
    expect(groupHeaders.length).toBe(1)
    expect(text).toContain('src/main.py')
    // 两个 target_module 都要显示
    expect(text).toContain('os')
    expect(text).toContain('sys')
  })

  it('c: target_module 全部渲染', async () => {
    const { getImports } = await import('~/api/codegraph')
    vi.mocked(getImports).mockResolvedValue({
      count: 2,
      offset: 0,
      limit: 50,
      results: [
        {
          id: 'imp-1',
          source_file: 'src/main.py',
          target_module: 'os',
          imported_names: ['path'],
          is_relative: false,
        },
        {
          id: 'imp-2',
          source_file: 'src/main.py',
          target_module: 'sys',
          imported_names: [],
          is_relative: false,
        },
      ],
    })
    const w = mountImportsTab()
    await flushPromises()
    expect(w.text()).toContain('os')
    expect(w.text()).toContain('sys')
  })
})
