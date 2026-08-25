# RegTrust-RAG 前端工程 (Frontend Project)

面向“银行业监管制度与统计报表的可信 RAG 问答”赛题构建的标准前后端分离前端系统。

## 🌟 架构分层设计规范

前端工程采用标准的分层架构设计，实现了高内聚、低耦合的模块划分：

```text
frontend/
├── package.json                # 前端工程配置与脚本 (npm run dev / serve)
├── index.html                  # 页面主入口 (HTML5 语义化三栏视窗)
├── src/                        # 前端源码核心分层
│   ├── assets/                 # 静态资源与样式层
│   │   └── css/
│   │       ├── variables.css   # 设计系统 Token（颜色、间距、圆角、阴影）
│   │       ├── layout.css      # 三栏网格布局、顶部栏与响应式规范
│   │       └── components.css  # 气泡对话、证据卡片、导入队列、模态框
│   ├── utils/                  # 通用工具函数层
│   │   ├── formatters.js       # 文本过滤、HTML 转义、数字格式化
│   │   ├── storage.js          # 本地 LocalStorage 状态持久化
│   │   └── event_bus.js        # 轻量级 Pub/Sub 事件总线
│   ├── api/                    # 接口请求与网络层
│   │   ├── http_client.js      # Fetch 适配器、BaseURL、超时与拦截器
│   │   ├── rag_api.js          # 问答 (/ask) 与检索 (/retrieve) API
│   │   ├── kb_api.js           # 知识库统计与文档列表 API
│   │   ├── import_api.js       # 文件解析与入库触发 API
│   │   └── api_service.js      # 统一 API Service（含离线 Mock 优雅降级）
│   ├── router/                 # 路由与控制器层
│   │   └── router.js           # 页面视图分发与 RBAC 权限守卫
│   ├── controllers/            # 业务交互控制层
│   │   ├── chat_controller.js  # 问答交互、示例问题选择、气泡渲染
│   │   ├── import_controller.js# 多格式文件导入、队列进度动态模拟
│   │   ├── kb_controller.js    # 知识库文档治理、搜索与切片预览
│   │   ├── evidence_controller.js # 单列证据链审查与原文片段高亮
│   │   └── pipeline_controller.js # 模块流水线状态与指标监控
│   ├── components/             # 通用 UI 组件层
│   │   ├── toast.js            # Toast 状态提示组件
│   │   └── modal.js            # 弹出对话框与预览弹窗组件
│   ├── state/                  # 响应式状态中心
│   │   └── app_state.js        # 会话、权限、证据、知识库全局状态
│   ├── services/               # 领域模拟与离线引擎
│   │   └── mock_service.js     # 内置高保真 Mock 检索与防幻觉模拟引擎
│   └── main.js                 # 前端应用主启动入口
├── app.py                      # 本地独立 Web 启动脚本
└── README.md                   # 本说明文档
```

---

## 🚀 独立启动与运行

### 方式一：Node.js / npm 独立启动（推荐）
```powershell
cd frontend
npm run dev
# 或使用 live-server:
# npx -y serve . -l 8080
```
在浏览器中打开 `http://localhost:8080`。

### 方式二：Python 静态服务器启动
```powershell
cd frontend
python -m http.server 8080
```

### 方式三：Python 一键启动器
```powershell
python frontend/app.py
```

---

## 🔒 RBAC 角色权限体系
- **管理员 (Admin)**：开放全部功能，包括【导入台】文件解析入库、【知识库管理】文档治理与删除、【模块对接】监控。
- **普通用户 (User)**：限制在【对话窗】合规问答与【证据审查】查阅，管理入口受权限守卫保护。
