<script setup lang="ts">
/**
 * Provider 凭证列表表格（Phase + work item §I-3）
 *
 * 6 列:Provider(图标+type) / 凭证名称(含 api_key_last4) / 作用域 badge /
 * 健康 badge(ProviderHealthBadge) / 启用 Switch / 操作菜单 DropdownMenu
 *
 * 交互:
 * - 禁用行(is_active=false)整行 opacity-60 视觉降级(work item §I-3)
 * - 响应式:"作用域"列在 <768px 隐藏(hidden md:table-cell)
 * - 空态:colspan=6 单元格提示"暂无凭证,点击新建凭证开始"
 * - ProviderHealthBadge @test 转发为 emit('testConnection', c)
 *
 * 轻量实现:用原生 <table> + v-for,未引入 @tanstack/vue-table
 * (Plan 集成时按需升级排序/过滤/分页)。
 */
import type { ProviderCredentialDto } from '~/types/providerCredential'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import {
 DropdownMenu,
 DropdownMenuContent,
 DropdownMenuItem,
 DropdownMenuTrigger,
} from '~/components/ui/dropdown-menu'
import { Switch } from '~/components/ui/switch'
import ProviderHealthBadge from './ProviderHealthBadge.vue'
interface Props {
 credentials: ProviderCredentialDto
}
defineProps<Props>
const emit = defineEmits<{
 (e: 'edit', c: ProviderCredentialDto): void
 (e: 'delete', c: ProviderCredentialDto): void
 (e: 'toggleActive', c: ProviderCredentialDto): void
 (e: 'testConnection', c: ProviderCredentialDto): void
 (e: 'refreshModels', c: ProviderCredentialDto): void
}>
function iconFor(providerType: string): string {
 const map: Record<string, string> = {
 anthropic: 'icon-[simple-icons--anthropic]',
 openai_chat: 'icon-[simple-icons--openai]',
 openai_responses: 'icon-[simple-icons--openai]',
 gemini: 'icon-[simple-icons--googlegemini]',
 ollama: 'icon-[lucide--cpu]',
 }
 return map[providerType] ?? 'icon-[lucide--key-round]'
}
</script>
<template>
 <div class="overflow-x-auto">
 <table class="w-full text-sm">
 <thead class="border-b text-xs text-muted-foreground">
 <tr>
 <th class="px-4 py-2 text-left font-normal">
 Provider
 </th>
 <th class="px-4 py-2 text-left font-normal">
 凭证名称
 </th>
 <th class="hidden md:table-cell px-4 py-2 text-left font-normal">
 作用域
 </th>
 <th class="px-4 py-2 text-left font-normal">
 健康
 </th>
 <th class="px-4 py-2 text-left font-normal">
 启用
 </th>
 <th class="px-4 py-2 text-right font-normal">
 操作
 </th>
 </tr>
 </thead>
 <tbody>
 <tr
 v-for="c in credentials":key="c.id"
 class="border-b hover:bg-muted/50":class="{ 'opacity-60': !c.is_active }"
 >
 <td class="px-4 py-3">
 <div class="flex items-center gap-2">
 <span class="w-4 ":class="[iconFor(c.provider_type)]" aria-hidden="true" />
 <span class="text-xs font-normal">{{ c.provider_type }}</span>
 </div>
 </td>
 <td class="px-4 py-3">
 <span class="text-foreground">{{ c.name }}</span>
 <span class="ml-2 font-mono text-xs text-muted-foreground">{{ c.api_key_last4 }}</span>
 </td>
 <td class="hidden md:table-cell px-4 py-3">
 <Badge:variant="c.scope === 'system' ? 'default': 'outline'">
 <span:class="c.scope === 'system' ? 'icon-[lucide--globe]': 'icon-[lucide--folder-lock]'"
 class="w-3 mr-1"
 aria-hidden="true"
 />
 <span class="text-xs font-normal">
 {{ c.scope === 'system' ? '系统默认': '仅本项目' }}
 </span>
 </Badge>
 </td>
 <td class="px-4 py-3">
 <ProviderHealthBadge:status="c.last_health_check_status":last-error="c.last_health_check_error":last-checked-at="c.last_health_check_at"
 @test="emit('testConnection', c)"
 />
 </td>
 <td class="px-4 py-3">
 <Switch:model-value="c.is_active":aria-label="`启用 ${c.name}`"
 @update:model-value="emit('toggleActive', c)"
 />
 </td>
 <td class="px-4 py-3 text-right">
 <DropdownMenu>
 <DropdownMenuTrigger as-child>
 <Button
 variant="ghost"
 size="icon":aria-label="`${c.name} 操作菜单`"
 >
 <span class="icon-[lucide--more-horizontal] w-4 " aria-hidden="true" />
 </Button>
 </DropdownMenuTrigger>
 <DropdownMenuContent>
 <DropdownMenuItem @click="emit('edit', c)">
 编辑
 </DropdownMenuItem>
 <DropdownMenuItem @click="emit('refreshModels', c)">
 刷新模型清单
 </DropdownMenuItem>
 <DropdownMenuItem
 class="text-destructive"
 @click="emit('delete', c)"
 >
 删除凭证
 </DropdownMenuItem>
 </DropdownMenuContent>
 </DropdownMenu>
 </td>
 </tr>
 <tr v-if="credentials.length === 0">
 <td
 colspan="6"
 class="px-4 py-12 text-center text-sm text-muted-foreground"
 >
 暂无凭证,点击"新建凭证"开始
 </td>
 </tr>
 </tbody>
 </table>
 </div>
</template>
