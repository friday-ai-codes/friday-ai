<script setup lang="ts">
import type { RegistrationToken } from '~/types'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '~/components/ui/table'
import { Badge } from '~/components/ui/badge'
import { Button } from '~/components/ui/button'
import CreateTokenModal from './CreateTokenModal.vue'
const runnersStore = useRunnersStore
const { success, error: showError } = useToast
const loading = ref(true)
onMounted(async => {
 try { await runnersStore.fetchTokens }
 catch (e) { showError('加载失败', e instanceof Error ? e.message: '无法获取令牌列表') }
 finally { loading.value = false }
})
const createModalOpen = ref(false)
const deleteDialogOpen = ref(false)
const tokenToDelete = ref<{ id: string, description: string } | null>(null)
const deleting = ref(false)
function confirmDelete(token: RegistrationToken) {
 tokenToDelete.value = { id: token.id, description: token.description || '未命名令牌' }
 deleteDialogOpen.value = true
}
async function handleDelete {
 if (!tokenToDelete.value) return
 deleting.value = true
 try {
 await runnersStore.removeToken(tokenToDelete.value.id)
 success('删除成功', `令牌「${tokenToDelete.value.description}」已删除`)
 deleteDialogOpen.value = false
 }
 catch (e) { showError('删除失败', e instanceof Error ? e.message: '无法删除令牌') }
 finally { deleting.value = false }
}
function statusOf(token: RegistrationToken) {
 if (token.is_used) return { label: '已使用', class: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400' }
 if (!token.is_valid) return { label: '已过期', class: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400' }
 return { label: '有效', class: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400' }
}
function formatDate(dateStr: string) {
 return new Date(dateStr).toLocaleString('zh-CN')
}
</script>
<template>
 <div class="space-y-4">
 <!-- 顶部操作栏 -->
 <div class="flex justify-end">
 <Button class="group relative overflow-hidden" @click="createModalOpen = true">
 <span class="absolute inset-0 bg-gradient-to-r from-white/0 via-white/20 to-white/0 translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-700" />
 <span class="icon-[lucide--plus] mr-1.5" />
 创建令牌
 </Button>
 </div>
 <!-- 加载状态 -->
 <LoadingState v-if="loading" variant="skeleton":count="3" />
 <!-- 空状态 -->
 <div v-else-if="runnersStore.tokens.length === 0" class="flex flex-col items-center justify-center py-16 text-center">
 <span class="icon-[lucide--key-round] text-4xl text-muted-foreground/30 mb-4" />
 <p class="text-muted-foreground">暂无注册令牌</p>
 </div>
 <!-- 令牌表格 -->
 <div v-else class="rounded-2xl border border-border/50 bg-card/80 backdrop-blur-sm overflow-hidden">
 <Table>
 <TableHeader>
 <TableRow>
 <TableHead>描述</TableHead>
 <TableHead>作用域</TableHead>
 <TableHead>状态</TableHead>
 <TableHead>过期时间</TableHead>
 <TableHead>创建时间</TableHead>
 <TableHead class="w-16">操作</TableHead>
 </TableRow>
 </TableHeader>
 <TableBody>
 <TableRow v-for="token in runnersStore.tokens":key="token.id">
 <TableCell>{{ token.description || '-' }}</TableCell>
 <TableCell><Badge variant="secondary">{{ token.scope === 'global' ? '全局': '项目' }}</Badge></TableCell>
 <TableCell><Badge variant="secondary":class="statusOf(token).class">{{ statusOf(token).label }}</Badge></TableCell>
 <!-- TOKEN_TABLE_CONTINUE -->
 <TableCell>{{ formatDate(token.expires_at) }}</TableCell>
 <TableCell>{{ formatDate(token.created_at) }}</TableCell>
 <TableCell>
 <Button variant="ghost" size="icon" class=" w-8 hover:bg-destructive/10 hover:text-destructive" @click="confirmDelete(token)">
 <span class="icon-[lucide--trash-2] text-sm" />
 </Button>
 </TableCell>
 </TableRow>
 </TableBody>
 </Table>
 </div>
 <!-- 创建令牌弹窗 -->
 <CreateTokenModal v-model:open="createModalOpen" />
 <!-- 删除确认对话框 -->
 <ConfirmDialog
 v-model:open="deleteDialogOpen"
 title="删除令牌":description="`确定要删除令牌「${tokenToDelete?.description}」吗？此操作不可撤销。`"
 confirm-text="删除"
 variant="destructive":loading="deleting"
 @confirm="handleDelete"
 />
 </div>
</template>
