"""
RAG：用 Chroma 存「检测原因 + 修改后提示词」，Leader 改提示词前先检索相似历史。
网络不可用时自动降级：仅用本地缓存，未缓存则本进程内不再尝试，避免阻塞流程。
"""

import os
import uuid
from pathlib import Path

# 与 database 共用数据目录
BACKEND_ROOT = Path(__file__).resolve().parent
DATA_DIR = os.getenv("LANGUAGE_AGENT_DATA_DIR", str(BACKEND_ROOT / "data"))
CHROMA_PATH = Path(DATA_DIR) / "chroma"
COLLECTION_NAME = "prompt_versions"

# 本进程内 RAG 若加载失败则不再重试，避免每次卡在 HuggingFace 超时
_rag_disabled = False


def _get_collection():
    global _rag_disabled
    if _rag_disabled:
        return None
    try:
        import chromadb
        from chromadb.utils import embedding_functions
        Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
        # 默认仅用本地缓存，不请求 HuggingFace，避免首次调用长时间超时阻塞；需联网时设置 LANGUAGE_AGENT_RAG_OFFLINE=0
        restore_offline = False
        if os.getenv("LANGUAGE_AGENT_RAG_OFFLINE", "1") == "1":
            restore_offline = True
            prev = os.environ.get("HF_HUB_OFFLINE")
            os.environ["HF_HUB_OFFLINE"] = "1"
        try:
            client = chromadb.PersistentClient(path=str(CHROMA_PATH))
            ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="paraphrase-multilingual-MiniLM-L12-v2")
            return client.get_or_create_collection(name=COLLECTION_NAME, embedding_function=ef)
        finally:
            if restore_offline:
                if prev is None:
                    os.environ.pop("HF_HUB_OFFLINE", None)
                else:
                    os.environ["HF_HUB_OFFLINE"] = prev
    except Exception:
        _rag_disabled = True
        return None


_SEP = "\n\n---PROMPT---\n\n"


def add_document(detection_reason: str, prompt_after: str, metadata: dict = None):
    """写入一条「检测原因 + 修改后提示词」，供后续检索。文档内容含完整 prompt，metadata 仅存短摘要。"""
    col = _get_collection()
    if col is None:
        return
    # 文档内容：检测原因 + 分隔符 + 修改后提示词（便于检索并完整返回）
    text = detection_reason + _SEP + prompt_after
    col.add(
        documents=[text],
        ids=[str(uuid.uuid4())],
        metadatas=[{**(metadata or {}), "reason_preview": detection_reason[:200]}],
    )


def query_similar(detection_reason: str, top_k: int = 3) -> list[dict]:
    """按检测原因检索相似历史，返回 [{ detection_reason, prompt_after }, ...]。RAG 不可用时返回 []。"""
    col = _get_collection()
    if col is None:
        return []
    n = col.count()
    if n == 0:
        return []
    try:
        results = col.query(query_texts=[detection_reason], n_results=min(top_k, n), include=["documents"])
    except Exception:
        return []
    out = []
    if results and results.get("documents") and results["documents"][0]:
        for doc in results["documents"][0]:
            if _SEP in doc:
                reason, prompt = doc.split(_SEP, 1)
                out.append({"detection_reason": reason.strip(), "prompt_after": prompt.strip()})
            else:
                out.append({"detection_reason": doc[:500], "prompt_after": ""})
    return out
