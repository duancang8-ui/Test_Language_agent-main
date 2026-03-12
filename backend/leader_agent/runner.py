"""
Leader Agent 训练主流程：
从「有问题」「没问题」两个文件夹随机选图，发给 language_agent；
若结果与预期不一致，由 leader 修改提示词后重试。
"""

import argparse
import asyncio
import os
import random
import time
import uuid
from pathlib import Path
from typing import TypedDict, Any
from langgraph.graph import StateGraph, START, END

from leader_agent.client import ui_check
from leader_agent.config import (
    BACKEND_URL,
    PROBLEM_DIR,
    NO_PROBLEM_DIR,
    MAX_ROUNDS_PER_IMAGE,
    SAMPLE_SIZE,
    REQUEST_DELAY_SECONDS,
    list_images,
)
from leader_agent.leader import revise_prompt, _detection_reason
from leader_agent.leader import revise_prompt_batch


class LeaderTrainState(TypedDict, total=False):
    prompt: str
    updated_prompt_count: int
    phase1_details: list[dict]
    failures: list[dict]
    ok1: int
    phase2_details: list[dict]
    ok2: int
    details: list[dict]
    ok: int
    total: int
    done: bool


def _is_trace_enabled() -> bool:
    return os.getenv("LEADER_GRAPH_TRACE", "false").lower() == "true"


def _trace(msg: str):
    if _is_trace_enabled():
        print(f"[LEADER_GRAPH_TRACE] {msg}")


def _get_db_and_rag():
    """延迟导入 DB 与 RAG，避免未安装 chromadb 时影响启动。"""
    import os
    import sys
    _backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _backend not in sys.path:
        sys.path.insert(0, _backend)
    try:
        import database
        import rag_service
        return database, rag_service
    except ImportError:
        return None, None


def _load_default_prompt() -> str:
    import sys
    import os
    _backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _backend not in sys.path:
        sys.path.insert(0, _backend)
    from prompts import get_ui_check_prompt
    return get_ui_check_prompt()


async def run_training(
    problem_dir: str,
    no_problem_dir: str,
    base_url: str = BACKEND_URL,
    max_rounds: int = MAX_ROUNDS_PER_IMAGE,
    sample_size: int = SAMPLE_SIZE,
    request_delay: float = REQUEST_DELAY_SECONDS,
    default_prompt: str | None = None,
):
    """
    执行一轮训练流程。
    
    - 从 problem_dir / no_problem_dir 列出图片，各随机抽 sample_size 张（0 表示全用）
    - 对每张图：用当前 prompt 调 language_agent；若与预期不一致，调用 leader 生成新 prompt 并重试，最多 max_rounds 次
    - 当前实现：每张图独立重试时更新 prompt，下一张图使用「上一张图若被修改过则用新 prompt，否则用当前 prompt」
    """
    # A 方案（批量策略）：为了结果可复现，按文件名排序 + 抽样取前 N（不随机）
    problem_paths = sorted(list_images(problem_dir), key=lambda p: p.name)
    no_problem_paths = sorted(list_images(no_problem_dir), key=lambda p: p.name)
    if not problem_paths and not no_problem_paths:
        print("未找到任何图片，请检查目录：", problem_dir, no_problem_dir)
        return

    if sample_size > 0:
        problem_paths = problem_paths[: min(sample_size, len(problem_paths))] if problem_paths else []
        no_problem_paths = no_problem_paths[: min(sample_size, len(no_problem_paths))] if no_problem_paths else []

    # 构建 (path, expected_has_issues, source_label)
    tasks = []
    for p in problem_paths:
        tasks.append((p, True, "有问题"))
    for p in no_problem_paths:
        tasks.append((p, False, "没问题"))
    # 保持可复现顺序：先 problem 后 no_problem，再按文件名排序
    tasks.sort(key=lambda x: (0 if x[1] else 1, x[0].name))

    database, rag_service = _get_db_and_rag()
    run_id = str(uuid.uuid4())
    _trace(
        f"run_start run_id={run_id} total={len(tasks)} sample_size={sample_size} "
        f"max_rounds={max_rounds} request_delay={request_delay}"
    )

    prompt = default_prompt or _load_default_prompt()
    total = len(tasks)
    ok = 0
    updated_prompt_count = 0
    details: list[dict] = []

    async def _eval_all(prompt_text: str, phase_label: str) -> tuple[list[dict], list[dict], int]:
        """用指定 prompt 对全部图片跑一遍。返回：(明细列表, 失败样本列表, 通过数)"""
        phase_details: list[dict] = []
        failures: list[dict] = []
        phase_ok = 0
        for i, (path, expected_has_issues, source_label) in enumerate(tasks):
            image_bytes = path.read_bytes()
            # 每次发起上游请求前先等待（避免 429）
            if request_delay > 0:
                await asyncio.sleep(request_delay)
            try:
                res = await ui_check(
                    image_bytes,
                    base_url,
                    prompt_text,
                    trace_stage=phase_label,
                    trace_image_name=path.name,
                )
            except Exception as e:
                err_msg = str(e)
                if "429" in err_msg or "1305" in err_msg:
                    err_msg = "API 限流 (429)，请增大「请求间隔」后重试"
                msg = f"{phase_label}: 调用失败: {err_msg}"
                print(f"[{i+1}/{total}] {path.name} 调用失败: {err_msg}")
                phase_details.append({
                    "filename": path.name,
                    "source_label": source_label,
                    "expected_has_issues": expected_has_issues,
                    "actual_has_issues": None,
                    "passed": False,
                    "attempt_count": 1,
                    "retry_count": 0,
                    "message": msg,
                })
                failures.append({
                    "filename": path.name,
                    "source_label": source_label,
                    "expected_has_issues": expected_has_issues,
                    "actual_has_issues": None,
                    "passed": False,
                    "message": msg,
                    "image_bytes": image_bytes,
                    "result": None,
                })
                continue
            if not res.get("success", False):
                msg = f"{phase_label}: 调用失败: {res.get('message', '调用失败')}"
                print(f"[{i+1}/{total}] {path.name} 调用失败: {res.get('message', '')}")
                phase_details.append({
                    "filename": path.name,
                    "source_label": source_label,
                    "expected_has_issues": expected_has_issues,
                    "actual_has_issues": None,
                    "passed": False,
                    "attempt_count": 1,
                    "retry_count": 0,
                    "message": msg,
                })
                failures.append({
                    "filename": path.name,
                    "source_label": source_label,
                    "expected_has_issues": expected_has_issues,
                    "actual_has_issues": None,
                    "passed": False,
                    "message": msg,
                    "image_bytes": image_bytes,
                    "result": res,
                })
                continue

            actual = res.get("has_issues", False)
            passed = (actual == expected_has_issues)
            if passed:
                phase_ok += 1
            else:
                failures.append({
                    "filename": path.name,
                    "source_label": source_label,
                    "expected_has_issues": expected_has_issues,
                    "actual_has_issues": actual,
                    "passed": False,
                    "message": f"{phase_label}: 不一致",
                    "image_bytes": image_bytes,
                    "result": res,
                })
            print(f"[{i+1}/{total}] {path.name} ({source_label}) {'一致' if passed else '不一致'} has_issues={actual} phase={phase_label}")
            phase_details.append({
                "filename": path.name,
                "source_label": source_label,
                "expected_has_issues": expected_has_issues,
                "actual_has_issues": actual,
                "passed": passed,
                "attempt_count": 1,
                "retry_count": 0,
                "message": "通过" if passed else "不一致",
            })
        return phase_details, failures, phase_ok

    # LangGraph 编排：phase1 -> (revise?) -> phase2/finish
    async def node_phase1(state: LeaderTrainState):
        t0 = time.perf_counter()
        _trace("node=phase1 start")
        p = state.get("prompt") or prompt
        phase1_details, failures, ok1 = await _eval_all(p, phase_label="phase1")
        _trace(
            f"node=phase1 end ok={ok1}/{total} failures={len(failures)} "
            f"elapsed_ms={int((time.perf_counter() - t0) * 1000)}"
        )
        return {
            "prompt": p,
            "phase1_details": phase1_details,
            "failures": failures,
            "ok1": ok1,
            "total": total,
            "updated_prompt_count": state.get("updated_prompt_count", 0),
        }

    def route_after_phase1(state: LeaderTrainState):
        failures = state.get("failures") or []
        _trace(f"route_after_phase1 failures={len(failures)} -> {'revise' if failures else 'finish'}")
        return "revise" if failures else "finish"

    async def node_revise(state: LeaderTrainState):
        t0 = time.perf_counter()
        _trace("node=revise start")
        failures = state.get("failures") or []
        cur_prompt = state.get("prompt") or prompt
        examples = []
        for f in failures:
            if f.get("result") and f.get("actual_has_issues") is not None:
                r = f["result"] or {}
                detection_reason = _detection_reason(
                    f.get("expected_has_issues", False),
                    f.get("actual_has_issues", False),
                    r.get("summary", ""),
                    r.get("issues", []),
                )
                examples.append({
                    "filename": f.get("filename"),
                    "image_source": f.get("source_label"),
                    "expected_has_issues": f.get("expected_has_issues"),
                    "result_has_issues": f.get("actual_has_issues"),
                    "result_summary": r.get("summary", ""),
                    "result_score": r.get("score", 0),
                    "result_issues": r.get("issues", []),
                    "detection_reason": detection_reason,
                    "image_bytes": f.get("image_bytes"),
                })
            if len(examples) >= 3:
                break

        detection_reason_all = f"本轮评测共 {total} 张：失败 {len(failures)} 张。请基于以下失败样本（含漏报/误报原因）集中修订提示词，并确保不引入新的误报/漏报。"
        rag_context = []
        if rag_service:
            try:
                rag_context = rag_service.query_similar(detection_reason_all, top_k=3)
            except Exception:
                pass
        new_prompt = cur_prompt
        updated_count = state.get("updated_prompt_count", 0)
        try:
            if examples:
                _trace(f"node=revise examples={len(examples)} rag_enabled={bool(rag_context)}")
                new_prompt = revise_prompt_batch(
                    current_prompt=cur_prompt,
                    detection_reason=detection_reason_all,
                    examples=examples,
                    rag_context=rag_context,
                )
                updated_count = 1
                if database:
                    try:
                        database.init_db()
                        database.insert_prompt_version(
                            run_id, detection_reason_all, new_prompt,
                            prompt_before=cur_prompt,
                            source_label="批量(A方案)",
                            expected_has_issues=False,
                            result_has_issues=False,
                        )
                    except Exception:
                        pass
                if rag_service:
                    try:
                        rag_service.add_document(detection_reason_all, new_prompt)
                    except Exception:
                        pass
        except Exception as e:
            print("批量修改提示词失败：", str(e))
        _trace(
            f"node=revise end updated_prompt_count={updated_count} "
            f"prompt_changed={new_prompt != cur_prompt} elapsed_ms={int((time.perf_counter() - t0) * 1000)}"
        )
        return {"prompt": new_prompt, "updated_prompt_count": updated_count}

    async def node_phase2(state: LeaderTrainState):
        t0 = time.perf_counter()
        _trace("node=phase2 start")
        p = state.get("prompt") or prompt
        phase1_details = state.get("phase1_details") or []
        phase2_details, failures2, ok2 = await _eval_all(p, phase_label="phase2")
        phase1_map = {d["filename"]: d for d in phase1_details}
        merged_details = []
        for d2 in phase2_details:
            d1 = phase1_map.get(d2["filename"], {})
            msg = f"phase1={'通过' if d1.get('passed') else '失败'}; phase2={'通过' if d2.get('passed') else '失败'}"
            merged_details.append({
                **d2,
                "attempt_count": 2,
                "retry_count": 1,
                "message": msg,
            })
        _trace(
            f"node=phase2 end ok={ok2}/{total} failures={len(failures2)} "
            f"elapsed_ms={int((time.perf_counter() - t0) * 1000)}"
        )
        return {"phase2_details": phase2_details, "ok2": ok2, "details": merged_details, "ok": ok2}

    async def node_finish(state: LeaderTrainState):
        _trace("node=finish start")
        if state.get("details"):
            _trace("node=finish end mode=phase2_details")
            return {}
        _trace("node=finish end mode=phase1_details")
        return {
            "ok": state.get("ok1", 0),
            "details": state.get("phase1_details", []),
        }

    g = StateGraph(LeaderTrainState)
    g.add_node("phase1", node_phase1)
    g.add_node("revise", node_revise)
    g.add_node("phase2", node_phase2)
    g.add_node("finish", node_finish)
    g.add_edge(START, "phase1")
    g.add_conditional_edges("phase1", route_after_phase1, {"revise": "revise", "finish": "finish"})
    g.add_edge("revise", "phase2")
    g.add_edge("phase2", "finish")
    g.add_edge("finish", END)
    graph = g.compile()
    final_state = await graph.ainvoke({
        "prompt": prompt,
        "updated_prompt_count": 0,
        "total": total,
    })

    prompt = final_state.get("prompt", prompt)
    ok = final_state.get("ok", 0)
    details = final_state.get("details", [])
    updated_prompt_count = final_state.get("updated_prompt_count", 0)
    _trace(
        f"run_end run_id={run_id} ok={ok}/{total} failed={total-ok} "
        f"updated_prompt_count={updated_prompt_count}"
    )

    print(f"完成: 一致 {ok}/{total}，提示词被 Leader 修改次数 {updated_prompt_count}")
    failed = total - ok
    if database:
        try:
            database.init_db()
            database.insert_run(run_id, total, ok, failed, updated_prompt_count, prompt)
            database.insert_run_details(run_id, details)
        except Exception:
            pass
    return {
        "total": total,
        "ok": ok,
        "failed": failed,
        "updated_prompt_count": updated_prompt_count,
        "final_prompt": prompt,
        "details": details,
        "run_id": run_id,
    }


def main():
    parser = argparse.ArgumentParser(description="Leader Agent：用「有问题/没问题」图片训练 Language Agent 的提示词")
    parser.add_argument("--problem-dir", "-p", default=PROBLEM_DIR, help="有问题的图片所在文件夹")
    parser.add_argument("--no-problem-dir", "-n", default=NO_PROBLEM_DIR, help="无问题的图片所在文件夹")
    parser.add_argument("--backend-url", "-b", default=BACKEND_URL, help="Language Agent 后端地址")
    parser.add_argument("--max-rounds", "-r", type=int, default=MAX_ROUNDS_PER_IMAGE, help="每张图最多重试次数（含 Leader 修改提示词）")
    parser.add_argument("--sample-size", "-s", type=int, default=SAMPLE_SIZE, help="每个文件夹抽样数量，0 表示全部")
    parser.add_argument("--request-delay", "-d", type=float, default=REQUEST_DELAY_SECONDS, help="每次调用上游 API 后等待秒数，避免 429 限流；0 表示不等待")
    args = parser.parse_args()
    if not args.problem_dir or not args.no_problem_dir:
        parser.error("请指定 --problem-dir 和 --no-problem-dir")
    asyncio.run(run_training(
        problem_dir=args.problem_dir,
        no_problem_dir=args.no_problem_dir,
        base_url=args.backend_url,
        max_rounds=args.max_rounds,
        sample_size=args.sample_size,
        request_delay=args.request_delay,
    ))


if __name__ == "__main__":
    main()
