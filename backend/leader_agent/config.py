import os
from pathlib import Path

# 默认从环境变量读取，也可由 runner 命令行参数覆盖
BACKEND_URL = os.getenv("LEADER_BACKEND_URL", "http://127.0.0.1:8000")
PROBLEM_DIR = os.getenv("LEADER_PROBLEM_DIR", "")
NO_PROBLEM_DIR = os.getenv("LEADER_NO_PROBLEM_DIR", "")
MAX_ROUNDS_PER_IMAGE = int(os.getenv("LEADER_MAX_ROUNDS", "3"))  # 每张图最多用新 prompt 重试次数
SAMPLE_SIZE = int(os.getenv("LEADER_SAMPLE_SIZE", "10"))  # 每轮从两个文件夹各抽多少张（0 表示全部）
# 每次调用上游 API（ui_check / revise_prompt）后的等待秒数，避免智谱 429 限流；约 2 秒则每分钟约 30 次
REQUEST_DELAY_SECONDS = float(os.getenv("LEADER_REQUEST_DELAY", "2.0"))
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


def list_images(folder: str) -> list[Path]:
    """列出文件夹下所有图片路径。"""
    path = Path(folder).resolve()
    if not path.is_dir():
        return []
    return [p for p in path.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
