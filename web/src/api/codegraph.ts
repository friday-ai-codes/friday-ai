import { get, post } from './client'
export interface SymbolRow {
 id: string
 name: string
 symbol_type: 'FUNCTION' | 'CLASS' | 'METHOD' | 'VARIABLE'
 file_path: string
 line_start: number
 line_end: number
 signature: string
 is_async: boolean
}
export interface ImportEdgeRow {
 id: string
 source_file: string
 target_module: string
 imported_names: string
 is_relative: boolean
}
export interface EndpointRow {
 id: string
 http_method: string
 url_path: string
 handler_name: string
 view_type: 'FUNCTION_VIEW' | 'CLASS_VIEW' | 'VIEWSET'
 file_path: string
 line_number: number
}
export interface PaginatedResponse<T> {
 count: number
 offset: number
 limit: number
 results: T
}
export interface GetSymbolsParams {
 repositoryId: string
 symbolTypes?: string
 name?: string
 filePath?: string
 limit?: number
 offset?: number
}
export interface GetImportsParams {
 repositoryId: string
 sourceFile?: string
 limit?: number
 offset?: number
}
export interface GetEndpointsParams {
 repositoryId: string
 limit?: number
 offset?: number
}
export interface DagNode {
 symbol: SymbolRow & { id: string }
 depth: number
 relationship: string
}
export interface DagEdge {
 source: string
 target: string
 call_type: string
}
export interface DagData {
 seed_symbol_id: string
 nodes: DagNode
 edges: DagEdge
}
export async function getSymbols(params: GetSymbolsParams): Promise<PaginatedResponse<SymbolRow>> {
 const { repositoryId, symbolTypes, name, filePath, limit = 50, offset = 0 } = params
 const query: Record<string, string | number | string | undefined> = {
 limit,
 offset,
 name: name || undefined,
 file_path: filePath || undefined,
 symbol_type: symbolTypes && symbolTypes.length > 0 ? symbolTypes: undefined,
 }
 return get<PaginatedResponse<SymbolRow>>(
 `/repositories/${repositoryId}/codegraph/symbols/`,
 query,
 )
}
export async function getCallsForSymbol(
 repositoryId: string,
 symbolId: string,
 hop = 1,
 limit = 50,
): Promise<DagData> {
 return get<DagData>(
 `/repositories/${repositoryId}/codegraph/symbols/${symbolId}/calls/`,
 { max_per_hop: limit, max_total: hop === 2 ? 50: limit * 2 },
 )
}
export async function getImports(
 repositoryId: string,
 params: Omit<GetImportsParams, 'repositoryId'> = {},
): Promise<PaginatedResponse<ImportEdgeRow>> {
 const { sourceFile, limit = 50, offset = 0 } = params
 return get<PaginatedResponse<ImportEdgeRow>>(
 `/repositories/${repositoryId}/codegraph/imports/`,
 { limit, offset, source_file: sourceFile || undefined },
 )
}
export async function getEndpoints(
 repositoryId: string,
 params: Omit<GetEndpointsParams, 'repositoryId'> = {},
): Promise<PaginatedResponse<EndpointRow>> {
 const { limit = 50, offset = 0 } = params
 return get<PaginatedResponse<EndpointRow>>(
 `/repositories/${repositoryId}/codegraph/endpoints/`,
 { limit, offset },
 )
}
export async function triggerCodegraphIndex(repositoryId: string): Promise<{ message: string }> {
 return post<{ message: string }>(`/repositories/${repositoryId}/codegraph/index/`)
}
// ============================================================================
// Playground Search
// ============================================================================
export interface PlaygroundSearchParams {
 query: string
 repositoryIds?: string
 maxTokens?: number
}
export interface LayerResult {
 layer: string
 status: string
 result_count: number
 items: unknown
 error: string | null
 extra: unknown | null
}
export interface PlaygroundSearchResponse {
 query: string
 repository_ids: string
 layers: LayerResult
 final_context: string
 total_tokens: number
}
export async function playgroundSearch(
 params: PlaygroundSearchParams,
): Promise<PlaygroundSearchResponse> {
 const body: Record<string, unknown> = { query: params.query }
 if (params.repositoryIds && params.repositoryIds.length > 0)
 body.repository_ids = params.repositoryIds
 if (params.maxTokens !== undefined)
 body.max_tokens = params.maxTokens
 return post<PlaygroundSearchResponse>('/codegraph/playground/search/', body)
}
