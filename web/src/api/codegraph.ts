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
 path: string
 method: string
 handler_name: string
 file_path: string
 line_start: number
 line_end: number
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
 id: string
 data: SymbolRow
}
export interface DagEdge {
 id: string
 source: string
 target: string
 call_type: 'DIRECT_CALL' | 'METHOD_CALL' | 'ATTRIBUTE_ACCESS' | 'INHERITANCE'
 label?: string
}
export interface DagData {
 nodes: DagNode
 edges: DagEdge
}
export async function getSymbols(params: GetSymbolsParams): Promise<PaginatedResponse<SymbolRow>> {
 const { repositoryId, symbolTypes, name, filePath, limit = 50, offset = 0 } = params
 const qs = new URLSearchParams
 qs.set('limit', String(limit))
 qs.set('offset', String(offset))
 if (name)
 qs.set('name', name)
 if (filePath)
 qs.set('file_path', filePath)
 if (symbolTypes && symbolTypes.length > 0) {
 for (const t of symbolTypes)
 qs.append('symbol_type', t)
 }
 return get<PaginatedResponse<SymbolRow>>(
 `/repositories/${repositoryId}/codegraph/symbols/?${qs.toString}`,
 )
}
export async function getCallsForSymbol(
 repositoryId: string,
 symbolId: string,
 hop = 1,
 limit = 50,
): Promise<DagData> {
 const qs = new URLSearchParams({ hop: String(hop), limit: String(limit) })
 return get<DagData>(
 `/repositories/${repositoryId}/codegraph/calls/${symbolId}/?${qs.toString}`,
 )
}
export async function getImports(
 repositoryId: string,
 params: Omit<GetImportsParams, 'repositoryId'> = {},
): Promise<PaginatedResponse<ImportEdgeRow>> {
 const { sourceFile, limit = 50, offset = 0 } = params
 const qs = new URLSearchParams({ limit: String(limit), offset: String(offset) })
 if (sourceFile)
 qs.set('source_file', sourceFile)
 return get<PaginatedResponse<ImportEdgeRow>>(
 `/repositories/${repositoryId}/codegraph/imports/?${qs.toString}`,
 )
}
export async function getEndpoints(
 repositoryId: string,
 params: Omit<GetEndpointsParams, 'repositoryId'> = {},
): Promise<PaginatedResponse<EndpointRow>> {
 const { limit = 50, offset = 0 } = params
 const qs = new URLSearchParams({ limit: String(limit), offset: String(offset) })
 return get<PaginatedResponse<EndpointRow>>(
 `/repositories/${repositoryId}/codegraph/endpoints/?${qs.toString}`,
 )
}
export async function triggerCodegraphIndex(repositoryId: string): Promise<{ message: string }> {
 return post<{ message: string }>(`/repositories/${repositoryId}/codegraph/index/`)
}
