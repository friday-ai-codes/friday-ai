import { get } from './client'
// ============================================================================
// Galaxy Node / Edge Types
// ============================================================================
export type GalaxyNodeType =
 | 'chunk_registry'
 | 'symbol'
 | 'endpoint'
 | 'api_wrapper'
 | 'api_call_site'
export type GalaxyEdgeType =
 | 'CALL'
 | 'IMPORT'
 | 'SAME_FILE'
 | 'TEST_OF'
 | 'CO_CHANGED'
 | 'SEMANTIC'
 | 'API_CALLS'
 | 'IMPLEMENTS'
export interface GalaxyNode {
 id: string
 type: GalaxyNodeType
 label: string
 repository_id: string
 file_path: string
 line_start: number
 line_end: number
 metadata: Record<string, unknown>
 degree: number
}
export interface GalaxyEdge {
 id: string
 source: string
 target: string
 edge_type: GalaxyEdgeType
 weight: number
 repository_id: string
 target_repository_id: string | null
 metadata: Record<string, unknown>
}
export interface GalaxyMeta {
 total_nodes: number
 total_edges: number
 sampled: boolean
 per_repo_hint: boolean
 max_nodes: number
}
export interface GalaxyResponse {
 nodes: GalaxyNode
 edges: GalaxyEdge
 meta: GalaxyMeta
}
export interface GetGalaxyParams {
 repoIds?: string
 nodeTypes?: GalaxyNodeType
 edgeTypes?: GalaxyEdgeType
 maxNodes?: number
}
export interface GalaxySearchResult {
 id: string
 type: GalaxyNodeType
 label: string
 file_path: string
 repository_id: string
 degree: number
 score?: number
}
export interface GalaxyNodeDetail {
 node: GalaxyNode
 neighbors: Array<{
 node: GalaxyNode
 edge_type: GalaxyEdgeType
 direction: 'in' | 'out'
 }>
 references: Array<{
 source_node_id: string
 edge_type: GalaxyEdgeType
 }>
 called_by: Array<{
 caller_node_id: string
 edge_type: GalaxyEdgeType
 }>
}
// ============================================================================
// API Functions
// ============================================================================
export async function getGalaxyGraph(params: GetGalaxyParams = {}): Promise<GalaxyResponse> {
 const query: Record<string, string | number | undefined> = {}
 if (params.repoIds && params.repoIds.length > 0)
 query.repo_ids = params.repoIds.join(',')
 if (params.nodeTypes && params.nodeTypes.length > 0)
 query.node_types = params.nodeTypes.join(',')
 if (params.edgeTypes && params.edgeTypes.length > 0)
 query.edge_types = params.edgeTypes.join(',')
 if (params.maxNodes !== undefined)
 query.max_nodes = params.maxNodes
 return get<GalaxyResponse>('/codegraph/galaxy/', query)
}
export async function searchGalaxyNodes(
 q: string,
 maxResults = 20,
): Promise<GalaxySearchResult> {
 const data = await get<{ results: GalaxySearchResult }>('/codegraph/galaxy/search/', {
 q,
 max_results: maxResults,
 })
 return data.results
}
export async function getGalaxyNodeDetail(nodeId: string): Promise<GalaxyNodeDetail> {
 const encoded = encodeURIComponent(nodeId)
 return get<GalaxyNodeDetail>(`/codegraph/galaxy/nodes/${encoded}/`)
}
