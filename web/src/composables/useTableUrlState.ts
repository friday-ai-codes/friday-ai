/**
 * 列表/表格视图状态 ↔ URL query 持久化（刷新可恢复）的单一权威。
 *
 * 统一管理一个页面表格的：分页（page/size）、排序（sort）、全局搜索（q）以及任意
 * 分面筛选（单选 single / 多选 list）。**单写入者**：所有受管状态变化都经由同一个
 * watcher 合并写回 URL（router.replace），既避免多 watcher 互相覆盖（竞态），又通过
 * `{ ...route.query }` 合并保留无关 query（如 detail/id/tab 深链）。
 *
 * 初始值从 URL 读取（URL→state），之后单向 state→URL（不监听 route.query 回写，
 * 避免回环）。收窄筛选/搜索时自动回到第 1 页。
 *
 * 用法：
 * ```ts
 * const { pagination, sorting, globalFilter, facets, resetFacets, activeFacetCount }
 *   = useTableUrlState({
 *     facets: {
 *       status: { type: 'single', default: 'all' },
 *       owners: { type: 'list' },
 *     },
 *   })
 * // 模板：<DataTable v-model:pagination v-model:sorting v-model:global-filter />
 * //       <FacetMultiSelect v-model="facets.owners" />
 * //       <Select v-model="facets.status" />
 * ```
 */
import type { PaginationState, SortingState } from '@tanstack/vue-table'
import type { Ref } from 'vue'
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

export type FacetSpec =
  | { type: 'single', default: string, key?: string }
  | { type: 'list', key?: string }

export interface TableUrlStateOptions {
  /** 默认每页条数（与 DataTable 默认一致，20）；等于该值时不写入 URL。 */
  pageSize?: number
  /** 是否持久化分页（默认 true） */
  paginate?: boolean
  /** 是否持久化排序（默认 true） */
  sort?: boolean
  /** 是否持久化全局搜索 q（默认 true） */
  search?: boolean
  /** 分面筛选定义；key 为返回 facets 上的属性名，spec.key 可自定义 URL 参数名。 */
  facets?: Record<string, FacetSpec>
  /** URL 参数前缀（同页多表时避免冲突，如 'a' → a_page / a_q）。 */
  prefix?: string
}

function parseList(v: unknown): string[] {
  return typeof v === 'string' && v ? v.split(',').filter(Boolean) : []
}
function parseSort(v: unknown): SortingState {
  if (typeof v !== 'string' || !v)
    return []
  const [id, dir] = v.split(':')
  return id ? [{ id, desc: dir === 'desc' }] : []
}

export function useTableUrlState(options: TableUrlStateOptions = {}) {
  const {
    pageSize = 20,
    paginate = true,
    sort: enableSort = true,
    search: enableSearch = true,
    facets: facetSpecs = {},
    prefix = '',
  } = options

  const route = useRoute()
  const router = useRouter()
  const k = (name: string) => (prefix ? `${prefix}_${name}` : name)

  // --- 初始化（URL → state）---
  const facetRefs: Record<string, Ref<string | string[]>> = {}
  for (const [name, spec] of Object.entries(facetSpecs)) {
    const qk = k(spec.key ?? name)
    if (spec.type === 'single') {
      const qv = route.query[qk]
      facetRefs[name] = ref(typeof qv === 'string' ? qv : spec.default)
    }
    else {
      facetRefs[name] = ref(parseList(route.query[qk]))
    }
  }

  const qInit = route.query[k('q')]
  const globalFilter = ref(typeof qInit === 'string' ? qInit : '')
  const sorting = ref<SortingState>(parseSort(route.query[k('sort')]))
  const pagination = ref<PaginationState>({
    pageIndex: Math.max(0, (Number(route.query[k('page')]) || 1) - 1),
    pageSize: Number(route.query[k('size')]) || pageSize,
  })

  const allFacetRefs = Object.values(facetRefs)

  // 收窄筛选/搜索时回到第一页，避免停留在越界空白页
  watch([...allFacetRefs, globalFilter], () => {
    if (paginate && pagination.value.pageIndex !== 0)
      pagination.value = { ...pagination.value, pageIndex: 0 }
  })

  // --- 单写入者（state → URL，merge-prune 保留无关 query）---
  watch([...allFacetRefs, globalFilter, sorting, pagination], () => {
    const query: Record<string, unknown> = { ...route.query }
    const setDel = (key: string, val: string) => {
      if (val)
        query[key] = val
      else
        delete query[key]
    }
    for (const [name, spec] of Object.entries(facetSpecs)) {
      const qk = k(spec.key ?? name)
      const v = facetRefs[name].value
      if (spec.type === 'single')
        setDel(qk, typeof v === 'string' && v && v !== spec.default ? v : '')
      else
        setDel(qk, Array.isArray(v) && v.length ? v.join(',') : '')
    }
    setDel(k('q'), enableSearch && globalFilter.value.trim() ? globalFilter.value.trim() : '')
    setDel(k('page'), paginate && pagination.value.pageIndex > 0 ? String(pagination.value.pageIndex + 1) : '')
    setDel(k('size'), paginate && pagination.value.pageSize !== pageSize ? String(pagination.value.pageSize) : '')
    setDel(k('sort'), enableSort && sorting.value.length ? `${sorting.value[0].id}:${sorting.value[0].desc ? 'desc' : 'asc'}` : '')
    router.replace({ query })
  })

  function resetFacets() {
    for (const [name, spec] of Object.entries(facetSpecs))
      facetRefs[name].value = spec.type === 'single' ? spec.default : []
    globalFilter.value = ''
  }

  /** 当前生效的分面筛选数量（single 计 1、list 计每个选项），用于「清除（N）」。 */
  const activeFacetCount = computed(() => {
    let n = 0
    for (const [name, spec] of Object.entries(facetSpecs)) {
      const v = facetRefs[name].value
      if (spec.type === 'single') {
        if (typeof v === 'string' && v && v !== spec.default)
          n++
      }
      else if (Array.isArray(v) && v.length) {
        n += v.length
      }
    }
    return n
  })

  // reactive 包裹：模板里 `facets.xxx` 自动解包、v-model 可写回底层 ref
  const facets = reactive(facetRefs) as Record<string, any>

  return { pagination, sorting, globalFilter, facets, resetFacets, activeFacetCount }
}
