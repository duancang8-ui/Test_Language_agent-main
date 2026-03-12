"""Leader Agent 用于修改 UI 检测提示词的系统/用户提示。"""

LEADER_SYSTEM = """你是一个「提示词优化专家」，负责**仅根据检测原因（漏报/误报）灵活调整**发给「文字显示检测模型」的提示词。

**重要：仅当检测结果与预期不一致（漏报或误报）时才调整提示词。若失败原因为 API 限流(429)、请求过多、网络超时等，则不应调整提示词（由用户增大请求间隔或重试解决）。**

你的任务：根据「本次检测原因」（必读，会明确写出漏报/误报及具体问题类型）、「当前提示词」「图片预期 vs 实际返回」，输出**修改后的完整提示词**（整段可被直接替换使用），使检测模型在同类图片上更符合预期。

**必须严格依据本次检测原因做针对性调整，不得泛泛而谈：**
1. **漏报（预期有问题但判为无问题）**：在提示词中加强「必须检出截断/乱码/异常换行/溢出/重叠」的表述，强化边缘检查、右侧裁切、形近字错显等判定标准，避免漏报。
2. **误报（预期无问题但判为有问题）**：在提示词中强调「仅在有明确可见、可指出的证据时才记入问题」「禁止联想、推测、臆测」「无确定证据则 issues 为空、score 高分」。
3. 若检测原因中提及具体问题类型（如只漏检截断、只误报换行），则**针对该类型做重点增删**，其余部分保持稳定。
4. 只输出修改后的**完整新提示词**，不要输出解释；保持为可执行的检测指令（JSON 输出格式等不变），纯文本、无 markdown 代码块包裹。
"""


def build_leader_user(
    current_prompt: str,
    expected_has_issues: bool,
    result_has_issues: bool,
    result_summary: str,
    result_score: int,
    result_issues_preview: str,
    image_source: str,
    detection_reason: str = "",
    rag_context: list[dict] = None,
) -> str:
    """构建发给 Leader 的用户消息（不含图片；图片由调用方作为 vision 内容附加）。检测原因放在最前；可选 RAG 历史案例。"""
    expected_label = "有文字显示问题" if expected_has_issues else "无问题"
    actual_label = "判为有问题" if result_has_issues else "判为无问题"
    reason_block = f"""【必读】本次检测原因（请严格据此做针对性调整，不得泛泛而谈）：
{detection_reason}

""" if detection_reason.strip() else ""
    rag_block = ""
    if rag_context and len(rag_context) > 0:
        parts = ["以下为历史类似案例的提示词修改，供参考（可借鉴思路，但须结合本次检测原因输出完整新提示词）："]
        for i, ctx in enumerate(rag_context[:3], 1):
            reason = (ctx.get("detection_reason") or "")[:400]
            prompt = (ctx.get("prompt_after") or "")[:1500]
            parts.append(f"\n[案例{i}] 检测原因：{reason}\n修改后提示词（节选）：{prompt}...")
        rag_block = "\n".join(parts) + "\n\n"
    return f"""{reason_block}{rag_block}本张图片来自「{image_source}」文件夹，预期：**{expected_label}**；实际：**{actual_label}**。
summary：{result_summary!r}；score：{result_score}；issues 摘要：{result_issues_preview}。

当前使用的检测提示词如下：

---
{current_prompt}
---

请**严格根据上述检测原因**输出修改后的**完整检测提示词**（整段可直接替换），针对漏报或误报做对应增删。只输出提示词正文，不要用 markdown 或解释。"""


def build_leader_user_batch(
    current_prompt: str,
    detection_reason: str,
    examples: list[dict],
    rag_context: list[dict] = None,
) -> str:
    """
    A 方案：批量提示词优化（多失败样本汇总）。
    examples 每项字段建议包含：
    - filename
    - image_source
    - expected_has_issues
    - result_has_issues
    - result_summary
    - result_score
    - result_issues
    - detection_reason
    """
    rag_block = ""
    if rag_context and len(rag_context) > 0:
        parts = ["以下为历史类似案例的提示词修改，供参考（可借鉴思路，但须结合本次批量检测原因输出完整新提示词）："]
        for i, ctx in enumerate(rag_context[:3], 1):
            reason = (ctx.get("detection_reason") or "")[:400]
            prompt = (ctx.get("prompt_after") or "")[:1500]
            parts.append(f"\n[案例{i}] 检测原因：{reason}\n修改后提示词（节选）：{prompt}...")
        rag_block = "\n".join(parts) + "\n\n"

    ex_lines = []
    for i, ex in enumerate((examples or [])[:3], 1):
        expected_label = "有文字显示问题" if ex.get("expected_has_issues") else "无问题"
        actual_label = "判为有问题" if ex.get("result_has_issues") else "判为无问题"
        issues = ex.get("result_issues") or []
        issues_preview = ""
        if issues:
            parts = [f"{it.get('type','')}: {(it.get('description','') or '')[:60]}" for it in issues[:4]]
            issues_preview = "; ".join(parts)
        else:
            issues_preview = "（无）"
        ex_lines.append(
            f"[样本{i}] 文件={ex.get('filename','')}, 来源={ex.get('image_source','')}\n"
            f"预期：{expected_label}；实际：{actual_label}\n"
            f"本样本检测原因：{ex.get('detection_reason','')}\n"
            f"summary：{(ex.get('result_summary') or '')!r}\n"
            f"score：{ex.get('result_score', 0)}；issues 摘要：{issues_preview}\n"
        )
    examples_block = "\n".join(ex_lines).strip() or "（无可用失败样本）"

    return f"""【必读】本轮批量检测原因（请严格据此做针对性调整，避免泛泛而谈）：\n{detection_reason}\n\n{rag_block}以下为失败样本摘要（图片已随消息提供，请结合图片与摘要修订提示词）：\n\n{examples_block}\n\n当前使用的检测提示词如下：\n\n---\n{current_prompt}\n---\n\n请输出修改后的**完整检测提示词**（整段可直接替换）。要求：\n1) 必须严格依据本轮检测原因与失败样本做“最小且有效”的增删；\n2) 明确区分漏报/误报：漏报则加强判定标准，误报则收紧证据原则；\n3) 不能为了通过某一张图而引入新的误报/漏报（要保证整体回归更稳定）；\n4) 只输出提示词正文，不要用 markdown 代码块或解释。"""
