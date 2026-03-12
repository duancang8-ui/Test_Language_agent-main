import base64
import asyncio
import json
import re
import time
from io import BytesIO
from typing import TypedDict, Any
from PIL import Image
from config import config
from prompts import (
    get_ui_structure_planner_prompt,
    get_ui_specialized_agent_prompt,
)
from langgraph.graph import StateGraph, START, END

if config.LANGFUSE_ENABLED and config.LANGFUSE_SECRET_KEY:
    from langfuse.openai import OpenAI
else:
    from openai import OpenAI

class UICheckGraphState(TypedDict, total=False):
    image_bytes: bytes
    full_data_url: str
    crops: list[dict]
    structure_ok: bool | None
    structure_assessment: str
    issues: list[dict]
    agent_process: list[dict]
    result: dict[str, Any]

class UICheckService:
    """UI 文字显示检测服务"""
    
    def __init__(self):
        self.client = OpenAI(
            api_key=config.LVM_API_KEY,
            base_url=config.LVM_BASE_URL
        )
        self.model = config.LVM_MODEL
        self.multi_agent_graph = self._build_multi_agent_graph()

    def _trace(self, msg: str):
        # 独立开关：仅在 UI_CHECK_TRACE=true 时输出多 Agent 细粒度日志
        if getattr(config, "UI_CHECK_TRACE", False):
            print(f"[UI_CHECK_TRACE] {msg}")
    
    def encode_image(self, image_bytes: bytes) -> str:
        """将图片编码为 base64"""
        return base64.b64encode(image_bytes).decode("utf-8")

    def _image_data_url(self, image_bytes: bytes) -> str:
        return f"data:image/png;base64,{self.encode_image(image_bytes)}"

    def _try_parse_json(self, text: str) -> dict | None:
        if not text:
            return None
        text = text.strip()
        try:
            return json.loads(text)
        except Exception:
            pass
        json_match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except Exception:
                pass
        json_obj_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
        if json_obj_match:
            try:
                return json.loads(json_obj_match.group(0))
            except Exception:
                pass
        return None

    def _chat_once(
        self,
        content: list,
        max_tokens: int = 3000,
        trace_name: str = "language-agent-ui-check-multi",
        trace_metadata: dict | None = None,
    ) -> dict:
        meta = {"model": self.model, "pipeline": "ui_check"}
        if trace_metadata:
            meta.update(trace_metadata)
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": content}],
            max_tokens=max_tokens,
            temperature=0,
            name=trace_name,
            metadata=meta,
        )
        result_text = response.choices[0].message.content or ""
        if config.DEBUG:
            print("=" * 80)
            print("UI 检测子Agent原始响应:")
            print(result_text)
            print("=" * 80)
        parsed = self._try_parse_json(result_text)
        return {"raw": result_text, "parsed": parsed}

    async def _graph_chat_once(
        self,
        content: list,
        max_tokens: int = 3000,
        trace_name: str = "language-agent-ui-check-multi",
        trace_metadata: dict | None = None,
    ) -> dict:
        # LangGraph 节点里复用现有 OpenAI 调用，避免 LangChain 版本兼容问题
        return await asyncio.to_thread(self._chat_once, content, max_tokens, trace_name, trace_metadata)

    def _parse_has_issue(self, parsed: dict) -> bool:
        # 兼容不同模型返回风格：has_issue / found / result("有问题|无问题")
        has_issue = parsed.get("has_issue", None)
        if isinstance(has_issue, bool):
            return has_issue
        found = parsed.get("found", None)
        if isinstance(found, bool):
            return found
        result_field = str(parsed.get("result", "")).strip().lower()
        if result_field:
            if any(k in result_field for k in ["有问题", "存在问题", "problem", "issue", "true"]):
                return True
            if any(k in result_field for k in ["无问题", "未发现", "no issue", "false", "ok"]):
                return False
        return False

    def _build_multi_agent_graph(self):
        graph = StateGraph(UICheckGraphState)

        async def planner_node(state: UICheckGraphState):
            image_bytes = state["image_bytes"]
            full_data_url = self._image_data_url(image_bytes)
            planner_out = await self._graph_chat_once(
                [
                    {"type": "image_url", "image_url": {"url": full_data_url}},
                    {"type": "text", "text": get_ui_structure_planner_prompt()},
                ],
                trace_name="ui-structure-planner",
                trace_metadata={"agent_type": "structure", "stage": "planner"},
            )
            planner = planner_out.get("parsed") or {}
            structure_ok = planner.get("structure_ok")
            structure_assessment = (planner.get("structure_assessment") or "").strip()
            planner_regions = planner.get("focus_regions") or []
            focus_regions = self._default_focus_regions() + planner_regions
            crops = self._make_crops(image_bytes, focus_regions, max_crops=6)
            self._trace(
                f"planner: structure_ok={structure_ok}, focus_regions={len(focus_regions)}, crops={len(crops)}, "
                f"structure_assessment={(structure_assessment or 'N/A')[:120]}"
            )
            return {
                "full_data_url": full_data_url,
                "crops": crops,
                "structure_ok": structure_ok,
                "structure_assessment": structure_assessment,
                "issues": [],
                "agent_process": [],
            }

        async def run_specialized_agent(
            issue_type: str,
            full_data_url: str,
            crops: list[dict],
        ) -> tuple[list[dict], dict]:
            """单个专项 Agent 的核心逻辑，返回 (issues, agent_process_entry)"""
            agent_slug = {
                "异常换行": "linebreak",
                "文字超框/溢出": "overflow",
                "文字截断": "truncation",
                "文字重叠": "overlap",
                "乱码/编码问题": "garbled",
            }.get(issue_type, "unknown")
            content = [{"type": "image_url", "image_url": {"url": full_data_url}}]
            for c in crops:
                content.append({"type": "image_url", "image_url": {"url": c["data_url"]}})
            content.append({"type": "text", "text": get_ui_specialized_agent_prompt(issue_type)})

            vote_runs = 2 if issue_type in ["文字超框/溢出", "文字截断"] else 1
            vote_has_issue = []
            vote_reasons = []
            vote_issues = []
            agent_t0 = time.perf_counter()
            for round_idx in range(vote_runs):
                out = await self._graph_chat_once(
                    content,
                    trace_name=f"ui-agent-{agent_slug}",
                    trace_metadata={
                        "agent_type": issue_type,
                        "stage": "specialized",
                        "round": round_idx + 1,
                        "vote_runs": vote_runs,
                    },
                )
                parsed = out.get("parsed") or {}
                has_issue = self._parse_has_issue(parsed)
                reason = (
                    (parsed.get("reason") or "").strip()
                    or (parsed.get("note") or "").strip()
                    or "未发现该类型明确可见证据。"
                )
                p_issues = parsed.get("issues") or []
                if not p_issues and parsed.get("evidence"):
                    ev = parsed.get("evidence")
                    if isinstance(ev, list):
                        reason = reason if reason != "未发现该类型明确可见证据。" else "；".join([str(x) for x in ev[:3]])
                if has_issue and not p_issues:
                    p_issues = [{
                        "type": issue_type,
                        "description": reason,
                        "location": "需要进一步检查",
                        "severity": "medium",
                        "suggestion": "建议复核对应区域布局与文字渲染。",
                    }]
                vote_has_issue.append(bool(has_issue))
                vote_reasons.append(reason)
                if p_issues:
                    vote_issues.extend(p_issues)
                self._trace(
                    f"agent={issue_type} round={round_idx + 1}/{vote_runs} has_issue={bool(has_issue)} "
                    f"issues_count={len(p_issues)} reason={(reason or '')[:120]}"
                )

            has_issue = any(vote_has_issue)
            reason = next(
                (r for i, r in enumerate(vote_reasons) if vote_has_issue[i] and r),
                vote_reasons[0] if vote_reasons else "未发现该类型明确可见证据。",
            )
            for i in vote_issues:
                if not i.get("type"):
                    i["type"] = issue_type
            agent_elapsed_ms = int((time.perf_counter() - agent_t0) * 1000)
            agent_entry = {
                "agent": f"{issue_type}Agent",
                "issue_type": issue_type,
                "has_issue": has_issue,
                "reason": reason if vote_runs == 1 else f"{reason}（复检投票: {sum(vote_has_issue)}/{vote_runs}）",
                "model_elapsed_ms": agent_elapsed_ms,
                "rounds": vote_runs,
            }
            self._trace(
                f"agent={issue_type} final_has_issue={has_issue} vote={sum(vote_has_issue)}/{vote_runs} total_issues={len(vote_issues)}"
            )
            return vote_issues, agent_entry

        async def parallel_agents_node(state: UICheckGraphState):
            full_data_url = state["full_data_url"]
            crops = state.get("crops", [])
            issue_types = ["异常换行", "文字超框/溢出", "文字截断", "文字重叠", "乱码/编码问题"]
            results = await asyncio.gather(
                *[run_specialized_agent(t, full_data_url, crops) for t in issue_types]
            )
            issues: list[dict] = []
            agent_process: list[dict] = []
            for agent_issues, agent_entry in results:
                issues.extend(agent_issues)
                agent_process.append(agent_entry)
            return {"issues": issues, "agent_process": agent_process}

        async def finalize_node(state: UICheckGraphState):
            image_bytes = state["image_bytes"]
            issues = list(state.get("issues", []))
            agent_process = list(state.get("agent_process", []))
            structure_ok = state.get("structure_ok")
            structure_assessment = (state.get("structure_assessment") or "").strip()

            hard_overflow_risk = self._detect_cta_right_edge_risk(image_bytes)
            if hard_overflow_risk:
                has_overflow_issue_now = any(
                    (i.get("type") == "文字超框/溢出" or "超框" in i.get("type", "") or "溢出" in i.get("type", ""))
                    for i in issues
                )
                if not has_overflow_issue_now:
                    issues.append({
                        "type": "文字超框/溢出",
                        "description": "规则检测到按钮文案右端安全边距过小，存在贴边/超框风险。",
                        "location": "底部主按钮右端",
                        "severity": "medium",
                        "suggestion": "建议增加按钮右内边距或按钮宽度（推荐 +6~10px），并复测多语言长度。",
                    })
                    for step in agent_process:
                        if step.get("issue_type") == "文字超框/溢出":
                            step["has_issue"] = True
                            step["reason"] = "规则兜底：检测到按钮文案右端安全边距不足（硬阈值触发）。"
                            break
                    self._trace("hard-rule: cta right-edge risk detected -> inject overflow issue")

            structure_has_issue = (structure_ok is False)
            if structure_has_issue:
                issues.append({
                    "type": "UI 结构/布局问题",
                    "description": structure_assessment or "检测到整体 UI 结构/布局异常。",
                    "location": "全图",
                    "severity": "medium",
                    "suggestion": "检查布局层级、容器尺寸与组件关系，修复错位/遮挡。",
                })
            agent_process.append({
                "agent": "结构Agent",
                "issue_type": "UI 结构/布局问题",
                "has_issue": structure_has_issue,
                "reason": structure_assessment or "未发现该类型明确可见证据。",
            })

            has_issues = len(issues) > 0
            penalty = 0
            for i in issues:
                sev = (i.get("severity") or "medium").lower()
                if sev == "high":
                    penalty += 25
                elif sev == "low":
                    penalty += 8
                else:
                    penalty += 15
            score = max(0, 100 - penalty)
            if any((i.get("type") in ["文字截断", "文字重叠", "乱码/编码问题"]) for i in issues):
                score = min(score, 79)
            main_types = "、".join(sorted(set([i.get("type", "") for i in issues if i.get("type")]))) if issues else "无"
            summary = (
                f"问题总数：{len(issues)}。主要类型：{main_types}。"
                f"结构判断：{'异常' if structure_has_issue else '正常'}。"
                + ("已发现可见证据问题，建议修复后复测。" if has_issues else "未发现明确可见问题。")
            )

            result = {
                "has_issues": has_issues,
                "issues": issues,
                "summary": summary,
                "score": score,
                "structure_ok": structure_ok,
                "structure_assessment": structure_assessment,
                "agent_process": agent_process,
            }
            result = self.validate_result(result, image_bytes, summary)
            result["agent_process"] = self._normalize_agent_process(result)
            self._trace(
                f"final: has_issues={result.get('has_issues', has_issues)} score={result.get('score', score)} "
                f"issues={len(result.get('issues', []))}"
            )
            return {"result": result}

        graph.add_node("planner", planner_node)
        graph.add_node("parallel_agents", parallel_agents_node)
        graph.add_node("finalize", finalize_node)

        graph.add_edge(START, "planner")
        graph.add_edge("planner", "parallel_agents")
        graph.add_edge("parallel_agents", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile()

    def _default_focus_regions(self) -> list[dict]:
        """
        兜底聚焦区域：
        - 底部中间按钮/文案区域（高频出现贴边、截断）
        - 中下部内容区（兼顾分数/标签等局部）
        """
        return [
            {
                "name": "bottom_action_area",
                "x1": 0.12,
                "y1": 0.72,
                "x2": 0.92,
                "y2": 0.96,
                "reason": "兜底复核底部按钮与文案，避免末尾贴边漏检",
            },
            {
                "name": "cta_button_tight",
                "x1": 0.24,
                "y1": 0.76,
                "x2": 0.84,
                "y2": 0.91,
                "reason": "紧裁剪主按钮区域，放大按钮文案边距细节",
            },
            {
                "name": "cta_text_right_edge",
                "x1": 0.58,
                "y1": 0.76,
                "x2": 0.88,
                "y2": 0.91,
                "reason": "专门复核按钮文案右端字符是否贴边/压边",
            },
            {
                "name": "lower_middle_area",
                "x1": 0.20,
                "y1": 0.52,
                "x2": 0.86,
                "y2": 0.82,
                "reason": "兜底复核中下部标签/按钮文字",
            },
        ]

    def _detect_cta_right_edge_risk(self, image_bytes: bytes) -> bool:
        """
        规则化硬阈值检测（不依赖 LLM）：
        - 对主按钮区域做灰度分析，估计“右侧有效暗色笔画”距裁剪右边界的安全边距。
        - 若边距过小，判为贴边/超框风险。
        """
        try:
            img = Image.open(BytesIO(image_bytes)).convert("RGB")
            w, h = img.size
            # 与默认 focus 区域保持一致：主按钮紧裁剪
            x1, y1, x2, y2 = 0.24, 0.76, 0.84, 0.91
            px1, py1 = int(x1 * w), int(y1 * h)
            px2, py2 = int(x2 * w), int(y2 * h)
            if px2 - px1 < 24 or py2 - py1 < 12:
                return False

            crop = img.crop((px1, py1, px2, py2)).convert("L")
            cw, ch = crop.size
            pixels = crop.load()

            # 仅看中间带，尽量避开按钮圆角和边框
            xs = int(cw * 0.08)
            xe = int(cw * 0.98)
            ys = int(ch * 0.20)
            ye = int(ch * 0.82)
            if xe - xs < 12 or ye - ys < 8:
                return False

            vals = []
            for x in range(xs, xe):
                for y in range(ys, ye):
                    vals.append(pixels[x, y])
            if not vals:
                return False

            mean_v = sum(vals) / len(vals)
            # 动态暗色阈值：兼容不同按钮底色
            dark_th = min(170, max(85, int(mean_v * 0.72)))
            band_h = max(1, ye - ys)
            rightmost_text_x = None
            for x in range(xs, xe):
                dark_cnt = 0
                for y in range(ys, ye):
                    if pixels[x, y] <= dark_th:
                        dark_cnt += 1
                ratio = dark_cnt / band_h
                # 过滤噪声与边框列（边框通常接近整列连续暗色）
                if 0.02 <= ratio <= 0.65:
                    rightmost_text_x = x

            if rightmost_text_x is None:
                return False

            margin_px = (xe - 1) - rightmost_text_x
            margin_th = max(2, int((xe - xs) * 0.03))
            return margin_px <= margin_th
        except Exception:
            return False

    def _make_crops(self, image_bytes: bytes, regions: list[dict], max_crops: int = 4) -> list[dict]:
        crops = []
        try:
            img = Image.open(BytesIO(image_bytes)).convert("RGB")
            w, h = img.size
            for r in (regions or [])[:max_crops]:
                try:
                    x1 = float(r.get("x1", 0))
                    y1 = float(r.get("y1", 0))
                    x2 = float(r.get("x2", 1))
                    y2 = float(r.get("y2", 1))
                except Exception:
                    continue
                x1 = max(0.0, min(1.0, x1))
                y1 = max(0.0, min(1.0, y1))
                x2 = max(0.0, min(1.0, x2))
                y2 = max(0.0, min(1.0, y2))
                if x2 <= x1 or y2 <= y1:
                    continue
                px1, py1 = int(x1 * w), int(y1 * h)
                px2, py2 = int(x2 * w), int(y2 * h)
                if (px2 - px1) < 8 or (py2 - py1) < 8:
                    continue
                cropped = img.crop((px1, py1, px2, py2))
                buf = BytesIO()
                cropped.save(buf, format="PNG")
                crop_bytes = buf.getvalue()
                crops.append({
                    "name": r.get("name") or "focus",
                    "reason": r.get("reason") or "",
                    "data_url": self._image_data_url(crop_bytes),
                })
        except Exception:
            return []
        return crops

    async def _check_ui_issues_multi_agent(self, image_bytes: bytes) -> dict:
        """两阶段：结构Agent全图规划 -> 裁剪图送5个专项Agent。"""
        wall_t0 = time.perf_counter()
        # 主流程：LangGraph 编排
        try:
            state = await self.multi_agent_graph.ainvoke({"image_bytes": image_bytes})
            result = (state or {}).get("result") or {}
            wall_elapsed_ms = int((time.perf_counter() - wall_t0) * 1000)
            agent_process = result.get("agent_process", self._normalize_agent_process(result))
            elapsed_ms = sum(a.get("model_elapsed_ms", 0) for a in agent_process)
            return {
                "success": True,
                "has_issues": result.get("has_issues", False),
                "issues": result.get("issues", []),
                "summary": result.get("summary", ""),
                "score": result.get("score", 100),
                "structure_ok": result.get("structure_ok"),
                "structure_assessment": result.get("structure_assessment", ""),
                "agent_process": agent_process,
                "elapsed_ms": elapsed_ms,
                "wall_elapsed_ms": wall_elapsed_ms,
                "message": "检测完成"
            }
        except Exception as e:
            self._trace(f"langgraph failed, fallback to legacy flow: {str(e)}")

        # 兜底：保留原有流程，避免迁移期间服务不可用
        full_data_url = self._image_data_url(image_bytes)

        # 1) 结构 Agent（全图）
        planner_out = self._chat_once(
            [
                {"type": "image_url", "image_url": {"url": full_data_url}},
                {"type": "text", "text": get_ui_structure_planner_prompt()},
            ],
            trace_name="ui-structure-planner",
            trace_metadata={"agent_type": "structure", "stage": "planner", "path": "legacy"},
        )
        planner = planner_out.get("parsed") or {}
        structure_ok = planner.get("structure_ok")
        structure_assessment = (planner.get("structure_assessment") or "").strip()
        planner_regions = planner.get("focus_regions") or []
        # 关键修复：兜底区域必须优先，避免被 planner 前 4 个区域挤掉
        focus_regions = self._default_focus_regions() + planner_regions
        crops = self._make_crops(image_bytes, focus_regions, max_crops=6)
        self._trace(
            f"planner: structure_ok={structure_ok}, focus_regions={len(focus_regions)}, crops={len(crops)}, "
            f"structure_assessment={(structure_assessment or 'N/A')[:120]}"
        )

        # 2) 5 个专项 Agent（全图 + 裁剪图）
        agent_types = ["异常换行", "文字超框/溢出", "文字截断", "文字重叠", "乱码/编码问题"]
        issues = []
        agent_process = []
        for t in agent_types:
            content = [{"type": "image_url", "image_url": {"url": full_data_url}}]
            for c in crops:
                content.append({"type": "image_url", "image_url": {"url": c["data_url"]}})
            content.append({"type": "text", "text": get_ui_specialized_agent_prompt(t)})
            vote_runs = 2 if t in ["文字超框/溢出", "文字截断"] else 1
            vote_has_issue = []
            vote_reasons = []
            vote_issues = []
            legacy_agent_t0 = time.perf_counter()
            for round_idx in range(vote_runs):
                agent_slug = {
                    "异常换行": "linebreak",
                    "文字超框/溢出": "overflow",
                    "文字截断": "truncation",
                    "文字重叠": "overlap",
                    "乱码/编码问题": "garbled",
                }.get(t, "unknown")
                out = self._chat_once(
                    content,
                    trace_name=f"ui-agent-{agent_slug}",
                    trace_metadata={
                        "agent_type": t,
                        "stage": "specialized",
                        "round": round_idx + 1,
                        "vote_runs": vote_runs,
                        "path": "legacy",
                    },
                )
                parsed = out.get("parsed") or {}
                # 兼容不同模型返回风格：has_issue / found / result("有问题|无问题")
                has_issue = parsed.get("has_issue", None)
                if not isinstance(has_issue, bool):
                    found = parsed.get("found", None)
                    if isinstance(found, bool):
                        has_issue = found
                if not isinstance(has_issue, bool):
                    result_field = str(parsed.get("result", "")).strip().lower()
                    if result_field:
                        if any(k in result_field for k in ["有问题", "存在问题", "problem", "issue", "true"]):
                            has_issue = True
                        elif any(k in result_field for k in ["无问题", "未发现", "no issue", "false", "ok"]):
                            has_issue = False
                if not isinstance(has_issue, bool):
                    has_issue = False

                reason = (
                    (parsed.get("reason") or "").strip()
                    or (parsed.get("note") or "").strip()
                    or "未发现该类型明确可见证据。"
                )
                p_issues = parsed.get("issues") or []
                # 部分模型会返回 evidence 而不是 issues
                if not p_issues and parsed.get("evidence"):
                    ev = parsed.get("evidence")
                    if isinstance(ev, list):
                        reason = reason if reason != "未发现该类型明确可见证据。" else "；".join([str(x) for x in ev[:3]])
                if has_issue and not p_issues:
                    p_issues = [{
                        "type": t,
                        "description": reason,
                        "location": "需要进一步检查",
                        "severity": "medium",
                        "suggestion": "建议复核对应区域布局与文字渲染。",
                    }]

                vote_has_issue.append(bool(has_issue))
                vote_reasons.append(reason)
                if p_issues:
                    vote_issues.extend(p_issues)
                self._trace(
                    f"agent={t} round={round_idx + 1}/{vote_runs} has_issue={bool(has_issue)} "
                    f"issues_count={len(p_issues)} reason={(reason or '')[:120]}"
                )

            has_issue = any(vote_has_issue)
            reason = next((r for i, r in enumerate(vote_reasons) if vote_has_issue[i] and r), vote_reasons[0] if vote_reasons else "未发现该类型明确可见证据。")
            p_issues = vote_issues
            for i in p_issues:
                if not i.get("type"):
                    i["type"] = t
            issues.extend(p_issues)
            legacy_agent_elapsed_ms = int((time.perf_counter() - legacy_agent_t0) * 1000)
            agent_process.append({
                "agent": f"{t}Agent",
                "issue_type": t,
                "has_issue": has_issue,
                "reason": reason if vote_runs == 1 else f"{reason}（复检投票: {sum(vote_has_issue)}/{vote_runs}）",
                "model_elapsed_ms": legacy_agent_elapsed_ms,
                "rounds": vote_runs,
            })
            self._trace(
                f"agent={t} final_has_issue={has_issue} vote={sum(vote_has_issue)}/{vote_runs} total_issues={len(p_issues)}"
            )

        # 2.5) 硬阈值兜底：按钮文案右端贴边风险（不依赖 LLM）
        hard_overflow_risk = self._detect_cta_right_edge_risk(image_bytes)
        if hard_overflow_risk:
            has_overflow_issue_now = any(
                (i.get("type") == "文字超框/溢出" or "超框" in i.get("type", "") or "溢出" in i.get("type", ""))
                for i in issues
            )
            if not has_overflow_issue_now:
                issues.append({
                    "type": "文字超框/溢出",
                    "description": "规则检测到按钮文案右端安全边距过小，存在贴边/超框风险。",
                    "location": "底部主按钮右端",
                    "severity": "medium",
                    "suggestion": "建议增加按钮右内边距或按钮宽度（推荐 +6~10px），并复测多语言长度。",
                })
                for step in agent_process:
                    if step.get("issue_type") == "文字超框/溢出":
                        step["has_issue"] = True
                        step["reason"] = "规则兜底：检测到按钮文案右端安全边距不足（硬阈值触发）。"
                        break
                self._trace("hard-rule: cta right-edge risk detected -> inject overflow issue")

        # 3) 结构 Agent 过程记录 + 结构问题并入 issues
        structure_has_issue = (structure_ok is False)
        if structure_has_issue:
            issues.append({
                "type": "UI 结构/布局问题",
                "description": structure_assessment or "检测到整体 UI 结构/布局异常。",
                "location": "全图",
                "severity": "medium",
                "suggestion": "检查布局层级、容器尺寸与组件关系，修复错位/遮挡。",
            })
        agent_process.append({
            "agent": "结构Agent",
            "issue_type": "UI 结构/布局问题",
            "has_issue": structure_has_issue,
            "reason": structure_assessment or "未发现该类型明确可见证据。",
        })

        # 4) 汇总
        has_issues = len(issues) > 0
        penalty = 0
        for i in issues:
            sev = (i.get("severity") or "medium").lower()
            if sev == "high":
                penalty += 25
            elif sev == "low":
                penalty += 8
            else:
                penalty += 15
        score = max(0, 100 - penalty)
        if any((i.get("type") in ["文字截断", "文字重叠"]) for i in issues):
            score = min(score, 79)
        main_types = "、".join(sorted(set([i.get("type", "") for i in issues if i.get("type")]))) if issues else "无"
        summary = (
            f"问题总数：{len(issues)}。主要类型：{main_types}。"
            f"结构判断：{'异常' if structure_has_issue else '正常'}。"
            + ("已发现可见证据问题，建议修复后复测。" if has_issues else "未发现明确可见问题。")
        )

        result = {
            "has_issues": has_issues,
            "issues": issues,
            "summary": summary,
            "score": score,
            "structure_ok": structure_ok,
            "structure_assessment": structure_assessment,
            "agent_process": agent_process,
        }
        result = self.validate_result(result, image_bytes, summary)
        result["agent_process"] = self._normalize_agent_process(result)
        wall_elapsed_ms = int((time.perf_counter() - wall_t0) * 1000)
        final_agent_process = result.get("agent_process", agent_process)
        elapsed_ms = sum(a.get("model_elapsed_ms", 0) for a in final_agent_process)
        self._trace(
            f"final: has_issues={result.get('has_issues', has_issues)} score={result.get('score', score)} "
            f"issues={len(result.get('issues', []))}"
        )
        return {
            "success": True,
            "has_issues": result.get("has_issues", has_issues),
            "issues": result.get("issues", []),
            "summary": result.get("summary", summary),
            "score": result.get("score", score),
            "structure_ok": result.get("structure_ok", structure_ok),
            "structure_assessment": result.get("structure_assessment", structure_assessment),
            "agent_process": final_agent_process,
            "elapsed_ms": elapsed_ms,
            "wall_elapsed_ms": wall_elapsed_ms,
            "message": "检测完成"
        }

    def _normalize_agent_process(self, result: dict) -> list[dict]:
        """统一 6 个专项 Agent 过程输出，确保前端可视化稳定。"""
        default_order = [
            ("异常换行Agent", "异常换行"),
            ("超框溢出Agent", "文字超框/溢出"),
            ("截断Agent", "文字截断"),
            ("重叠Agent", "文字重叠"),
            ("乱码Agent", "乱码/编码问题"),
            ("结构Agent", "UI 结构/布局问题"),
        ]
        issues = (result or {}).get("issues", []) or []
        structure_ok = (result or {}).get("structure_ok")
        provided = (result or {}).get("agent_process", []) or []

        inferred = {}
        for agent_name, issue_type in default_order:
            matched = [i for i in issues if (i.get("type") or "").strip() == issue_type]
            has_issue = len(matched) > 0
            if issue_type == "UI 结构/布局问题" and structure_ok is False:
                has_issue = True
            reason = "未发现该类型明确可见证据。"
            if matched:
                reason = (matched[0].get("description") or "发现该类型问题。").strip()
            elif issue_type == "UI 结构/布局问题":
                sa = ((result or {}).get("structure_assessment") or "").strip()
                if sa:
                    reason = sa
            inferred[issue_type] = {
                "agent": agent_name,
                "issue_type": issue_type,
                "has_issue": has_issue,
                "reason": reason,
            }

        for p in provided:
            t = (p.get("issue_type") or "").strip()
            if t in inferred:
                if isinstance(p.get("has_issue"), bool):
                    inferred[t]["has_issue"] = p["has_issue"]
                if p.get("reason"):
                    inferred[t]["reason"] = str(p["reason"]).strip()
                if p.get("agent"):
                    inferred[t]["agent"] = str(p["agent"]).strip()

        return [inferred[t] for _, t in default_order]
    
    def validate_result(self, result: dict, image_bytes: bytes, raw_response_text: str = "") -> dict:
        """
        验证和修正检测结果
        如果发现矛盾（如有截断但得分很高），自动修正
        这是从根源杜绝问题的关键机制
        """
        if not result:
            return result
        
        issues = result.get("issues", [])
        score = result.get("score", 100)
        has_issues = result.get("has_issues", False)

        # 规则0：先过滤“阴影/描边/浮雕”导致的截断误报
        shadow_like_keywords = ["阴影", "投影", "描边", "浮雕", "高光", "shadow", "outline", "emboss", "antialias"]
        hard_cut_evidence_keywords = ["裁切", "被切", "切掉", "缺失", "缺口", "不完整", "断裂", "clipped", "cut off", "missing stroke"]
        filtered_issues = []
        for issue in issues:
            issue_type = issue.get("type", "")
            text_blob = " ".join([
                str(issue.get("description", "")),
                str(issue.get("location", "")),
                str(issue.get("suggestion", "")),
            ]).lower()
            is_truncation_type = (issue_type == "文字截断" or "截断" in issue_type)
            mentions_shadow = any(k in text_blob for k in [kw.lower() for kw in shadow_like_keywords])
            has_hard_cut_evidence = any(k in text_blob for k in [kw.lower() for kw in hard_cut_evidence_keywords])
            if is_truncation_type and mentions_shadow and not has_hard_cut_evidence:
                if config.DEBUG:
                    print("⚠️ 过滤疑似阴影/描边导致的截断误报")
                continue

            # 规则0b：截图边界裁切不算截断（截图工具导致的边缘裁切）
            screenshot_boundary_keywords = ["截图边界", "截图边缘", "图片边缘", "图片边界", "screenshot edge", "screenshot border", "image border", "image edge"]
            if is_truncation_type and any(k in text_blob for k in screenshot_boundary_keywords):
                if config.DEBUG:
                    print("⚠️ 过滤截图边界裁切导致的截断误报")
                continue

            # 规则0c：滚动列表末项被视窗裁切不算截断
            scroll_viewport_keywords = ["滚动", "列表末项", "列表底部", "视窗", "viewport", "scroll", "last item", "bottom of list", "可滚动区域"]
            if is_truncation_type and any(k in text_blob for k in scroll_viewport_keywords):
                if config.DEBUG:
                    print("⚠️ 过滤滚动列表末项/视窗裁切导致的截断误报")
                continue

            filtered_issues.append(issue)
        issues = filtered_issues
        
        # 检查是否有截断问题
        has_truncation = any(
            issue.get("type") == "文字截断" or "截断" in issue.get("type", "")
            for issue in issues
        )
        
        # 检查是否有异常换行问题
        has_linebreak_issue = any(
            issue.get("type") == "异常换行" or "换行" in issue.get("type", "")
            for issue in issues
        )
        
        # 检查是否有乱码/形近字问题
        has_garbled_issue = any(
            issue.get("type") == "乱码/编码问题" or "乱码" in issue.get("type", "") or "编码" in issue.get("type", "")
            for issue in issues
        )
        
        # 检查是否有超框/溢出问题（包括贴边风险）
        has_overflow_issue = any(
            issue.get("type") == "文字超框/溢出" or "超框" in issue.get("type", "") or "溢出" in issue.get("type", "")
            for issue in issues
        )
        
        # 判断 summary 是否明确为「无问题」——若为无问题，则不再根据原始响应补全 issues（避免误报）
        summary_text = (result.get("summary") or "").strip()
        summary_says_no_issues = any(
            phrase in summary_text
            for phrase in [
                "未发现任何", "未发现任何文字显示问题", "无任何问题", "无截断", "无乱码",
                "无异常换行", "无溢出", "无重叠", "显示完美", "整体文字显示质量完美",
                "无截断、乱码、异常换行", "all characters", "无问题", "no text display issues",
                "共发现 0 个问题", "问题总数：0", "未见截断", "未见乱码", "均未见", "未见任何",
            ]
        )
        # 模型已返回「无问题」：issues 为空且得分高时，一律视为无问题，不再从原文补全或降分
        model_says_no_issues = (len(issues) == 0 and score >= 90)

        # 若 summary 明确为无问题，或模型已返回空 issues+高分，但 issues 非空（解析/补全导致），以「无问题」为准
        if (summary_says_no_issues or model_says_no_issues) and issues:
            if config.DEBUG:
                print("⚠️ summary/模型声明无问题但 issues 非空，以无问题为准，清除 issues")
            issues = []
            has_truncation = has_linebreak_issue = has_garbled_issue = False
            has_issues = False
            result["score"] = min(100, max(result.get("score", 100), 95))

        # 仅当未声明无问题且模型有 issues 或低分时，才考虑从原始响应补全；模型已空 issues+高分则跳过，避免误报
        if raw_response_text and not summary_says_no_issues and not model_says_no_issues and not has_truncation:
            # 明确肯定表述：存在/发现/有 + 截断/被切 等，排除“无截断”“未发现截断”
            truncation_positive = ["存在截断", "发现截断", "被截断", "有截断", "截断问题", "被切", "不完整", "truncat", "cut off", "incomplete"]
            truncation_negative = [
                "无截断", "无被切", "无不完整", "完整显示", "no truncat", "no cut", "未见截断",
                "未发现截断", "未见任何", "共发现 0 个问题", "阴影", "投影", "描边", "浮雕", "outline", "shadow"
            ]
            has_pos = any(k in raw_response_text for k in truncation_positive)
            has_neg = any(k in raw_response_text for k in truncation_negative)
            if has_pos and not has_neg:
                if config.DEBUG:
                    print("⚠️ 原始响应明确提到截断但结果中没有，自动添加截断问题")
                issues.append({
                    "type": "文字截断",
                    "description": "检测到文字截断问题（从原始响应中识别）",
                    "location": "需要进一步检查",
                    "severity": "high",
                    "suggestion": "检查图片边界和文字完整性"
                })
                has_truncation = True
                has_issues = True

        if raw_response_text and not summary_says_no_issues and not model_says_no_issues and not has_linebreak_issue:
            linebreak_positive = ["存在异常换行", "发现异常换行", "异常换行问题", "不合理换行", "单词分割", "word break", "line break"]
            linebreak_negative = ["无异常换行", "无不合理换行", "换行正常", "正常换行", "no line break"]
            has_pos = any(k in raw_response_text for k in linebreak_positive)
            has_neg = any(k in raw_response_text for k in linebreak_negative)
            if has_pos and not has_neg:
                if config.DEBUG:
                    print("⚠️ 原始响应明确提到异常换行但结果中没有，自动添加异常换行问题")
                issues.append({
                    "type": "异常换行",
                    "description": "检测到异常换行问题（从原始响应中识别）",
                    "location": "需要进一步检查",
                    "severity": "medium",
                    "suggestion": "检查文字换行位置是否合理"
                })
                has_linebreak_issue = True
                has_issues = True

        if raw_response_text and not summary_says_no_issues and not model_says_no_issues and not has_garbled_issue:
            garbled_positive = ["存在乱码", "发现乱码", "乱码问题", "形近字错显", "错显", "编码问题", "garbled", "wrong character"]
            garbled_negative = ["无乱码", "无编码问题", "无错显", "显示正确", "未见乱码", "未发现乱码", "未见任何", "共发现 0 个问题"]
            has_pos = any(k in raw_response_text for k in garbled_positive)
            has_neg = any(k in raw_response_text for k in garbled_negative)
            if has_pos and not has_neg:
                if config.DEBUG:
                    print("⚠️ 原始响应明确提到乱码/形近字但结果中没有，自动添加乱码问题")
                issues.append({
                    "type": "乱码/编码问题",
                    "description": "检测到乱码或形近字错显问题（从原始响应中识别）",
                    "location": "需要进一步检查",
                    "severity": "high",
                    "suggestion": "检查字体、编码与渲染，核对形近字（如厶/么、日/曰）"
                })
                has_garbled_issue = True
                has_issues = True

        if raw_response_text and not summary_says_no_issues and not model_says_no_issues and not has_overflow_issue:
            overflow_positive = ["超框", "溢出", "贴边", "挤边", "压边", "越界", "紧贴边界", "overflow", "clipping risk"]
            overflow_negative = ["无超框", "无溢出", "无贴边", "未见超框", "未见溢出", "未见贴边", "共发现 0 个问题"]
            has_pos = any(k in raw_response_text for k in overflow_positive)
            has_neg = any(k in raw_response_text for k in overflow_negative)
            if has_pos and not has_neg:
                if config.DEBUG:
                    print("⚠️ 原始响应提到超框/贴边风险但结果中没有，自动添加超框/溢出问题")
                issues.append({
                    "type": "文字超框/溢出",
                    "description": "检测到文字贴边或超框风险（从原始响应中识别）",
                    "location": "需要进一步检查",
                    "severity": "medium",
                    "suggestion": "建议增加容器内边距、扩大按钮宽度或降低字号后复测"
                })
                has_overflow_issue = True
                has_issues = True
        
        # 规则2：如果检测到截断、异常换行或乱码问题，但得分 >= 80，这是矛盾的，需要修正
        if (has_truncation or has_linebreak_issue or has_garbled_issue) and score >= 80:
            if config.DEBUG:
                print(f"⚠️ 检测到矛盾：有截断/乱码/换行问题但得分是 {score}，自动修正为 65")
            
            # 自动修正得分
            result["score"] = 65
            result["has_issues"] = True
            
            # 确保截断问题的严重程度是 high
            for issue in issues:
                if issue.get("type") == "文字截断" or "截断" in issue.get("type", ""):
                    issue["severity"] = "high"
                if issue.get("type") == "乱码/编码问题" or "乱码" in issue.get("type", ""):
                    issue["severity"] = "high"
        
        # 规则2.5：存在超框/贴边问题时，得分不应过高
        if has_overflow_issue and result.get("score", score) >= 85:
            if config.DEBUG:
                print(f"⚠️ 检测到矛盾：有超框/贴边问题但得分是 {result.get('score', score)}，自动修正为 78")
            result["score"] = 78
            result["has_issues"] = True
        
        # 规则3：如果 has_issues 是 False 但有问题列表，修正
        if not has_issues and issues:
            if config.DEBUG:
                print("⚠️ 检测到矛盾：有问题列表但 has_issues 是 False，自动修正")
            result["has_issues"] = True
            if score >= 80:
                result["score"] = max(60, score - 20)  # 降低得分
        
        # 规则4：如果得分是 100 但有问题，修正
        if score == 100 and (issues or has_issues):
            if config.DEBUG:
                print(f"⚠️ 检测到矛盾：有问题但得分是 100，自动修正为 70")
            result["score"] = 70
            result["has_issues"] = True
        
        # 规则5：如果得分 >= 90 但有问题，至少降低到 80 以下
        if score >= 90 and (issues or has_issues):
            if config.DEBUG:
                print(f"⚠️ 检测到矛盾：有问题但得分是 {score}，自动降低到 75")
            result["score"] = 75
            result["has_issues"] = True
        
        # 更新 issues 列表
        result["issues"] = issues
        
        return result
    
    async def check_ui_issues(
        self,
        image_bytes: bytes,
        prompt: str | None = None,
        trace_stage: str | None = None,
        trace_image_name: str | None = None,
    ) -> dict:
        """
        检测图片中文字的 UI 显示问题
        
        Args:
            image_bytes: 图片二进制数据
            prompt: 可选，自定义检测提示词；为 None 时使用默认 get_ui_check_prompt()
        
        Returns:
            {
                "success": bool,
                "has_issues": bool,      # 是否有问题
                "issues": list,          # 问题列表
                "summary": str,          # 总结
                "score": int             # 得分 (0-100)
            }
        """
        # 未传自定义 prompt：走两阶段多 Agent（结构->裁剪->专项）
        if prompt is None:
            return await self._check_ui_issues_multi_agent(image_bytes)

        base64_image = self.encode_image(image_bytes)
        image_data_url = f"data:image/png;base64,{base64_image}"

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": image_data_url
                                }
                            },
                            {"type": "text", "text": prompt}
                        ]
                    }
                ],
                max_tokens=4000,
                temperature=0,
                name=(f"leader-{trace_stage}-eval" if trace_stage else "ui-agent-custom-prompt"),
                metadata={
                    "model": self.model,
                    "pipeline": ("leader_train" if trace_stage else "ui_check"),
                    "agent_type": "custom_prompt",
                    "stage": (trace_stage or "single_call"),
                    "image_name": (trace_image_name or ""),
                },
            )
            
            result_text = response.choices[0].message.content
            
            # 调试：打印原始响应（开发环境）
            if config.DEBUG:
                print("=" * 80)
                print("UI 检测原始响应:")
                print(result_text)
                print("=" * 80)
            
            # 预先检查原始响应中是否提到截断（用于后续验证）
            raw_text_mentions_truncation = any(
                keyword in result_text 
                for keyword in ['截断', 'truncat', '不完整', '被切', '缺失', 'incomplete']
            )
            
            # 解析 JSON 结果
            result = None
            json_match = re.search(r'```json\s*(.*?)\s*```', result_text, re.DOTALL)
            if json_match:
                try:
                    result = json.loads(json_match.group(1))
                except json.JSONDecodeError:
                    pass
            
            # 如果没找到或解析失败，尝试直接解析整个文本
            if result is None:
                try:
                    result = json.loads(result_text)
                except json.JSONDecodeError:
                    # 尝试提取 JSON 对象（更宽松的匹配）
                    json_obj_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', result_text, re.DOTALL)
                    if json_obj_match:
                        try:
                            result = json.loads(json_obj_match.group(0))
                        except json.JSONDecodeError:
                            pass
            
            # 如果仍然无法解析，尝试从文本中提取关键信息
            if result is None:
                # 尝试从文本中判断是否有问题
                has_issues_detected = False
                issues_found = []
                
                # 检查文本中是否提到问题
                problem_keywords = ['截断', '溢出', '重叠', '模糊', '对齐', '间距', '乱码', '字体', '换行', '问题', 'issue', 'problem', 'line break', 'word break']
                if any(keyword in result_text for keyword in problem_keywords):
                    has_issues_detected = True
                    # 尝试提取问题描述
                    if '截断' in result_text or 'truncat' in result_text.lower():
                        issues_found.append({
                            "type": "文字截断",
                            "description": "检测到文字截断问题，但无法解析详细结果",
                            "location": "需要查看原始响应",
                            "severity": "high",
                            "suggestion": "请检查图片边界和文字完整性"
                        })
                
                return {
                    "success": True,
                    "has_issues": has_issues_detected,
                    "issues": issues_found,
                    "summary": f"检测完成，但结果格式非标准。原始响应：{result_text[:500]}...",
                    "score": 0 if has_issues_detected else 50,
                    "structure_ok": None,
                    "structure_assessment": "",
                    "agent_process": self._normalize_agent_process({
                        "issues": issues_found,
                        "structure_ok": None,
                        "structure_assessment": "",
                    }),
                    "message": "检测完成，但结果格式非标准，已尝试从文本中提取信息"
                }
            
            # 确保 score 是整数类型
            score = result.get("score", 100)
            if isinstance(score, str):
                try:
                    score = int(score)
                except (ValueError, TypeError):
                    score = 100
            elif not isinstance(score, (int, float)):
                score = 100
            
            # 确保 score 在有效范围内
            score = max(0, min(100, int(score)))
            result["score"] = score
            
            # 验证和修正结果（关键步骤：从根源杜绝矛盾）
            result = self.validate_result(result, image_bytes, result_text)
            # AI 对 UI 结构的判断：若 structure_ok 为 false，则合并为 has_issues
            has_issues = result.get("has_issues", False)
            if result.get("structure_ok") is False:
                has_issues = True
            agent_process = self._normalize_agent_process(result)
            return {
                "success": True,
                "has_issues": has_issues,
                "issues": result.get("issues", []),
                "summary": result.get("summary", ""),
                "score": result.get("score", score),
                "structure_ok": result.get("structure_ok"),
                "structure_assessment": result.get("structure_assessment", ""),
                "agent_process": agent_process,
                "message": "检测完成"
            }
            
        except json.JSONDecodeError:
            return {
                "success": True,
                "has_issues": False,
                "issues": [],
                "summary": result_text,
                "score": 0,
                "structure_ok": None,
                "structure_assessment": "",
                "agent_process": self._normalize_agent_process({"issues": []}),
                "message": "检测完成，但结果格式非标准"
            }
        except Exception as e:
            return {
                "success": False,
                "has_issues": False,
                "issues": [],
                "summary": "",
                "score": 0,
                "structure_ok": None,
                "structure_assessment": "",
                "agent_process": self._normalize_agent_process({"issues": []}),
                "message": f"检测失败: {str(e)}"
            }
