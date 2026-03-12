"""
提示词模板汇总入口
集中管理并对外导出所有 AI 模型提示词。
各 Agent 具体提示词已拆分到 `prompt_agents/` 目录。
"""

from prompt_agents import (
    OCR_PROMPT_TEMPLATE,
    UI_AGENT_COMMON_RULES,
    UI_AGENT_LINEBREAK_PROMPT,
    UI_SPECIALIZED_LINEBREAK_PROMPT,
    UI_AGENT_OVERFLOW_PROMPT,
    UI_SPECIALIZED_OVERFLOW_PROMPT,
    UI_AGENT_TRUNCATION_PROMPT,
    UI_SPECIALIZED_TRUNCATION_PROMPT,
    UI_AGENT_OVERLAP_PROMPT,
    UI_SPECIALIZED_OVERLAP_PROMPT,
    UI_AGENT_STRUCTURE_PROMPT,
    UI_STRUCTURE_PLANNER_PROMPT,
    UI_AGENT_GARBLED_PROMPT,
    UI_SPECIALIZED_GARBLED_PROMPT,
)

UI_CHECK_PROMPT = f"""【多专项 Agent 协同检测（6 类）】
你将串行执行 6 个专项 Agent，每个 Agent 只负责一种类型：
- 异常换行
- 文字超框/溢出
- 文字截断
- 文字重叠
- 乱码/编码问题
- 整体 UI 结构问题

{UI_AGENT_COMMON_RULES}

{UI_AGENT_LINEBREAK_PROMPT}

{UI_AGENT_OVERFLOW_PROMPT}

{UI_AGENT_TRUNCATION_PROMPT}

{UI_AGENT_OVERLAP_PROMPT}

{UI_AGENT_GARBLED_PROMPT}

{UI_AGENT_STRUCTURE_PROMPT}

【汇总规则（必须执行）】
1) 最终 has_issues：只要任一专项 Agent 发现问题即为 true，否则 false。
2) issues 只允许包含上述 6 类 type：
   - 异常换行
   - 文字超框/溢出
   - 文字截断
   - 文字重叠
   - 乱码/编码问题
   - UI 结构/布局问题
3) structure_ok/structure_assessment 必须给出（即使 structure_ok=true）。
4) 若 has_issues=false，则 issues 必须为空，score 建议 >= 90。
5) 若包含"文字截断"或"文字重叠"或"乱码/编码问题"，score 必须 < 80。
6) summary 必须与 issues 完全一致，不允许自相矛盾。
7) 必须输出 agent_process，且严格包含 6 个专项 Agent 的过程记录（按固定顺序）。

请按以下 JSON 返回：
```json
{{
  "has_issues": true或false,
  "structure_ok": true或false,
  "structure_assessment": "AI 对整体 UI 结构判断与理由",
  "agent_process": [
    {{
      "agent": "异常换行Agent",
      "issue_type": "异常换行",
      "has_issue": true或false,
      "reason": "该 Agent 的判断理由（仅基于可见证据）"
    }},
    {{
      "agent": "超框溢出Agent",
      "issue_type": "文字超框/溢出",
      "has_issue": true或false,
      "reason": "该 Agent 的判断理由（仅基于可见证据）"
    }},
    {{
      "agent": "截断Agent",
      "issue_type": "文字截断",
      "has_issue": true或false,
      "reason": "该 Agent 的判断理由（仅基于可见证据）"
    }},
    {{
      "agent": "重叠Agent",
      "issue_type": "文字重叠",
      "has_issue": true或false,
      "reason": "该 Agent 的判断理由（仅基于可见证据）"
    }},
    {{
      "agent": "乱码Agent",
      "issue_type": "乱码/编码问题",
      "has_issue": true或false,
      "reason": "该 Agent 的判断理由（仅基于可见证据）"
    }},
    {{
      "agent": "结构Agent",
      "issue_type": "UI 结构/布局问题",
      "has_issue": true或false,
      "reason": "该 Agent 的判断理由（仅基于可见证据）"
    }}
  ],
  "issues": [
    {{
      "type": "异常换行/文字超框/溢出/文字截断/文字重叠/乱码/编码问题/UI 结构/布局问题",
      "description": "必须是可见证据，不得臆测",
      "location": "具体位置（区域/组件/行）",
      "severity": "high/medium/low",
      "suggestion": "可执行修复建议"
    }}
  ],
  "summary": "问题总数+主要类型+整体评估+结构判断结论",
  "score": 85
}}
```"""


UI_SPECIALIZED_AGENT_PROMPTS = {
    "异常换行": UI_SPECIALIZED_LINEBREAK_PROMPT,
    "文字超框/溢出": UI_SPECIALIZED_OVERFLOW_PROMPT,
    "文字截断": UI_SPECIALIZED_TRUNCATION_PROMPT,
    "文字重叠": UI_SPECIALIZED_OVERLAP_PROMPT,
    "乱码/编码问题": UI_SPECIALIZED_GARBLED_PROMPT,
}


def get_ocr_prompt(languages: list[str] = None) -> str:
    lang_hint = ""
    if languages:
        lang_hint = f"重点关注以下语言：{', '.join(languages)}。"
    return OCR_PROMPT_TEMPLATE.format(lang_hint=lang_hint)


def get_ui_check_prompt() -> str:
    return UI_CHECK_PROMPT


def get_ui_structure_planner_prompt() -> str:
    return UI_STRUCTURE_PLANNER_PROMPT


def get_ui_specialized_agent_prompt(issue_type: str) -> str:
    return UI_SPECIALIZED_AGENT_PROMPTS.get(issue_type, "")
