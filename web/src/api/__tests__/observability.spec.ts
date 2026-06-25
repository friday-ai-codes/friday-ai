import { beforeEach, describe, expect, expectTypeOf, it, vi } from 'vitest'

// 镜像 setup.spec.ts 的 mock 范式：拦截 ~/api/client 的 get/post/patch/del，
// 断言运维端点的 URL 构造与参数体，不触达真实网络。
const getMock = vi.fn()
const postMock = vi.fn()
const patchMock = vi.fn()
const delMock = vi.fn()

vi.mock('~/api/client', () => ({
  get: (url: string, params?: unknown) => getMock(url, params),
  post: (url: string, body?: unknown) => postMock(url, body),
  patch: (url: string, body?: unknown) => patchMock(url, body),
  del: (url: string) => delMock(url),
}))

const {
  queryMetrics,
  querySla,
  clearSystemLogs,
  getConversationDrilldown,
} = await import('~/api/system')
type MetricsApi = typeof import('~/api/system')

beforeEach(() => {
  vi.clearAllMocks()
})

describe('queryMetrics', () => {
  it('hits /system/metrics/query/ with metric/step/dimension in params', async () => {
    getMock.mockResolvedValueOnce({ metric: 'qps', series: [] })

    await queryMetrics({ metric: 'qps', step: '1m', dimension: 'provider' })

    expect(getMock).toHaveBeenCalledWith('/system/metrics/query/', {
      metric: 'qps',
      step: '1m',
      dimension: 'provider',
    })
  })
})

describe('querySla', () => {
  it('forces metric=sla on /system/metrics/query/', async () => {
    getMock.mockResolvedValueOnce({ metric: 'sla', series: [] })

    await querySla({ step: '5m' })

    expect(getMock).toHaveBeenCalledWith('/system/metrics/query/', {
      step: '5m',
      metric: 'sla',
    })
  })
})

describe('clearSystemLogs', () => {
  it('posts filters + confirm_all to /system/logs/clear/', async () => {
    postMock.mockResolvedValueOnce({ deleted: 3 })

    const result = await clearSystemLogs({ level: 'error', confirm_all: false })

    expect(result.deleted).toBe(3)
    expect(postMock).toHaveBeenCalledWith('/system/logs/clear/', {
      level: 'error',
      confirm_all: false,
    })
  })
})

describe('getConversationDrilldown', () => {
  it('hits /system/conversations/<uuid>/drilldown/', async () => {
    getMock.mockResolvedValueOnce({ conversation: {}, created_by: null, messages: [], related_logs: [], related_runs: [] })

    await getConversationDrilldown('uuid-x')

    expect(getMock).toHaveBeenCalledWith('/system/conversations/uuid-x/drilldown/', undefined)
  })
})

describe('metrics series types', () => {
  it('queryMetrics 返回 MetricPoint[]，querySla 返回 SlaPoint[]（编译期类型断言）', () => {
    type QueryMetricsSeries = Awaited<ReturnType<MetricsApi['queryMetrics']>>['series'][number]
    type QuerySlaSeries = Awaited<ReturnType<MetricsApi['querySla']>>['series'][number]

    expectTypeOf<QueryMetricsSeries>().toEqualTypeOf<import('~/api/system').MetricPoint>()
    expectTypeOf<QuerySlaSeries>().toEqualTypeOf<import('~/api/system').SlaPoint>()
  })
})
