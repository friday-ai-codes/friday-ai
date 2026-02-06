<script setup lang="ts">
import X6BaseNode from './X6BaseNode.vue'
/**
 * X6ActionNode - Action node component with purple gradient styling.
 *
 * Visual identity per CONTEXT.md:
 * - Purple gradient icon background (from-violet-500/20 to-purple-400/10)
 * - Vertical layout (icon on top, text below)
 * - Zap icon for action operations
 */
</script>
<template>
 <X6BaseNode v-slot="{ label, description }">
 <div class="flex flex-col items-center gap-2 ">
 <!-- Icon with purple gradient background -->
 <div class=" rounded-xl bg-gradient-to-br from-violet-500/20 to-purple-400/10">
 <span class="icon-[lucide--zap] text-xl text-violet-500" />
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
