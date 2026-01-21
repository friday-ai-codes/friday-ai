<script setup lang="ts">
import { Card, CardContent, CardHeader, CardTitle } from '~/components/ui/card'
import { Button } from '~/components/ui/button'
const props = defineProps<{
 prdUrl: string
 description: string
 techDocUrl: string
}>
const { success } = useToast
// 复制到剪贴板
async function copyToClipboard(text: string, label: string) {
 try {
 await navigator.clipboard.writeText(text)
 success('已复制', `${label}已复制到剪贴板`)
 }
 catch {
 // Fallback for older browsers
 const textarea = document.createElement('textarea')
 textarea.value = text
 document.body.appendChild(textarea)
 textarea.select
 document.execCommand('copy')
 document.body.removeChild(textarea)
 success('已复制', `${label}已复制到剪贴板`)
 }
}
// 检查是否为有效链接
function isValidUrl(url: string): boolean {
 if (!url) return false
 try {
 new URL(url)
 return true
 }
 catch {
 return false
 }
}
</script>
<template>
 <Card class="border-primary/20 bg-primary/5">
 <CardHeader class="pb-3">
 <CardTitle class="flex items-center gap-2 text-base">
 <span class="icon-[lucide--star] w-4 text-primary" />
 关键字段
 </CardTitle>
 </CardHeader>
 <CardContent class="space-y-4">
 <!-- 需求文档链接 -->
 <div class="space-y-1">
 <div class="flex items-center justify-between">
 <label class="text-sm font-medium text-muted-foreground">需求文档链接</label>
 <div v-if="props.prdUrl" class="flex gap-1">
 <Button
 v-if="isValidUrl(props.prdUrl)"
 variant="ghost"
 size="sm"
 as="a":href="props.prdUrl"
 target="_blank"
 >
 <span class="icon-[lucide--external-link] .5 w-3.5" />
 </Button>
 <Button
 variant="ghost"
 size="sm"
 @click="copyToClipboard(props.prdUrl, '需求文档链接')"
 >
 <span class="icon-[lucide--copy] .5 w-3.5" />
 </Button>
 </div>
 </div>
 <p v-if="props.prdUrl" class="break-all text-sm">
 <a
 v-if="isValidUrl(props.prdUrl)":href="props.prdUrl"
 target="_blank"
 class="text-primary hover:underline"
 >
 {{ props.prdUrl }}
 </a>
 <span v-else>{{ props.prdUrl }}</span>
 </p>
 <p v-else class="text-sm text-muted-foreground">
 -
 </p>
 </div>
 <!-- 需求描述 -->
 <div class="space-y-1">
 <label class="text-sm font-medium text-muted-foreground">需求描述</label>
 <p v-if="props.description" class="whitespace-pre-wrap text-sm">
 {{ props.description }}
 </p>
 <p v-else class="text-sm text-muted-foreground">
 -
 </p>
 </div>
 <!-- 技术方案文档链接 -->
 <div class="space-y-1">
 <div class="flex items-center justify-between">
 <label class="text-sm font-medium text-muted-foreground">技术方案文档链接</label>
 <div v-if="props.techDocUrl" class="flex gap-1">
 <Button
 v-if="isValidUrl(props.techDocUrl)"
 variant="ghost"
 size="sm"
 as="a":href="props.techDocUrl"
 target="_blank"
 >
 <span class="icon-[lucide--external-link] .5 w-3.5" />
 </Button>
 <Button
 variant="ghost"
 size="sm"
 @click="copyToClipboard(props.techDocUrl, '技术方案文档链接')"
 >
 <span class="icon-[lucide--copy] .5 w-3.5" />
 </Button>
 </div>
 </div>
 <p v-if="props.techDocUrl" class="break-all text-sm">
 <a
 v-if="isValidUrl(props.techDocUrl)":href="props.techDocUrl"
 target="_blank"
 class="text-primary hover:underline"
 >
 {{ props.techDocUrl }}
 </a>
 <span v-else>{{ props.techDocUrl }}</span>
 </p>
 <p v-else class="text-sm text-muted-foreground">
 -
 </p>
 </div>
 </CardContent>
 </Card>
</template>
