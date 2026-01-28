<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import { Download } from 'lucide-vue-next'
import BaseNodeComponent from './BaseNodeComponent.vue'
const props = defineProps<NodeProps>
// 预设字段中文映射
const fieldLabels: Record<string, string> = {
 description: '需求描述',
 prd_url: '需求文档',
 tech_doc_url: '技术方案',
 title: '标题',
 status: '状态',
}
function getFieldLabel(field: string): string {
 return fieldLabels[field] || field
}
</script>
<template>
 <BaseNodeComponent
 v-bind="props":icon="Download"
 badge="数据获取"
 badge-color="orange"
 theme="feishu"
 >
 <div class="space-y-1">
 <!-- 显示工作项 ID 配置 -->
 <div v-if="props.data?.config?.work_item_id" class="font-mono text-[10px] bg-orange-100 dark:bg-orange-900/30 text-orange-600 dark:text-orange-400 px-1.5 py-0.5 rounded inline-block">
 {{ props.data.config.work_item_id }}
 </div>
 <!-- 显示提取字段 -->
 <div v-if="props.data?.config?.extract_fields?.length" class="flex flex-wrap gap-1">
 <div
 v-for="field in props.data.config.extract_fields.slice(0, 3)":key="field"
 class="text-[10px] bg-secondary px-1.5 py-0.5 rounded"
 >
 {{ getFieldLabel(field) }}
 </div>
 <div
 v-if="props.data.config.extract_fields.length > 3"
 class="text-[10px] bg-secondary px-1.5 py-0.5 rounded"
 >
 +{{ props.data.config.extract_fields.length - 3 }}
 </div>
 </div>
 <!-- 全局参数标识 -->
 <div v-if="props.data?.config?.set_global_params" class="text-[10px] text-green-600 dark:text-green-400">
 ✓ 设为全局参数
 </div>
 <p class="line-clamp-2">
 {{ props.data?.description || '获取飞书工作项详情' }}
 </p>
 </div>
 </BaseNodeComponent>
</template>
