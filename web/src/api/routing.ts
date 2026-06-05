/**
 * ：路由决策手动微调 API client。
 *
 * 与后端 `POST /api/chat/routing-traces/<uuid>/override/` 对接。
 */

import type { ManualOverrideRequest, ManualOverrideResponse } from '~/types/routing'
import { post } from '~/api/client'

export async function postManualOverride(
  traceId: string,
  payload: ManualOverrideRequest,
): Promise<ManualOverrideResponse> {
  return post<ManualOverrideResponse>(
    `/chat/routing-traces/${traceId}/override/`,
    payload,
  )
}
