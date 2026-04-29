/**
 * Built-in functions for SmartInput expression language
 *
 * These functions are rendered as FunctionNode chips in the editor
 * and evaluated by the backend execution engine.
 */
export interface BuiltInFunctionParam {
 name: string
 type?: string
 description?: string
}
export interface BuiltInFunction {
 name: string
 description: string
 params: BuiltInFunctionParam
}
/**
 * Built-in expression functions available in SmartInput
 */
export const BUILT_IN_FUNCTIONS: BuiltInFunction = [
 {
 name: 'if',
 description: '条件判断：condition 为真时返回 trueValue，否则返回 falseValue',
 params: [
 { name: 'condition', type: 'boolean', description: '条件表达式' },
 { name: 'trueValue', description: '条件为真时的返回值' },
 { name: 'falseValue', description: '条件为假时的返回值' },
 ],
 },
 {
 name: 'concat',
 description: '字符串拼接：将多个字符串连接为一个',
 params: [
 { name: '...strings', type: 'string', description: '要拼接的字符串' },
 ],
 },
 {
 name: 'len',
 description: '获取长度：返回字符串或数组的长度',
 params: [
 { name: 'value', type: 'string|array', description: '字符串或数组' },
 ],
 },
 {
 name: 'upper',
 description: '转大写：将字符串转换为大写',
 params: [
 { name: 'string', type: 'string', description: '要转换的字符串' },
 ],
 },
 {
 name: 'lower',
 description: '转小写：将字符串转换为小写',
 params: [
 { name: 'string', type: 'string', description: '要转换的字符串' },
 ],
 },
 {
 name: 'trim',
 description: '去除空白：去除字符串首尾的空白字符',
 params: [
 { name: 'string', type: 'string', description: '要处理的字符串' },
 ],
 },
 {
 name: 'defaultIfEmpty',
 description: '空值默认值：value 为空时返回 default',
 params: [
 { name: 'value', description: '要检查的值' },
 { name: 'default', description: '默认值' },
 ],
 },
]
