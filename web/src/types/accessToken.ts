/**
 * Friday Access Token 管理 DTO（Phase）
 *
 * 与后端 server/access_tokens/serializers.py 中的 AccessTokenSerializer /
 * AccessTokenCreateSerializer 字段一一对应。
 *
 * 安全契约：列表 / 详情 DTO 永不含明文 token；明文仅在 create
 * 响应里一次性返回（见 AccessTokenCreateResult.token）。
 */
/** Read Serializer 对应的元数据 DTO（绝不含明文 / token_hash）。 */
export interface AccessTokenDto {
 id: string
 name: string
 /** 明文前 12 字符，供 UI 指纹识别（非完整明文）。 */
 token_prefix: string
 created_at: string
 /** null = 永不过期。 */
 expires_at: string | null
 /** 非 null = 已软吊销。 */
 revoked_at: string | null
 last_used_at: string | null
 /** 后端计算：未吊销且未过期。 */
 is_valid: boolean
}
/**
 * POST /api/access-tokens/ body。
 *
 * 过期语义三态：
 * - 省略 expires_at → 后端默认 90 天
 * - 显式 expires_at: null → 永不过期
 * - expires_at: ISO 字符串 → 自定义过期时间
 */
export interface AccessTokenCreatePayload {
 name: string
 expires_at?: string | null
}
/**
 * create 响应：在元数据基础上额外携带一次性明文 token。
 *
 * 明文仅此处出现一次，调用方须立即交给瞬态内存 ref 展示，绝不持久化。
 */
export interface AccessTokenCreateResult extends AccessTokenDto {
 token: string
}
