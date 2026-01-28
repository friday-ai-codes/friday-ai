import { computed } from 'vue'
import {
 getDefaultConfig,
 getNodeDefinition,
 getNodesByCategory,
 hasNodeDefinition,
 validateNodeConfig,
 type NodeCategory,
 type NodeTypeDefinition,
 type NodeTypeKey,
} from '~/types/workflow'
// ============================================================================
// Composable 实现
// ============================================================================
/**
 * 节点元数据访问 composable
 *
 * @example
 * ```ts
 * const { getDefinition, byCategory } = useNodeMeta
 *
 * // 获取节点定义
 * const def = getDefinition('ai_prompt')
 * console.log(def?.icon, def?.color)
 *
 * // 按分类获取节点
 * const aiNodes = byCategory.value.ai
 * ```
 */
export function useNodeMeta {
 /** 按分类分组的节点定义 */
 const byCategory = computed( => getNodesByCategory)
 /** 获取指定分类的节点列表 */
 function getByCategory(category: NodeCategory): NodeTypeDefinition {
 return byCategory.value[category] ||
 }
 /** 检查节点类型是否有自定义配置面板 */
 function hasCustomConfig(nodeType: string): boolean {
 const def = getNodeDefinition(nodeType)
 return def?.configComponent !== undefined
 }
 /** 获取所有已注册的节点类型 */
 function getAllNodeTypes: NodeTypeKey {
 return Object.keys(getNodesByCategory).flatMap(
 category => byCategory.value[category as NodeCategory].map(def => def.nodeType),
 ) as NodeTypeKey
 }
 return {
 // 直接导出的函数
 getDefinition: getNodeDefinition,
 getDefaultConfig,
 hasNodeDefinition,
 validateConfig: validateNodeConfig,
 // 组合后的功能
 byCategory,
 getByCategory,
 hasCustomConfig,
 getAllNodeTypes,
 }
}
