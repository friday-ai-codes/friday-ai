---
# 语言约束
**所有回复必须使用中文。** 包括：
- 主对话回复
- GSD 规划输出（阶段名称、任务描述、验证结果）
- 代码注释和文档字符串
- 提交信息
英文仅用于：代码变量名、技术术语、CLI 命令
---
# Friday 开发规范
全栈 Monorepo 项目：
- **前端**: `web/` — Vue 3 + TypeScript + shadcn-vue
- **后端**: `server/` — Django 6.0 + Python 3.14+
---
## 第一部分：前端 (Vue 3 / shadcn-vue)
### 1. 核心理念
- 以设计系统思维生成生产级 Vue 3 代码
- 优先考虑清晰性、可组合性和长期可维护性，而非炫技
- 优雅源于克制，而非视觉复杂度
- 每个抽象都必须有明确的实际理由
假设读者是有经验的前端工程师。
### 2. 技术栈与约定
- 框架：Vue 3
- 语法：`<script setup lang="ts">` + TypeScript (strict)
- 组件库：shadcn-vue
- 样式：Tailwind CSS（utility-first，禁止内联样式）
- 状态：优先使用局部状态；仅在必要时提升
- 始终使用 Composition API，禁止 Options API
**禁止：**
- 使用 React 模式或术语
- 模拟 hooks 或 React 风格的状态流
- 过早将简单逻辑抽象为 composables
### 3. shadcn-vue 使用原则
- 将 shadcn-vue 组件视为**无样式原语**，而非成品 UI
- 优先通过 `slots` 组合，而非 prop 堆砌
- 仅在复用明确时通过包装组件扩展
- 尊重 shadcn 组件的原始意图和语义
**添加组件时，使用命令行：**
```bash
cd web
npx shadcn-vue@latest add <component-name>
```
**禁止：**
- 未经调整直接复制粘贴大型 shadcn 组件
- 除非明确要求，否则不修改组件库内部实现
### 4. 设计风格：Glassmorphism + 渐变装饰
本项目采用 **玻璃拟态（Glassmorphism）** 风格，结合渐变装饰和丰富的视觉层次。
#### 核心视觉特征
| 特征 | 实现方式 |
|------|---------|
| 玻璃卡片 | `bg-card/80 backdrop-blur-sm border-border/50 rounded-2xl` |
| 环境光晕 | 大面积 `blur-3xl` 渐变圆形作为背景装饰 |
| 渐变图标背景 | `bg-gradient-to-br from-xxx/20 to-xxx/10` |
| 渐变文字 | `bg-gradient-to-r bg-clip-text text-transparent` |
| 大圆角 | `rounded-2xl`（16px）为主，`rounded-xl`（12px）为辅 |
| 悬浮光效 | hover 时出现渐变阴影 `group-hover:shadow-primary/5` |
#### 卡片结构
```html
<!-- 标准卡片模式 -->
<div class="rounded-2xl bg-card/70 backdrop-blur-sm border border-border/50 overflow-hidden">
 <!-- 标题栏 -->
 <div class="flex items-center justify-between border-b border-border/50">
 <div class="flex items-center gap-3">
 <div class=" rounded-lg bg-gradient-to-br from-primary/20 to-primary/10">
 <span class="icon-[lucide--xxx] text-xl text-primary" />
 </div>
 <div>
 <h2 class="text-lg font-semibold">标题</h2>
 <p class="text-sm text-muted-foreground">描述</p>
 </div>
 </div>
 </div>
 <!-- 内容区 -->
 <div class="">...</div>
</div>
```
#### 背景装饰
页面级别使用模糊渐变圆形作为环境光效：
```html
<div class="absolute inset-0 -z-10 overflow-hidden">
 <div class="absolute -top-40 -right-40 w-80 bg-gradient-to-br from-primary/20 to-secondary/40 rounded-full blur-3xl" />
 <div class="absolute top-1/2 -left-40 w-96 bg-gradient-to-tr from-secondary/30 to-primary/10 rounded-full blur-3xl" />
</div>
```
#### 多彩渐变系统
不同功能区块使用不同色系的渐变，保持视觉丰富性：
| 用途 | 渐变 |
|------|------|
| 主要/项目 | `from-blue-500 to-cyan-400` |
| 任务/紫色 | `from-violet-500 to-purple-400` |
| 运行中/警示 | `from-amber-500 to-orange-400` |
| 成功/审核 | `from-emerald-500 to-teal-400` |
#### 交互状态
悬浮效果应丰富且有反馈：
```html
<!-- 可点击卡片 -->
<div class="group relative">
 <!-- 悬浮时的光晕 -->
 <div class="absolute inset-0 bg-gradient-to-r opacity-0 group-hover:opacity-100
 transition-opacity duration-500 rounded-2xl blur-xl -z-10":class="gradient" />
 <!-- 卡片主体 -->
 <div class="relative rounded-2xl bg-card/80 backdrop-blur-sm border border-border/50
 group-hover:border-primary/30 group-hover:shadow-lg group-hover:shadow-primary/5
 transition-all duration-300">
 ...
 </div>
</div>
```
#### 动画与过渡
- 使用 `transition-all duration-300` 作为默认过渡
- 悬浮光效使用 `duration-500` 更柔和
- 图标/箭头位移：`group-hover:translate-x-1 transition-transform`
- 按钮光效扫过：`translate-x-[-100%] group-hover:translate-x-[100%] transition-transform duration-700`
### 5. 设计细节与巧思
#### 必须包含的细节
- **序号装饰**：列表项使用渐变背景的序号徽章
- **箭头动画**：链接/卡片右侧的箭头在 hover 时位移
- **渐变数字**：统计数字使用 `bg-clip-text text-transparent` 渐变
- **加载骨架**：使用 `bg-gradient-to-r from-muted to-muted/50 animate-pulse`
- **空状态**：居中布局 + 大图标 + 渐变背景容器
#### 图标使用
- 图标容器使用渐变背景：`bg-gradient-to-br from-xxx/20 to-xxx/10 rounded-xl `
- 功能图标使用纯色渐变容器：`bg-gradient-to-br from-xxx to-xxx text-white rounded-lg `
- 图标大小层级：`text-xl`（标准）、`text-2xl`（强调）、`text-4xl+`（空状态）
#### 禁止
- 使用扁平、无装饰的纯色卡片
- 省略背景光晕装饰
- 使用小圆角（`rounded-md` 或更小）
- 单调的 hover 效果（仅变色，无阴影/光效）
### 6. 组件架构
- 组件应小巧、专注、单一职责
- 优先扁平组件层级，除非嵌套增加清晰度
- Props 应最小化、显式且语义明确
- 避免布尔 prop 爆炸；需要时使用枚举或配置对象
- 当可读性提升时，分离视觉组件与业务逻辑
Slots：
- 有意使用具名 slots
- 避免过度泛化的 slot API
- Slot 名称应描述意图，而非结构
### 7. 代码风格与可读性
- 优先选择显式、可读的代码，而非聪明的抽象
- 使用描述性的变量和组件名
- 避免魔法数字；提取有意义的常量
- 注释应解释*为什么*，而非*是什么*
假设未来会有重构和扩展。
### 8. 性能与用户体验意识
- 避免不必要的响应式状态
- 有意使用 computed 属性
- Watchers 应稀少且有充分理由
- 优化感知性能和交互流畅度
**禁止：**
- 无证据的过早优化
- 仅为理论收益引入复杂度
### 9. 处理模糊需求
当需求模糊时：
- 做出合理、保守的假设
- 选择更简单、更可维护的方案
- 如果假设显著影响 API 或用户体验，简要记录
---
## 第二部分：后端 (Django / Python)
### 1. 核心理念
- 编写干净、可维护、类型明确的 Python 代码
- 遵循 Django 约定，除非有明确理由不这样做
- 优先简洁和可读性，而非过早优化
- 每个模块应有单一、明确的职责
### 2. 技术栈与约定
- 框架：Django 6.0 + Django REST Framework
- Python：3.14+，严格类型注解
- Lint 与格式化：Ruff（取代 Black、isort、flake8）
- 认证：JWT via `rest_framework_simplejwt`
- API 文档：`drf-spectacular` (OpenAPI/Swagger)
代码风格：
- 严格遵循 PEP 8
- **所有函数签名必须有类型注解**
- I/O 密集操作使用 `async/await`（LLM 调用、Docker API、外部 HTTP）
**创建新 Django App 时，使用命令行：**
```bash
cd server
python manage.py startapp <app_name>
```
### 3. API 设计
#### URL 约定
- 所有 API 端点前缀为 `/api/`
- **URL 必须以斜杠结尾**
 - ✅ `/api/projects/`
 - ❌ `/api/projects`
- Django 的 `APPEND_SLASH = True` 会重定向，但优先显式加斜杠
#### 认证
- Authorization header 使用 Bearer token：`Authorization: Bearer <token>`
- JWT token 用于无状态认证
#### API 文档
可用端点：
- Swagger UI：`/api/docs`
- Redoc：`/api/redoc`
- OpenAPI Schema：`/api/schema`
### 4. 项目结构
```text
server/
├── friday/ # Django 项目配置
│ ├── settings.py
│ ├── urls.py
│ └── asgi.py
├── accounts/ # 用户认证与权限
├── projects/ # 项目管理
├── repositories/ # 代码仓库管理
├── tasks/ # 任务生命周期管理
├── feishu/ # 飞书集成与 Webhooks
├── chat/ # AI 对话功能
├── system/ # 系统级设置
├── common/ # 共享工具与异常
├── services/ # 业务逻辑 (Docker, LLM 等)
└── tests/ # 所有测试（集中管理）
```
### 5. 测试
#### 测试框架与位置
- 使用 **pytest** 作为测试运行器
- **所有测试放在 `server/tests/`**，不在各 App 目录中
- 文件命名：`test_<module>.py`（如 `test_auth.py`、`test_tasks.py`）
- 使用 `conftest.py` 存放共享 fixtures
#### 编写测试
```python
# server/tests/test_example.py
import pytest
from django.test import Client
@pytest.mark.django_db
def test_example_endpoint(client: Client):
 response = client.get("/api/example/")
 assert response.status_code == 200
```
#### 异步测试
使用 `pytest-asyncio`：
```python
import pytest
@pytest.mark.asyncio
async def test_async_operation:
 result = await some_async_function
 assert result is not None
```
#### 运行测试
```bash
cd server
pytest # 运行所有测试
pytest tests/test_auth.py # 运行特定测试文件
pytest -v # 详细输出
pytest --cov # 带覆盖率报告
```
### 6. 日志
**重要**：禁止使用 Python 标准 `logging` 模块。
使用 **structlog** 进行结构化 JSON 日志：
```python
import structlog
logger = structlog.get_logger
# ✅ 正确
logger.info("task_started", task_id=task.id, user=user.username)
# ❌ 错误 - 不要使用标准 logging
import logging
logging.info("Task started")
```
### 7. 数据库
- 默认：SQLite (`data/friday.db`)
- 生产环境：通过 `DATABASE_URL` 环境变量配置
- **Schema 变更必须生成迁移文件**：`python manage.py makemigrations`
- 敏感数据使用 `FRIDAY_ENCRYPTION_KEY` 加密存储
**重要**：每当更改数据库模型后，询问用户是否执行数据库迁移：
```bash
python manage.py makemigrations
python manage.py migrate
```
### 8. 错误处理
- 使用 `common/exceptions.py` 中的自定义异常
- 让 DRF 处理异常到响应的转换
- 使用 structlog 记录带上下文的错误
---
## 第三部分：通用实践
### 1. Git 工作流
- 编写清晰、描述性的提交信息
- 适用时引用 issue 编号
- 保持提交专注且原子化
### 2. 代码审查思维
编写代码时考虑：
- 对不熟悉上下文的人是否易于理解？
- 边界情况是否处理得当？
- 代码是否可测试？
- 是否遵循代码库中的现有模式？
### 3. 文档
- 代码应尽可能自文档化
- 注释解释*为什么*，而非*是什么*
