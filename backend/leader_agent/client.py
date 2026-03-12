"""
调用 language_agent 的 /api/ui-check 接口。
支持传入可选的自定义 prompt，供 leader 训练时使用。
"""

import httpx


async def ui_check(
    image_bytes: bytes,
    base_url: str,
    prompt: str | None = None,
    trace_stage: str | None = None,
    trace_image_name: str | None = None,
) -> dict:
    """
    调用 backend 的 UI 检测接口。
    
    Args:
        image_bytes: 图片二进制
        base_url: 后端地址，如 http://127.0.0.1:8000
        prompt: 可选，自定义检测提示词
    
    Returns:
        language_agent 返回的 JSON：success, has_issues, issues, summary, score, message
    """
    url = f"{base_url.rstrip('/')}/api/ui-check"
    files = {"file": ("image.png", image_bytes, "image/png")}
    data = {}
    if prompt is not None and prompt.strip():
        data["prompt"] = prompt.strip()
    if trace_stage:
        data["trace_stage"] = trace_stage
    if trace_image_name:
        data["trace_image_name"] = trace_image_name
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, files=files, data=data if data else None)
        resp.raise_for_status()
        return resp.json()


def ui_check_sync(
    image_bytes: bytes,
    base_url: str,
    prompt: str | None = None,
    trace_stage: str | None = None,
    trace_image_name: str | None = None,
) -> dict:
    """同步版本，供非 async 环境使用。"""
    import asyncio
    return asyncio.run(ui_check(image_bytes, base_url, prompt, trace_stage, trace_image_name))
