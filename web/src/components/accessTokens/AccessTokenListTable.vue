<script setup lang="ts">
/**
 * Access Token 列表表格（Phase）
 *
 * 设计基线仿 ProviderCredentialListTable：glassmorphism 圆角描边容器、
 * uppercase 列头、行 hover、空态 row。
 *
 * 安全：列表仅渲染元数据字段（name / 指纹前缀 / 时间 / 状态），
 * 绝不渲染明文（DTO 本身无此数据，）。
 */
import type { AccessTokenDto } from '~/types/accessToken'
import { Button } from '~/components/ui/button'
defineProps<{
 tokens: AccessTokenDto
}>
const emit = defineEmits<{
 (e: 'revoke', t: AccessTokenDto): void
}>
/** 时间字符串格式化为本地可读；空值降级提示。 */
function formatDate(value: string | null, fallback: string): string {
 if (!value)
 return fallback
 return new Date(value).toLocaleString('zh-CN')
}
interface StatusMeta {
 label: string
 class: string
}
/** 计算状态徽标：已吊销（红）/ 有效（绿）/ 已过期（灰）。 */
function statusOf(t: AccessTokenDto): StatusMeta {
 if (t.revoked_at)
 return { label: '已吊销', class: 'bg-destructive/10 text-destructive' }
 if (t.is_valid)
 return { label: '有效', class: 'bg-green-500/10 text-green-600 dark:text-green-400' }
 return { label: '已过期', class: 'bg-muted text-muted-foreground' }
}
</script>
<template>
 <div class="overflow-hidden rounded-xl border border-border/60">
 <table class="w-full border-collapse text-sm">
 <thead>
 <tr class="border-b border-border/60 bg-muted/30">
 <th class="px-4 py-2.5 text-left text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
 名称
 </th>
 <th class="px-4 py-2.5 text-left text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
 指纹
 </th>
 <th class="hidden md:table-cell px-4 py-2.5 text-left text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
 创建时间
 </th>
 <th class="hidden lg:table-cell px-4 py-2.5 text-left text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
 过期时间
 </th>
 <th class="px-4 py-2.5 text-left text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
 状态
 </th>
 <th class="hidden lg:table-cell px-4 py-2.5 text-left text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
 最近使用
 </th>
 <th class="px-4 py-2.5 text-right text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
 操作
 </th>
 </tr>
 </thead>
 <tbody class="divide-y divide-border/50">
 <tr
 v-for="t in tokens":key="t.id"
 class="group transition-colors hover:bg-muted/40":class="{ 'opacity-55': !!t.revoked_at }"
 >
 <!-- 名称 -->
 <td class="px-4 py-3.5">
 <span class="truncate font-medium text-foreground">{{ t.name }}</span>
 </td>
 <!-- 指纹（明文前缀，非完整明文） -->
 <td class="px-4 py-3.5">
 <span class="font-mono text-xs text-muted-foreground">{{ t.token_prefix }}</span>
 </td>
 <!-- 创建时间 -->
 <td class="hidden md:table-cell px-4 py-3.5 text-muted-foreground">
 {{ formatDate(t.created_at, '—') }}
 </td>
 <!-- 过期时间：null → 永不过期 chip -->
 <td class="hidden lg:table-cell px-4 py-3.5">
 <span
 v-if="!t.expires_at"
 class="inline-flex items-center gap-1 whitespace-nowrap rounded-md border border-border/60 bg-muted/40 px-2 py-0.5 text-xs text-muted-foreground"
 >
 <span class="icon-[lucide--infinity] w-3" aria-hidden="true" />
 永不过期
 </span>
 <span v-else class="text-muted-foreground">{{ formatDate(t.expires_at, '—') }}</span>
 </td>
 <!-- 状态徽标 -->
 <td class="px-4 py-3.5">
 <span
 class="inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium":class="statusOf(t).class"
 >
 {{ statusOf(t).label }}
 </span>
 </td>
 <!-- 最近使用 -->
 <td class="hidden lg:table-cell px-4 py-3.5 text-muted-foreground">
 {{ formatDate(t.last_used_at, '从未') }}
 </td>
 <!-- 操作：仅未吊销时可吊销 -->
 <td class="px-4 py-3.5 text-right">
 <Button
 v-if="!t.revoked_at"
 variant="ghost"
 size="sm"
 class="text-destructive hover:text-destructive":aria-label="`吊销 ${t.name}`"
 @click="emit('revoke', t)"
 >
 <span class="icon-[lucide--ban] mr-1.5 .5 w-3.5" aria-hidden="true" />
 吊销
 </Button>
 </td>
 </tr>
 <tr v-if="tokens.length === 0">
 <td
 colspan="7"
 class="px-4 py-12 text-center text-sm text-muted-foreground"
 >
 暂无 Access Token，点击右上角新建
 </td>
 </tr>
 </tbody>
 </table>
 </div>
</template>
