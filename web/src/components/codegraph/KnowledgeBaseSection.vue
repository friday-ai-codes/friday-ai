<script setup lang="ts">
import { useLocalStorage } from '@vueuse/core'
import { ref } from 'vue'
import { Button } from '~/components/ui/button'
import {
 Collapsible,
 CollapsibleContent,
} from '~/components/ui/collapsible'
import {
 Tabs,
 TabsContent,
 TabsList,
 TabsTrigger,
} from '~/components/ui/tabs'
import CallsDagTab from './CallsDagTab.vue'
import DependenciesTab from './DependenciesTab.vue'
import ImportsTab from './ImportsTab.vue'
import SymbolsTab from './SymbolsTab.vue'
const props = withDefaults(defineProps<{
 repositoryId: string
 /** 嵌入知识库 Hub 时隐藏外层 card 壳与折叠按钮 */
 embedded?: boolean
}>, {
 embedded: false,
})
// 持久化折叠状态（embedded 默认展开；独立使用时也默认展开）
const isOpen = useLocalStorage(`kbs-open-${props.repositoryId}`, true)
// 跨 Tab 共享状态
const selectedSymbolId = ref<string | null>(null)
const activeTab = ref<'symbols' | 'calls' | 'dependencies' | 'imports'>('symbols')
function toggle {
 isOpen.value = !isOpen.value
}
function handleSelectSymbol(id: string) {
 selectedSymbolId.value = id
 activeTab.value = 'calls'
}
</script>
<template>
 <div:class="embedded ? '': 'card'">
 <!-- Header：图标 + 标题 + 折叠按钮 -->
 <div
 v-if="!embedded"
 class="px-5 py-3.5 border-b border-border/50 flex items-center justify-between"
 >
 <div class="flex items-center gap-2">
 <span class="icon-[lucide--git-graph] text-primary" />
 <h3 class="text-sm font-semibold">
 代码图谱
 </h3>
 <span class="text-xs text-muted-foreground">Symbols · 调用关系 · 导入</span>
 </div>
 <Button variant="ghost" size="sm" class=" w-7 " @click="toggle">
 <span:class="isOpen ? 'icon-[lucide--chevron-up]': 'icon-[lucide--chevron-down]'"
 class="text-muted-foreground"
 />
 </Button>
 </div>
 <!-- embedded 模式：轻量标题条 -->
 <div
 v-else
 class="mb-4 flex items-center gap-2 text-xs text-muted-foreground"
 >
 <span class="icon-[lucide--git-graph] text-primary" />
 浏览 Symbols · 调用关系 DAG · 导入
 </div>
 <!-- 折叠区 + Tabs -->
 <Collapsible v-model:open="isOpen">
 <CollapsibleContent>
 <div:class="embedded ? '': ''">
 <Tabs v-model="activeTab">
 <TabsList class="mb-4">
 <TabsTrigger value="symbols">
 Symbols
 </TabsTrigger>
 <TabsTrigger value="calls">
 调用关系 DAG
 </TabsTrigger>
 <TabsTrigger value="dependencies">
 依赖关系
 </TabsTrigger>
 <TabsTrigger value="imports">
 导入
 </TabsTrigger>
 </TabsList>
 <TabsContent value="symbols">
 <SymbolsTab:repository-id="repositoryId"
 @select-symbol="handleSelectSymbol"
 />
 </TabsContent>
 <TabsContent value="calls">
 <CallsDagTab:repository-id="repositoryId":selected-symbol-id="selectedSymbolId"
 @select-symbol="handleSelectSymbol"
 />
 </TabsContent>
 <TabsContent value="dependencies">
 <DependenciesTab:repository-id="repositoryId"
 @select-symbol="handleSelectSymbol"
 />
 </TabsContent>
 <TabsContent value="imports">
 <ImportsTab:repository-id="repositoryId" />
 </TabsContent>
 </Tabs>
 </div>
 </CollapsibleContent>
 </Collapsible>
 </div>
</template>
