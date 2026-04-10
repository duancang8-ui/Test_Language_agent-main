# Language Agent 接口文档

> 基础地址：`http://localhost:8000`
> 前端代理：开发模式下 Vite 将 `/api` 代理到 `http://localhost:8000`

---

## 目录

- [1. 服务信息](#1-服务信息)
- [2. 健康检查](#2-健康检查)
- [3. OCR 文字识别](#3-ocr-文字识别)
- [4. UI 文字显示检测](#4-ui-文字显示检测)
- [5. 批量 UI 检测](#5-批量-ui-检测)
- [6. 综合分析（OCR + UI）](#6-综合分析ocr--ui)
- [7. Leader Agent 训练](#7-leader-agent-训练)
- [8. 训练记录](#8-训练记录)
- [9. 提示词版本](#9-提示词版本)
- [10. 测试报告](#10-测试报告)
- [附录 A：UI 检测问题类型](#附录-aui-检测问题类型)
- [附录 B：Agent 过程结构](#附录-bagent-过程结构)
- [附录 C：错误码](#附录-c错误码)

---

## 1. 服务信息

### `GET /`

返回服务基本信息与可用端点列表。

**响应示例：**

```json
{
  "name": "多语言 OCR Agent",
  "version": "1.0.0",
  "endpoints": {
    "OCR 识别": "POST /api/ocr",
    "UI 检测": "POST /api/ui-check",
    "批量 UI 检测": "POST /api/ui-check-batch",
    "综合分析": "POST /api/analyze",
    "Leader Agent 训练": "POST /api/leader-train",
    "测试报告": "POST/GET /api/test-reports"
  }
}
```

---

## 2. 健康检查

### `GET /api/health`

检查服务是否正常运行。

**响应示例：**

```json
{
  "status": "ok",
  "model": "gemini-2.5-pro"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | string | 服务状态，正常为 `"ok"` |
| `model` | string | 当前使用的视觉模型名称 |

---

## 3. OCR 文字识别

### `POST /api/ocr`

对上传图片进行多语言 OCR 文字识别。

**请求格式：** `multipart/form-data`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | File | 是 | 图片文件（支持 jpg/png/gif/webp/bmp） |
| `languages` | string | 否 | 期望识别的语言，逗号分隔，如 `"中文,英文,日文"` |

**请求示例：**

```bash
curl -X POST http://localhost:8000/api/ocr \
  -F "file=@screenshot.png" \
  -F "languages=中文,英文"
```

**响应示例：**

```json
{
  "success": true,
  "texts": [
    {
      "text": "开始游戏",
      "language": "中文",
      "confidence": 0.95
    }
  ],
  "message": "识别完成"
}
```

---

## 4. UI 文字显示检测

### `POST /api/ui-check`

检测图片中的 UI 文字显示问题。采用多 Agent 并行架构（结构 Agent + 6 个专项 Agent）。

**请求格式：** `multipart/form-data`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | File | 是 | 图片文件 |
| `prompt` | string | 否 | 自定义检测提示词（用于 Leader Agent 训练时动态替换） |
| `trace_stage` | string | 否 | Langfuse 追踪阶段标识 |
| `trace_image_name` | string | 否 | Langfuse 追踪图片名称标识 |

**请求示例：**

```bash
curl -X POST http://localhost:8000/api/ui-check \
  -F "file=@screenshot.png"
```

**响应示例：**

```json
{
  "success": true,
  "has_issues": true,
  "issues": [
    {
      "type": "UI堆叠",
      "description": "设置图标的左上部分被进度条容器的边框覆盖和遮挡",
      "location": "图片顶部，进度条右侧的设置图标处",
      "severity": "medium",
      "suggestion": "调整设置图标或进度条容器的布局，确保两者之间有足够的间距"
    }
  ],
  "summary": "问题总数：1。主要类型：UI堆叠。结构判断：正常。已发现可见证据问题，建议修复后复测。",
  "score": 79,
  "structure_ok": true,
  "structure_assessment": "整体UI结构清晰，布局合理",
  "agent_process": [
    {
      "agent": "异常换行Agent",
      "issue_type": "异常换行",
      "has_issue": false,
      "reason": "未发现该类型明确可见证据。"
    },
    {
      "agent": "超框溢出Agent",
      "issue_type": "文字超框/溢出",
      "has_issue": false,
      "reason": "未发现该类型明确可见证据。"
    },
    {
      "agent": "截断Agent",
      "issue_type": "文字截断",
      "has_issue": false,
      "reason": "未发现该类型明确可见证据。（复检投票: 0/2）"
    },
    {
      "agent": "重叠Agent",
      "issue_type": "文字重叠",
      "has_issue": false,
      "reason": "未发现该类型明确可见证据。"
    },
    {
      "agent": "堆叠Agent",
      "issue_type": "UI堆叠",
      "has_issue": true,
      "reason": "设置图标被进度条容器的边框部分覆盖，构成了UI堆叠。"
    },
    {
      "agent": "乱码Agent",
      "issue_type": "乱码/编码问题",
      "has_issue": false,
      "reason": "未发现该类型明确可见证据。"
    },
    {
      "agent": "结构Agent",
      "issue_type": "UI 结构/布局问题",
      "has_issue": false,
      "reason": "整体UI结构清晰，布局合理。"
    }
  ],
  "elapsed_ms": 12345,
  "wall_elapsed_ms": 58729,
  "message": "检测完成"
}
```

**响应字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `success` | boolean | 请求是否成功 |
| `has_issues` | boolean | 是否发现 UI 问题 |
| `issues` | array | 问题详情列表，见 [附录 A](#附录-aui-检测问题类型) |
| `summary` | string | 检测结果摘要 |
| `score` | integer | 质量得分（0-100），100 为满分 |
| `structure_ok` | boolean\|null | 整体 UI 结构是否正常 |
| `structure_assessment` | string | 结构判断理由 |
| `agent_process` | array | 各 Agent 检测过程，见 [附录 B](#附录-bagent-过程结构) |
| `elapsed_ms` | integer | 模型推理累计耗时（毫秒） |
| `wall_elapsed_ms` | integer | 总墙钟耗时（毫秒） |
| `message` | string | 状态消息 |

**得分规则：**

| 条件 | 得分约束 |
|------|---------|
| 无问题 | 100 |
| 存在文字截断 / 文字重叠 / UI堆叠 / 乱码 | score < 80 |
| 存在超框/溢出 | score < 85 |
| severity=high 的问题 | 每个扣 25 分 |
| severity=medium 的问题 | 每个扣 15 分 |
| severity=low 的问题 | 每个扣 8 分 |

---

## 5. 批量 UI 检测

### `POST /api/ui-check-batch`

批量上传多张图片并发执行 UI 检测。

**请求格式：** `multipart/form-data`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `files` | File[] | 是 | 多张图片文件 |
| `concurrency` | integer | 否 | 并发数，默认 2，范围 1-5 |

**请求示例：**

```bash
curl -X POST http://localhost:8000/api/ui-check-batch \
  -F "files=@img1.png" \
  -F "files=@img2.png" \
  -F "files=@img3.png" \
  -F "concurrency=3"
```

**响应示例：**

```json
{
  "success": true,
  "total": 3,
  "concurrency": 3,
  "results": [
    {
      "filename": "img1.png",
      "success": true,
      "has_issues": false,
      "score": 100,
      "issues": [],
      "summary": "未发现明确可见问题。",
      "structure_ok": true,
      "agent_process": [],
      "elapsed_ms": 0,
      "wall_elapsed_ms": 45000,
      "message": "检测完成"
    }
  ],
  "elapsed_ms": 12345,
  "wall_elapsed_ms": 50000
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `total` | integer | 检测图片总数 |
| `concurrency` | integer | 实际使用的并发数 |
| `results` | array | 每张图的检测结果，结构同 `/api/ui-check` 响应，额外包含 `filename` |
| `elapsed_ms` | integer | 所有图片模型推理累计耗时 |
| `wall_elapsed_ms` | integer | 总墙钟耗时 |

---

## 6. 综合分析（OCR + UI）

### `POST /api/analyze`

同时进行 OCR 文字识别和 UI 问题检测（并行执行）。

**请求格式：** `multipart/form-data`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | File | 是 | 图片文件 |
| `languages` | string | 否 | 期望识别的语言，逗号分隔 |

**请求示例：**

```bash
curl -X POST http://localhost:8000/api/analyze \
  -F "file=@screenshot.png" \
  -F "languages=中文"
```

**响应示例：**

```json
{
  "success": true,
  "ocr": {
    "success": true,
    "texts": [],
    "message": "识别完成"
  },
  "ui_check": {
    "success": true,
    "has_issues": false,
    "issues": [],
    "summary": "未发现明确可见问题。",
    "score": 100,
    "structure_ok": true,
    "structure_assessment": "结构正常",
    "agent_process": [],
    "elapsed_ms": 0,
    "wall_elapsed_ms": 45000,
    "message": "检测完成"
  },
  "message": "分析完成"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `success` | boolean | OCR 和 UI 检测是否都成功 |
| `ocr` | object | OCR 识别结果 |
| `ui_check` | object | UI 检测结果，结构同 `/api/ui-check` 响应 |
| `message` | string | 状态消息 |

---

## 7. Leader Agent 训练

### `POST /api/leader-train`

上传「有问题」和「没问题」两类图片，执行 Leader Agent 训练流程，迭代优化检测提示词。

**请求格式：** `multipart/form-data`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `problem` | File[] | 否* | 有问题的图片 |
| `no_problem` | File[] | 否* | 无问题的图片 |
| `max_rounds` | integer | 否 | 每张图最多重试次数，默认 3 |
| `sample_size` | integer | 否 | 每类抽样数量，0 表示全部，默认 10 |
| `request_delay` | float | 否 | 每次 API 调用后等待秒数（避免 429 限流），默认 2.0，范围 0-300 |

> \* `problem` 和 `no_problem` 至少需要提供一类

**请求示例：**

```bash
curl -X POST http://localhost:8000/api/leader-train \
  -F "problem=@bad1.png" \
  -F "problem=@bad2.png" \
  -F "no_problem=@good1.png" \
  -F "max_rounds=3" \
  -F "sample_size=10" \
  -F "request_delay=2"
```

**响应示例：**

```json
{
  "success": true,
  "run_id": "20260409_143052_abc123",
  "total": 3,
  "ok": 2,
  "failed": 1,
  "updated_prompt_count": 2,
  "final_prompt": "最终优化后的提示词内容...",
  "details": [
    {
      "filename": "bad1.png",
      "expected": "has_issues",
      "actual": "has_issues",
      "passed": true,
      "retries": 0
    }
  ],
  "message": "训练完成：共 3 张，通过 2 张，失败 1 张，提示词被修改 2 次"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `run_id` | string | 训练运行 ID |
| `total` | integer | 处理图片总数 |
| `ok` | integer | 通过的图片数 |
| `failed` | integer | 失败的图片数 |
| `updated_prompt_count` | integer | 提示词被修改的次数 |
| `final_prompt` | string | 训练后最终的提示词 |
| `details` | array | 每张图的训练明细 |

---

## 8. 训练记录

### `GET /api/training-runs`

列出最近的训练记录。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `limit` | integer | 否 | 返回数量，默认 50 |

**响应：** 训练记录数组，每条包含 `id`、`created_at`、`total`、`ok`、`failed`、`updated_prompt_count` 等字段。

---

### `GET /api/training-runs/{run_id}`

获取单次训练的汇总与明细。

| 路径参数 | 类型 | 说明 |
|---------|------|------|
| `run_id` | string | 训练运行 ID |

**响应：** 包含训练汇总信息、每张图的明细记录、以及相关提示词版本。

**错误响应：**

| 状态码 | 说明 |
|--------|------|
| 404 | 未找到该训练记录 |

---

## 9. 提示词版本

### `GET /api/prompt-versions`

列出最近的提示词版本（RAG 知识库列表）。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `limit` | integer | 否 | 返回数量，默认 50 |

**响应：** 提示词版本数组，每条包含版本内容、修改原因、创建时间等。

---

## 10. 测试报告

### `POST /api/test-reports`

创建一个新的测试报告会话。

**请求格式：** `multipart/form-data`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `total` | integer | 否 | 预计图片总数，默认 0 |

**响应示例：**

```json
{
  "report_id": "20260409_143052_abc123"
}
```

---

### `POST /api/test-reports/{report_id}/items`

向测试报告中提交单张图片，后端自动执行 UI 检测并保存结果。

**请求格式：** `multipart/form-data`

| 路径参数 | 类型 | 说明 |
|---------|------|------|
| `report_id` | string | 报告 ID |

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | File | 是 | 图片文件 |

**响应：** 结构同 `/api/ui-check` 响应，额外包含 `filename` 和 `image_path`。

---

### `PATCH /api/test-reports/{report_id}/complete`

标记测试报告为已完成。

| 路径参数 | 类型 | 说明 |
|---------|------|------|
| `report_id` | string | 报告 ID |

**响应示例：**

```json
{
  "success": true
}
```

---

### `GET /api/test-reports`

列出历史测试报告。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `limit` | integer | 否 | 返回数量，默认 50 |

**响应：** 报告数组，每条包含 `report_id`、`created_at`、`status`、`total` 等。

---

### `GET /api/test-reports/{report_id}`

获取测试报告详情，包含所有图片的检测结果。

| 路径参数 | 类型 | 说明 |
|---------|------|------|
| `report_id` | string | 报告 ID |

**错误响应：**

| 状态码 | 说明 |
|--------|------|
| 404 | 未找到该测试报告 |

---

### `GET /api/report-images/{report_id}/{filename}`

获取报告中保存的图片文件。

| 路径参数 | 类型 | 说明 |
|---------|------|------|
| `report_id` | string | 报告 ID |
| `filename` | string | 图片文件名 |

**响应：** 图片文件（Binary）

**错误响应：**

| 状态码 | 说明 |
|--------|------|
| 404 | 图片不存在 |

---

## 附录 A：UI 检测问题类型

UI 检测共支持 **7 类** 专项检测：

| 类型 | Agent | 说明 | 复检投票 |
|------|-------|------|---------|
| `异常换行` | 异常换行Agent | 文字在不合理位置换行，单词被强制分割 | 1 轮 |
| `文字超框/溢出` | 超框溢出Agent | 文字超出容器边界、被裁切、贴边 | 2 轮 |
| `文字截断` | 截断Agent | 字符笔画缺失、文字不完整 | 2 轮 |
| `文字重叠` | 重叠Agent | 文字与文字/图标/按钮平面交叉重叠 | 1 轮 |
| `UI堆叠` | 堆叠Agent | UI 元素在 z 轴方向上错误层叠覆盖 | 1 轮 |
| `乱码/编码问题` | 乱码Agent | 方块字、替代符、形近字错显等 | 1 轮 |
| `UI 结构/布局问题` | 结构Agent | 布局崩溃、模块错位、层级混乱 | 1 轮 |

**issue 对象结构：**

```json
{
  "type": "UI堆叠",
  "description": "设置图标被进度条边框覆盖",
  "location": "顶部进度条右侧",
  "severity": "high|medium|low",
  "suggestion": "调整元素层级或布局间距"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `type` | string | 问题类型（上表 7 种之一） |
| `description` | string | 问题描述（基于可见证据） |
| `location` | string | 具体位置 |
| `severity` | string | 严重程度：`high` / `medium` / `low` |
| `suggestion` | string | 修复建议 |

---

## 附录 B：Agent 过程结构

`agent_process` 数组固定包含 **7 个** Agent 的检测过程记录，顺序固定：

```
异常换行Agent → 超框溢出Agent → 截断Agent → 重叠Agent → 堆叠Agent → 乱码Agent → 结构Agent
```

**单条 agent_process 结构：**

```json
{
  "agent": "堆叠Agent",
  "issue_type": "UI堆叠",
  "has_issue": true,
  "reason": "检测到设置图标被进度条覆盖",
  "model_elapsed_ms": 5200,
  "rounds": 1
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `agent` | string | Agent 名称 |
| `issue_type` | string | 对应的问题类型 |
| `has_issue` | boolean | 该 Agent 是否检测到问题 |
| `reason` | string | 判断理由 |
| `model_elapsed_ms` | integer | 该 Agent 模型推理耗时（毫秒），可选 |
| `rounds` | integer | 投票轮数，可选 |

---

## 附录 C：错误码

| HTTP 状态码 | 说明 |
|-------------|------|
| 200 | 请求成功 |
| 400 | 请求参数错误（如未上传图片、文件类型不是图片） |
| 404 | 资源不存在（训练记录/测试报告/图片未找到） |
| 500 | 服务器内部错误 |

**错误响应格式：**

```json
{
  "detail": "请上传图片文件"
}
```
