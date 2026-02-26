<script setup lang="ts">
/**
 * WorkflowCanvas - Vue Flow 画布基础骨架
 *
 * Phase: 渲染空画布 + 点阵背景。
 * Phase: 接入真实节点/边数据。
 */
import { VueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { nodeTypes } from './nodes'
</script>
<template>
 <div class="h-full w-full bg-background">
 <VueFlow:nodes="":edges="":node-types="nodeTypes":fit-view-on-init="true"
 >
 <Background
 variant="dots":gap="35":size="1.5"
 color="#3b82f620"
 />
 </VueFlow>
 </div>
</template>
