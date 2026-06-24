/**
 * Phase 75-02 运维大盘组件 spec：钉死纯展示组件的关键契约（不触网，纯 props 驱动）。
 *
 *   (a) SnapshotRow 在 host.available=false 时渲染 n/a 灰态、不抛异常。
 *   (b) SnapshotRow CPU 超严重阈值（≥95）时主值命中 danger（rose）色。
 *   (c) MetricInfoCard 传 subItems / footnote 时渲染分位副行 + 副注。
 *   (d) HealthScoreGauge 缺源（snapshot=null）渲染 n/a、不崩。
 *
 * 这 4 个组件均为纯 props 组件（不调 useQuery / 不依赖 QueryClient），故可直接 mount。
 */
import type { MetricsSnapshot } from '~/api/system'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import HealthScoreGauge from '~/components/observability/HealthScoreGauge.vue'
import MetricInfoCard from '~/components/observability/MetricInfoCard.vue'
import SnapshotRow from '~/components/observability/SnapshotRow.vue'

/** 构造一个最小完整的 MetricsSnapshot，按需覆盖各源。 */
function makeSnapshot(overrides: Partial<MetricsSnapshot> = {}): MetricsSnapshot {
  return {
    host: { available: true, error: '', cpu_percent: 30, mem_percent: 40, asyncio_tasks: 100, threads: 20, background_tasks: { total_active: 2, durable_active: 1, subagent_active: 1 } as any },
    db: { available: true, error: '', vendor: 'postgres', connections: { total: 5, active: 2, idle: 3 }, max_connections: 100 },
    redis: { available: true, error: '', clients: { cache: { available: true, error: '', connected_clients: 10, maxclients: 1000, hit_rate: 0.95 } } },
    qdrant: { available: true, error: '', liveness: true, collection_count: 3 },
    concurrency: { available: true, error: '' },
    counters: {},
    generated_at: '2026-06-25T00:00:00Z',
    ...overrides,
  }
}

describe('snapshotRow', () => {
  it('(a) host.available=false 时 CPU/内存渲染 n/a 灰态且不抛', () => {
    const snapshot = makeSnapshot({
      host: { available: false, error: 'collect failed' } as any,
    })
    const wrapper = mount(SnapshotRow, { props: { snapshot } })
    const text = wrapper.text()
    expect(text).toContain('n/a')
    expect(text).toContain('数据源不可用')
    // 不应渲染出具体百分比主值（CPU 卡降级）。
    expect(wrapper.html()).toContain('text-muted-foreground')
    wrapper.unmount()
  })

  it('(b) CPU 超严重阈值（≥95）主值命中 danger（rose）色', () => {
    const snapshot = makeSnapshot({
      host: { available: true, cpu_percent: 97, mem_percent: 40, asyncio_tasks: 100, threads: 20 } as any,
    })
    const wrapper = mount(SnapshotRow, { props: { snapshot } })
    expect(wrapper.html()).toContain('text-rose-500')
    expect(wrapper.text()).toContain('97.0%')
    wrapper.unmount()
  })

  it('sqlite dev 下 DB available=false 显示 n/a (sqlite dev)', () => {
    const snapshot = makeSnapshot({
      db: { available: false, vendor: 'sqlite', error: 'sqlite' } as any,
    })
    const wrapper = mount(SnapshotRow, { props: { snapshot } })
    expect(wrapper.text()).toContain('n/a (sqlite dev)')
    wrapper.unmount()
  })
})

describe('metricInfoCard', () => {
  it('(c) 传 subItems / footnote 渲染分位副行 + 副注', () => {
    const wrapper = mount(MetricInfoCard, {
      props: {
        title: '请求时长',
        icon: 'lucide--timer',
        mainValue: '120ms',
        mainLabel: 'P95',
        subItems: [
          { label: 'P90', value: '90ms' },
          { label: 'P50', value: '40ms' },
        ],
        footnote: '头部为 P95',
      },
    })
    const text = wrapper.text()
    expect(text).toContain('120ms')
    expect(text).toContain('P95')
    expect(text).toContain('P90')
    expect(text).toContain('90ms')
    expect(text).toContain('头部为 P95')
    wrapper.unmount()
  })

  it('loading 时渲染骨架、不渲染主值', () => {
    const wrapper = mount(MetricInfoCard, {
      props: { title: 'X', icon: 'lucide--timer', mainValue: '999', loading: true },
    })
    expect(wrapper.text()).not.toContain('999')
    wrapper.unmount()
  })
})

describe('healthScoreGauge', () => {
  it('(d) snapshot=null 渲染 n/a、不崩', () => {
    const wrapper = mount(HealthScoreGauge, { props: { snapshot: null } })
    expect(wrapper.text()).toContain('n/a')
    expect(wrapper.text()).toContain('暂无数据')
    wrapper.unmount()
  })

  it('有 snapshot + 错误率时算出 0–100 分数并显示徽标', () => {
    const wrapper = mount(HealthScoreGauge, {
      props: {
        snapshot: makeSnapshot(),
        errorRate: 0.01,
        upstreamErrorRate: 0,
      },
    })
    // 低负载 + 低错误率 → 高分（健康）。
    expect(wrapper.text()).toContain('健康')
    wrapper.unmount()
  })
})
