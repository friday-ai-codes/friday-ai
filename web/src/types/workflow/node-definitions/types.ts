/**
 * 统一 NodeDefinition 契约类型
 *
 * 前后端共享的单一 source of truth。
 * 前端直接 import，后端通过构建脚本生成 JSON 消费。
 */
import type { Component } from 'vue'
import type { ZodSchema } from 'zod'

// ============================================================================
// UiSchema 类型
// ============================================================================

/** 支持的表单 widget 类型 */
export type UiWidget = 'text' | 'textarea' | 'select' | 'number' | 'boolean' | 'json-editor'

/** 条件显隐运算符 */
export type UiConditionOperator = 'eq' | 'ne' | 'in' | 'not_in'

/** 字段条件显隐 */
export interface UiVisibleIf {
  field: string
  operator: UiConditionOperator
  value: unknown
}

/** 单个字段的 UI 渲染提示 */
export interface UiSchemaField {
  /** 表单 widget 类型 */
  widget?: UiWidget
  /** 输入占位文本 */
  placeholder?: string
  /** 字段帮助文本 */
  help?: string
  /** 条件显隐规则 */
  visible_if?: UiVisibleIf
}

/** 字段分组 */
export interface UiSchemaGroup {
  /** 分组唯一标识 */
  key: string
  /** 分组显示标题 */
  label: string
  /** 分组内的字段 key 列表（按显示顺序） */
  fields: string[]
  /** 是否默认折叠 */
  collapsed?: boolean
}

/** 声明式 UI Schema，描述配置表单的渲染方式 */
export interface UiSchema {
  /** 字段分组（可选，无则平铺所有字段） */
  groups?: UiSchemaGroup[]
  /** 每个字段的渲染提示 */
  fields?: Record<string, UiSchemaField>
}

// ============================================================================
// 节点分类
// ============================================================================

/** 节点分类（与后端 NodeCategory 枚举一致） */
export type NodeCategory = 'trigger' | 'action' | 'control' | 'integration' | 'ai'

// ============================================================================
// NodeDefinition
// ============================================================================

/**
 * 统一的节点类型定义
 *
 * 包含后端需要的元数据（config_schema 由 Zod schema 生成）
 * 和前端渲染需要的元数据（uiSchema、configComponent）
 */
export interface NodeDefinition<T = unknown> {
  /** 节点类型标识（唯一） */
  nodeType: string
  /** 显示名称 */
  displayName: string
  /** 描述 */
  description: string
  /** 图标 (iconify class) */
  icon: string
  /** 渐变色 (Tailwind gradient classes, e.g. 'from-violet-500 to-purple-400') */
  color: string
  /** 分类 */
  category: NodeCategory
  /** Zod Schema（前端运行时校验 + 构建时生成 JSON Schema） */
  schema: ZodSchema<T>
  /** 默认配置 */
  defaultConfig: T
  /** 声明式 UI Schema（可选，70% 简单节点用此自动生成表单） */
  uiSchema?: UiSchema
  /** 自定义配置组件（可选，复杂节点覆盖 uiSchema） */
  configComponent?: () => Promise<{ default: Component }>
}
