<script setup lang="ts">
/**
 * 飞书文档摘要卡片 -- 在对话消息流中展示文档读取结果。
 *
 * 两种状态：
 * - type="summary": 成功读取，显示标题+字数+预览（per, ）
 * - type="error": 读取失败，按 error_type 区分展示（per,, ）
 */
const props = defineProps<{
 type: 'summary' | 'error' | 'loading'
 // 成功状态
 title?: string
 wordCount?: number
 preview?: string
 truncated?: boolean
 truncatedLength?: number
 // 错误状态
 errorType?: 'permission_denied' | 'not_found' | 'not_configured' | 'unknown'
 errorMessage?: string
}>
const emit = defineEmits<{
 retry:
}>
const showAuthGuide = ref(false)
</script>
<template>
 <!-- Loading 状态 -->
 <div v-if="type === 'loading'" class="card mt-2">
 <div class="px-4 py-3 flex items-center gap-2">
 <span class="icon-[lucide--loader-2] text-muted-foreground animate-spin" aria-label="加载中" />
 <span class="text-sm text-muted-foreground">正在读取飞书文档...</span>
 </div>
 </div>
 <!-- 成功状态 -->
 <div v-else-if="type === 'summary'" class="card mt-2 animate-fade-in">
 <div class="px-4 py-3 border-b border-border/50 flex items-center gap-2">
 <span class="icon-[lucide--file-text] text-primary" aria-label="飞书文档" />
 <span class="text-sm font-semibold">{{ title || '飞书文档' }}</span>
 <span class="text-xs text-muted-foreground ml-auto">{{ wordCount }} 字</span>
 </div>
 <div class=" text-sm text-muted-foreground">
 <p class="line-clamp-3 whitespace-pre-line">{{ preview }}</p>
 <p v-if="truncated" class="mt-2 text-xs text-amber-600">
 文档较长，已截取前 {{ truncatedLength }} 字
 </p>
 </div>
 </div>
 <!-- 权限不足 -->
 <div v-else-if="type === 'error' && errorType === 'permission_denied'" class="card mt-2 border-amber-200 animate-fade-in">
 <div class="px-4 py-3 flex items-center gap-2">
 <span class="icon-[lucide--lock] text-amber-500" aria-label="无权限" />
 <span class="text-sm font-medium">无法访问此文档</span>
 </div>
 <div class="px-4 pb-3">
 <button
 class="text-xs text-primary cursor-pointer"
 role="button":aria-expanded="showAuthGuide"
 @click="showAuthGuide = !showAuthGuide"
 >
 如何授权?
 </button>
 <div v-if="showAuthGuide" class="mt-2 text-xs text-muted-foreground">
 请在飞书中将此文档分享给应用「Friday AI」，授予阅读权限后重试。
 </div>
 </div>
 </div>
 <!-- 文档不存在 -->
 <div v-else-if="type === 'error' && errorType === 'not_found'" class="card mt-2 animate-fade-in">
 <div class="px-4 py-3 flex items-center gap-2">
 <span class="icon-[lucide--file-x] text-muted-foreground" />
 <span class="text-sm font-medium">文档不存在</span>
 </div>
 <div class="px-4 pb-3 text-xs text-muted-foreground">
 请检查链接是否正确，文档可能已被删除或移动。
 </div>
 </div>
 <!-- 未配置飞书 -->
 <div v-else-if="type === 'error' && errorType === 'not_configured'" class="card mt-2 animate-fade-in">
 <div class="px-4 py-3 flex items-center gap-2">
 <span class="icon-[lucide--settings] text-muted-foreground" />
 <span class="text-sm font-medium">飞书应用未配置</span>
 </div>
 <div class="px-4 pb-3 text-xs text-muted-foreground">
 当前项目尚未配置飞书应用凭证，请在项目设置中添加飞书 App ID 和 App Secret。
 </div>
 </div>
 <!-- 其他错误 -->
 <div v-else-if="type === 'error'" class="card mt-2 animate-fade-in">
 <div class="px-4 py-3 flex items-center gap-2">
 <span class="icon-[lucide--alert-circle] text-destructive" />
 <span class="text-sm font-medium">读取文档失败</span>
 </div>
 <div class="px-4 pb-3 flex items-center justify-between">
 <span class="text-xs text-muted-foreground">{{ errorMessage }}</span>
 <button
 class="text-xs text-primary cursor-pointer"
 role="button"
 tabindex="0"
 @click="emit('retry')"
 >
 重试
 </button>
 </div>
 </div>
</template>
