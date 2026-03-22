<script setup lang="ts">
/**
 * DownstreamVarWarning -- 下游变量缺失警告
 *
 * 在编辑/Mock 模式下，提示用户编辑后的数据缺少下游节点依赖的变量键。
 * 警告仅提示，不阻止放行/提交操作。
 */
defineProps<{
 warnings: Array<{ nodeName: string, missingKeys: string }>
}>
</script>
<template>
 <div
 v-if="warnings.length > 0"
 class="bg-yellow-500/10 border border-yellow-500/30 text-yellow-200 rounded-lg space-y-1"
 >
 <div
 v-for="(warning, index) in warnings":key="index"
 class="text-xs flex items-start gap-1.5"
 >
 <span class="icon-[lucide--alert-triangle] w-3.5 .5 shrink-0 mt-0.5" />
 <span>
 下游节点「{{ warning.nodeName }}」依赖的变量 {{ warning.missingKeys.join(', ') }} 缺失
 </span>
 </div>
 </div>
</template>
