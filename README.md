# Language Agent

一个用于图片 OCR 与 UI 文字显示质检的全栈项目，支持多 Agent 检测、Leader 提示词训练、数据管理与 Langfuse 可观测。

## 主要能力

### OCR 识别
- 多语言识别（中文/英文/日文/韩文等）
- 返回识别文本、语言列表、文字块信息

### UI 质检（多 Agent + LangGraph）
- 结构规划 Agent：全图结构判断 + 聚焦区域建议
- 专项 Agent：异常换行、文字超框/溢出、文字截断、文字重叠
- 汇总输出：`has_issues / issues / summary / score / structure_ok / structure_assessment / agent_process`
- 内置兜底规则：
  - 贴边风险硬阈值检测
  - 阴影/描边导致的“截断误报”过滤
  - 结果一致性修正（高分但有问题等矛盾场景）

### Leader 提示词训练
- 输入：有问题/无问题两类图片
- 执行：Phase1 全量评测 -> 批量改词 -> Phase2 回归
- 编排：LangGraph 节点化流程
- 输出：训练汇总、逐图明细、最终提示词、提示词版本记录

### 前端能力
- 单图检测（OCR / UI / 综合分析）
- 批量 UI 检测（顺序执行）
- 支持直接上传图片文件夹
- 数据管理页（训练记录、提示词版本、详情弹窗）

## 项目结构

```text
language_agent/
├── backend/
│   ├── app.py
│   ├── config.py
│   ├── database.py
│   ├── rag_service.py
│   ├── prompts.py
│   ├── prompt_agents/              # 每个 Agent 提示词独立文件
│   │   ├── ui_agent_structure.py
│   │   ├── ui_agent_linebreak.py
│   │   ├── ui_agent_overflow.py
│   │   ├── ui_agent_truncation.py
│   │   ├── ui_agent_overlap.py
│   │   └── ocr_prompt.py
│   ├── services/
│   │   ├── ocr_service.py
│   │   └── ui_check_service.py
│   ├── leader_agent/
│   │   ├── runner.py
│   │   ├── leader.py
│   │   └── client.py
│   └── requirements.txt
├── frontend/
│   └── src/App.vue
└── README.md
```

## 依赖清单（第三方库/包）

### 运行环境
- Python `3.10+`（建议 `3.11/3.12`）
- Node.js `18+`（建议 `20+`）
- npm `9+`

### 后端 Python 依赖（`backend/requirements.txt`）

| 包名 | 版本约束 | 用途 |
|---|---|---|
| `fastapi` | `==0.115.0` | Web API 框架 |
| `uvicorn[standard]` | `==0.30.0` | ASGI 服务启动 |
| `python-multipart` | `==0.0.9` | 表单/文件上传解析 |
| `httpx` | `==0.27.0` | 异步 HTTP 客户端（Leader 调用后端） |
| `python-dotenv` | `==1.0.1` | 加载 `.env` 配置 |
| `openai` | `==1.50.0` | OpenAI 兼容接口调用 |
| `langfuse[openai]` | `>=2.0.0` | LLM 观测（Tracing） |
| `Pillow` | `==10.4.0` | 图像处理/裁剪 |
| `pydantic` | `==2.9.0` | 数据模型校验 |
| `numpy` | `<2` | 数值库（与现有依赖兼容） |
| `chromadb` | `>=0.4.0` | 向量数据库（RAG） |
| `sentence-transformers` | `>=2.2.0` | 向量化模型（RAG） |
| `langgraph` | `latest` | 多 Agent 流程编排 |
| `langchain-openai` | `latest` | LangChain/OpenAI 适配层（当前为可选保留） |

> 安装命令：`cd backend && pip install -r requirements.txt`

### 前端依赖（`frontend/package.json`）

#### Dependencies

| 包名 | 版本约束 | 用途 |
|---|---|---|
| `vue` | `^3.4.0` | 前端核心框架 |
| `axios` | `^1.7.0` | HTTP 请求客户端 |
| `element-plus` | `^2.8.0` | UI 组件库 |

#### DevDependencies

| 包名 | 版本约束 | 用途 |
|---|---|---|
| `vite` | `^5.4.0` | 前端构建/开发服务器 |
| `@vitejs/plugin-vue` | `^5.0.0` | Vue + Vite 插件 |

> 安装命令：`cd frontend && npm install`

## 快速开始

### 1) 配置环境变量

```bash
cd backend
cp .env.example .env
```

最小必填项：

```bash
LVM_API_KEY=...
LVM_BASE_URL=...
LVM_MODEL=...
```

可选观测与调试项：

```bash
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_ENABLED=true

DEBUG=true
UI_CHECK_TRACE=true
LEADER_GRAPH_TRACE=true
```

### 2) 启动后端

```bash
cd backend
pip install -r requirements.txt
python app.py
```

- API: `http://localhost:8000`
- Docs: `http://localhost:8000/docs`

### 3) 启动前端

```bash
cd frontend
npm install
npm run dev
```

## 核心 API

### `POST /api/ocr`
- 表单参数：`file`、`languages(可选, 逗号分隔)`

### `POST /api/ui-check`
- 表单参数：`file`、`prompt(可选)`
- Leader 训练内部还会透传：
  - `trace_stage(可选)`
  - `trace_image_name(可选)`

### `POST /api/analyze`
- 表单参数：`file`、`languages(可选)`
- 返回 OCR + UI 组合结果

### `POST /api/leader-train`
- 表单参数：
  - `problem[]`、`no_problem[]`
  - `max_rounds`
  - `sample_size`
  - `request_delay`

### 数据管理
- `GET /api/training-runs`
- `GET /api/training-runs/{run_id}`
- `GET /api/prompt-versions`

## Langfuse 观测说明

本项目使用 `langfuse.openai` 自动采集模型调用。  
在 Tracing 中可按 `name` 直接筛选不同节点：

- UI 多 Agent：
  - `ui-structure-planner`
  - `ui-agent-linebreak`
  - `ui-agent-overflow`
  - `ui-agent-truncation`
  - `ui-agent-overlap`
  - `ui-agent-custom-prompt`
- Leader 训练：
  - `leader-phase1-eval`
  - `leader-phase2-eval`
  - `leader-prompt-revise-batch`
  - `leader-prompt-revise-single`

建议同时使用 metadata 过滤：
- `pipeline`（`ui_check` / `leader_train`）
- `agent_type`
- `stage`
- `round`
- `image_name`

## Leader CLI 用法

```bash
cd backend
python -m leader_agent.runner \
  --problem-dir /path/to/problem \
  --no-problem-dir /path/to/no_problem \
  --backend-url http://127.0.0.1:8000 \
  --sample-size 10 \
  --request-delay 2
```

参数：

| 参数 | 说明 | 默认 |
|---|---|---|
| `--problem-dir` | 有问题图片目录 | `LEADER_PROBLEM_DIR` |
| `--no-problem-dir` | 无问题图片目录 | `LEADER_NO_PROBLEM_DIR` |
| `--backend-url` | 后端地址 | `http://127.0.0.1:8000` |
| `--max-rounds` | 每图最大重试轮次 | 3 |
| `--sample-size` | 每类采样数量（0=全部） | 10 |
| `--request-delay` | 上游调用间隔秒数 | 2 |

## 技术栈

- 后端：FastAPI、LangGraph、OpenAI-compatible API、SQLite、ChromaDB
- 前端：Vue3、Element Plus、Vite
- 观测：Langfuse

## 许可证

MIT
