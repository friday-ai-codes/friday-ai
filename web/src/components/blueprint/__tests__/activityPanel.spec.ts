/**
 * 过程分析面板的组件测试（Phase 119，LIVE-01/02/03）。
 *
 * 守五件事：
 *  1. ⭐ **两张视图都空 ⇒ 整块不渲染**（⛔ 不出「暂无数据」空卡片：编排还没跑到路由阶段是
 *     正常态，一张空卡只会挤占正文首屏）。
 *  2. ⭐ 适配度渲染成**百分比**（79.87%）而不是原始小数，且三分量可核对。
 *  3. ⭐ 无分数的仓**不显示 0%**（那会被读成「完全不适配」）。
 *  4. 分仓每仓渲染三态与波次、产出计数。
 *  5. 生成中默认展开、收官后默认折叠（`isLive` 驱动）。
 */

import type { BlueprintEvent } from '~/types/blueprint'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { createI18n } from 'vue-i18n'
import BlueprintActivityPanel from '~/components/blueprint/BlueprintActivityPanel.vue'

// ⭐ 仓名兜底解析的接口 mock：旧事件缺 repository_name 时组件会拉仓库列表补全。
vi.mock('~/api/repositories', () => ({
  repositoriesApi: {
    list: vi.fn().mockResolvedValue([
      { id: 'ec433b88-2e6a-422c-8073-1b4612e373c1', name: '解析出的仓库名' },
    ]),
  },
}))

const PANEL = '[data-testid="blueprint-activity-panel"]'
const FITNESS = '[data-testid="blueprint-activity-fitness"]'
const REPOS = '[data-testid="blueprint-activity-repos"]'
const SCORE = '[data-testid="blueprint-activity-fitness-score"]'

const i18n = createI18n({
  legacy: false,
  locale: 'zh-CN',
  missingWarn: false,
  fallbackWarn: false,
  messages: {
    'zh-CN': {
      knowledge: {
        blueprints: {
          activity: {
            title: '过程分析',
            repoCount: '{n} 个仓',
            fitnessTitle: '仓库适配度与路由依据',
            repoPlanTitle: '分仓方案进度',
            component: {
              charter_match: '章程契合',
              history_match: '历史落点',
              router_base: '能力匹配',
            },
            evidence: '命中能力树 {nodes} 处 · 章程域 {domains} 个 · 引用 {citations} 条',
            boundaryHit: '触碰边界禁区 {n} 处',
            repoStateRunning: '拟定中',
            repoStateDone: '已产出',
            repoStateWaiting: '等待依赖',
            wave: '第 {n} 波',
            repoOutput: '{items} 项实现 · {apis} 条接口',
            repoUnknown: '未知仓库',
          },
        },
      },
    },
  },
})

function event(name: string, payload: Record<string, unknown>, ts = '2026-08-05T01:00:00+00:00'): BlueprintEvent {
  return { id: `${name}-${ts}`, event: name, payload, ts }
}

function mountPanel(events: BlueprintEvent[], isLive = true) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return mount(BlueprintActivityPanel, {
    props: { events, isLive },
    global: { plugins: [i18n, [VueQueryPlugin, { queryClient }]] },
  })
}

/** 等 useQuery 的 promise 落定（mock 是同步 resolve，两个微任务足够）。 */
async function flushQueries(): Promise<void> {
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()
}

describe('blueprintActivityPanel', () => {
  it('⭐ 无内容 ⇒ 整块不渲染（不出空卡片）', () => {
    expect(mountPanel([]).find(PANEL).exists()).toBe(false)
    // 与活动流无关的事件同样不该把面板撑出来
    expect(mountPanel([event('blueprint.status.transitioned', {})]).find(PANEL).exists()).toBe(false)
  })

  it('⭐ 适配度渲染成百分比，三分量可核对', () => {
    const wrapper = mountPanel([
      event('blueprint.route.scored', {
        candidates: [{
          repository_id: 'r1',
          repository_name: '高中数学仓',
          total: 0.7987,
          charter_match: 0.812,
          history_match: 0.65,
          router_base: 0.9,
          role_suggestion: 'direct',
          confidence: 'high',
        }],
      }),
      event('blueprint.route.plan_drafted', {
        repositories: [{
          repository_id: 'r1',
          matched_node_path_count: 4,
          matched_domain_count: 2,
          violated_boundary_count: 1,
          citation_ids: ['c1', 'c2', 'c3'],
        }],
      }, '2026-08-05T02:00:00+00:00'),
    ])

    expect(wrapper.find(PANEL).exists()).toBe(true)
    expect(wrapper.find(SCORE).text()).toBe('79.87%')
    const text = wrapper.find(FITNESS).text()
    expect(text).toContain('高中数学仓')
    expect(text).toContain('章程契合')
    expect(text).toContain('0.812')
    expect(text).toContain('命中能力树 4 处')
    expect(text).toContain('引用 3 条')
    expect(text).toContain('触碰边界禁区 1 处')
  })

  it('⭐ 无分数的仓不显示 0%', () => {
    const wrapper = mountPanel([
      event('blueprint.route.scored', {
        candidates: [{ repository_id: 'r1', repository_name: '无分仓' }],
      }),
    ])

    expect(wrapper.find(SCORE).exists()).toBe(false)
    expect(wrapper.find(FITNESS).text()).not.toContain('0.00%')
  })

  it('分仓每仓渲染三态、波次与产出计数', () => {
    const wrapper = mountPanel([
      event('blueprint.repo_plan.repo_started', { repository_id: 'a', repository_name: 'A 仓', wave: 1 }),
      event('blueprint.repo_plan.repo_completed', { repository_id: 'a', item_count: 5, api_count: 3 }, '2026-08-05T02:00:00+00:00'),
      event('blueprint.repo_plan.repo_started', { repository_id: 'b', repository_name: 'B 仓', wave: 2 }),
      event('blueprint.context.waiter_registered', { from_repository_id: 'b', to_key: 'contract:x' }, '2026-08-05T02:00:00+00:00'),
    ])

    const section = wrapper.find(REPOS)
    expect(section.text()).toContain('A 仓')
    expect(section.text()).toContain('已产出')
    expect(section.text()).toContain('5 项实现 · 3 条接口')
    expect(section.text()).toContain('B 仓')
    expect(section.text()).toContain('等待依赖')
    expect(section.text()).toContain('第 2 波')
    expect(wrapper.findAll('[data-repo-state]')).toHaveLength(2)
  })

  it('仓名缺失时回落短 id，⛔ 不渲染整串 UUID', () => {
    const wrapper = mountPanel([
      event('blueprint.repo_plan.repo_started', { repository_id: '0123456789abcdef-long-uuid', wave: 1 }),
    ])

    const text = wrapper.find(REPOS).text()
    expect(text).toContain('01234567…')
    expect(text).not.toContain('0123456789abcdef-long-uuid')
  })

  it('⭐ 旧事件缺仓名 ⇒ 按 id 从仓库列表补全成可读名字', async () => {
    const wrapper = mountPanel([
      event('blueprint.route.scored', {
        candidates: [{ repository_id: 'ec433b88-2e6a-422c-8073-1b4612e373c1', total: 0.3479 }],
      }),
    ])
    await flushQueries()
    await wrapper.vm.$nextTick()

    const text = wrapper.find(FITNESS).text()
    expect(text).toContain('解析出的仓库名')
    expect(text).not.toContain('ec433b88…')
  })

  it('⭐ 仓名是新窗口链接，指向仓库详情页', () => {
    const wrapper = mountPanel([
      event('blueprint.route.scored', {
        candidates: [{ repository_id: 'r1', repository_name: '高中数学仓', total: 0.5 }],
      }),
      event('blueprint.repo_plan.repo_started', { repository_id: 'r2', repository_name: 'B 仓', wave: 1 }, '2026-08-05T02:00:00+00:00'),
    ])

    const links = wrapper.findAll('[data-testid="blueprint-activity-repo-link"]')
    expect(links).toHaveLength(2)
    expect(links[0].attributes('href')).toBe('/repositories/r1')
    expect(links[0].attributes('target')).toBe('_blank')
    expect(links[0].attributes('rel')).toContain('noopener')
    expect(links[1].attributes('href')).toBe('/repositories/r2')
  })

  it('isLive 驱动默认展开态', () => {
    const events = [event('blueprint.repo_plan.repo_started', { repository_id: 'a', wave: 1 })]

    expect(mountPanel(events, true).find(REPOS).exists()).toBe(true)
    // 收官后默认折叠 ⇒ 内容区不在 DOM（reka-ui Collapsible 默认卸载内容）
    expect(mountPanel(events, false).find(REPOS).exists()).toBe(false)
  })
})
