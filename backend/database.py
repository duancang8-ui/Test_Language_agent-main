"""
SQLite 存储：训练结果、每张图明细、提示词版本。
"""

import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

# 数据目录与 DB 路径
BACKEND_ROOT = Path(__file__).resolve().parent
DATA_DIR = os.getenv("LANGUAGE_AGENT_DATA_DIR", str(BACKEND_ROOT / "data"))
DB_PATH = Path(DATA_DIR) / "language_agent.db"


def _ensure_data_dir():
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)


def get_connection():
    _ensure_data_dir()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """创建表（若不存在）。"""
    conn = get_connection()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS training_runs (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                total INTEGER NOT NULL,
                ok INTEGER NOT NULL,
                failed INTEGER NOT NULL,
                updated_prompt_count INTEGER NOT NULL,
                final_prompt TEXT
            );
            CREATE TABLE IF NOT EXISTS training_run_details (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                source_label TEXT NOT NULL,
                expected_has_issues INTEGER NOT NULL,
                actual_has_issues INTEGER,
                passed INTEGER NOT NULL,
                attempt_count INTEGER NOT NULL,
                retry_count INTEGER NOT NULL,
                message TEXT,
                FOREIGN KEY (run_id) REFERENCES training_runs(id)
            );
            CREATE TABLE IF NOT EXISTS prompt_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                created_at TEXT NOT NULL,
                detection_reason TEXT NOT NULL,
                prompt_before TEXT,
                prompt_after TEXT NOT NULL,
                source_label TEXT,
                expected_has_issues INTEGER,
                result_has_issues INTEGER,
                FOREIGN KEY (run_id) REFERENCES training_runs(id)
            );
            CREATE TABLE IF NOT EXISTS test_reports (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                total INTEGER NOT NULL DEFAULT 0,
                success_count INTEGER NOT NULL DEFAULT 0,
                fail_count INTEGER NOT NULL DEFAULT 0,
                has_issue_count INTEGER NOT NULL DEFAULT 0,
                no_issue_count INTEGER NOT NULL DEFAULT 0,
                elapsed_ms INTEGER NOT NULL DEFAULT 0,
                wall_elapsed_ms INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS test_report_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                success INTEGER NOT NULL DEFAULT 1,
                has_issues INTEGER,
                score INTEGER,
                issues TEXT,
                summary TEXT,
                structure_ok INTEGER,
                agent_process TEXT,
                elapsed_ms INTEGER DEFAULT 0,
                wall_elapsed_ms INTEGER DEFAULT 0,
                message TEXT,
                image_path TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (report_id) REFERENCES test_reports(id)
            );
        """)
        conn.commit()
    finally:
        conn.close()


def insert_run(run_id: str, total: int, ok: int, failed: int, updated_prompt_count: int, final_prompt: str = ""):
    """写入一次训练汇总。"""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO training_runs (id, created_at, total, ok, failed, updated_prompt_count, final_prompt) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, datetime.utcnow().isoformat(), total, ok, failed, updated_prompt_count, final_prompt or ""),
        )
        conn.commit()
    finally:
        conn.close()


def insert_run_details(run_id: str, details: list):
    """写入一次训练的每张图明细。"""
    if not details:
        return
    conn = get_connection()
    try:
        for d in details:
            conn.execute(
                """INSERT INTO training_run_details (run_id, filename, source_label, expected_has_issues, actual_has_issues, passed, attempt_count, retry_count, message)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    d.get("filename", ""),
                    d.get("source_label", ""),
                    1 if d.get("expected_has_issues") else 0,
                    None if d.get("actual_has_issues") is None else (1 if d.get("actual_has_issues") else 0),
                    1 if d.get("passed") else 0,
                    d.get("attempt_count", 0),
                    d.get("retry_count", 0),
                    d.get("message", ""),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def insert_prompt_version(
    run_id: str,
    detection_reason: str,
    prompt_after: str,
    prompt_before: str = "",
    source_label: str = "",
    expected_has_issues: bool = False,
    result_has_issues: bool = False,
):
    """写入一条提示词版本（供 RAG 索引）。"""
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO prompt_versions (run_id, created_at, detection_reason, prompt_before, prompt_after, source_label, expected_has_issues, result_has_issues)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                datetime.utcnow().isoformat(),
                detection_reason,
                prompt_before or "",
                prompt_after,
                source_label,
                1 if expected_has_issues else 0,
                1 if result_has_issues else 0,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def list_runs(limit: int = 50):
    """最近训练记录。"""
    init_db()
    conn = get_connection()
    try:
        cur = conn.execute(
            "SELECT id, created_at, total, ok, failed, updated_prompt_count FROM training_runs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def get_prompt_versions_by_run_id(run_id: str):
    """某次训练产生的提示词修改记录（修改前/修改后，供详情页对比）。"""
    init_db()
    conn = get_connection()
    try:
        cur = conn.execute(
            "SELECT id, run_id, created_at, detection_reason, prompt_before, prompt_after, source_label, expected_has_issues, result_has_issues FROM prompt_versions WHERE run_id = ? ORDER BY id",
            (run_id,),
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def get_run(run_id: str):
    """单次训练汇总 + 明细 + 该 run 的提示词修改记录（修改前/修改后）。"""
    init_db()
    conn = get_connection()
    try:
        run = conn.execute("SELECT * FROM training_runs WHERE id = ?", (run_id,)).fetchone()
        if not run:
            return None
        details = conn.execute("SELECT * FROM training_run_details WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()
        prompt_versions = get_prompt_versions_by_run_id(run_id)
        return {
            "run": dict(run),
            "details": [dict(d) for d in details],
            "prompt_versions": prompt_versions,
        }
    finally:
        conn.close()


def list_prompt_versions(limit: int = 50):
    """最近提示词版本（RAG 知识库列表）。"""
    init_db()
    conn = get_connection()
    try:
        cur = conn.execute(
            "SELECT id, run_id, created_at, detection_reason, prompt_before, prompt_after, source_label, expected_has_issues, result_has_issues FROM prompt_versions ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def generate_run_id():
    return str(uuid.uuid4())


# --------------- 测试报告 ---------------

def create_test_report(report_id: str, total: int = 0):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO test_reports (id, created_at, status, total) VALUES (?, ?, 'running', ?)",
            (report_id, datetime.utcnow().isoformat(), total),
        )
        conn.commit()
    finally:
        conn.close()


def insert_test_report_item(report_id: str, item: dict):
    import json as _json
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO test_report_items
               (report_id, filename, success, has_issues, score, issues, summary,
                structure_ok, agent_process, elapsed_ms, wall_elapsed_ms, message, image_path, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                report_id,
                item.get("filename", ""),
                1 if item.get("success", True) else 0,
                None if item.get("has_issues") is None else (1 if item.get("has_issues") else 0),
                item.get("score"),
                _json.dumps(item.get("issues", []), ensure_ascii=False),
                item.get("summary", ""),
                None if item.get("structure_ok") is None else (1 if item.get("structure_ok") else 0),
                _json.dumps(item.get("agent_process", []), ensure_ascii=False),
                item.get("elapsed_ms", 0),
                item.get("wall_elapsed_ms", 0),
                item.get("message", ""),
                item.get("image_path", ""),
                datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def complete_test_report(report_id: str):
    conn = get_connection()
    try:
        items = conn.execute(
            "SELECT success, has_issues FROM test_report_items WHERE report_id = ?",
            (report_id,),
        ).fetchall()
        total = len(items)
        success_count = sum(1 for i in items if i["success"])
        fail_count = total - success_count
        has_issue_count = sum(1 for i in items if i["success"] and i["has_issues"])
        no_issue_count = sum(1 for i in items if i["success"] and not i["has_issues"])
        elapsed = conn.execute(
            "SELECT COALESCE(SUM(elapsed_ms),0) as te, COALESCE(SUM(wall_elapsed_ms),0) as tw FROM test_report_items WHERE report_id = ?",
            (report_id,),
        ).fetchone()
        conn.execute(
            """UPDATE test_reports
               SET status='completed', total=?, success_count=?, fail_count=?,
                   has_issue_count=?, no_issue_count=?, elapsed_ms=?, wall_elapsed_ms=?
               WHERE id=?""",
            (total, success_count, fail_count, has_issue_count, no_issue_count,
             elapsed["te"], elapsed["tw"], report_id),
        )
        conn.commit()
    finally:
        conn.close()


def list_test_reports(limit: int = 50):
    init_db()
    conn = get_connection()
    try:
        cur = conn.execute(
            "SELECT * FROM test_reports ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def get_test_report(report_id: str):
    import json as _json
    init_db()
    conn = get_connection()
    try:
        report = conn.execute("SELECT * FROM test_reports WHERE id = ?", (report_id,)).fetchone()
        if not report:
            return None
        items = conn.execute(
            "SELECT * FROM test_report_items WHERE report_id = ? ORDER BY id",
            (report_id,),
        ).fetchall()
        result_items = []
        for item in items:
            d = dict(item)
            d["issues"] = _json.loads(d["issues"]) if d["issues"] else []
            d["agent_process"] = _json.loads(d["agent_process"]) if d["agent_process"] else []
            d["success"] = bool(d["success"])
            d["has_issues"] = bool(d["has_issues"]) if d["has_issues"] is not None else None
            d["structure_ok"] = bool(d["structure_ok"]) if d["structure_ok"] is not None else None
            result_items.append(d)
        return {
            "report": dict(report),
            "items": result_items,
        }
    finally:
        conn.close()
