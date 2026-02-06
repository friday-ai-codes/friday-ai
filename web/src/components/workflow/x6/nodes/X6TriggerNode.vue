<script setup lang="ts">
import X6BaseNode from './X6BaseNode.vue'
/**
 * X6TriggerNode - Trigger node component with blue gradient styling.
 *
 * Visual identity per CONTEXT.md:
 * - Blue gradient icon background (from-blue-500/20 to-cyan-400/10)
 * - Vertical layout (icon on top, text below)
 * - Play icon for trigger actions
 */
</script>
<template>
 <X6BaseNode v-slot="{ label, description }">
 <div class="flex flex-col items-center gap-2 ">
 <!-- Icon with blue gradient background -->
 <div class=" rounded-xl bg-gradient-to-br from-blue-500/20 to-cyan-400/10">
 <span class="icon-[lucide--play] text-xl text-blue-500" />
 </div>
 <!-- Title + description (vertical stack) -->
 <div class="text-center">
 <div
 class="font-semibold text-sm truncate max-w-[200px]":title="label"
 >
 {{ label }}
 </div>
 <div
 v-if="description"
 class="text-xs text-muted-foreground truncate max-w-[200px]":title="description"
 >
 {{ description }}
 </div>
 </div>
 </div>
 </X6BaseNode>
</template>
