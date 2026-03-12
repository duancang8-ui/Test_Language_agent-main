import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # LVM (视觉模型) 配置
    LVM_API_KEY = os.getenv("LVM_API_KEY", "")
    LVM_BASE_URL = os.getenv("LVM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
    LVM_MODEL = os.getenv("LVM_MODEL", "glm-4v-flash")  # 必填，由网关支持的模型名决定

    # Langfuse 可观测（可选，不配置则不上报）
    LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
    # SDK 官方用 LANGFUSE_BASE_URL，兼容 LANGFUSE_HOST
    _langfuse_url = os.getenv("LANGFUSE_BASE_URL") or os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
    LANGFUSE_BASE_URL = _langfuse_url.rstrip("/") if _langfuse_url else "https://cloud.langfuse.com"
    LANGFUSE_ENABLED = os.getenv("LANGFUSE_ENABLED", "true").lower() == "true"

    # 服务配置
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", 8000))
    DEBUG = os.getenv("DEBUG", "false").lower() == "true"
    # UI 检测链路调试日志（用于排查同图漏检/抖动）
    UI_CHECK_TRACE = os.getenv("UI_CHECK_TRACE", "false").lower() == "true"

config = Config()
