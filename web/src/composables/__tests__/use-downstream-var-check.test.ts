import { describe, expect, it } from 'vitest'
import {
 checkMissingKeys,
 extractNodeVarRefs,
 getDownstreamVarDeps,
} from '../useDownstreamVarCheck'
describe('extractNodeVarRefs', => {
 it('从 config JSON 中正确提取 {{nodes.SLT.result}} 中的 "result"', => {
 const config = {
 prompt: '请处理: {{nodes.SLT.result}}',
 }
 const keys = extractNodeVarRefs(config, 'SLT')
 expect(keys).toEqual(['result'])
 })
 it('多个下游节点引用同一节点不同 key，返回所有 key', => {
 const config = {
 prompt: '输入: {{nodes.ABC.title}}，内容: {{nodes.ABC.content}}',
 system: '参考: {{nodes.ABC.summary}}',
 }
 const keys = extractNodeVarRefs(config, 'ABC')
 expect(keys).toEqual(['title', 'content', 'summary'])
 })
 it('无引用时返回空数组', => {
 const config = {
 prompt: '你好世界',
 temperature: 0.7,
 }
 const keys = extractNodeVarRefs(config, 'XYZ')
 expect(keys).toEqual
 })
 it('去重重复引用的 key', => {
 const config = {
 prompt: '{{nodes.N1.result}} 和 {{nodes.N1.result}}',
 }
 const keys = extractNodeVarRefs(config, 'N1')
 expect(keys).toEqual(['result'])
 })
 it('支持嵌套对象中的引用', => {
 const config = {
 nested: {
 deep: {
 value: '{{nodes.N2.output}}',
 },
 },
 }
 const keys = extractNodeVarRefs(config, 'N2')
 expect(keys).toEqual(['output'])
 })
 it('支持 dot notation 路径，如 {{nodes.N1.data.name}}', => {
 const config = {
 prompt: '名称: {{nodes.N1.data.name}}',
 }
 const keys = extractNodeVarRefs(config, 'N1')
 expect(keys).toEqual(['data.name'])
 })
})
describe('getDownstreamVarDeps', => {
 const nodes = [
 { id: 'node-1', short_id: 'A1', name: '节点A', config: { prompt: '{{nodes.B2.result}}' } },
 { id: 'node-2', short_id: 'B2', name: '节点B', config: {} },
 { id: 'node-3', short_id: 'C3', name: '节点C', config: { prompt: '{{nodes.B2.output}} {{nodes.B2.title}}' } },
 ]
 const edges = [
 { source: 'node-2', target: 'node-1' },
 { source: 'node-2', target: 'node-3' },
 ]
 it('获取下游节点对当前节点的变量依赖', => {
 const deps = getDownstreamVarDeps(nodes, edges, 'node-2', 'B2')
 expect(deps).toEqual([
 { nodeId: 'node-1', nodeName: '节点A', keys: ['result'] },
 { nodeId: 'node-3', nodeName: '节点C', keys: ['output', 'title'] },
 ])
 })
 it('无下游节点时返回空数组', => {
 const deps = getDownstreamVarDeps(nodes, edges, 'node-1', 'A1')
 expect(deps).toEqual
 })
 it('同时支持 full id 和 short_id 引用', => {
 const nodesWithFullId = [
 { id: 'node-1', short_id: 'A1', name: '节点A', config: { prompt: '{{nodes.node-2.result}}' } },
 { id: 'node-2', short_id: 'B2', name: '节点B', config: {} },
 ]
 const edgesForTest = [
 { source: 'node-2', target: 'node-1' },
 ]
 const deps = getDownstreamVarDeps(nodesWithFullId, edgesForTest, 'node-2', 'B2')
 expect(deps).toEqual([
 { nodeId: 'node-1', nodeName: '节点A', keys: ['result'] },
 ])
 })
})
describe('checkMissingKeys', => {
 it('编辑后 JSON 缺少下游依赖的 key 时返回警告列表', => {
 const editedData = { title: '标题' }
 const deps = [
 { nodeId: 'n1', nodeName: '节点A', keys: ['title', 'content'] },
 ]
 const warnings = checkMissingKeys(editedData, deps)
 expect(warnings).toEqual([
 { nodeName: '节点A', missingKeys: ['content'] },
 ])
 })
 it('编辑后 JSON 包含所有依赖 key 时返回空警告', => {
 const editedData = { title: '标题', content: '内容' }
 const deps = [
 { nodeId: 'n1', nodeName: '节点A', keys: ['title', 'content'] },
 ]
 const warnings = checkMissingKeys(editedData, deps)
 expect(warnings).toEqual
 })
 it('支持 dot notation 路径检查', => {
 const editedData = { data: { name: '张三' }, result: '成功' }
 const deps = [
 { nodeId: 'n1', nodeName: '节点A', keys: ['data.name', 'result'] },
 ]
 const warnings = checkMissingKeys(editedData, deps)
 expect(warnings).toEqual
 })
 it('dot notation 路径缺失时返回警告', => {
 const editedData = { data: { age: 20 }, result: '成功' }
 const deps = [
 { nodeId: 'n1', nodeName: '节点A', keys: ['data.name', 'result'] },
 ]
 const warnings = checkMissingKeys(editedData, deps)
 expect(warnings).toEqual([
 { nodeName: '节点A', missingKeys: ['data.name'] },
 ])
 })
 it('无依赖时返回空数组', => {
 const editedData = { foo: 'bar' }
 const warnings = checkMissingKeys(editedData, )
 expect(warnings).toEqual
 })
})
