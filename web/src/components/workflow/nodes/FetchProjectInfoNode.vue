<script setup lang="ts">
import type { NodeProps } from '@vue-flow/core'
import { FolderSearch } from 'lucide-vue-next'
import BaseNodeComponent from './BaseNodeComponent.vue'
const props = defineProps<NodeProps>
function getIncludedItems: string {
 const items: string =
 const config = props.data?.config
 if (config?.include_repositories)
 items.push('仓库')
 if (config?.include_feishu_config)
 items.push('飞书')
 if (config?.include_claude_config)
 items.push('Claude')
 if (config?.include_webhook_token)
 items.push('Token')
 return items
}
function hasIdentifier: boolean {
 return !!props.data?.config?.project_identifier
}
</script>
<template>
 <BaseNodeComponent
 v-bind="props":icon="FolderSearch"
 badge="数据"
 badge-color="orange"
 theme="action"
 >
 <div class="space-y-1">
 <!-- 显示配置状态 -->
 <div class="flex items-center gap-1 flex-wrap">
 <div
 v-if="hasIdentifier"
 class="font-mono text-[10px] bg-emerald-100 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400 px-1.5 py-0.5 rounded"
 >
 已配置
 </div>
 <div
 v-else
 class="font-mono text-[10px] bg-amber-100 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400 px-1.5 py-0.5 rounded"
 >
 未配置
 </div>
 <div
 v-for="item in getIncludedItems":key="item"
 class="text-[10px] bg-secondary px-1.5 py-0.5 rounded"
 >
 {{ item }}
 </div>
 </div>
 <!-- 标识符预览 -->
 <p v-if="hasIdentifier" class="text-[10px] text-muted-foreground truncate max-w-[180px]">
 {{ props.data?.config?.project_identifier }}
 </p>
 <p v-else class="text-[10px] text-muted-foreground">
 {{ props.data?.description || '获取项目关联的配置信息' }}
 </p>
 </div>
 </BaseNodeComponent>
</template>
