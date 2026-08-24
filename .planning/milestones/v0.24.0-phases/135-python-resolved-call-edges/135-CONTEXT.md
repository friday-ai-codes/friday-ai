# Phase 135 Context：Python resolved 调用边

## Smart Discuss 自动决策

| 灰区 | ✅ Recommended 决策 |
|---|---|
| module import | `import pkg.mod [as alias]` 的 qualifier 绑定模块文件，再解析 member |
| 局部同名 | 有 qualifier 的调用不得先命中同文件裸名，避免 `mod.foo()` 被 local `foo` 污染 |
| class binding | 仅 class import/local class 唯一且目标文件 member 唯一时 resolved |
| MRO/动态 receiver | 无继承图或类型证据时 unresolved；同证据多 method 时 ambiguous |
| 评测 | 复用 Phase 133 分桶口径，以 Python 专项 resolver 用例锁 call shape 三态 |

## 边界

不推断运行时 monkey patch、duck typing、复杂赋值数据流或 MRO；Go 深化与 LSP 默认值不变。
