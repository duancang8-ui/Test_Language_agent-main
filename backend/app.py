import asyncio
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
from typing import Optional, List
import uvicorn

from config import config

# 在导入 services 前设置 Langfuse 环境变量（供 langfuse.openai 读取）
if config.LANGFUSE_SECRET_KEY:
    os.environ.setdefault("LANGFUSE_SECRET_KEY", config.LANGFUSE_SECRET_KEY)
if config.LANGFUSE_PUBLIC_KEY:
    os.environ.setdefault("LANGFUSE_PUBLIC_KEY", config.LANGFUSE_PUBLIC_KEY)
if config.LANGFUSE_BASE_URL:
    os.environ.setdefault("LANGFUSE_BASE_URL", config.LANGFUSE_BASE_URL)
if not config.LANGFUSE_ENABLED:
    os.environ["LANGFUSE_TRACING_ENABLED"] = "false"

from services import OCRService, UICheckService


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        from database import init_db
        init_db()
    except Exception:
        pass
    yield
    try:
        from langfuse import get_client
        get_client().flush()
    except Exception:
        pass


app = FastAPI(
    title="多语言 OCR Agent",
    description="图片文字识别与 UI 检测服务",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化服务
ocr_service = OCRService()
ui_check_service = UICheckService()


class OCRRequest(BaseModel):
    languages: Optional[List[str]] = None


@app.get("/")
async def root():
    return {
        "name": "多语言 OCR Agent",
        "version": "1.0.0",
        "endpoints": {
            "OCR 识别": "POST /api/ocr",
            "UI 检测": "POST /api/ui-check",
            "批量 UI 检测": "POST /api/ui-check-batch",
            "综合分析": "POST /api/analyze",
            "Leader Agent 训练": "POST /api/leader-train",
            "测试报告": "POST/GET /api/test-reports",
        }
    }


@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "model": config.LVM_MODEL}


@app.post("/api/ocr")
async def ocr_recognize(
    file: UploadFile = File(...),
    languages: Optional[str] = None
):
    """
    OCR 文字识别
    
    - **file**: 上传的图片文件
    - **languages**: 可选，期望识别的语言（逗号分隔），如 "中文,英文,日文"
    """
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="请上传图片文件")
    
    image_bytes = await file.read()
    
    lang_list = None
    if languages:
        lang_list = [lang.strip() for lang in languages.split(",")]
    
    result = await ocr_service.recognize(image_bytes, lang_list)
    return JSONResponse(content=result)


@app.post("/api/ui-check")
async def ui_check(
    file: UploadFile = File(...),
    prompt: Optional[str] = Form(None),
    trace_stage: Optional[str] = Form(None),
    trace_image_name: Optional[str] = Form(None),
):
    """
    UI 文字显示检测
    
    检测图片中的文字显示问题，包括：
    - 文字超框/溢出
    - 文字截断
    - 文字重叠
    - 对齐问题
    - 间距问题
    等
    
    - **prompt**: 可选，自定义检测提示词（用于 leader_agent 训练时动态修改提示词）
    """
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="请上传图片文件")
    
    image_bytes = await file.read()
    result = await ui_check_service.check_ui_issues(
        image_bytes,
        prompt=prompt,
        trace_stage=trace_stage,
        trace_image_name=trace_image_name,
    )
    return JSONResponse(content=result)


@app.post("/api/ui-check-batch")
async def ui_check_batch(
    files: List[UploadFile] = File(..., description="多张图片"),
    concurrency: int = Form(2, description="并发数，默认 2，上限 5"),
):
    """
    批量 UI 文字显示检测

    并发检测多张图片，通过 concurrency 控制并发数。
    """
    import time as _time
    concurrency = max(1, min(5, concurrency))
    image_files = [f for f in files if f.filename and f.content_type and f.content_type.startswith("image/")]
    if not image_files:
        raise HTTPException(status_code=400, detail="请上传至少一张图片文件")

    wall_t0 = _time.perf_counter()
    sem = asyncio.Semaphore(concurrency)

    async def _check_one(uf: UploadFile) -> dict:
        async with sem:
            try:
                image_bytes = await uf.read()
                result = await ui_check_service.check_ui_issues(image_bytes)
                return {
                    "filename": uf.filename,
                    "success": result.get("success", True),
                    "has_issues": result.get("has_issues", False),
                    "score": result.get("score", 100),
                    "issues": result.get("issues", []),
                    "summary": result.get("summary", ""),
                    "structure_ok": result.get("structure_ok"),
                    "agent_process": result.get("agent_process", []),
                    "elapsed_ms": result.get("elapsed_ms", 0),
                    "wall_elapsed_ms": result.get("wall_elapsed_ms", 0),
                    "message": result.get("message", "检测完成"),
                }
            except Exception as e:
                return {
                    "filename": uf.filename,
                    "success": False,
                    "message": str(e),
                }

    results = await asyncio.gather(*[_check_one(uf) for uf in image_files])
    wall_elapsed_ms = int((_time.perf_counter() - wall_t0) * 1000)
    elapsed_ms = sum(r.get("elapsed_ms", 0) for r in results)

    return JSONResponse(content={
        "success": True,
        "total": len(results),
        "concurrency": concurrency,
        "results": list(results),
        "elapsed_ms": elapsed_ms,
        "wall_elapsed_ms": wall_elapsed_ms,
    })


@app.post("/api/analyze")
async def full_analyze(
    file: UploadFile = File(...),
    languages: Optional[str] = None
):
    """
    综合分析（OCR + UI 检测）
    
    同时进行文字识别和 UI 问题检测
    """
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="请上传图片文件")
    
    image_bytes = await file.read()
    
    lang_list = None
    if languages:
        lang_list = [lang.strip() for lang in languages.split(",")]
    
    # 并行执行两个服务
    import asyncio
    ocr_task = ocr_service.recognize(image_bytes, lang_list)
    ui_task = ui_check_service.check_ui_issues(image_bytes)
    
    ocr_result, ui_result = await asyncio.gather(ocr_task, ui_task)
    
    return JSONResponse(content={
        "success": ocr_result["success"] and ui_result["success"],
        "ocr": ocr_result,
        "ui_check": ui_result,
        "message": "分析完成"
    })


# 允许的图片扩展名（与 leader_agent 一致）
_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


@app.post("/api/leader-train")
async def leader_train(
    request: Request,
    problem: List[UploadFile] = File(default=[], description="有问题的图片"),
    no_problem: List[UploadFile] = File(default=[], description="无问题的图片"),
    max_rounds: int = Form(3, description="每张图最多重试次数"),
    sample_size: int = Form(10, description="每类抽样数量，0 表示全部"),
    request_delay: float = Form(2.0, description="每次调用上游 API 后等待秒数，用于避免 429 限流；0 表示不等待"),
):
    """
    Leader Agent 训练：上传「有问题」「没问题」两类图片，后端执行训练并返回结果。
    """
    try:
        request_delay = float(request_delay) if request_delay not in (None, "") else 2.0
    except (TypeError, ValueError):
        request_delay = 2.0
    request_delay = max(0.0, min(300.0, request_delay))  # 限制在 0～300 秒

    if not problem and not no_problem:
        raise HTTPException(status_code=400, detail="请至少上传「有问题的图片」或「无问题的图片」其中一类")
    problem_files = [f for f in problem if f.filename and Path(f.filename).suffix.lower() in _IMAGE_EXT]
    no_problem_files = [f for f in no_problem if f.filename and Path(f.filename).suffix.lower() in _IMAGE_EXT]
    if not problem_files and not no_problem_files:
        raise HTTPException(status_code=400, detail="未包含有效图片文件（支持 jpg/png/gif/webp/bmp）")
    problem_dir = tempfile.mkdtemp(prefix="leader_problem_")
    no_problem_dir = tempfile.mkdtemp(prefix="leader_no_problem_")
    try:
        for i, uf in enumerate(problem_files):
            ext = Path(uf.filename).suffix or ".png"
            path = Path(problem_dir) / f"img_{i}{ext}"
            path.write_bytes(await uf.read())
        for i, uf in enumerate(no_problem_files):
            ext = Path(uf.filename).suffix or ".png"
            path = Path(no_problem_dir) / f"img_{i}{ext}"
            path.write_bytes(await uf.read())
        base_url = str(request.base_url).rstrip("/")
        from leader_agent.runner import run_training
        result = await run_training(
            problem_dir=problem_dir,
            no_problem_dir=no_problem_dir,
            base_url=base_url,
            max_rounds=max_rounds,
            sample_size=sample_size,
            request_delay=request_delay,
        )
        return JSONResponse(content={
            "success": True,
            "run_id": result.get("run_id"),
            "total": result.get("total", 0),
            "ok": result.get("ok", 0),
            "failed": result.get("failed", 0),
            "updated_prompt_count": result.get("updated_prompt_count", 0),
            "final_prompt": result.get("final_prompt", ""),
            "details": result.get("details", []),
            "message": f"训练完成：共 {result.get('total', 0)} 张，通过 {result.get('ok', 0)} 张，失败 {result.get('failed', 0)} 张，提示词被修改 {result.get('updated_prompt_count', 0)} 次",
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        for p in Path(problem_dir).iterdir():
            try:
                p.unlink()
            except Exception:
                pass
        for p in Path(no_problem_dir).iterdir():
            try:
                p.unlink()
            except Exception:
                pass
        try:
            Path(problem_dir).rmdir()
            Path(no_problem_dir).rmdir()
        except Exception:
            pass


@app.get("/api/training-runs")
async def list_training_runs(limit: int = 50):
    """列出最近训练记录（DB）。"""
    try:
        from database import list_runs
        return JSONResponse(content=list_runs(limit=limit))
    except ImportError:
        return JSONResponse(content=[])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/training-runs/{run_id}")
async def get_training_run(run_id: str):
    """单次训练汇总与明细（DB）。"""
    try:
        from database import get_run
        out = get_run(run_id)
        if out is None:
            raise HTTPException(status_code=404, detail="未找到该训练记录")
        return JSONResponse(content=out)
    except HTTPException:
        raise
    except ImportError:
        raise HTTPException(status_code=404, detail="未找到该训练记录")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/prompt-versions")
async def list_prompt_versions_api(limit: int = 50):
    """列出最近提示词版本（RAG 知识库列表）。"""
    try:
        from database import list_prompt_versions
        return JSONResponse(content=list_prompt_versions(limit=limit))
    except ImportError:
        return JSONResponse(content=[])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --------------- 测试报告 API ---------------

@app.post("/api/test-reports")
async def create_test_report_api(
    total: int = Form(0, description="预计图片总数"),
):
    """创建测试报告会话"""
    from database import generate_run_id, create_test_report
    report_id = generate_run_id()
    create_test_report(report_id, total)
    return JSONResponse(content={"report_id": report_id})


@app.post("/api/test-reports/{report_id}/items")
async def add_test_report_item(
    report_id: str,
    file: UploadFile = File(...),
):
    """提交单张图片进行 UI 检测并保存结果到报告"""
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="请上传图片文件")

    from database import insert_test_report_item, DATA_DIR

    image_bytes = await file.read()

    report_image_dir = Path(DATA_DIR) / "report_images" / report_id
    report_image_dir.mkdir(parents=True, exist_ok=True)
    image_filename = file.filename or f"image_{int(__import__('time').time() * 1000)}.png"
    safe_filename = Path(image_filename).name
    image_path = report_image_dir / safe_filename
    image_path.write_bytes(image_bytes)

    try:
        result = await ui_check_service.check_ui_issues(image_bytes)
        item = {
            "filename": safe_filename,
            "success": result.get("success", True),
            "has_issues": result.get("has_issues", False),
            "score": result.get("score", 100),
            "issues": result.get("issues", []),
            "summary": result.get("summary", ""),
            "structure_ok": result.get("structure_ok"),
            "agent_process": result.get("agent_process", []),
            "elapsed_ms": result.get("elapsed_ms", 0),
            "wall_elapsed_ms": result.get("wall_elapsed_ms", 0),
            "message": result.get("message", "检测完成"),
            "image_path": f"report_images/{report_id}/{safe_filename}",
        }
    except Exception as e:
        item = {
            "filename": safe_filename,
            "success": False,
            "has_issues": None,
            "score": None,
            "issues": [],
            "summary": "",
            "structure_ok": None,
            "agent_process": [],
            "elapsed_ms": 0,
            "wall_elapsed_ms": 0,
            "message": str(e),
            "image_path": f"report_images/{report_id}/{safe_filename}",
        }

    insert_test_report_item(report_id, item)
    return JSONResponse(content=item)


@app.patch("/api/test-reports/{report_id}/complete")
async def complete_test_report_api(report_id: str):
    """标记测试报告为已完成"""
    from database import complete_test_report
    try:
        complete_test_report(report_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return JSONResponse(content={"success": True})


@app.get("/api/test-reports")
async def list_test_reports_api(limit: int = 50):
    """列出历史测试报告"""
    from database import list_test_reports
    return JSONResponse(content=list_test_reports(limit))


@app.get("/api/test-reports/{report_id}")
async def get_test_report_api(report_id: str):
    """获取测试报告详情"""
    from database import get_test_report
    report = get_test_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="未找到该测试报告")
    return JSONResponse(content=report)


@app.get("/api/report-images/{report_id}/{filename}")
async def serve_report_image(report_id: str, filename: str):
    """提供报告中保存的图片"""
    from database import DATA_DIR
    safe_name = Path(filename).name
    image_path = Path(DATA_DIR) / "report_images" / report_id / safe_name
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="图片不存在")
    return FileResponse(str(image_path))


if __name__ == "__main__":
    print(f"""
╔══════════════════════════════════════════════════╗
║       多语言 OCR Agent 服务启动中...              ║
╠══════════════════════════════════════════════════╣
║  API 文档: http://{config.HOST}:{config.PORT}/docs         ║
║  健康检查: http://{config.HOST}:{config.PORT}/api/health   ║
╚══════════════════════════════════════════════════╝
    """)
    uvicorn.run(
        "app:app",
        host=config.HOST,
        port=config.PORT,
        reload=config.DEBUG
    )
