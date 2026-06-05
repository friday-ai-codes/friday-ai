import type { IFuseOptions } from 'fuse.js'
import type { GalaxyNode, GalaxySearchResult } from '~/api/galaxy'
import Fuse from 'fuse.js'
import { ref } from 'vue'
import { searchGalaxyNodes } from '~/api/galaxy'

const FUSE_OPTIONS: IFuseOptions<GalaxySearchResult> = {
  keys: ['label', 'file_path'],
  threshold: 0.4,
  includeScore: true,
}

export function useGalaxySearch() {
  const query = ref('')
  const results = ref<GalaxySearchResult[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  let fuseInstance: Fuse<GalaxySearchResult> | null = null
  let debounceTimer: ReturnType<typeof setTimeout> | null = null

  function setCorpus(nodes: GalaxyNode[]) {
    const corpus: GalaxySearchResult[] = nodes.map(n => ({
      id: n.id,
      type: n.type,
      label: n.label,
      file_path: n.file_path,
      repository_id: n.repository_id,
      degree: n.degree,
    }))
    fuseInstance = new Fuse(corpus, FUSE_OPTIONS)
  }

  function searchLocal(nodes: GalaxyNode[], q: string): GalaxySearchResult[] {
    if (!q.trim())
      return []
    const corpus: GalaxySearchResult[] = nodes.map(n => ({
      id: n.id,
      type: n.type,
      label: n.label,
      file_path: n.file_path,
      repository_id: n.repository_id,
      degree: n.degree,
    }))
    const fuse = new Fuse(corpus, FUSE_OPTIONS)
    return fuse.search(q).map(r => r.item)
  }

  function fuseFilter(apiResults: GalaxySearchResult[], q: string): GalaxySearchResult[] {
    if (!q.trim() || !fuseInstance)
      return apiResults
    const localMatches = fuseInstance.search(q).map(r => r.item)
    const seen = new Set(apiResults.map(r => r.id))
    const extras = localMatches.filter(r => !seen.has(r.id))
    return [...apiResults, ...extras]
  }

  function search(q: string): void {
    if (debounceTimer)
      clearTimeout(debounceTimer)

    if (!q.trim()) {
      results.value = []
      return
    }

    debounceTimer = setTimeout(async () => {
      loading.value = true
      error.value = null
      try {
        const apiResults = await searchGalaxyNodes(q, 20)
        results.value = fuseFilter(apiResults, q)
      }
      catch (e: unknown) {
        error.value = e instanceof Error ? e.message : '搜索失败'
        if (fuseInstance) {
          results.value = fuseInstance.search(q).map(r => r.item)
        }
      }
      finally {
        loading.value = false
      }
    }, 300)
  }

  return {
    query,
    results,
    loading,
    error,
    search,
    searchLocal,
    setCorpus,
  }
}
