import { describe, expect, it } from 'vitest'
import { BUILT_IN_FUNCTIONS } from '../smart-input/extensions/FunctionSuggestion'
/**
 * 内置表达式函数定义结构验证
 *
 * 不 mock 任何依赖，纯数据校验：函数数量、字段完整性、参数数量与类型签名。
 * 每条用例针对一个函数或一个属性维度，定位失败时更精确。
 */
describe('BUILT_IN_FUNCTIONS', => {
 it('包含 7 个内置函数', => {
 expect(BUILT_IN_FUNCTIONS).toHaveLength(7)
 })
 it('每个函数都有 name / description / params 字段', => {
 for (const fn of BUILT_IN_FUNCTIONS) {
 expect(typeof fn.name).toBe('string')
 expect(fn.name.length).toBeGreaterThan(0)
 expect(typeof fn.description).toBe('string')
 expect(fn.description.length).toBeGreaterThan(0)
 expect(Array.isArray(fn.params)).toBe(true)
 }
 })
 it('所有函数名互不重复', => {
 const names = BUILT_IN_FUNCTIONS.map(fn => fn.name)
 expect(new Set(names).size).toBe(names.length)
 })
 it('if 函数有 3 个参数 condition / trueValue / falseValue，condition 类型为 boolean', => {
 const fn = BUILT_IN_FUNCTIONS.find(f => f.name === 'if')
 expect(fn).toBeDefined
 expect(fn!.params).toHaveLength(3)
 expect(fn!.params.map(p => p.name)).toEqual(['condition', 'trueValue', 'falseValue'])
 expect(fn!.params[0].type).toBe('boolean')
 // trueValue / falseValue 不约束类型，验证可选性
 expect(fn!.params[1].type).toBeUndefined
 expect(fn!.params[2].type).toBeUndefined
 })
 it('concat 函数有 1 个变长参数 ...strings，type 为 string', => {
 const fn = BUILT_IN_FUNCTIONS.find(f => f.name === 'concat')
 expect(fn).toBeDefined
 expect(fn!.params).toHaveLength(1)
 expect(fn!.params[0].name).toBe('...strings')
 expect(fn!.params[0].type).toBe('string')
 })
 it('len 函数 1 个参数 value，type 为 string|array', => {
 const fn = BUILT_IN_FUNCTIONS.find(f => f.name === 'len')
 expect(fn).toBeDefined
 expect(fn!.params).toHaveLength(1)
 expect(fn!.params[0].name).toBe('value')
 expect(fn!.params[0].type).toBe('string|array')
 })
 it('upper / lower / trim 各有 1 个 string 参数', => {
 for (const name of ['upper', 'lower', 'trim'] as const) {
 const fn = BUILT_IN_FUNCTIONS.find(f => f.name === name)
 expect(fn, `function ${name} not found`).toBeDefined
 expect(fn!.params, `function ${name} params length`).toHaveLength(1)
 expect(fn!.params[0].name).toBe('string')
 expect(fn!.params[0].type).toBe('string')
 }
 })
 it('defaultIfEmpty 有 2 个参数 value / default 且不限定 type（验证 type 字段可选）', => {
 const fn = BUILT_IN_FUNCTIONS.find(f => f.name === 'defaultIfEmpty')
 expect(fn).toBeDefined
 expect(fn!.params).toHaveLength(2)
 expect(fn!.params.map(p => p.name)).toEqual(['value', 'default'])
 expect(fn!.params[0].type).toBeUndefined
 expect(fn!.params[1].type).toBeUndefined
 })
 it('每个参数都包含 name 字段', => {
 for (const fn of BUILT_IN_FUNCTIONS) {
 for (const param of fn.params) {
 expect(typeof param.name).toBe('string')
 expect(param.name.length).toBeGreaterThan(0)
 }
 }
 })
})
