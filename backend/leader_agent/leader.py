"""
Leader Agent：根据「预期 vs 实际」与当前提示词，调用视觉模型生成修改后的完整提示词。
"""

import base64
import importlib.util
import re
import os

# 明确加载 backend 根目录的 config（与 leader_agent.config 区分）
_backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "backend_config",
    os.path.join(_backend_root, "config.py"),
)
_backend_config = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_backend_config)
config = _backend_config.config
from leader_agent.prompts import LEADER_SYSTEM, build_leader_user
from leader_agent.prompts import build_leader_user_batch

if config.LANGFUSE_ENABLED and config.LANGFUSE_SECRET_KEY:
    from langfuse.openai import OpenAI
else:
    from openai import OpenAI


def _encode_image(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode("utf-8")


def _detection_reason(expected_has_issues: bool, result_has_issues: bool, result_summary: str, result_issues: list) -> str:
    """根据预期与实际结果生成检测原因，供 Leader 灵活调整提示词。"""
    if expected_has_issues and not result_has_issues:
        # 漏报：预期有问题但判为无问题
        types = [i.get("type", "") for i in (result_issues or []) if i.get("type")]
        if types:
            return f"漏报：预期有问题但模型判为无问题。模型未检出以下类型的问题，请针对性地加强相关判定标准：{', '.join(types)}。"
        return "漏报：预期有问题但模型判为无问题，需加强对截断/乱码/异常换行/溢出/重叠等的检出，避免漏报。"
    if not expected_has_issues and result_has_issues:
        # 误报：预期无问题但判为有问题
        types = [i.get("type", "") for i in (result_issues or []) if i.get("type")]
        if types:
            return f"误报：预期无问题但模型判为有问题。模型误报了以下类型，请强调仅在有明确可见证据时才记入：{', '.join(types)}。"
        return "误报：预期无问题但模型判为有问题，需强调仅在有明确可见、可指出的证据时才记入问题，禁止联想与推测，减少误报。"
    return ""


def revise_prompt(
    image_bytes: bytes,
    current_prompt: str,
    expected_has_issues: bool,
    result_has_issues: bool,
    result_summary: str,
    result_score: int,
    result_issues: list,
    image_source: str,
    detection_reason: str = "",
    rag_context: list[dict] = None,
) -> str:
    """
    根据当前提示词、预期、language_agent 返回结果与检测原因，用 Leader 视觉模型生成新的完整提示词。
    
    Args:
        image_bytes: 当前图片（供 Leader 参考）
        current_prompt: 当前使用的 UI 检测提示词
        expected_has_issues: 预期是否有问题（True=有问题文件夹，False=没问题文件夹）
        result_has_issues: language_agent 返回的 has_issues
        result_summary: language_agent 返回的 summary
        result_score: language_agent 返回的 score
        result_issues: language_agent 返回的 issues 列表
        image_source: 来源文件夹描述，如 "有问题" / "没问题"
        detection_reason: 可选，检测原因描述；若为空则根据 expected/result 自动生成
    
    Returns:
        修改后的完整提示词（纯文本）
    """
    issues_preview = ""
    if result_issues:
        parts = [f"{i.get('type', '')}: {i.get('description', '')[:80]}" for i in result_issues[:5]]
        issues_preview = "; ".join(parts)
    else:
        issues_preview = "（无）"

    if not detection_reason.strip():
        detection_reason = _detection_reason(expected_has_issues, result_has_issues, result_summary or "", result_issues or [])

    user_text = build_leader_user(
        current_prompt=current_prompt,
        expected_has_issues=expected_has_issues,
        result_has_issues=result_has_issues,
        result_summary=result_summary or "",
        result_score=result_score,
        result_issues_preview=issues_preview,
        image_source=image_source,
        detection_reason=detection_reason,
        rag_context=rag_context or [],
    )

    client = OpenAI(
        api_key=config.LVM_API_KEY,
        base_url=config.LVM_BASE_URL,
    )
    b64 = _encode_image(image_bytes)
    response = client.chat.completions.create(
        model=config.LVM_MODEL,
        messages=[
            {"role": "system", "content": LEADER_SYSTEM},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    },
                    {"type": "text", "text": user_text},
                ],
            },
        ],
        max_tokens=8000,
        name="leader-prompt-revise-single",
        metadata={"pipeline": "leader_train", "stage": "revise_single", "model": config.LVM_MODEL},
    )
    new_prompt = (response.choices[0].message.content or "").strip()
    # 去掉可能的 markdown 代码块
    if new_prompt.startswith("```"):
        new_prompt = re.sub(r"^```\w*\n?", "", new_prompt)
    if new_prompt.endswith("```"):
        new_prompt = re.sub(r"\n?```\s*$", "", new_prompt)
    return new_prompt.strip()


def revise_prompt_batch(
    current_prompt: str,
    detection_reason: str,
    examples: list[dict],
    rag_context: list[dict] = None,
) -> str:
    """
    A 方案（批量策略）：基于多张失败样本集中修订提示词，输出修改后的完整提示词。

    Args:
        current_prompt: 当前 UI 检测提示词
        detection_reason: 本轮整体失败概述（漏报/误报汇总）
        examples: 失败样本列表（每项包含 image_bytes/expected/result/summary/issues 等）
        rag_context: 可选，历史类似案例

    Returns:
        修改后的完整提示词（纯文本）
    """
    # 最多取 3 张样本，避免上下文过长
    examples = (examples or [])[:3]
    user_text = build_leader_user_batch(
        current_prompt=current_prompt,
        detection_reason=detection_reason,
        examples=examples,
        rag_context=rag_context or [],
    )

    client = OpenAI(
        api_key=config.LVM_API_KEY,
        base_url=config.LVM_BASE_URL,
    )

    content_parts = []
    for ex in examples:
        b64 = _encode_image(ex.get("image_bytes") or b"")
        if b64:
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}"},
            })
    content_parts.append({"type": "text", "text": user_text})

    response = client.chat.completions.create(
        model=config.LVM_MODEL,
        messages=[
            {"role": "system", "content": LEADER_SYSTEM},
            {"role": "user", "content": content_parts},
        ],
        max_tokens=8000,
        name="leader-prompt-revise-batch",
        metadata={"pipeline": "leader_train", "stage": "revise_batch", "model": config.LVM_MODEL, "example_count": len(examples)},
    )
    new_prompt = (response.choices[0].message.content or "").strip()
    # 去掉可能的 markdown 代码块
    if new_prompt.startswith("```"):
        new_prompt = re.sub(r"^```\w*\n?", "", new_prompt)
    if new_prompt.endswith("```"):
        new_prompt = re.sub(r"\n?```\s*$", "", new_prompt)
    return new_prompt.strip()
