/**
 * 引用二级预览弹层的开关与装配（Phase 115-02，UI-SPEC §10.1）。
 *
 * 受控 Dialog 的四 ref 形状抄 `pages/knowledge/index.vue:165-191`（open / loading / data +
 * 当前对象），但**失败分支与那个 analog 完全相反**：
 *
 * | | analog（知识库工件弹窗） | 本 composable |
 * |---|---|---|
 * | 读取失败时 | 关掉弹窗 + toast 报错 | **保持弹窗打开**，渲染 citation 自带的 `title` / `quote` 快照 |
 *
 * ⭐ **兜底不留白（强制）**：任何来源的**任何非 2xx 或网络失败**（含 400 / 404 / 5xx / 超时 /
 * 解析失败）一律走快照兜底。⛔ 不关弹窗、⛔ 不渲染空白弹窗、⛔ 不回显后端错误体。
 *
 * 为什么判据是「拿不到数据」而不是「404 / 5xx / 网络」三档：`chunk-at` 的 `path` 与 `line`
 * **都是必填**，而 citation 的 `locator.line_start` 是**可能缺的**（不是所有 `repo_file` 引用都
 * 精确到行）—— 此时请求稳定 **400**，落在三档之外就漏进「未处理」路径。且它的错误体键是
 * `error` 而非 `detail`，任何试图回显 `detail` 的分支只会得到无意义的 `'请求失败'`。
 * ⇒ 调用侧纪律：`locator.line_start` 缺失时**直接不发请求**，立刻走兜底（省一次注定 400 的往返）。
 */

import type { Citation } from '~/types/blueprint'
import { computed, ref } from 'vue'

/** 预览弹层的兜底快照（来源不可达时渲染它）。 */
export interface CitationFallback {
  title: string
  quote: string
}

export function useCitationPreview() {
  const open = ref(false)
  const loading = ref(false)
  const citation = ref<Citation | null>(null)
  const data = ref<unknown>(null)
  /** 非 `null` 即「正在展示快照兜底」，UI 据此渲染那行「原始来源不可达…」说明。 */
  const fallback = ref<CitationFallback | null>(null)

  const sourceType = computed(() => citation.value?.source_type ?? '')

  function snapshotOf(item: Citation): CitationFallback {
    return { title: String(item.title ?? ''), quote: String(item.quote ?? '') }
  }

  /** 直接以快照形态打开（`locator` 不全、或 `source_type` 本就不需要请求时用）。 */
  function openWithSnapshot(item: Citation): void {
    citation.value = item
    data.value = null
    fallback.value = snapshotOf(item)
    loading.value = false
    open.value = true
  }

  /** 关闭弹层并清空装配（⚠️ 只由用户显式关闭触发，读取失败**不**走这里）。 */
  function close(): void {
    open.value = false
    loading.value = false
    citation.value = null
    data.value = null
    fallback.value = null
  }

  /**
   * 打开弹层并按 `source_type` 取详情。
   *
   * @param item 被点击的 citation。
   * @param loader 该 `source_type` 对应的读取函数；返回 `null` / 抛异常都视为不可达。
   */
  async function openCitation(
    item: Citation,
    loader?: (citation: Citation) => Promise<unknown>,
  ): Promise<void> {
    citation.value = item
    data.value = null
    fallback.value = null
    open.value = true

    if (!loader) {
      fallback.value = snapshotOf(item)
      return
    }

    loading.value = true
    try {
      const result = await loader(item)
      if (result === null || result === undefined) {
        // 「拿不到数据」与「请求失败」同档：判据是有没有内容，⛔ 不是状态码。
        fallback.value = snapshotOf(item)
        return
      }
      data.value = result
    }
    catch {
      // ⛔ 不关弹窗、⛔ 不回显后端错误体（§10.1 兜底不留白）。
      fallback.value = snapshotOf(item)
    }
    finally {
      loading.value = false
    }
  }

  return {
    open,
    loading,
    citation,
    data,
    fallback,
    sourceType,
    openCitation,
    openWithSnapshot,
    close,
  }
}
