<script setup lang="ts">
import { useHead } from '@vueuse/head'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '~/components/ui/tabs'
import PageContainer from '~/components/layout/PageContainer.vue'
import RunnerGrid from '~/components/runners/RunnerGrid.vue'
import TokenTable from '~/components/runners/TokenTable.vue'
useHead({ title: 'Runner 管理 - Friday AI' })
const activeTab = ref('runners')
// 断线横幅：断开超过 10 秒才显示，避免短暂断线闪烁
const { status } = useRunnerMonitor
const disconnectedTooLong = ref(false)
let disconnectTimer: ReturnType<typeof setTimeout> | undefined
watch(status, (val) => {
 if (val === 'connected') {
 disconnectedTooLong.value = false
 if (disconnectTimer) {
 clearTimeout(disconnectTimer)
 disconnectTimer = undefined
 }
 }
 else if (!disconnectTimer) {
 disconnectTimer = setTimeout( => {
 disconnectedTooLong.value = true
 disconnectTimer = undefined
 }, 10_000)
 }
})
onUnmounted( => {
 if (disconnectTimer) clearTimeout(disconnectTimer)
})
</script>
<template>
 <PageContainer>
 <div class="space-y-1">
 <div class="flex items-center gap-3">
 <div class=" rounded-xl bg-gradient-to-br from-violet-500/20 to-purple-500/10 flex items-center justify-center">
 <span class="icon-[lucide--server] text-2xl text-violet-500" />
 </div>
 <h1 class="text-2xl font-bold">Runner 管理</h1>
 </div>
 <p class="text-muted-foreground ml-12">管理和监控您的 Runner 实例</p>
 </div>
 <Transition enter-active-class="transition-all duration-300" enter-from-class="opacity-0 -translate-y-2" enter-to-class="opacity-100 translate-y-0" leave-active-class="transition-all duration-200" leave-from-class="opacity-100" leave-to-class="opacity-0">
 <div v-if="disconnectedTooLong" class="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-700 dark:text-amber-400 text-sm">
 <span class="icon-[lucide--wifi-off] text-base" />
 <span>连接已断开，正在重连...</span>
 <span v-if="status === 'disconnected'" class="ml-auto text-xs text-muted-foreground">无法连接，请刷新页面</span>
 </div>
 </Transition>
 <Tabs v-model="activeTab">
 <TabsList>
 <TabsTrigger value="runners">
 <span class="icon-[lucide--server] mr-1.5" />
 Runner 列表
 </TabsTrigger>
 <TabsTrigger value="tokens">
 <span class="icon-[lucide--key-round] mr-1.5" />
 注册令牌
 </TabsTrigger>
 </TabsList>
 <TabsContent value="runners">
 <RunnerGrid @switch-to-tokens="activeTab = 'tokens'" />
 </TabsContent>
 <TabsContent value="tokens">
 <TokenTable />
 </TabsContent>
 </Tabs>
 </PageContainer>
</template>
